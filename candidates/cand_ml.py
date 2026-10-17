"""Candidate: online stacked ridge over faithful base nowcasts (pure numpy).

A global ridge stacker, retrained at every predict() call on the whole
fleet pooled (only hours <= cutoff = target_time - 1h), learns to combine
four base nowcasts computed in closed form:

  b_diu : diurnal-anomaly anchor (0.5*clim[T] + 0.5*lv*clim[T]/clim[cur],
          lv = last reading smoothed with the previous two readings)
  b_reg : regime anchor (0.2*last + 0.8*recency-decayed median at the
          target hour +/-1h, 10% blend of the value 24h back)
  b_rob : robust anchor (despike, mean-revert to rolling median level,
          own+fleet diurnal drift, diurnal-mean rescale, neighbor fusion)
  b_med : median of the three (the current champion ensemble)

plus side features (diurnal sin/cos, anomaly, last delta, deviation from
24h median, neighbor IDW delta, recent own-vs-neighbor offset, and the
staleness gap = hours from the anchor reading to the target).  Level-like
features are normalized by the station's own overall median s_i so samples
pool cleanly across stations.  The fit uses recency weighting, Huber IRLS,
and pseudo-sample shrinkage toward b_med alone, so with weak signal the
stacker falls back to the champion ensemble.

Training pairs: features anchored at reading h -> v(nxt)/s_i, where nxt is
the NEXT REAL READING after h (not necessarily h+1h) and nxt <= cutoff —
including stale rows teaches the stacker how to rebalance the bases when
the last reading is old.  No data after cutoff is ever touched.  Rolling
profile quantities (clim, drift, diurnal means) are built from the
<= cutoff history and shared by all rows.  The fitted model is cached per
target_time: at a given T every task sees the same fleet truncated at
<= T-1h, so the cache is identical work, not shared state.
"""

import math
from bisect import bisect_right
from datetime import timedelta

import numpy as np

H = timedelta(hours=1)
D1 = timedelta(days=1)

K_NEIGH = 4          # nearest stations used for neighbor features
RIDGE = 2.0          # ridge strength
LAMBDA = 60.0        # pseudo-sample shrinkage toward PRIOR (b_med alone)
HALF_LIFE_D = 0.75   # recency half-life of training samples, in days
IRLS_ITERS = 2       # Huber IRLS refinement passes
IRLS_C = 2.0         # Huber constant (robust-sigma units)

# [const, b_med, b_diu, b_reg, b_rob, sin, cos, an, d1, dev24, nd, dmean, gap]
PRIOR = [0.0, 1.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0]

_MODEL_CACHE = {}


def _hour_map(series):
    return {t.replace(minute=0, second=0, microsecond=0): float(v)
            for t, v in series}


def _hav_km(a_lat, a_lon, b_lat, b_lon):
    r = 6371.0
    p1, p2 = math.radians(a_lat), math.radians(b_lat)
    dp = math.radians(b_lat - a_lat)
    dl = math.radians(b_lon - a_lon)
    x = math.sin(dp / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
    return 2 * r * math.asin(math.sqrt(x))


def _median(xs):
    xs = sorted(xs)
    n = len(xs)
    if not n:
        return None
    m = n // 2
    return xs[m] if n % 2 else 0.5 * (xs[m - 1] + xs[m])


def _despike(vals, win=7, k=2.0):
    n = len(vals)
    if n < win:
        return list(vals)
    half = win // 2
    med = [_median(vals[max(0, i - half):min(n, i + half + 1)]) for i in range(n)]
    devs = [abs(v - m) for v, m in zip(vals, med)]
    mad = _median(devs) or 0.0
    sigma = 1.4826 * mad
    if sigma <= 0:
        return list(vals)
    return [m if abs(v - m) > k * sigma else v for v, m in zip(vals, med)]


def _hour_deltas(items, acc):
    for i in range(1, len(items)):
        dt = (items[i][0] - items[i - 1][0]).total_seconds()
        if dt == 3600:
            acc.setdefault(items[i][0].hour, []).append(items[i][1] - items[i - 1][1])


class _StationView:
    """Per-station precomputations over the truncated (<= ref) history."""

    def __init__(self, hm, nbrs, ref, fleet_drift):
        self.hm = hm
        self.ref = ref
        items = sorted(hm.items())
        self.times = [t for t, _ in items]
        self.vals = [v for _, v in items]
        self.pos = {t: i for i, t in enumerate(self.times)}
        self.clean = _despike(self.vals)
        self.overall = _median(self.vals) or 1.0
        self.cmed = _median(self.clean) or self.overall

        by = [[] for _ in range(24)]
        bym = [[] for _ in range(24)]
        for t, v in items:
            by[t.hour].append(v)
            bym[t.hour].append(v)
        prof = [(_median(b) if b else self.overall) for b in by]
        self.clim = [0.5 * prof[h] + 0.25 * prof[(h - 1) % 24] + 0.25 * prof[(h + 1) % 24]
                     for h in range(24)]
        self.dmean_prof = [(sum(b) / len(b) if b else self.overall) for b in bym]

        # regime profile: recency-decayed median at hour +/-1
        self.reg = []
        for th in range(24):
            pool = []
            for hh in ((th - 1) % 24, th, (th + 1) % 24):
                for t, v in items:
                    if t.hour == hh:
                        age = (ref - t).total_seconds() / 86400.0
                        pool.append((v, 0.85 ** age))
            if not pool:
                self.reg.append(self.overall)
                continue
            pool.sort()
            tot = sum(w for _, w in pool)
            acc = 0.0
            val = pool[-1][0]
            for v, w in pool:
                acc += w
                if acc >= 0.5 * tot:
                    val = v
                    break
            self.reg.append(val)

        # own diurnal drift (shrunk) + fleet drift
        own = {}
        _hour_deltas(items, own)
        self.own_drift = {}
        for h, vs in own.items():
            self.own_drift[h] = _median(vs) * len(vs) / (len(vs) + 20.0)
        self.fleet_drift = fleet_drift

        # robust historical clamp range (from despiked values)
        cs = sorted(self.clean)
        self.lo = cs[max(0, int(0.01 * len(cs)))]
        self.hi = cs[min(len(cs) - 1, int(0.995 * len(cs)))]

        # neighbor IDW structures
        self.nbrs = nbrs  # list of (dist, times, vals, nmed)
        ws = [1.0 / max(d, 0.5) ** 2 for d, _, _, _ in nbrs]
        self.nws = ws
        need = set()
        for h in hm:
            need.add(h)
            need.add(h - H)
        self.nid = {}
        for h in need:
            num = den = 0.0
            for (d, nts, nvs, _), w in zip(nbrs, ws):
                j = bisect_right(nts, h) - 1
                if j >= 0 and nts[j] == h:
                    num += w * nvs[j]
                    den += w
            if den > 0:
                self.nid[h] = num / den
        dh = sorted(h for h in hm if h in self.nid)
        self._dh = dh
        self._dv = [hm[h] - self.nid[h] for h in dh]

    def dmean_at(self, h):
        lo = h - D1
        vals = [dv for dh, dv in zip(self._dh, self._dv) if lo <= dh <= h]
        return sum(vals) / len(vals) if vals else 0.0


def _base_robust(sv: _StationView, h, idx, nxt):
    """Faithful reimplementation of the robust anchor for target nxt."""
    v0 = sv.vals[idx]
    t0 = sv.times[idx]
    tail = sv.clean[max(0, idx - 23):idx + 1]
    level = _median(tail)
    pred = v0 + 0.2 * (level - v0)
    th = nxt.hour
    drift = 0.2 * sv.own_drift.get(th, 0.0) + 0.8 * sv.fleet_drift.get(th, 0.0)
    pred += 1.6 * drift
    mu_from = sv.dmean_prof[t0.hour]
    mu_to = sv.dmean_prof[th]
    if mu_from and mu_to and mu_from >= 1.0:
        ratio = mu_to / mu_from
        ratio = 1.0 + 0.4 * (ratio - 1.0)
        ratio = min(max(ratio, 0.6), 1.7)
        pred *= ratio
    stale_h = max(0.0, (nxt - t0).total_seconds() / 3600.0 - 1.0)
    if stale_h > 0:
        f = 1.0 - math.exp(-stale_h / 6.0)
        pred = (1 - f) * pred + f * level
    # neighbor consensus: median of the nearest fresh translated readings
    cands = []
    for d, nts, nvs, nmed in sv.nbrs:
        j = bisect_right(nts, t0) - 1
        if j < 0 or (t0 - nts[j]).total_seconds() > 3.0 * 3600:
            continue
        if nmed <= 0:
            continue
        cands.append((d, nvs[j] * sv.cmed / nmed))
    if cands:
        cands.sort()
        cons = _median([v for _, v in cands[:8]])
        if cons is not None:
            pred = 0.7 * pred + 0.3 * cons
    return min(max(pred, 0.3 * sv.lo), 1.5 * sv.hi + 5.0)


def _row(sv: _StationView, h, nxt):
    """Base predictions + side features anchored at the last reading h,
    for target time nxt, normalized by the station's overall median."""
    idx = sv.pos.get(h)
    if idx is None:
        return None
    v0 = sv.vals[idx]
    v1 = sv.vals[idx - 1] if idx >= 1 else v0
    v2 = sv.vals[idx - 2] if idx >= 2 else v1
    s = max(sv.overall, 2.0)
    th = nxt.hour

    lv = 0.65 * v0 + 0.35 * (0.6 * v1 + 0.4 * v2)
    c_next = sv.clim[th]
    c_cur = max(sv.clim[h.hour], 1.0)
    b_diu = 0.5 * c_next + 0.5 * lv * c_next / c_cur

    reg = sv.reg[th]
    v24 = sv.hm.get(nxt - 24 * H)
    if v24 is not None:
        reg = 0.9 * reg + 0.1 * v24
    b_reg = 0.2 * v0 + 0.8 * reg

    b_rob = _base_robust(sv, h, idx, nxt)
    b_med = _median([b_diu, b_reg, b_rob])

    tail = sv.vals[max(0, idx - 23):idx + 1]
    med24 = _median(tail)
    ang = 2.0 * math.pi * th / 24.0
    nid0 = sv.nid.get(h)
    nid1 = sv.nid.get(h - H)
    nd = (nid0 - nid1) if (nid0 is not None and nid1 is not None) else 0.0
    gap = min((nxt - sv.times[idx]).total_seconds() / 3600.0, 24.0)
    return [1.0, b_med / s, b_diu / s, b_reg / s, b_rob / s,
            math.sin(ang), math.cos(ang), lv / c_cur,
            (v0 - v1) / s, (v0 - med24) / s, nd / s, sv.dmean_at(h) / s,
            gap / 6.0]


def _own_neighbors(station, neighbors):
    slat, slon = float(station["lat"]), float(station["lon"])
    nbrs = []
    for nb in neighbors or []:
        hm = nb.get("hm") or _hour_map(nb.get("series") or [])
        if not hm:
            continue
        d = _hav_km(slat, slon, float(nb["lat"]), float(nb["lon"]))
        items = sorted(hm.items())
        nmed = _median([v for _, v in items]) or 1.0
        nbrs.append((d, [t for t, _ in items], [v for _, v in items], nmed))
    nbrs.sort(key=lambda p: p[0])
    return nbrs[:K_NEIGH]


def _fleet_drift(stations, ref):
    fleet = {}
    for st in stations:
        _hour_deltas(sorted(st["hm"].items()), fleet)
    return {h: _median(vs) for h, vs in fleet.items() if len(vs) >= 30}


def _train_global(station, neighbors, target_time):
    ref = (target_time - H).replace(minute=0, second=0, microsecond=0)
    raw = [{"lat": station["lat"], "lon": station["lon"],
            "series": station["series"]}]
    raw.extend(neighbors or [])
    stations = []
    for r in raw:
        hm = _hour_map(r["series"])
        if hm:
            stations.append({"lat": float(r["lat"]), "lon": float(r["lon"]),
                             "hm": hm})
    if not stations:
        return None
    fleet = _fleet_drift(stations, ref)

    Xs, Ys, Ws = [], [], []
    for i, st in enumerate(stations):
        nbrs = _own_neighbors(st, [o for j, o in enumerate(stations) if j != i])
        sv = _StationView(st["hm"], nbrs, ref, fleet)
        s = max(sv.overall, 2.0)
        X, Y, times = [], [], []
        for idx, h in enumerate(sv.times[:-1]):
            nxt = sv.times[idx + 1]
            if nxt > ref:
                break
            row = _row(sv, h, nxt)
            if row is None:
                continue
            X.append(row)
            Y.append(sv.vals[idx + 1] / s)
            times.append(h)
        if not X:
            continue
        age_d = np.array([(ref - t).total_seconds() / 86400.0 for t in times])
        w = 0.5 ** (age_d / HALF_LIFE_D)
        Xs.append(np.array(X))
        Ys.append(np.array(Y))
        Ws.append(w)
    if not Xs:
        return None
    X = np.vstack(Xs)
    Y = np.concatenate(Ys)
    W = np.concatenate(Ws)

    # pseudo-samples pulling the coefficients toward PRIOR (b_med alone)
    k = X.shape[1]
    Xp = np.eye(k)
    Yp = np.array(PRIOR, dtype=float)
    Wp = np.full(k, LAMBDA)

    def fit(w):
        Xa = np.vstack([X, Xp])
        Ya = np.concatenate([Y, Yp])
        Wa = np.concatenate([w, Wp])
        A = (Xa * Wa[:, None]).T @ Xa
        b = (Xa * Wa[:, None]).T @ Ya
        reg = RIDGE * np.eye(k)
        reg[0, 0] = 1e-6
        return np.linalg.solve(A + reg, b)

    beta = fit(W)
    for _ in range(IRLS_ITERS):
        r = np.abs(Y - X @ beta)
        s_r = max(np.median(r) * 1.4826, 1e-3)
        w = W * np.minimum(1.0, IRLS_C * s_r / np.maximum(r, 1e-9))
        beta = fit(w)

    return {"beta": beta, "ref": ref, "fleet": fleet}


def predict(station, neighbors, target_time):
    s = station.get("series") or []
    if not s:
        return None
    key = target_time
    if key not in _MODEL_CACHE:
        try:
            model = _train_global(station, neighbors, target_time)
        except Exception:
            model = None
        if len(_MODEL_CACHE) > 4096:
            _MODEL_CACHE.clear()
        _MODEL_CACHE[key] = model
    model = _MODEL_CACHE[key]

    hm = _hour_map(s)
    if model is None:
        return hm[max(hm)]
    ref = model["ref"]
    if ref not in hm:
        ref = max((h for h in hm if h <= ref), default=max(hm))

    nbrs = _own_neighbors(station, neighbors)
    sv = _StationView(hm, nbrs, ref, model["fleet"])
    tn = target_time.replace(minute=0, second=0, microsecond=0)
    row = _row(sv, ref, tn)
    if row is None:
        return hm[ref]
    pred = float(np.dot(row, model["beta"])) * max(sv.overall, 2.0)
    return max(0.0, pred)
