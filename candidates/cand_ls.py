"""Strategy 3: online least-squares feature fusion.

At every predict() call the station's own truncated history is turned into
+1h training samples: features at hour h -> value at h+1.  A ridge fit with
prior-mean shrinkage (toward a persistence-leaning blend) is then refined
with IRLS iterations toward an L1 (conditional-median) fit, which matches
the MAE/HIT metrics better than a pure least-squares fit.  No future data
is used: training hours h satisfy h+1 <= reference hour (target - 1h).

Features: const, last value, EWMA, diurnal mean at the target hour
(decay-weighted over previous days), neighbor IDW (1/d^2, fresh readings
rescaled by the station-vs-neighbor diurnal ratio), sin/cos of target hour.
"""

import math
from datetime import timedelta

H = timedelta(hours=1)
NEIGH_FRESH = 3.0
MAX_NEIGH = 10
MIN_SAMPLES = 24

EWMA_ALPHA = 0.5
RIDGE = 3.0
LAMBDA = 20.0    # shrinkage weight toward PRIOR (relative to one sample)
L1_ITERS = 3     # IRLS iterations toward an L1 fit

# prior: const, last, ewma, diurnal, neighbor, sin, cos
PRIOR = [0.0, 0.85, 0.10, 0.05, 0.0, 0.0, 0.0]


def _hav_km(a_lat, a_lon, b_lat, b_lon):
    r = 6371.0
    p1, p2 = math.radians(a_lat), math.radians(b_lat)
    dp = math.radians(b_lat - a_lat)
    dl = math.radians(b_lon - a_lon)
    x = math.sin(dp / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
    return 2 * r * math.asin(math.sqrt(x))


def _hour_map(series):
    return {t.replace(minute=0, second=0, microsecond=0): v for t, v in series}


def _ewma_at(hm, ref_hour, alpha=EWMA_ALPHA, max_back=48):
    acc = None
    n = 0
    t = ref_hour
    while n < max_back and t in hm:
        v = hm[t]
        acc = v if acc is None else alpha * v + (1 - alpha) * acc
        t -= H
        n += 1
    return acc


def _diurnal_vals(hm, ref_hour):
    out = []
    day = ref_hour.replace(hour=0)
    h = ref_hour.hour
    for d in range(1, 8):
        t = day - timedelta(days=d) + timedelta(hours=h)
        if t in hm:
            out.append(hm[t])
    return out


def _neighbor_idw(hm_neigh, ref_hour, station_hm):
    """IDW (1/d^2) mean of fresh neighbor readings, diurnal-ratio rescaled."""
    sv = _diurnal_vals(station_hm, ref_hour)
    s_mean = sum(sv) / len(sv) if sv else None
    num = den = 0.0
    for d, hm in hm_neigh[:MAX_NEIGH]:
        v = None
        for back in range(int(NEIGH_FRESH)):
            t = ref_hour - back * H
            if t in hm:
                v = hm[t]
                break
        if v is None:
            continue
        if s_mean is not None:
            nv = _diurnal_vals(hm, ref_hour)
            if nv:
                n_mean = sum(nv) / len(nv)
                if n_mean > 2.0:
                    v *= max(0.3, min(3.0, s_mean / n_mean))
        w = 1.0 / max(d, 0.5) ** 2
        num += w * v
        den += w
    return num / den if den else None


def _feats(hm, hour, hm_neigh):
    if hour not in hm:
        return None
    last = hm[hour]
    ewma = _ewma_at(hm, hour)
    if ewma is None:
        ewma = last
    nxt = hour + H
    dv = _diurnal_vals(hm, nxt)
    if dv:
        w = [0.5 ** i for i in range(len(dv))]
        diu = sum(v * x for v, x in zip(dv, w)) / sum(w)
    else:
        diu = last
    nb = _neighbor_idw(hm_neigh, nxt, hm)
    if nb is None:
        nb = last
    ang = 2.0 * math.pi * nxt.hour / 24.0
    return [1.0, last, ewma, diu, nb, math.sin(ang), math.cos(ang)]


def _solve(a, b):
    n = len(b)
    m = [row[:] + [b[i]] for i, row in enumerate(a)]
    for col in range(n):
        piv = max(range(col, n), key=lambda r: abs(m[r][col]))
        if abs(m[piv][col]) < 1e-10:
            return None
        m[col], m[piv] = m[piv], m[col]
        pv = m[col][col]
        for r in range(col + 1, n):
            f = m[r][col] / pv
            if f:
                for c in range(col, n + 1):
                    m[r][c] -= f * m[col][c]
    x = [0.0] * n
    for r in range(n - 1, -1, -1):
        s = m[r][n] - sum(m[r][c] * x[c] for c in range(r + 1, n))
        x[r] = s / m[r][r]
    return x


def predict(station, neighbors, target_time):
    s = station["series"]
    if not s:
        return None
    hm = _hour_map(s)
    ref = (target_time - H).replace(minute=0, second=0, microsecond=0)
    if ref not in hm:
        ref = max(hm)

    slat, slon = float(station["lat"]), float(station["lon"])
    hm_neigh = []
    for nb in neighbors:
        nm = _hour_map(nb["series"])
        if not nm:
            continue
        d = _hav_km(slat, slon, float(nb["lat"]), float(nb["lon"]))
        hm_neigh.append((d, nm))
    hm_neigh.sort(key=lambda p: p[0])

    xf = _feats(hm, ref, hm_neigh)
    if xf is None:
        return hm[ref]

    hours = sorted(hm)
    X, Y = [], []
    for h in hours:
        nxt = h + H
        if nxt >= ref or nxt not in hm:
            continue
        f = _feats(hm, h, hm_neigh)
        if f is not None:
            X.append(f)
            Y.append(hm[nxt])

    k = len(xf)
    if len(X) < MIN_SAMPLES:
        return hm[ref]

    def fit(weights):
        xtx = [[0.0] * k for _ in range(k)]
        xty = [0.0] * k
        for f, y, w in zip(X, Y, weights):
            for i in range(k):
                xty[i] += w * f[i] * y
                fi = w * f[i]
                for j in range(i, k):
                    xtx[i][j] += fi * f[j]
        for i in range(k):
            for j in range(i):
                xtx[i][j] = xtx[j][i]
        for i in range(1, k):
            xtx[i][i] += RIDGE + LAMBDA
            xty[i] += LAMBDA * PRIOR[i]
        xtx[0][0] += RIDGE
        return _solve(xtx, xty)

    wts = [1.0] * len(X)
    beta = fit(wts)
    if beta is None:
        return hm[ref]
    for _ in range(L1_ITERS):
        wts = [1.0 / max(abs(y - sum(b * f for b, f in zip(beta, f))), 1.0)
               for f, y in zip(X, Y)]
        beta = fit(wts)
        if beta is None:
            return hm[ref]
    return sum(b * f for b, f in zip(beta, xf))
