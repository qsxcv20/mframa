"""Backtest harness for +1h PM2.5 nowcast candidates.

Usage:  python bench_nowcast.py candidates/cand_xxx.py

Protocol (leak-free): for every station with >=96h of hourly data, take the
last 24 hourly points (stride 2) as targets T. The candidate only receives
series truncated to <= T-1h — for the target station and all neighbors —
and must return a predicted value for T.

Candidate interface (module-level function):

    def predict(station: dict, neighbors: list[dict], target_time) -> float | None

    station:    {'lat': float, 'lon': float, 'series': [(datetime, value), ...]}
    neighbors:  [{'lat': float, 'lon': float, 'series': [...truncated...]}]
    target_time: datetime (timezone-aware, UTC)

Metrics printed for ALL stations and for deterministic halves A/B
(overfitting guard): MAE, RMSE, ACC (=1-WMAPE), MAPE (denom max(actual,3)),
HIT10 (|err| <= max(10%*actual, 1.5)), HIT2 (|err| <= 2.0).
"""

import importlib.util
import json
import math
import sys
from datetime import datetime, timedelta

SNAP = "data/snapshot.json"


def parse(ts: str) -> datetime:
    return datetime.fromisoformat(ts.replace("Z", "+00:00"))


def series(loc: dict):
    return sorted(
        ((parse(h["hour_utc"]), float(h["value"]))
         for h in loc.get("hourly_pm25", []) if h.get("value") is not None),
        key=lambda x: x[0],
    )


def metrics(results):
    n = len(results)
    if not n:
        return {"n": 0}
    errs = [abs(a - p) for a, p in results]
    mae = sum(errs) / n
    rmse = math.sqrt(sum(e * e for e in errs) / n)
    wmape = sum(errs) / max(sum(abs(a) for a, _ in results), 1e-9)
    mape = sum(e / max(a, 3.0) for (a, _), e in zip(results, errs)) / n
    hit10 = sum(1 for (a, _), e in zip(results, errs) if e <= max(0.10 * a, 1.5)) / n
    hit2 = sum(1 for e in errs if e <= 2.0) / n
    return {"n": n, "MAE": round(mae, 2), "RMSE": round(rmse, 2),
            "ACC": round(1 - wmape, 4), "MAPE": round(mape, 4),
            "HIT10": round(hit10, 4), "HIT2": round(hit2, 4)}


def main():
    if len(sys.argv) < 2:
        sys.exit("usage: python bench_nowcast.py <candidate.py>")
    spec = importlib.util.spec_from_file_location("cand", sys.argv[1])
    cand = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(cand)

    d = json.load(open(SNAP, encoding="utf-8"))
    locs = [l for l in d["locations"] if len(series(l)) >= 96]
    print(f"stations in bench: {len(locs)}")

    results, results_a, results_b = [], [], []
    errors = 0
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
                for j, o in enumerate(locs) if j != i
            ]
            try:
                pred = cand.predict(
                    {"lat": loc["lat"], "lon": loc["lon"], "series": hist},
                    neighbors, T)
            except Exception as e:
                errors += 1
                if errors <= 3:
                    print(f"ERR {loc['name']} {T}: {e}")
                continue
            if pred is None:
                continue
            pred = max(0.0, float(pred))
            (results_a if half_a else results_b).append((actual, pred))
            results.append((actual, pred))

    print("ALL :", metrics(results))
    print("HALF-A:", metrics(results_a))
    print("HALF-B:", metrics(results_b))
    if errors:
        print(f"(prediction errors: {errors})")


if __name__ == "__main__":
    main()
