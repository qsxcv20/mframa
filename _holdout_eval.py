"""Out-of-sample holdout evaluation: run candidates on a FRESH snapshot never
used during algorithm tuning. Reuses bench_nowcast.py's leak-free protocol.

Usage: PYTHONIOENCODING=utf-8 python _holdout_eval.py
"""

import importlib.util
import json
import sys
from datetime import datetime, timedelta

import bench_nowcast as B

HOLDOUT = "data/snapshot_holdout.json"
# tuning snapshot ended here; targets strictly after this are 100% unseen
TUNING_END = datetime.fromisoformat("2026-10-17T12:00:00+00:00")

CANDIDATES = [
    ("cand_regime2 (new champion)", "candidates/cand_regime2.py"),
    ("cand_ml (runner-up)", "candidates/cand_ml.py"),
    ("cand_ensemble (old champion)", "candidates/cand_ensemble.py"),
    ("cand_persistence (baseline)", "candidates/cand_persistence.py"),
]


def load_cand(path):
    spec = importlib.util.spec_from_file_location("cand_" + path, path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def evaluate(mod, locs):
    results, unseen = [], []
    for i, loc in enumerate(locs):
        s = B.series(loc)
        for k in range(len(s) - 24, len(s), 2):
            T, actual = s[k]
            cutoff = T - timedelta(hours=1)
            hist = [(t, v) for t, v in s if t <= cutoff]
            if len(hist) < 72:
                continue
            neighbors = [
                {"lat": o["lat"], "lon": o["lon"],
                 "series": [(t, v) for t, v in B.series(o) if t <= cutoff]}
                for j, o in enumerate(locs) if j != i
            ]
            try:
                pred = mod.predict(
                    {"lat": loc["lat"], "lon": loc["lon"], "series": hist},
                    neighbors, T)
            except Exception:
                continue
            if pred is None:
                continue
            row = (actual, max(0.0, float(pred)))
            results.append(row)
            if T > TUNING_END:
                unseen.append(row)
    return results, unseen


def main():
    d = json.load(open(HOLDOUT, encoding="utf-8"))
    locs = [l for l in d["locations"] if len(B.series(l)) >= 96]
    print(f"holdout snapshot: {HOLDOUT}  stations in bench: {len(locs)}")
    print(f"unseen cutoff: targets after {TUNING_END.isoformat()} "
          f"were never available during tuning\n")
    for name, path in CANDIDATES:
        mod = load_cand(path)
        all_r, unseen_r = evaluate(mod, locs)
        print(f"{name}")
        print(f"  last-24h protocol : {B.metrics(all_r)}")
        print(f"  unseen-only       : {B.metrics(unseen_r)}")
        print()


main()
