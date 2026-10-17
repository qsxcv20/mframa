"""In-process parameter sweep replicating bench_nowcast protocol (dev tool)."""

import importlib.util
import itertools
import json
import math
import sys
from datetime import timedelta

SNAP = "data/snapshot.json"


def parse(ts):
    from datetime import datetime
    return datetime.fromisoformat(ts.replace("Z", "+00:00"))


def series(loc):
    return sorted(
        ((parse(h["hour_utc"]), float(h["value"]))
         for h in loc.get("hourly_pm25", []) if h.get("value") is not None),
        key=lambda x: x[0])


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


def load_cases():
    d = json.load(open(SNAP, encoding="utf-8"))
    locs = [l for l in d["locations"] if len(series(l)) >= 96]
    cases = []
    for i, loc in enumerate(locs):
        s = series(loc)
        half_a = (hash(loc["name"]) % 2 == 0)
        for k in range(len(s) - 24, len(s), 2):
            T, actual = s[k]
            cutoff = T - timedelta(hours=1)
            hist = [(t, v) for t, v in s if t <= cutoff]
            if len(hist) < 72:
                continue
            neighbors = [
                {"lat": o["lat"], "lon": o["lon"],
                 "series": [(t, v) for t, v in series(o) if t <= cutoff]}
                for j, o in enumerate(locs) if j != i]
            cases.append(({"lat": loc["lat"], "lon": loc["lon"], "series": hist},
                          neighbors, T, actual, half_a))
    return cases


def evaluate(cand, cases):
    ra, rb = [], []
    for st, nb, T, actual, half_a in cases:
        try:
            p = cand.predict(st, nb, T)
        except Exception:
            continue
        if p is None:
            continue
        p = max(0.0, float(p))
        (ra if half_a else rb).append((actual, p))
    return metrics(ra + rb), metrics(ra), metrics(rb)


def main():
    spec = importlib.util.spec_from_file_location("cand", "candidates/cand_diurnal.py")
    cand = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(cand)
    cases = load_cases()
    print(f"cases: {len(cases)}")

    grids = {
        "GAMMA": [0.7, 0.85, 1.0, 1.15],
        "PERSIST_W": [0.0, 0.15, 0.3],
        "TRANS_W": [0.0, 0.3, 0.5, 0.7, 1.0],
        "SMOOTH": [0, 1, 2, 3],
        "DAMP": [0.0, 0.2, 0.35, 0.5],
        "TREND_H": [2, 3, 4],
        "TREND_W": [0.0, 0.15, 0.3],
        "NEIGH_W": [0.0, 0.15, 0.3],
        "MIN_DENOM": [2.0, 4.0, 8.0],
    }
    # coordinate descent from current defaults
    best = {k: getattr(cand, k) for k in grids}
    def score(cfg):
        for k, v in cfg.items():
            setattr(cand, k, v)
        allm, ma, mb = evaluate(cand, cases)
        return allm, ma, mb
    best_all, _, _ = score(best)
    print("start", best, best_all)
    improved = True
    while improved:
        improved = False
        for k, vals in grids.items():
            for v in vals:
                if v == best[k]:
                    continue
                trial = dict(best); trial[k] = v
                allm, ma, mb = score(trial)
                if allm["ACC"] > best_all["ACC"] + 1e-5:
                    best, best_all = trial, allm
                    improved = True
                    print("->", best, "ALL", allm, "A", ma, "B", mb)
    print("BEST", best, best_all)


if __name__ == "__main__":
    main()
