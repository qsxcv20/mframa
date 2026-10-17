"""Fast in-process tuner for cand_robust (replicates bench_nowcast loop)."""
import itertools
import json
import math
import sys
from datetime import datetime, timedelta

sys.path.insert(0, "candidates")
import cand_robust

SNAP = "data/snapshot.json"


def parse(ts):
    return datetime.fromisoformat(ts.replace("Z", "+00:00"))


def series(loc):
    return sorted(
        ((parse(h["hour_utc"]), float(h["value"]))
         for h in loc.get("hourly_pm25", []) if h.get("value") is not None),
        key=lambda x: x[0])


def build_tasks():
    d = json.load(open(SNAP, encoding="utf-8"))
    locs = [l for l in d["locations"] if len(series(l)) >= 96]
    tasks = []
    for i, loc in enumerate(locs):
        s = series(loc)
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
            tasks.append(({"lat": loc["lat"], "lon": loc["lon"], "series": hist},
                          neighbors, T, actual))
    return tasks


def metrics(results):
    n = len(results)
    errs = [abs(a - p) for a, p in results]
    mae = sum(errs) / n
    wmape = sum(errs) / max(sum(abs(a) for a, _ in results), 1e-9)
    hit10 = sum(1 for (a, _), e in zip(results, errs) if e <= max(0.10 * a, 1.5)) / n
    hit2 = sum(1 for e in errs if e <= 2.0) / n
    return round(mae, 2), round(1 - wmape, 4), round(hit10, 4), round(hit2, 4)


def run(tasks, **kw):
    for k, v in kw.items():
        setattr(cand_robust, k, v)
    res = []
    for st, nb, T, a in tasks:
        p = cand_robust.predict(st, nb, T)
        if p is not None:
            res.append((a, max(0.0, float(p))))
    return metrics(res)


if __name__ == "__main__":
    tasks = build_tasks()
    print("tasks:", len(tasks))
    base = {}
    print("base  ", run(tasks, **base))
    grid = {
        "REVERT": [0.2, 0.35, 0.45, 0.6, 0.8],
        "LEVEL_WIN": [3, 4, 6, 9, 12],
        "W_NEIGHBOR": [0.0, 0.15, 0.25, 0.4],
        "CAP_MULT": [1.5, 2.5, 4.0, 8.0],
        "DIURNAL_SHRINK": [0.0, 0.3, 0.5, 0.8],
    }
    best = dict(REVERT=0.45, LEVEL_WIN=6, W_NEIGHBOR=0.25, CAP_MULT=2.5,
                DIURNAL_SHRINK=0.5)
    best_score = run(tasks, **best)
    print("start ", best_score, best)
    for _ in range(2):  # two coordinate-descent passes
        for key, vals in grid.items():
            for v in vals:
                trial = dict(best)
                trial[key] = v
                sc = run(tasks, **trial)
                # objective: ACC first, then HIT10
                if (sc[1], sc[2]) > (best_score[1], best_score[2]):
                    best_score = sc
                    best = trial
            print(f"after {key}: {best_score} {best}")
    print("BEST  ", best_score, best)
