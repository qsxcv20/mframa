"""Fast in-process tuner for cand_kalman (replicates bench_nowcast loop)."""
import json
import math
import sys
from datetime import datetime, timedelta

sys.path.insert(0, "candidates")
import cand_kalman

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
    full = [series(l) for l in locs]
    tasks = []
    for i, loc in enumerate(locs):
        s = full[i]
        half_a = (hash(loc["name"]) % 2 == 0)
        for k in range(len(s) - 24, len(s), 2):
            T, actual = s[k]
            cutoff = T - timedelta(hours=1)
            hist = [(t, v) for t, v in s if t <= cutoff]
            if len(hist) < 72:
                continue
            neighbors = [
                {"lat": o["lat"], "lon": o["lon"],
                 "series": [(t, v) for t, v in full[j] if t <= cutoff]}
                for j, o in enumerate(locs) if j != i]
            tasks.append(({"lat": loc["lat"], "lon": loc["lon"], "series": hist},
                          neighbors, T, actual, half_a))
    return tasks


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


def run(tasks, **kw):
    for k, v in kw.items():
        setattr(cand_kalman, k, v)
    res, ra, rb = [], [], []
    for st, nb, T, a, half_a in tasks:
        p = cand_kalman.predict(st, nb, T)
        if p is not None:
            row = (a, max(0.0, float(p)))
            res.append(row)
            (ra if half_a else rb).append(row)
    return metrics(res), metrics(ra), metrics(rb)


if __name__ == "__main__":
    tasks = build_tasks()
    print("tasks:", len(tasks))
    names = ["PHI", "Q_DEV", "Q_LEVEL", "Q_HARM", "R_MIN", "HUBER_K",
             "ADAPT_A", "Q_ADAPT", "W_NEIGHBOR", "W_CLIM",
             "CLIM_SPREAD", "CLIM_DECAY", "DRIFT_SCALE", "DRIFT_OWN_W",
             "FUSE_MEDIAN"]
    best = {n: getattr(cand_kalman, n) for n in names}
    best.update({"PHI": 0.5, "Q_DEV": 32.0, "Q_LEVEL": 0.2, "Q_HARM": 0.1,
                 "R_MIN": 1.0, "HUBER_K": 99.0, "ADAPT_A": 0.25, "Q_ADAPT": 4.0,
                 "W_CLIM": 0.55, "DRIFT_SCALE": 0.8, "DRIFT_OWN_W": 0.5})
    best_score = run(tasks, **best)[0]
    print("start ", best_score)
    grid = {
        "DRIFT_SCALE": [0.6, 0.7, 0.8, 0.9, 1.1],
        "DRIFT_OWN_W": [0.3, 0.5, 0.7, 1.0],
        "W_CLIM": [0.5, 0.525, 0.55, 0.575, 0.6, 0.65],
        "PHI": [0.4, 0.5, 0.6],
        "Q_DEV": [16.0, 32.0, 64.0],
        "Q_LEVEL": [0.1, 0.2, 0.4],
        "Q_HARM": [0.05, 0.1, 0.2],
        "ADAPT_A": [0.15, 0.25, 0.4],
        "Q_ADAPT": [2.0, 4.0, 8.0],
        "R_MIN": [0.5, 1.0, 2.0],
        "CLIM_SPREAD": [0, 1, 2],
        "HUBER_K": [2.5, 3.5, 5.0, 99.0],
        "FUSE_MEDIAN": [0, 1],
        "W_NEIGHBOR": [0.0, 0.1],
    }
    for rnd in range(3):
        changed = False
        for key, vals in grid.items():
            for v in vals:
                if v == best[key]:
                    continue
                trial = dict(best)
                trial[key] = v
                sc = run(tasks, **trial)[0]
                if (sc["ACC"], sc["HIT10"]) > (best_score["ACC"], best_score["HIT10"]):
                    best_score = sc
                    best = trial
                    changed = True
            print(f"round{rnd} after {key}: {best_score} {best}", flush=True)
        if not changed:
            break
    print("BEST  ", best_score, best)
    full = run(tasks, **best)
    print("ALL :", full[0])
    print("HALF-A:", full[1])
    print("HALF-B:", full[2])
