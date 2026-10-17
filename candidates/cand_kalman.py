"""Candidate: adaptive robust Kalman filter nowcast.

State-space model per station (hourly PM2.5), 6-dim state:

    y_t = M_t + D_t + c1_t*cos(w t) + s1_t*sin(w t)
                 + c2_t*cos(2w t) + s2_t*sin(2w t) + e_t,   w = 2*pi/24

with a time-invariant observation vector H = [1,1,1,0,1,0]:

    M' = M                    (slow baseline level, small process noise)
    D' = PHI * D              (fast deviation, mean-reverting: hourly deltas
                               in this data have lag-1 autocorr ~ -0.3, so
                               after a jump the level reverts)
    [c'; s'] = Rot(w) [c; s]  (deterministic diurnal rotation + noise)

Key features:
- innovation-based adaptive observation noise: R tracked from an EMA of
  squared innovations (R = innov_var - H P H', floored/capped);
- process noise scaled up when the recent innovation variance exceeds its
  slow baseline (volatile regime -> faster tracking);
- robust update: Huber clipping of the standardized innovation, so a spike
  moves the state by at most ~HUBER_K standard deviations (no overreaction;
  combined with PHI < 1 the post-spike reversion falls out naturally);
- gap handling: the transition is applied for the actual dt (rotation by
  dt*w, D decayed by PHI^dt, process noise scaled by dt);
- initialization: least-squares fit of [1, cos, sin, cos2, sin2] on the
  first INIT_H hours so the short (~7 day) histories start with a sane
  diurnal;
- prediction: propagate the filtered state (no updates) to target_time,
  then fuse two complementary nowcast signals:
    * climatology anchor (W_CLIM): recency-decayed median of the station's
      own readings at the target hour +/- CLIM_SPREAD — stabilizes the
      extrapolation against filter overshoot;
    * diurnal drift (DRIFT_SCALE): expected hourly delta at the target
      hour, own-station median shrunk toward 0 blended with the fleet-wide
      (own + neighbors) median delta — the harmonics capture the average
      diurnal shape, this captures the systematic hour-of-day move.

Leak-free: only series truncated to <= T-1h are used (the fleet-drift cache
is keyed by target_time; at a given T every task sees the same truncation,
so it is identical work, not shared state). Pure stdlib; no network.

Tuning log (bench_nowcast, 684 cases, coordinate descent):
  persistence baseline        ACC 0.581 / MAE 5.89
  plain level+harmonics KF    ACC 0.6646
  + mean-reverting deviation  ACC 0.6704  (PHI<1, matches lag-1 autocorr -0.3)
  + noise/Huber tuning        ACC 0.6779
  + climatology anchor        ACC 0.6867  (W_CLIM 0.5-0.6)
  + diurnal drift term        ACC 0.6910
  + fine noise tuning         ACC 0.6952 / MAE 4.28 / HIT10 0.3743  <- final
Rejected by the sweeps (kept behind zero weights): neighbor IDW level
consensus (W_NEIGHBOR: every weight lowered ACC, same finding as
cand_diurnal/cand_regime), median-of-three fusion (FUSE_MEDIAN), recency
decay in the climatology anchor (CLIM_DECAY < 1.0). Huber clipping costs
~0.0001 ACC versus HUBER_K=inf and is kept as the spike guard.
"""

from __future__ import annotations

import math

W = 2.0 * math.pi / 24.0

# ---- tunables ----
INIT_H = 72          # hours used for the LS initialization of the state
PHI = 0.5            # mean-reversion of the fast deviation per hour
P0_LEVEL = 400.0     # initial covariance of the slow level
P0_DEV = 100.0       # initial covariance of the fast deviation
P0_HARM = 100.0      # initial covariance of harmonic coefficients
Q_LEVEL = 0.4        # process noise variance / h on the slow level
Q_DEV = 64.0         # process noise variance / h on the fast deviation
Q_HARM = 0.1         # process noise variance / h on each harmonic coeff
R_MIN = 2.0          # floor for the observation noise variance
R_MAX = 900.0        # cap for the adaptive observation noise variance
ADAPT_A = 0.4        # EMA rate for the innovation variance
Q_ADAPT = 8.0        # process-noise boost when innovations run hot
HUBER_K = 3.5        # clip innovations beyond this many std devs
N = 6

# ---- fusion channels (inverse-variance style blends on the KF extrapolation)
W_NEIGHBOR = 0.0     # weight of the neighbor IDW consensus (0 disables)
NEIGHBOR_MAX = 8
NEIGHBOR_FRESH_H = 3.0
W_CLIM = 0.5         # weight of the recency-decayed same-hour median anchor
CLIM_SPREAD = 1      # +/- hours around target hour for the anchor
CLIM_DECAY = 1.0     # recency weight per day of age for the anchor
DRIFT_SCALE = 1.1    # additive expected diurnal drift at the target hour (ug)
DRIFT_OWN_W = 0.7    # blend: own-station drift vs fleet drift
DRIFT_OWN_LAM = 20.0 # shrinkage pseudo-count for own-station drift
FUSE_MEDIAN = 0      # 1: median(kf, clim, persistence+drift); 0: weighted blend


def _median(xs):
    xs = sorted(xs)
    n = len(xs)
    if n == 0:
        return None
    m = n // 2
    return xs[m] if n % 2 else 0.5 * (xs[m - 1] + xs[m])


def _haversine_km(a, b):
    r = 6371.0
    p1, p2 = math.radians(a[0]), math.radians(b[0])
    dp = math.radians(b[0] - a[0])
    dl = math.radians(b[1] - a[1])
    h = math.sin(dp / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
    return 2 * r * math.asin(math.sqrt(h))


def _neighbor_consensus(station, clean_med, neighbors, target_time):
    """Median of the nearest fresh neighbor readings, rescaled by the ratio
    of overall medians (robust station offset), IDW-ordered."""
    origin = (station.get("lat"), station.get("lon"))
    cands = []
    for nb in neighbors or []:
        ns = nb.get("series") or []
        if not ns:
            continue
        tn, vn = ns[-1]
        if (target_time - tn).total_seconds() > NEIGHBOR_FRESH_H * 3600:
            continue
        nmed = _median([v for _, v in ns]) or vn
        if nmed <= 0:
            continue
        try:
            d = _haversine_km(origin, (nb.get("lat"), nb.get("lon")))
        except (TypeError, ValueError):
            continue
        cands.append((d, vn * clean_med / nmed))
    if not cands:
        return None
    cands.sort(key=lambda p: p[0])
    return _median([v for _, v in cands[:NEIGHBOR_MAX]])


def _clim_anchor(series, target_time):
    """Recency-decayed median of readings at target hour +/- CLIM_SPREAD."""
    t0 = series[-1][0]
    th = target_time.hour
    items = []
    for t, v in series:
        dh = abs(((t.hour - th + 12) % 24) - 12)
        if dh <= CLIM_SPREAD:
            age_days = (t0 - t).total_seconds() / 86400.0
            items.append((v, CLIM_DECAY ** age_days))
    if not items:
        return None
    items.sort(key=lambda p: p[0])
    total = sum(w for _, w in items)
    acc = 0.0
    for v, w in items:
        acc += w
        if acc >= 0.5 * total:
            return v
    return items[-1][0]


def _hour_deltas(series, acc):
    """Accumulate contiguous hourly deltas per hour-of-day into acc."""
    for i in range(1, len(series)):
        dt = (series[i][0] - series[i - 1][0]).total_seconds()
        if dt == 3600:
            acc.setdefault(series[i][0].hour, []).append(series[i][1] - series[i - 1][1])


# Fleet drift per cutoff hour: at a given T every task sees the same stations
# truncated at <= T-1h, so the aggregate is identical work, and leak-free.
_FLEET_CACHE = {}


def _fleet_drift(key, own_series, neighbors):
    hit = _FLEET_CACHE.get(key)
    if hit is not None:
        return hit
    fleet = {}
    _hour_deltas(own_series, fleet)
    for nb in neighbors or []:
        ns = nb.get("series") or []
        if ns:
            _hour_deltas(ns, fleet)
    drift = {h: _median(vs) for h, vs in fleet.items() if len(vs) >= 30}
    if len(_FLEET_CACHE) > 400:
        _FLEET_CACHE.clear()
    _FLEET_CACHE[key] = drift
    return drift


def _drift(own_series, neighbors, target_hour, target_time):
    """Expected hourly delta at target_hour: own history shrunk toward 0,
    blended with the fleet-wide (own + neighbours) median drift."""
    own = {}
    _hour_deltas(own_series, own)
    d_own = 0.0
    if target_hour in own:
        vs = own[target_hour]
        d_own = _median(vs) * len(vs) / (len(vs) + DRIFT_OWN_LAM)
    d_fleet = _fleet_drift(target_time, own_series, neighbors).get(target_hour, 0.0)
    return DRIFT_OWN_W * d_own + (1.0 - DRIFT_OWN_W) * d_fleet


def _rot(c, s, ang):
    ca, sa = math.cos(ang), math.sin(ang)
    return c * ca + s * sa, -c * sa + s * ca


def _init_state(series):
    """Least-squares fit of level + 2 harmonics on the first INIT_H hours."""
    pts = series[:INIT_H]
    n = 5
    ata = [[0.0] * n for _ in range(n)]
    aty = [0.0] * n
    t0 = pts[0][0]
    rows = []
    for t, v in pts:
        h = (t - t0).total_seconds() / 3600.0
        row = [1.0, math.cos(W * h), math.sin(W * h),
               math.cos(2 * W * h), math.sin(2 * W * h)]
        rows.append((row, v))
        for i in range(n):
            aty[i] += row[i] * v
            ri = row[i]
            for j in range(n):
                ata[i][j] += ri * row[j]
    for i in range(n):
        ata[i][i] += 1e-3
    for col in range(n):
        piv = max(range(col, n), key=lambda r: abs(ata[r][col]))
        if abs(ata[piv][col]) < 1e-9:
            break
        ata[col], ata[piv] = ata[piv], ata[col]
        aty[col], aty[piv] = aty[piv], aty[col]
        d = ata[col][col]
        for r in range(n):
            if r == col:
                continue
            f = ata[r][col] / d
            if f == 0.0:
                continue
            for c in range(col, n):
                ata[r][c] -= f * ata[col][c]
            aty[r] -= f * aty[col]
    x = [0.0] * n
    for i in range(n):
        if abs(ata[i][i]) > 1e-9:
            x[i] = aty[i] / ata[i][i]
    rss = 0.0
    for row, v in rows:
        fit = sum(a * b for a, b in zip(x, row))
        rss += (v - fit) ** 2
    r0 = max(R_MIN, rss / max(len(rows) - n, 1))
    # state: [M, D, c1, s1, c2, s2]
    return [x[0], 0.0, x[1], x[2], x[3], x[4]], r0


class _KF:
    def __init__(self, series):
        self.x, self.r_ema = _init_state(series)
        self.r_slow = self.r_ema
        self.P = [[0.0] * N for _ in range(N)]
        self.P[0][0] = P0_LEVEL
        self.P[1][1] = P0_DEV
        for i in (2, 3, 4, 5):
            self.P[i][i] = P0_HARM
        self.t = series[0][0]

    def _propagate(self, steps):
        if steps <= 0:
            return
        x, P = self.x, self.P
        phi = PHI ** steps
        x[1] *= phi
        x[2], x[3] = _rot(x[2], x[3], W * steps)
        x[4], x[5] = _rot(x[4], x[5], 2 * W * steps)

        # P <- F P F^T + Q
        for k in range(N):           # scale row/col 1 by phi (D' = phi D)
            P[1][k] *= phi
            P[k][1] *= phi
        self._rot_block(2, 3, W * steps)
        self._rot_block(4, 5, 2 * W * steps)

        # innovation-adaptive process noise
        ratio = self.r_ema / max(self.r_slow, 1e-9)
        qscale = 1.0 + Q_ADAPT * max(0.0, min(ratio, 4.0) - 1.0)
        P[0][0] += Q_LEVEL * steps * qscale
        P[1][1] += Q_DEV * steps * qscale
        for i in (2, 3, 4, 5):
            P[i][i] += Q_HARM * steps * qscale
        self._sym()

    def _rot_block(self, i, j, ang):
        P = self.P
        ca, sa = math.cos(ang), math.sin(ang)
        for k in range(N):
            a, b = P[i][k], P[j][k]
            P[i][k] = ca * a + sa * b
            P[j][k] = -sa * a + ca * b
        for k in range(N):
            a, b = P[k][i], P[k][j]
            P[k][i] = ca * a + sa * b
            P[k][j] = -sa * a + ca * b

    def _sym(self):
        P = self.P
        for i in range(N):
            for j in range(i + 1, N):
                m = 0.5 * (P[i][j] + P[j][i])
                P[i][j] = P[j][i] = m

    def update(self, t, y):
        steps = int(round((t - self.t).total_seconds() / 3600.0))
        if steps > 0:
            self._propagate(steps)
            self.t = t
        x, P = self.x, self.P
        # H = [1,1,1,0,1,0]
        yhat = x[0] + x[1] + x[2] + x[4]
        innov = y - yhat
        hp = [P[0][k] + P[1][k] + P[2][k] + P[4][k] for k in range(N)]
        php = hp[0] + hp[1] + hp[2] + hp[4]
        self.r_slow = 0.97 * self.r_slow + 0.03 * innov * innov
        self.r_ema = (1.0 - ADAPT_A) * self.r_ema + ADAPT_A * innov * innov
        R = min(R_MAX, max(R_MIN, self.r_ema - php))
        S = php + R
        z = innov / math.sqrt(S)
        g = 1.0
        if abs(z) > HUBER_K:
            g = HUBER_K / abs(z)
        ph = [P[k][0] + P[k][1] + P[k][2] + P[k][4] for k in range(N)]
        gs = g / S
        for i in range(N):
            x[i] += gs * ph[i] * innov
        for i in range(N):
            pi = ph[i]
            for j in range(N):
                P[i][j] -= gs * pi * hp[j]
        self._sym()

    def predict_at(self, t):
        steps = int(round((t - self.t).total_seconds() / 3600.0))
        x = list(self.x)
        if steps > 0:
            x[1] *= PHI ** steps
            x[2], x[3] = _rot(x[2], x[3], W * steps)
            x[4], x[5] = _rot(x[4], x[5], 2 * W * steps)
        return x[0] + x[1] + x[2] + x[4]


def predict(station, neighbors, target_time):
    s = [(t, float(v)) for t, v in (station.get("series") or []) if v is not None]
    if len(s) < 8:
        return s[-1][1] if s else None
    s.sort(key=lambda p: p[0])
    kf = _KF(s)
    for t, v in s:
        kf.update(t, v)
    pred = kf.predict_at(target_time)

    clim = _clim_anchor(s, target_time) if (W_CLIM > 0.0 or FUSE_MEDIAN) else None

    drift = 0.0
    if DRIFT_SCALE > 0.0:
        drift = DRIFT_SCALE * _drift(s, neighbors, target_time.hour, target_time)

    if FUSE_MEDIAN:
        comp = [pred]
        if clim is not None:
            comp.append(clim)
        comp.append(s[-1][1] + drift)
        pred = _median(comp)
    else:
        if W_CLIM > 0.0 and clim is not None:
            pred = (1.0 - W_CLIM) * pred + W_CLIM * clim
        pred += drift

    # fuse the neighbor IDW consensus (translated by overall-median ratio)
    if W_NEIGHBOR > 0.0 and neighbors:
        clean_med = _median([v for _, v in s]) or s[-1][1]
        nb = _neighbor_consensus(station, clean_med, neighbors, target_time)
        if nb is not None:
            pred = (1.0 - W_NEIGHBOR) * pred + W_NEIGHBOR * nb

    return max(0.0, pred)
