"""Offline sweep for cand_ensemble2 meta-parameters.

Replicates bench_nowcast's leak-free protocol, caches every base candidate's
prediction per (station, cutoff) once, then evaluates many Hedge variants
(learning rate, validation window, loss form, weighted mean vs weighted
median, median blending) in milliseconds each.

Usage: PYTHONHASHSEED=0 python candidates/_sweep_ensemble2.py
"""

import bisect
import importlib.util
import json
import math
import pickle
import sys
from datetime import datetime, timedelta
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SNAP = ROOT / "data" / "snapshot.json"
CACHE = ROOT / "candidates" / "_e2_cache.pkl"
H = timedelta(hours=1)

COMPS = ("cand_robust", "cand_diurnal", "cand_regime", "cand_persistence")


def _load(name):
    spec = importlib.util.spec_from_file_location(f"sw_{name}",
                                                  Path(__file__).parent / f"{name}.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


MODS = [_load(n) for n in COMPS]


def parse(ts):
    return datetime.fromisoformat(ts.replace("Z", "+00:00"))


def series(loc):
    return sorted(
        ((parse(h["hour_utc"]), float(h["value"]))
         for h in loc.get("hourly_pm25", []) if h.get("value") is not None),
        key=lambda x: x[0])


def build_cache():
    d = json.load(open(SNAP, encoding="utf-8"))
    locs = [l for l in d["locations"] if len(series(l)) >= 96]
    data = []  # per station: dict with series, half, targets
    for loc in locs:
        s = series(loc)
        targets = [s[k] for k in range(len(s) - 24, len(s), 2)]
        data.append({"name": loc["name"], "lat": loc["lat"], "lon": loc["lon"],
                     "series": s, "targets": targets,
                     "half_a": hash(loc["name"]) % 2 == 0})

    # all cutoffs needed: targets' T-1h and validation points' v-1h
    # validation window up to 48h back from last known time
    cache = {}  # (si, cutoff) -> [pred per comp]
    for si, st in enumerate(data):
        s = st["series"]
        times = [t for t, _ in s]
        actual = dict(s)
        cutoffs = set()
        for T, _ in st["targets"]:
            cutoffs.add(T - H)
            for v in [t for t, _ in s if T - H - timedelta(hours=48) < t <= T - H]:
                cutoffs.add(v - H)
        nb_all = [data[j] for j in range(len(data)) if j != si]
        nb_times = {j["name"]: [t for t, _ in j["series"]] for j in nb_all}
        for c in sorted(cutoffs):
            hi = bisect.bisect_right(times, c)
            if hi < 48:
                cache[(si, c)] = None
                continue
            hist = s[:hi]
            nbs = []
            for j in nb_all:
                k = bisect.bisect_right(nb_times[j["name"]], c)
                nbs.append({"lat": j["lat"], "lon": j["lon"], "series": j["series"][:k]})
            st_d = {"lat": st["lat"], "lon": st["lon"], "series": hist}
            preds = []
            for m in MODS:
                try:
                    p = m.predict(st_d, nbs, c + H)
                except Exception:
                    p = None
                preds.append(None if p is None else max(0.0, float(p)))
            cache[(si, c)] = preds
    with open(CACHE, "wb") as f:
        pickle.dump({"data": data, "cache": cache}, f)
    return data, cache


def wmedian(vals, wts):
    pairs = sorted(zip(vals, wts))
    tot = sum(wts)
    acc = 0.0
    for v, w in pairs:
        acc += w
        if acc >= 0.5 * tot:
            return v
    return pairs[-1][0]


def evaluate(data, cache, val_hours, eta, loss_form, comb, w_med, shrink,
             use_pers=True, alpha_med3=0.0, decay=1.0):
    """loss_form: 'mae' | 'norm' | 'sq' ; comb: 'mean' | 'wmed'.
    alpha_med3: final blend toward the plain median of the 3 strong comps."""
    res, res_a, res_b = [], [], []
    for si, st in enumerate(data):
        s = st["series"]
        actual = dict(s)
        s_times = [t for t, _ in s]
        for T, act in st["targets"]:
            cutoff = T - H
            preds = cache.get((si, cutoff))
            if preds is None or all(p is None for p in preds):
                continue
            idxs = list(range(len(MODS))) if use_pers else [0, 1, 2]
            losses = [0.0] * len(MODS)
            counts = [0] * len(MODS)
            lo_t = cutoff - timedelta(hours=val_hours)
            for vt in s_times:
                if vt <= lo_t or vt > cutoff:
                    continue
                vp = cache.get((si, vt - H))
                if vp is None:
                    continue
                a = actual[vt]
                age_h = (cutoff - vt).total_seconds() / 3600.0
                lw = decay ** age_h
                for i in idxs:
                    p = vp[i]
                    if p is None:
                        continue
                    e = abs(p - a)
                    if loss_form == "norm":
                        e /= max(a, 3.0)
                    elif loss_form == "sq":
                        e = e * e
                    losses[i] += lw * e
                    counts[i] += 1
            avg = [(losses[i] / counts[i] if counts[i] else None)
                   for i in range(len(MODS))]
            seen = [a for a in avg if a is not None]
            if not seen:
                continue
            worst = max(seen)
            nval = max(counts) if max(counts) else 1
            filled = [a if a is not None else worst for a in avg]
            best = min(filled)
            ws = [math.exp(-eta * nval * (a - best)) for a in filled]
            # shrinkage toward uniform
            uni = 1.0 / len(MODS)
            tot = sum(ws)
            ws = [(1 - shrink) * w / tot + shrink * uni for w in ws]
            live = [(preds[i], ws[i]) for i in idxs if preds[i] is not None]
            if not live:
                continue
            if comb == "wmed":
                blend = wmedian([p for p, _ in live], [w for _, w in live])
            else:
                tw = sum(w for _, w in live)
                blend = sum(p * w for p, w in live) / tw
            if w_med > 0:
                med = wmedian([p for p, _ in live], [1.0] * len(live))
                blend = (1 - w_med) * blend + w_med * med
            if alpha_med3 > 0:
                strong = [preds[i] for i in (0, 1, 2) if preds[i] is not None]
                if strong:
                    ss = sorted(strong)
                    m3 = ss[len(ss) // 2] if len(ss) % 2 else \
                        0.5 * (ss[len(ss) // 2 - 1] + ss[len(ss) // 2])
                    blend = (1 - alpha_med3) * blend + alpha_med3 * m3
            row = (act, blend)
            res.append(row)
            (res_a if st["half_a"] else res_b).append(row)
    return res, res_a, res_b


def metrics(results):
    n = len(results)
    if not n:
        return {"n": 0}
    errs = [abs(a - p) for a, p in results]
    mae = sum(errs) / n
    wmape = sum(errs) / max(sum(abs(a) for a, _ in results), 1e-9)
    hit10 = sum(1 for (a, _), e in zip(results, errs) if e <= max(0.10 * a, 1.5)) / n
    return {"n": n, "MAE": round(mae, 2), "ACC": round(1 - wmape, 4),
            "HIT10": round(hit10, 4)}


def main():
    if CACHE.exists() and "--rebuild" not in sys.argv:
        with open(CACHE, "rb") as f:
            blob = pickle.load(f)
        data, cache = blob["data"], blob["cache"]
        print(f"cache loaded: {len(cache)} entries")
    else:
        print("building cache (slow)...")
        data, cache = build_cache()
        print(f"cache built: {len(cache)} entries")

    # sanity: single-component performance
    for ci, cn in enumerate(COMS if False else COMPS):
        res = []
        for si, st in enumerate(data):
            for T, act in st["targets"]:
                p = cache.get((si, T - H))
                if p and p[ci] is not None:
                    res.append((act, p[ci]))
        print(f"  {cn:18s}", metrics(res))

    rows = []
    for decay in (1.0, 0.95, 0.9, 0.85):
        for val_hours in (6, 8, 10, 12, 16, 18, 24):
            for eta in (0.08, 0.12, 0.15, 0.2, 0.25, 0.3, 0.4):
                for loss_form in ("mae", "norm", "sq"):
                    r, ra, rb = evaluate(data, cache, val_hours, eta,
                                         loss_form, "wmed", 0.0, 0.0,
                                         False, 0.0, decay)
                    m = metrics(r)
                    rows.append((m["ACC"], m["MAE"], m["HIT10"],
                                 decay, val_hours, eta, loss_form,
                                 metrics(ra)["ACC"], metrics(rb)["ACC"]))
    rows.sort(reverse=True)
    print("\ntop 30 (ACC, MAE, HIT10, decay, vh, eta, loss, ACC_A, ACC_B):")
    for r in rows[:30]:
        print("  ACC %.4f MAE %.2f HIT10 %.4f | decay=%.2f vh=%d eta=%.2f %s | A %.4f B %.4f"
              % r)
    print("\nbaseline fixed-median-of-3 champion: ACC 0.6947 MAE 4.29 HIT10 0.3713")


if __name__ == "__main__":
    main()
