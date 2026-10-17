"""Strategy: regime-classified spike dynamics for +1h PM2.5 nowcast.

Offline findings that shaped this candidate (leak-free analysis on the
truncated histories):

- After a fresh up-jump >= 20 ug the next-hour delta has median ~ -15 ug;
  the implied reversion is ~30% of the gap to the 24h baseline.  Mild
  elevations (anomaly 1.1-1.6x climatology) revert almost fully next hour
  (MAE-optimal persistence PHI ~ 0.05-0.3), while *low* anomalies persist
  (PHI ~ 0.7-0.8) and fresh big spikes sit near PHI ~ 0.45-0.5.
- The previous champion (median ensemble) loses 35% of its total error in
  "spike-in" states and under-predicts sustained rises (mean bias +3.6);
  calm states carry another 38% of error.

Design (all inputs truncated to <= T-1h by the harness):

1.  Features: despiked history, robust diurnal profile D[h] (per-hour
    medians, circularly smoothed, normalized), climatology path
    clim(h) = overall_med * D[h], smoothed last value lv, anomaly
    an = lv / clim(h_last), last deltas d1/d2, 24h robust level.
2.  Regime classification from (an, d1, d2): calm / rising / fresh spike /
    post-spike decay / sustained high / dip.
3.  Three sub-predictors combined by weighted median:
      P_diu   = clim(T) * (1 + (an - 1) * PHI(an))   regime-conditional
                anomaly persistence (piecewise-linear in an);
      P_anchor = LAM_LAST * last + (1-LAM_LAST) * wmed(same hour +/-1h,
                recency-decayed);
      P_drift = last + REVERT * (level24 - last) + expected diurnal drift,
                rescaled by the shrunk diurnal ratio.
4.  Spike overlays:
      fresh spike (d1 >= SPIKE_D1): blend toward an additive decay
        pred_spike = base_T + SPIKE_KEEP * (last - base_T);
      post-spike decay (an high, d1 < 0): extra reversion gain (tuned to 0
        -- the PHI schedule already handles it);
      sustained rise (d1, d2 > 0, moderate an): damped extrapolation.
5.  Staleness fade toward the robust level; neighbour-consensus fusion in
    calm regimes; robust range clamp.

Rejected after measurement: regional-anomaly (neighbour-synchronised)
conditioning of the persist/revert decision in sustained-high states --
too weak to separate persistence from collapse; yesterday-same-hour anchor
term (W_YDAY -> 0); explicit post-spike decay gain (DECAY_GAIN -> 0).

Pure stdlib; no network.  Tunables at module top were fitted with the
in-process tuner candidates/_sweep_regime2.py (coordinate descent on the
leak-free bench protocol, objective ACC then HIT10; converged, third pass
found no further improvement).

Final bench (bench_nowcast.py, PYTHONHASHSEED=0, n=684):
  ALL    ACC 0.7049 / MAE 4.14 / HIT10 0.3874
  HALF-A ACC 0.7353 | HALF-B ACC 0.6740  (champion: 0.6947; A 0.7274; B 0.6613)
"""

from __future__ import annotations

import math
from datetime import timedelta

# ---- despike / level ----
DESPIKE_WIN = 7
DESPIKE_K = 2.0
LEVEL_WIN = 24

# ---- diurnal profile ----
SMOOTH = 1
SMOOTH_LV = 0.5      # weight of previous 2h in the level estimate

# ---- regime-conditional anomaly persistence PHI(an) ----
# piecewise-linear schedule over anomaly knots
AN_KNOTS = (0.0, 0.7, 0.9, 1.1, 1.3, 1.6, 2.2, 1e9)
PHI_KNOTS = (1.0, 0.6, 0.65, 0.2, 0.55, 0.0, 0.55, 0.45)

# ---- fresh spike overlay (additive decay toward diurnal-anchored base) ----
SPIKE_D1 = 24.0      # last-hour delta that flags a fresh spike
SPIKE_KEEP = 0.80    # fraction of the (last - base) gap kept after +1h
SPIKE_BLEND = 0.4    # how strongly the overlay overrides the base combo

# ---- post-spike decay overlay (still elevated, already falling) ----
DECAY_AN = 1.4       # anomaly threshold for "post-spike decay"
DECAY_D1 = 0.0       # must already be falling
DECAY_GAIN = 0.0     # extra reversion: pred -= GAIN * (pred - base_T)

# ---- sustained rise overlay (damped extrapolation) ----
RISE_AN_MAX = 1.1    # only when not already spiking
RISE_GAIN = 0.2      # pred += GAIN * damped recent slope
RISE_CAP = 6.0

# ---- anchor sub-predictor ----
LAM_LAST = 0.05
W_YDAY = 0.0
HOUR_SPREAD = 1
DAY_DECAY = 0.85

# ---- drift sub-predictor ----
REVERT = 0.3
DRIFT_SCALE = 2.6
DRIFT_OWN_W = 0.2
DRIFT_OWN_LAM = 20.0
DIURNAL_SHRINK = 0.3
DIURNAL_MIN = 1.0

# ---- combination ----
W_COMBO = (1.0, 1.0, 1.0)   # weights of (P_diu, P_anchor, P_drift): weighted median

# ---- neighbours (calm regimes only) ----
W_NEIGHBOR = 0.15
NEIGHBOR_MAX = 6
NEIGHBOR_FRESH_H = 4.0
NEIGH_CALM_ONLY = 1        # 1 = skip fusion when |an-1| > NEIGH_AN_BAND or |d1| large
NEIGH_AN_BAND = 0.5
NEIGH_D1_BAND = 5.0

# ---- staleness / clamp ----
STALE_TAU = 12.0
CLAMP_LO_M = 0.3
CLAMP_HI_M = 1.5
CLAMP_ADD = 5.0


# ---------------------------------------------------------------------------
# helpers

def _median(xs):
    xs = sorted(xs)
    n = len(xs)
    if n == 0:
        return None
    m = n // 2
    return xs[m] if n % 2 else 0.5 * (xs[m - 1] + xs[m])


def _despike(vals):
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
    return [m if abs(v - m) > DESPIKE_K * sigma else v
            for v, m in zip(vals, med)]


def _diurnal(series):
    by = [[] for _ in range(24)]
    for t, v in series:
        by[t.hour].append(v)
    overall = _median([v for _, v in series])
    if not overall or overall <= 0:
        return None, None
    filled = [m if m is not None else overall for m in (_median(b) for b in by)]
    for _ in range(SMOOTH):
        filled = [0.5 * filled[h] + 0.25 * filled[(h - 1) % 24] + 0.25 * filled[(h + 1) % 24]
                  for h in range(24)]
    return [f / overall for f in filled], overall


def _haversine_km(a, b):
    r = 6371.0
    p1, p2 = math.radians(a[0]), math.radians(b[0])
    dp = math.radians(b[0] - a[0])
    dl = math.radians(b[1] - a[1])
    h = math.sin(dp / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
    return 2 * r * math.asin(math.sqrt(h))


def _hour_deltas(series, acc):
    for i in range(1, len(series)):
        dt = (series[i][0] - series[i - 1][0]).total_seconds()
        if dt == 3600:
            acc.setdefault(series[i][0].hour, []).append(series[i][1] - series[i - 1][1])


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
            _hour_deltas(sorted(ns, key=lambda p: p[0]), fleet)
    drift = {h: _median(vs) for h, vs in fleet.items() if len(vs) >= 30}
    if len(_FLEET_CACHE) > 400:
        _FLEET_CACHE.clear()
    _FLEET_CACHE[key] = drift
    return drift


def _drift(own_series, neighbors, target_hour, target_time):
    own = {}
    _hour_deltas(own_series, own)
    d_own = 0.0
    if target_hour in own:
        vs = own[target_hour]
        d_own = _median(vs) * len(vs) / (len(vs) + DRIFT_OWN_LAM)
    d_fleet = _fleet_drift(target_time, own_series, neighbors).get(target_hour, 0.0)
    return DRIFT_OWN_W * d_own + (1.0 - DRIFT_OWN_W) * d_fleet


def _wmed_hour(hist, target_time):
    t0 = hist[-1][0]
    th = target_time.hour
    items = []
    for t, v in hist:
        dh = abs(((t.hour - th + 12) % 24) - 12)
        if dh <= HOUR_SPREAD:
            age_days = (t0 - t).total_seconds() / 86400.0
            items.append((v, DAY_DECAY ** age_days))
    if not items:
        return _median([v for _, v in hist[-24:]])
    items.sort(key=lambda p: p[0])
    total = sum(w for _, w in items)
    acc = 0.0
    for v, w in items:
        acc += w
        if acc >= 0.5 * total:
            return v
    return items[-1][0]


def _phi(an):
    """Piecewise-linear regime-conditional anomaly persistence."""
    knots, vals = AN_KNOTS, PHI_KNOTS
    if an <= knots[0]:
        return vals[0]
    for i in range(1, len(knots)):
        if an <= knots[i]:
            f = (an - knots[i - 1]) / (knots[i] - knots[i - 1])
            return vals[i - 1] + f * (vals[i] - vals[i - 1])
    return vals[-1]


def _wmedian(pairs):
    """Weighted median of (value, weight) pairs."""
    items = sorted(pairs, key=lambda p: p[0])
    total = sum(w for _, w in items)
    if total <= 0:
        return items[len(items) // 2][0]
    acc = 0.0
    for v, w in items:
        acc += w
        if acc >= 0.5 * total:
            return v
    return items[-1][0]


# ---------------------------------------------------------------------------
# feature extraction (shared with the tuner)

def extract(station, neighbors, target_time):
    """Compute all expensive features once; returns None if not predictable."""
    s = [(t, float(v)) for t, v in (station.get("series") or []) if v is not None]
    if not s:
        return None
    s = sorted(s, key=lambda p: p[0])
    t_last, v_last = s[-1]

    vals = [v for _, v in s]
    clean = _despike(vals)
    level = _median(clean[-LEVEL_WIN:])

    D, overall = _diurnal(s)
    if D is None:
        return None
    climT = overall * D[target_time.hour]
    climL = max(overall * D[t_last.hour], 1e-6)

    lv = v_last
    if SMOOTH_LV > 0.0 and len(s) >= 3:
        lv = (1.0 - SMOOTH_LV) * v_last + SMOOTH_LV * (0.6 * s[-2][1] + 0.4 * s[-3][1])
    an = lv / climL

    d1 = v_last - s[-2][1] if len(s) >= 2 else 0.0
    d2 = s[-2][1] - s[-3][1] if len(s) >= 3 else 0.0

    # diurnal ratio last hour -> target hour (shrunk)
    ratio = 1.0
    mu_from, mu_to = overall * D[t_last.hour], overall * D[target_time.hour]
    if mu_from >= DIURNAL_MIN:
        ratio = mu_to / mu_from
        ratio = 1.0 + DIURNAL_SHRINK * (ratio - 1.0)
        ratio = min(max(ratio, 0.6), 1.7)

    drift = _drift(s, neighbors, target_time.hour, target_time)

    # anchor
    base_anchor = _wmed_hour(s, target_time)
    yday = {t: v for t, v in s}.get(target_time - timedelta(hours=24))
    if yday is not None:
        base_anchor = (1.0 - W_YDAY) * base_anchor + W_YDAY * yday

    # staleness
    stale_h = max(0.0, (target_time - t_last).total_seconds() / 3600.0 - 1.0)

    # neighbour consensus (translated by overall-median ratio, nearest fresh)
    nb_cons = None
    if neighbors:
        origin = (station.get("lat"), station.get("lon"))
        overall_med = _median(clean) or v_last
        cands = []
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
            try:
                dd = _haversine_km(origin, (nb.get("lat"), nb.get("lon")))
            except (TypeError, ValueError):
                continue
            cands.append((dd, vn * overall_med / nmed))
        if cands:
            cands.sort(key=lambda p: p[0])
            nb_cons = _median([v for _, v in cands[:NEIGHBOR_MAX]])

    # clamp bounds
    hs = sorted(clean)
    lo = hs[max(0, int(0.01 * len(hs)))]
    hi = hs[min(len(hs) - 1, int(0.995 * len(hs)))]

    return {
        "v_last": v_last, "lv": lv, "an": an, "d1": d1, "d2": d2,
        "climT": climT, "climL": climL, "level": level, "ratio": ratio,
        "drift": drift, "base_anchor": base_anchor, "stale_h": stale_h,
        "nb_cons": nb_cons, "lo": lo, "hi": hi,
        "yday": yday,
    }


def combine(f):
    """Combine features into a prediction using module-level tunables."""
    an, d1, d2 = f["an"], f["d1"], f["d2"]
    v_last, climT, level = f["v_last"], f["climT"], f["level"]

    # --- sub-predictors ---
    phi = _phi(an)
    p_diu = climT * (1.0 + (an - 1.0) * phi)

    p_anchor = LAM_LAST * v_last + (1.0 - LAM_LAST) * f["base_anchor"]

    p_drift = v_last + REVERT * (level - v_last) + DRIFT_SCALE * f["drift"]
    p_drift *= f["ratio"]

    pred = _wmedian(list(zip((p_diu, p_anchor, p_drift), W_COMBO)))

    # diurnal-anchored base for the additive spike/decay overlays
    base_T = level * f["ratio"]

    # --- regime overlays ---
    # fresh spike: additive exponential decay toward the diurnal-anchored base
    if d1 >= SPIKE_D1:
        p_spike = base_T + SPIKE_KEEP * (v_last - base_T)
        blend = SPIKE_BLEND * min(1.0, d1 / (2.0 * SPIKE_D1))
        pred = (1.0 - blend) * pred + blend * p_spike
    # post-spike decay: still elevated but already falling -> revert harder
    elif an >= DECAY_AN and d1 <= DECAY_D1:
        pred -= DECAY_GAIN * max(0.0, pred - base_T)
    # sustained moderate rise: damped extrapolation
    elif d1 > 1.5 and d2 > 0 and an < RISE_AN_MAX:
        slope = min(0.6 * d1 + 0.4 * d2, RISE_CAP)
        pred += RISE_GAIN * slope

    # staleness fade toward the robust level
    if f["stale_h"] > 0:
        stale_f = 1.0 - math.exp(-f["stale_h"] / STALE_TAU)
        pred = (1.0 - stale_f) * pred + stale_f * level

    # neighbour consensus, only in calm regimes (spikes are local)
    if (W_NEIGHBOR > 0 and f["nb_cons"] is not None and
            (not NEIGH_CALM_ONLY or
             (abs(an - 1.0) <= NEIGH_AN_BAND and abs(d1) <= NEIGH_D1_BAND))):
        pred = (1.0 - W_NEIGHBOR) * pred + W_NEIGHBOR * f["nb_cons"]

    pred = min(max(pred, CLAMP_LO_M * f["lo"]), CLAMP_HI_M * f["hi"] + CLAMP_ADD)
    return max(0.0, pred)


def predict(station, neighbors, target_time):
    f = extract(station, neighbors, target_time)
    if f is None:
        return None
    return combine(f)
