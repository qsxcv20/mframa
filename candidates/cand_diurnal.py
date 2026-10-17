"""Candidate: robust diurnal-ratio scaling with anomaly decay.

Final tuned form (see notes at bottom for what was tried and rejected):

1. Build a robust diurnal profile D[h] from the station's own history:
   per-hour medians (not means), circularly smoothed, normalized by the
   overall median so mean(D) ~ 1.
2. Smooth the last value with the previous 2 hours (kills sensor jitter).
3. Express the current level as an anomaly  an = lv / (D[h0] * overall_med)
   and decay it toward climatology:  an' = 1 + (an - 1) * PHI.
4. Predict  pred = an' * overall_med * D[T.hour].

A damped-trend term and a 1/d^2 neighbor-fusion term from the original
strategy are retained behind weights; backtest tuning set both to 0
(they consistently lowered ACC — see module notes).
"""

import math
import statistics

# tuned on bench_nowcast (coordinate descent + grid refinement)
PHI = 0.50           # anomaly persistence toward climatology (flat 0.4-0.55)
SMOOTH_LV = 0.35     # weight given to previous 2h in the level estimate
SMOOTH = 1           # circular smoothing passes on diurnal medians
TREND_W = 0.0        # damped-trend blend weight (tuned out: hurts ACC)
TREND_DAMP = 0.35
TREND_H = 3
NEIGH_W = 0.0        # neighbor fusion weight (tuned out: hurts ACC)
NEIGH_FRESH_H = 3
MIN_D_KM = 2.0


def _median(xs):
    return statistics.median(xs) if xs else None


def _diurnal(series):
    """Robust normalized diurnal profile D[hour]; normalized by overall median."""
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


def _hav_km(a_lat, a_lon, b_lat, b_lon):
    r = 6371.0
    p1, p2 = math.radians(a_lat), math.radians(b_lat)
    dp = math.radians(b_lat - a_lat)
    dl = math.radians(b_lon - a_lon)
    h = math.sin(dp / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
    return 2 * r * math.asin(math.sqrt(h))


def predict(station, neighbors, target_time):
    s = station["series"]
    if not s:
        return None
    D, overall = _diurnal(s)
    last_t, last_v = s[-1]
    if D is None:
        return last_v

    # de-noise the current level with the previous two hours
    lv = last_v
    if SMOOTH_LV > 0.0 and len(s) >= 3:
        lv = (1.0 - SMOOTH_LV) * last_v + SMOOTH_LV * (0.6 * s[-2][1] + 0.4 * s[-3][1])

    # anomaly relative to climatology, decayed toward 1
    an = lv / max(D[last_t.hour], 1e-6) / overall
    an = 1.0 + (an - 1.0) * PHI

    own = an * overall * D[target_time.hour]

    # damped recent-slope trend (weight tuned to 0 by backtest)
    if TREND_W > 0.0 and len(s) >= TREND_H + 1:
        t_old, v_old = s[-1 - TREND_H]
        dt_h = max((last_t - t_old).total_seconds() / 3600.0, 0.5)
        slope = (last_v - v_old) / dt_h
        trend_pred = last_v + slope * TREND_DAMP
        own = (1.0 - TREND_W) * own + TREND_W * trend_pred

    # neighbor fusion via own-diurnal translation (weight tuned to 0)
    if NEIGH_W > 0.0:
        num, den = 0.0, 0.0
        for n in neighbors:
            ns = n["series"]
            if not ns:
                continue
            nt, nv = ns[-1]
            age_h = (target_time - nt).total_seconds() / 3600.0
            if age_h < 0.5 or age_h > NEIGH_FRESH_H + 1:
                continue
            Dn, omn = _diurnal(ns)
            if Dn is None:
                continue
            norm = nv / max(Dn[nt.hour], 1e-6)          # neighbor normalized level
            translated = norm * overall * D[target_time.hour]
            d = max(_hav_km(station["lat"], station["lon"], n["lat"], n["lon"]), MIN_D_KM)
            w = 1.0 / (d * d)
            num += w * translated
            den += w
        if den > 0:
            own = (1.0 - NEIGH_W) * own + NEIGH_W * (num / den)

    return own


# Tuning log (bench_nowcast, 684 cases):
#   persistence baseline            ACC 0.581 / MAE 5.89 / HIT10 0.314
#   full diurnal ratio (PHI=1)      ACC 0.649
#   + anomaly decay PHI=0.5         ACC 0.681
#   + last-value smoothing 0.35     ACC 0.686 / MAE 4.41 / HIT10 0.358   <- final
# Rejected (all lowered or did not change ACC):
#   damped trend (any weight/damp), neighbor level translation (1/d^2),
#   regional anomaly median, regional change-ratio fusion, t-24h blend
#   (helps HIT10, costs ACC), anomaly clamping, lv = median of last 3,
#   hour-adaptive PHI, ratio exponent GAMMA != 1, transition-based ratios.
