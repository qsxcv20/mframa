"""Strategy: spatial statistics with online neighbour-reliability learning.

Core idea: a neighbour's usefulness is not a fixed function of distance — it
depends on the station pair and on recent conditions.  For every (station,
neighbour) pair we maintain, using ONLY data <= target-1h:

  * a lag-1 anomaly regression  an_own(h+1) ~ 1 + b_j * (an_nb(h) - 1)
    (anomalies are value / diurnal-profile level, so neighbour readings are
    expressed on the station's own scale);
  * an exponentially-weighted record of the pair's recent +1h translation
    errors (REPLAY_GAMMA decay per hour) -> the pair's *reliability*;
  * a variogram prior: lag-0 anomaly correlation vs distance is fitted online
    over all station pairs (rho(d) = c0 * exp(-d/L)); pairs with little
    overlap fall back to this distance-based prior (shrunk by sample count).

Prediction (what survived bench iteration):

  1. Own gated diurnal-anomaly nowcast: the station's smoothed current level
     is expressed as an anomaly vs its robust diurnal profile and decayed
     toward climatology with PHI^age.  The decay rate is *gated* by the
     reliability-weighted regional anomaly: a deviation the neighbourhood
     confirms (same sign) is likely regional (harmattan haze, rush hour) and
     reverts slowly (PHI up to PHI_HI); an unconfirmed one is likely a local
     spike / sensor artefact and reverts fast (down to PHI_LO).
  2. The gated anomaly is fused by median with two sibling nowcasts
     (cand_robust, cand_regime — imported read-only, same pattern as
     cand_ensemble.py).  The own component alone beats cand_diurnal, so the
     trio edges past the champion ensemble.
  3. Robust historical range clamp.

Measured and rejected (ALL ACC, n=684): blending a reliability-weighted
neighbour *level* consensus into the prediction — monotonically worse the
more weight it gets (inverse-error online mixing chose ~0 itself), so the
mechanism is retained behind LSCALE/LMAX = 0; 4-way median with
cand_diurnal (0.6950 < 0.6974); DIU_SMOOTH = 2; PHI outside 0.55-0.65.

Leak-free: every quantity is computed from series truncated at <= T-1h.
The only cross-call cache is the variogram fit keyed by target_time — at a
given T every task sees the same stations truncated at <= T-1h, so the fit
is identical work, not shared state.

Pure stdlib; no network.
"""

from __future__ import annotations

import importlib.util
import math
from datetime import timedelta
from pathlib import Path

H = timedelta(hours=1)

# Own-base siblings (same pattern as cand_ensemble.py): the robust and regime
# nowcasts are imported read-only and fused with this file's gated
# diurnal-anomaly predictor.  If the siblings are unavailable the predictor
# degrades gracefully to the gated diurnal anomaly alone.
def _load_sibling(name):
    try:
        spec = importlib.util.spec_from_file_location(
            name, Path(__file__).parent / f"{name}.py")
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)
        return mod
    except Exception:
        return None


_MOD_ROBUST = _load_sibling("cand_robust")
_MOD_REGIME = _load_sibling("cand_regime")
_MOD_DIURNAL = _load_sibling("cand_diurnal")
BASE_ENSEMBLE = True   # fuse own gated anomaly with the imported siblings
BASE_4WAY = False      # also include cand_diurnal as a 4th component

# ---- own-station base ----
PHI = 0.60           # anomaly persistence toward climatology
SMOOTH_LV = 0.35     # weight of previous 2h in the current level estimate
DIU_SMOOTH = 1       # circular smoothing passes on diurnal medians
DIU_FLOOR = 0.15     # floor on normalized diurnal profile entries

# ---- pair reliability ----
MIN_OVERLAP = 24     # min simultaneous hours to trust pair stats
REG_B = 1.0          # ridge on the anomaly slope (shrinks b toward 0)
REPLAY_GAMMA = 0.90  # per-hour decay of the online error record
EPS_E = 1.0          # error floor (ug/m3) inside reliability

# ---- variogram prior ----
PRIOR_N0 = 30.0      # pseudo-count blending prior vs observed reliability

# ---- consensus + mixing ----
PHI_NB = 0.5         # extra decay applied to neighbour anomalies
FRESH_H = 3.0        # max age (h) of a neighbour reading used in consensus
TOP_K = 8
MIX_REPLAY_H = 48    # hours replayed to score the consensus online
LSCALE = 0.0         # scale on inverse-error consensus weight (0 = off:
                     # level blending with neighbours measured worse on bench)
LMAX = 0.0           # hard cap on consensus weight
STALE_DECAY = 0.7    # extra anomaly decay per hour of neighbour staleness

# ---- regional gate ----
GATE_K = 0.6         # PHI shift per unit of (saturated) regional anomaly
GATE_SAT = 0.3       # regional anomaly magnitude at which the gate saturates
PHI_LO = 0.15
PHI_HI = 0.85

# ---- robust range clamp ----
CLAMP_LO_Q, CLAMP_HI_Q = 0.01, 0.995


def _median(xs):
    xs = sorted(xs)
    n = len(xs)
    if n == 0:
        return None
    m = n // 2
    return xs[m] if n % 2 else 0.5 * (xs[m - 1] + xs[m])


def _wmedian(items):
    """items: [(value, weight)] -> weighted median."""
    items = sorted(items)
    tot = sum(w for _, w in items)
    if tot <= 0:
        return None
    acc = 0.0
    for v, w in items:
        acc += w
        if acc >= 0.5 * tot:
            return v
    return items[-1][0]


def _hour_map(series):
    return {t.replace(minute=0, second=0, microsecond=0): float(v)
            for t, v in series if v is not None}


def _diurnal(hm):
    """Robust normalized diurnal profile D[hour] + overall median."""
    if not hm:
        return None, None
    by = [[] for _ in range(24)]
    for t, v in hm.items():
        by[t.hour].append(v)
    overall = _median(list(hm.values()))
    if not overall or overall <= 0:
        return None, None
    filled = [(_median(b) if b else overall) for b in by]
    for _ in range(DIU_SMOOTH):
        filled = [0.5 * filled[h] + 0.25 * filled[(h - 1) % 24]
                  + 0.25 * filled[(h + 1) % 24] for h in range(24)]
    # floor the profile: hours whose median is 0 would otherwise divide by 0
    return [max(f / overall, DIU_FLOOR) for f in filled], overall


def _hav_km(a_lat, a_lon, b_lat, b_lon):
    r = 6371.0
    p1, p2 = math.radians(a_lat), math.radians(b_lat)
    dp = math.radians(b_lat - a_lat)
    dl = math.radians(b_lon - a_lon)
    x = math.sin(dp / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
    return 2 * r * math.asin(math.sqrt(x))


# ---------------------------------------------------------------- variogram
# Fitted once per target_time: at a given T all tasks see the same stations
# truncated at <= T-1h, so this is identical work, not shared state.
_VARIO_CACHE = {}


def _anoms(hm, D, overall):
    return {t: v / (D[t.hour] * overall) for t, v in hm.items()}


def _pair_corr(a, b):
    """Pearson corr of simultaneous anomaly pairs (keys = hours)."""
    if len(a) > len(b):
        a, b = b, a
    xs, ys = [], []
    for t, v in a.items():
        w = b.get(t)
        if w is not None:
            xs.append(v)
            ys.append(w)
    n = len(xs)
    if n < 24:
        return None, n
    mx = sum(xs) / n
    my = sum(ys) / n
    sxx = sum((v - mx) ** 2 for v in xs)
    syy = sum((v - my) ** 2 for v in ys)
    if sxx <= 0 or syy <= 0:
        return None, n
    sxy = sum((x - mx) * (y - my) for x, y in zip(xs, ys))
    return sxy / math.sqrt(sxx * syy), n


def _variogram(key, own, neighbors):
    """Fit rho(d) = c0 * exp(-d/L) over all station pairs; returns f(d)->rho."""
    hit = _VARIO_CACHE.get(key)
    if hit is not None:
        return hit
    profs = []
    for st in [own] + list(neighbors or []):
        hm = _hour_map(st.get("series") or [])
        D, ov = _diurnal(hm)
        if D is None:
            continue
        profs.append(((st.get("lat"), st.get("lon")), _anoms(hm, D, ov)))
    pts = []  # (dist, rho)
    for i in range(len(profs)):
        for j in range(i + 1, len(profs)):
            (la, lo), aa = profs[i]
            (lb, ln), bb = profs[j]
            if la is None or lb is None:
                continue
            rho, n = _pair_corr(aa, bb)
            if rho is None:
                continue
            try:
                d = _hav_km(la, lo, lb, ln)
            except (TypeError, ValueError):
                continue
            pts.append((d, rho))
    best, best_sse = (0.3, 5.0), None
    for c0 in (0.2, 0.35, 0.5, 0.65, 0.8):
        for L in (1.0, 2.0, 4.0, 8.0, 16.0, 32.0):
            sse = sum((r - c0 * math.exp(-d / L)) ** 2 for d, r in pts)
            if best_sse is None or sse < best_sse:
                best_sse, best = sse, (c0, L)
    c0, L = best

    def prior(d):
        return c0 * math.exp(-d / L)

    if len(_VARIO_CACHE) > 200:
        _VARIO_CACHE.clear()
    _VARIO_CACHE[key] = prior
    return prior


# ------------------------------------------------------------------- model
def _own_level(hm, D, overall, hour):
    """Smoothed anomaly of the station at 'hour' (its latest reading <= hour)."""
    v = hm.get(hour)
    if v is None:
        return None, None
    lv = v
    if SMOOTH_LV > 0.0:
        v1 = hm.get(hour - H)
        v2 = hm.get(hour - 2 * H)
        if v1 is not None and v2 is not None:
            lv = (1.0 - SMOOTH_LV) * v + SMOOTH_LV * (0.6 * v1 + 0.4 * v2)
    return lv / (D[hour.hour] * overall), v


def predict(station, neighbors, target_time):
    hm = _hour_map(station.get("series") or [])
    if not hm:
        return None
    D, overall = _diurnal(hm)
    if D is None:
        return None
    t_ref = (target_time - H).replace(minute=0, second=0, microsecond=0)
    last_t = min(t_ref, max(hm))
    th = target_time.replace(minute=0, second=0, microsecond=0)

    # ---- own level anomaly (decay applied after the regional gate) ----
    an, v_last = _own_level(hm, D, overall, last_t)
    if an is None:
        return None
    age = max(1.0, (th - last_t).total_seconds() / 3600.0)

    # ---- own replay error eO (EWMA of recent +1h abs errors) ----
    eO = None
    h = last_t
    back = 0
    while back < 72:
        nxt = h + H
        actual = hm.get(nxt)
        a_h, _ = _own_level(hm, D, overall, h)
        if actual is not None and a_h is not None:
            pred = (1.0 + (a_h - 1.0) * PHI) * overall * D[nxt.hour]
            err = abs(pred - actual)
            eO = err if eO is None else REPLAY_GAMMA * eO + (1 - REPLAY_GAMMA) * err
        h -= H
        back += 1
    eO = eO if eO is not None else 5.0

    # ---- neighbour pair stats ----
    prior = _variogram(target_time, station, neighbors)
    slat, slon = station.get("lat"), station.get("lon")
    pairs = []
    for nb in neighbors or []:
        nm = _hour_map(nb.get("series") or [])
        if len(nm) < 12:
            continue
        Dn, on = _diurnal(nm)
        if Dn is None:
            continue
        try:
            d = _hav_km(slat, slon, nb.get("lat"), nb.get("lon"))
        except (TypeError, ValueError):
            continue

        # collect lag-1 anomaly pairs (neighbour at h -> station at h+1)
        obs = []  # (h, xa, y)
        h = last_t
        back = 0
        while back < 96:
            x = nm.get(h)
            y = hm.get(h + H)
            if x is not None and y is not None:
                xa = x / (Dn[h.hour] * on) - 1.0
                obs.append((h, xa, y))
            h -= H
            back += 1
        n_pair = len(obs)
        if n_pair == 0:
            continue
        sxy = sum(xa * (y / (D[(h + H).hour] * overall) - 1.0) for h, xa, y in obs)
        sxx = sum(xa * xa for _, xa, _ in obs)
        b = sxy / (sxx + REG_B)

        # pair's online error record: EWMA (recent first) of +1h translation
        eJ = None
        for h, xa, y in obs:  # obs is already most-recent-first
            pred = (1.0 + PHI_NB * b * xa) * overall * D[(h + H).hour]
            err = abs(pred - y)
            eJ = err if eJ is None else REPLAY_GAMMA * eJ + (1 - REPLAY_GAMMA) * err

        # reliability: observed EWMA error shrunk toward variogram prior
        rho_prior = prior(d)
        rel_prior = max(rho_prior, 0.0) / (eO + EPS_E)
        if eJ is not None and n_pair >= MIN_OVERLAP:
            rel_obs = 1.0 / (eJ + EPS_E)
            w_rel = (n_pair * rel_obs + PRIOR_N0 * rel_prior) / (n_pair + PRIOR_N0)
        else:
            w_rel = rel_prior
        if w_rel <= 0:
            continue

        # freshest reading for the consensus
        t_n = min(t_ref, max(nm))
        age_n = (th - t_n).total_seconds() / 3600.0
        if age_n > FRESH_H:
            continue
        xa_now = nm[t_n] / (Dn[t_n.hour] * on) - 1.0
        xa_now *= STALE_DECAY ** max(0.0, age_n - 1.0)
        trans = (1.0 + PHI_NB * b * xa_now) * overall * D[th.hour]
        pairs.append({"w": w_rel, "trans": trans, "xa": xa_now, "b": b,
                      "nm": nm, "Dn": Dn, "on": on})

    # ---- regional gate: neighbours modulate the anomaly decay, not the
    # level.  A deviation confirmed by the reliable neighbourhood is likely
    # regional (harmattan haze, traffic rush) and persists; an unconfirmed
    # one is likely a local spike / sensor artefact and reverts fast.
    dev = an - 1.0
    phi_eff = PHI
    if pairs and GATE_K > 0.0:
        pairs.sort(key=lambda p: -p["w"])
        reg = _wmedian([(p["xa"], p["w"]) for p in pairs[:TOP_K]])
        if reg is not None:
            agree = dev * reg
            if agree >= 0:
                phi_eff = PHI + GATE_K * min(abs(reg), GATE_SAT)
            else:
                phi_eff = PHI - GATE_K * min(abs(reg), GATE_SAT)
            phi_eff = min(max(phi_eff, PHI_LO), PHI_HI)
    an_own = 1.0 + dev * (phi_eff ** age)
    own_pred = an_own * overall * D[th.hour]

    if BASE_ENSEMBLE and (_MOD_ROBUST is not None or _MOD_REGIME is not None):
        comps = [own_pred]
        mods = [_MOD_ROBUST, _MOD_REGIME]
        if BASE_4WAY:
            mods.append(_MOD_DIURNAL)
        for mod in mods:
            if mod is None:
                continue
            try:
                p = mod.predict(station, neighbors, target_time)
                if p is not None:
                    comps.append(float(p))
            except Exception:
                pass
        comps.sort()
        own_pred = comps[len(comps) // 2] if len(comps) % 2 else \
            0.5 * (comps[len(comps) // 2 - 1] + comps[len(comps) // 2])

    pred = own_pred
    if pairs:
        pairs.sort(key=lambda p: -p["w"])
        used = pairs[:TOP_K]
        cons = _wmedian([(p["trans"], p["w"]) for p in used])
        if cons is not None:
            # consensus online error: replay the SAME weighted median of
            # translated anomalies over recent hours (today's weights,
            # historical values)
            eC = None
            h = last_t
            back = 0
            while back < MIX_REPLAY_H:
                nxt = h + H
                actual = hm.get(nxt)
                if actual is not None:
                    items = []
                    for p in used:
                        x = p["nm"].get(h)
                        if x is None:
                            continue
                        xa = x / (p["Dn"][h.hour] * p["on"]) - 1.0
                        tr = (1.0 + PHI_NB * p["b"] * xa) * overall * D[nxt.hour]
                        items.append((tr, p["w"]))
                    if len(items) >= 2:
                        cp = _wmedian(items)
                        err = abs(cp - actual)
                        eC = err if eC is None else REPLAY_GAMMA * eC + (1 - REPLAY_GAMMA) * err
                h -= H
                back += 1
            if eC is not None:
                lam = LSCALE * eO / (eO + eC + EPS_E)
                lam = min(LMAX, lam)
                pred = (1.0 - lam) * own_pred + lam * cons

    # ---- robust range clamp ----
    vals = sorted(hm.values())
    lo = vals[max(0, int(CLAMP_LO_Q * len(vals)))]
    hi = vals[min(len(vals) - 1, int(CLAMP_HI_Q * len(vals)))]
    pred = min(max(pred, 0.3 * lo), 1.5 * hi + 5.0)
    return max(0.0, pred)
