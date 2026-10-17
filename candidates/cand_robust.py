"""Strategy 1: robust smoothing + spike guard for +1h PM2.5 nowcast.

Offline findings on data/snapshot.json that shaped the algorithm:
- hourly deltas are heavy-tailed and negatively autocorrelated (lag-1 ~ -0.3):
  after an up-jump >10 ug the next hour reverts by ~ -8 ug on median, so raw
  persistence overshoots right after spikes -> mean reversion toward a robust
  local level is the main spike guard.
- strong systematic diurnal drift: hours 4-6 rise +3..+6 ug (median), hours
  8-13 fall -1..-2 ug. Persistence misses this entirely; adding the expected
  drift was the single biggest win (ACC +0.03).
- neighbour consensus correlates only ~0.26 with the station's own jumps, so
  neighbours help as a low-weight stabilizer, not as a spike predictor.
- rejected by sweeps: hard delta clamping (hurts vs. soft reversion), a
  fleet-fitted piecewise gap-response (no gain over linear reversion + drift),
  log-space reversion, per-station revert coefficients.

Pipeline (all inputs truncated to <= T-1h by the harness):
1. despike the history with a rolling-median/MAD filter (robust z-score);
2. robust level = median of the last LEVEL_WIN despiked values;
3. mean-revert: pred = last + REVERT * (level - last);
4. add expected diurnal drift (own per-hour median delta shrunk toward 0,
   blended with the fleet-wide median delta at the target hour);
5. rescale along the station's own diurnal ratio mu[T]/mu[T-1] (shrunk);
6. staleness: if the last reading is older than ~1h, fade toward the level;
7. fuse neighbour consensus (median of the 8 nearest fresh readings, rescaled
   by overall-median ratio) with weight W_NEIGHBOR;
8. clamp into a robust historical range.

Pure stdlib; no network. Fleet aggregates are cached per target hour: at a
given T every task sees the same stations truncated at <= T-1h, so the cache
is identical work, not shared state (and leak-free by construction).
"""

from __future__ import annotations

import math

# ---- tunables ----
DESPIKE_WIN = 7        # rolling median window (odd)
DESPIKE_K = 2.0        # robust z threshold (in MAD units)
LEVEL_WIN = 24         # hours used for the robust level (median)
REVERT = 0.2           # mean-reversion strength toward robust level
DIURNAL_SHRINK = 0.4   # 0 = ignore diurnal ratio, 1 = full ratio
DIURNAL_MIN = 1.0      # min diurnal mean allowed in a ratio denominator
DRIFT_SCALE = 1.6      # weight of the expected diurnal drift term
DRIFT_OWN_W = 0.2      # blend: own-station drift vs fleet drift
DRIFT_OWN_LAM = 20.0   # shrinkage for own-station drift (pseudo-count)
W_NEIGHBOR = 0.3       # fusion weight of neighbour consensus (0 disables)
NEIGHBOR_MAX = 8
NEIGHBOR_FRESH_H = 3.0


def _median(xs):
    xs = sorted(xs)
    n = len(xs)
    if n == 0:
        return None
    m = n // 2
    return xs[m] if n % 2 else 0.5 * (xs[m - 1] + xs[m])


def _despike(vals):
    """Replace points whose robust z vs rolling median exceeds DESPIKE_K."""
    n = len(vals)
    if n < DESPIKE_WIN:
        return list(vals)
    half = DESPIKE_WIN // 2
    med = []
    for i in range(n):
        lo, hi = max(0, i - half), min(n, i + half + 1)
        med.append(_median(vals[lo:hi]))
    devs = [abs(v - m) for v, m in zip(vals, med)]
    mad = _median(devs) or 0.0
    sigma = 1.4826 * mad
    if sigma <= 0:
        return list(vals)
    out = []
    for v, m in zip(vals, med):
        out.append(m if abs(v - m) > DESPIKE_K * sigma else v)
    return out


def _diurnal_means(series):
    """Per hour-of-day mean over the truncated history."""
    acc = {}
    for t, v in series:
        acc.setdefault(t.hour, []).append(v)
    return {h: sum(vs) / len(vs) for h, vs in acc.items()}


def _haversine_km(a, b):
    r = 6371.0
    p1, p2 = math.radians(a[0]), math.radians(b[0])
    dp = math.radians(b[0] - a[0])
    dl = math.radians(b[1] - a[1])
    h = math.sin(dp / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
    return 2 * r * math.asin(math.sqrt(h))


def _hour_deltas(series, acc):
    """Accumulate contiguous hourly deltas per hour-of-day into acc."""
    for i in range(1, len(series)):
        dt = (series[i][0] - series[i - 1][0]).total_seconds()
        if dt == 3600:
            acc.setdefault(series[i][0].hour, []).append(series[i][1] - series[i - 1][1])


# Cache fleet drift per cutoff hour: at a given T, every task's fleet
# (own + neighbours) covers the same stations truncated at <= T-1h, so the
# aggregate is identical and safe to reuse. Keyed by target_time.
_FLEET_CACHE = {}


def _fleet_drift(key, own_series, neighbors):
    """Fleet-wide median hourly delta per hour-of-day, cached."""
    hit = _FLEET_CACHE.get(key)
    if hit is not None:
        return hit
    fleet = {}
    _hour_deltas(own_series, fleet)
    for nb in neighbors or []:
        ns = nb.get("series") or []
        if ns:
            _hour_deltas(sorted(ns, key=lambda p: p[0]), fleet)
    drift = {h: _median(vs) for h, vs in fleet.items() if len(vs) >= 30}
    if len(_FLEET_CACHE) > 400:
        _FLEET_CACHE.clear()
    _FLEET_CACHE[key] = drift
    return drift


def _drift(own_series, neighbors, target_hour, target_time):
    """Expected hourly delta at target_hour: own history shrunk toward 0,
    blended with the fleet-wide (own + all neighbours) median drift."""
    own = {}
    _hour_deltas(own_series, own)
    d_own = 0.0
    if target_hour in own:
        vs = own[target_hour]
        d_own = _median(vs) * len(vs) / (len(vs) + DRIFT_OWN_LAM)
    d_fleet = _fleet_drift(target_time, own_series, neighbors).get(target_hour, 0.0)
    return DRIFT_OWN_W * d_own + (1.0 - DRIFT_OWN_W) * d_fleet


def predict(station, neighbors, target_time):
    s = station.get("series") or []
    if not s:
        return None
    s = sorted(s, key=lambda p: p[0])
    t_last, v_last = s[-1]

    vals = [v for _, v in s]
    clean = _despike(vals)

    # robust local level: median of the last LEVEL_WIN despiked values
    tail = clean[-LEVEL_WIN:]
    level = _median(tail)

    # mean reversion toward the robust level (soft spike guard)
    pred = v_last + REVERT * (level - v_last)

    # expected diurnal drift (own shrunk + fleet-wide median delta at this hour)
    pred += DRIFT_SCALE * _drift(s, neighbors, target_time.hour, target_time)

    # diurnal rescale from last observed hour to target hour (shrunk toward 1)
    dm = _diurnal_means(s)
    mu_from = dm.get(t_last.hour)
    mu_to = dm.get(target_time.hour)
    if mu_from and mu_to and mu_from >= DIURNAL_MIN:
        ratio = mu_to / mu_from
        ratio = 1.0 + DIURNAL_SHRINK * (ratio - 1.0)
        ratio = min(max(ratio, 0.6), 1.7)
        pred *= ratio

    # staleness: if the last own reading is older than ~1h, lean more on the level
    stale_h = max(0.0, (target_time - t_last).total_seconds() / 3600.0 - 1.0)
    if stale_h > 0:
        f = 1.0 - math.exp(-stale_h / 6.0)
        pred = (1 - f) * pred + f * level

    # neighbour consensus: median of the nearest fresh readings,
    # rescaled by the ratio of overall medians (robust station offset)
    if W_NEIGHBOR > 0 and neighbors:
        origin = (station.get("lat"), station.get("lon"))
        overall_med = _median(clean) or v_last
        cands = []  # (dist, translated)
        for nb in neighbors:
            ns = nb.get("series") or []
            if not ns:
                continue
            ns = sorted(ns, key=lambda p: p[0])
            tn, vn = ns[-1]
            if (target_time - tn).total_seconds() > NEIGHBOR_FRESH_H * 3600:
                continue
            nmed = _median([v for _, v in ns]) or vn
            if nmed <= 0:
                continue
            trans = vn * overall_med / nmed
            try:
                d = _haversine_km(origin, (nb.get("lat"), nb.get("lon")))
            except (TypeError, ValueError):
                continue
            cands.append((d, trans))
        if cands:
            cands.sort(key=lambda p: p[0])
            used = cands[:NEIGHBOR_MAX]
            nb_cons = _median([v for _, v in used])
            if nb_cons is not None:
                pred = (1 - W_NEIGHBOR) * pred + W_NEIGHBOR * nb_cons

    # robust historical range clamp
    hist_sorted = sorted(clean)
    lo = hist_sorted[max(0, int(0.01 * len(hist_sorted)))]
    hi = hist_sorted[min(len(hist_sorted) - 1, int(0.995 * len(hist_sorted)))]
    pred = min(max(pred, 0.3 * lo), 1.5 * hi + 5.0)

    return max(0.0, pred)
