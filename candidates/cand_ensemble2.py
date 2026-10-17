"""Meta-ensemble: Hedge / exponential-weights online combination.

For every predict() call the station's own truncated history provides a
window of the most recent VAL_HOURS verifiable points (each hour h with an
observed value, h <= last known hour).  Every base candidate is re-run at
each such h on data truncated to <= h-1h (the same leak-free protocol the
bench uses), and its Hedge weight is

    w_i ~ exp(-ETA * n * (avgloss_i - best_avgloss))

with avgloss the mean normalized absolute error  |err| / max(actual, 3)
over the window, so the combination automatically leans toward whichever
component has been best *recently at this station*.  Only past errors set
the weights — no future data is ever used.

The final forecast is the *weighted median* of the components' predictions
for target_time.  The weighted median keeps the outlier immunity that made
the fixed median-of-3 champion strong, while the Hedge weights tilt it
toward the currently-best component.

Tuning (offline sweep replicating bench_nowcast's protocol on all 684
cases, candidates/_sweep_ensemble2.py):
- pure Hedge weighted MEAN over 4 comps (incl. persistence): ACC 0.6851
- Hedge weighted median over the 3 strong comps:             ACC 0.6972
- the optimum is a flat plateau (VAL_HOURS 10-18, ETA 0.15-0.20,
  recency decay ~1.0), i.e. not knife-edge overfitting.
Components: cand_robust, cand_diurnal, cand_regime.  cand_persistence and
cand_ls were measured too weak (ACC 0.58 / 0.61) and only dilute the pool.
"""

import bisect
import importlib.util
import math
from datetime import timedelta
from pathlib import Path

_HERE = Path(__file__).parent
H = timedelta(hours=1)

# ---- tunables (center of the swept plateau) ----
VAL_HOURS = 12        # recent verifiable points that set the weights
ETA = 0.15            # hedge learning rate on cumulative normalized abs error
LOSS_NORM = 3.0       # loss = |err| / max(actual, LOSS_NORM)
MIN_HIST = 48         # need at least this much history at a validation point

_COMPONENTS = ("cand_robust", "cand_diurnal", "cand_regime")


def _load(name):
    spec = importlib.util.spec_from_file_location(f"e2_{name}", _HERE / f"{name}.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


_MODS = [_load(n) for n in _COMPONENTS]


def _wmedian(vals, wts):
    pairs = sorted(zip(vals, wts))
    tot = sum(w for _, w in pairs)
    acc = 0.0
    for v, w in pairs:
        acc += w
        if acc >= 0.5 * tot:
            return v
    return pairs[-1][0]


def predict(station, neighbors, target_time):
    s = station.get("series") or []
    if not s:
        return None
    s = sorted(s, key=lambda p: p[0])
    lat, lon = station.get("lat", 0.0), station.get("lon", 0.0)

    # neighbor series sorted once for cheap truncation
    nb_sorted = []
    for nb in neighbors or []:
        ns = nb.get("series") or []
        if ns:
            ns = sorted(ns, key=lambda p: p[0])
            nb_sorted.append((nb.get("lat"), nb.get("lon"),
                              ns, [t for t, _ in ns]))

    def call_all(hist, nb_list, when):
        st_d = {"lat": lat, "lon": lon, "series": hist}
        out = []
        for m in _MODS:
            try:
                p = m.predict(st_d, nb_list, when)
            except Exception:
                p = None
            out.append(None if p is None else max(0.0, float(p)))
        return out

    s_times = [t for t, _ in s]
    actual = dict(s)

    # ---- hedge weights from the last VAL_HOURS verifiable points ----
    losses = [0.0] * len(_MODS)
    counts = [0] * len(_MODS)
    for vt in s_times[-VAL_HOURS:]:
        cutoff = vt - H
        hi = bisect.bisect_right(s_times, cutoff)
        if hi < MIN_HIST:
            continue
        hist = s[:hi]
        nb_trunc = [{"lat": la, "lon": lo,
                     "series": ns[:bisect.bisect_right(nts, cutoff)]}
                    for la, lo, ns, nts in nb_sorted]
        a = actual[vt]
        denom = max(a, LOSS_NORM)
        for i, p in enumerate(call_all(hist, nb_trunc, vt)):
            if p is not None:
                losses[i] += abs(p - a) / denom
                counts[i] += 1

    nval = max(counts)
    if nval == 0:
        weights = [1.0] * len(_MODS)
    else:
        avg = [(losses[i] / counts[i] if counts[i] else None)
               for i in range(len(_MODS))]
        seen = [x for x in avg if x is not None]
        worst = max(seen) if seen else 1.0
        filled = [x if x is not None else worst for x in avg]
        best = min(filled)
        weights = [math.exp(-ETA * nval * (x - best)) for x in filled]

    # ---- predictions at target_time -> weighted median ----
    nb_full = [{"lat": la, "lon": lo, "series": ns} for la, lo, ns, _ in nb_sorted]
    preds = call_all(s, nb_full, target_time)
    live = [(p, w) for p, w in zip(preds, weights) if p is not None]
    if not live:
        return None
    return max(0.0, _wmedian([p for p, _ in live], [w for _, w in live]))
