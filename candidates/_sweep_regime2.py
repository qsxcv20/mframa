"""Fast in-process tuner for cand_regime2 (replicates bench_nowcast loop).

Two phases:
  A) combine-level coordinate descent on cached features (fast);
  B) extract-level coordinate descent, rebuilding features per trial (slow).
Objective: (ACC, HIT10). Snapshots and re-verifies the best state.
"""
import json
import sys
from datetime import datetime, timedelta

sys.path.insert(0, "candidates")
import cand_regime2 as C

SNAP = "data/snapshot.json"

C_PARAMS = ["SPIKE_D1", "SPIKE_KEEP", "SPIKE_BLEND", "DECAY_AN", "DECAY_D1",
            "DECAY_GAIN", "RISE_AN_MAX", "RISE_GAIN", "RISE_CAP", "LAM_LAST",
            "REVERT", "DRIFT_SCALE", "W_NEIGHBOR", "NEIGH_CALM_ONLY",
            "NEIGH_AN_BAND", "NEIGH_D1_BAND", "STALE_TAU", "CLAMP_LO_M",
            "CLAMP_HI_M", "CLAMP_ADD", "W_COMBO", "PHI_KNOTS"]
E_PARAMS = ["SMOOTH_LV", "LEVEL_WIN", "W_YDAY", "DAY_DECAY", "HOUR_SPREAD",
            "DIURNAL_SHRINK", "SMOOTH", "DRIFT_OWN_W", "NEIGHBOR_MAX",
            "NEIGHBOR_FRESH_H", "DESPIKE_K"]


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
    feats = []
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
            f = C.extract({"lat": loc["lat"], "lon": loc["lon"], "series": hist},
                          neighbors, T)
            if f is not None:
                feats.append((f, actual))
    return feats


def metrics(results):
    n = len(results)
    if not n:
        return (0, 0, 0, 0)
    errs = [abs(a - p) for a, p in results]
    mae = sum(errs) / n
    wmape = sum(errs) / max(sum(abs(a) for a, _ in results), 1e-9)
    hit10 = sum(1 for (a, _), e in zip(results, errs) if e <= max(0.10 * a, 1.5)) / n
    return (round(1 - wmape, 4), round(mae, 2), round(hit10, 4), n)


def run(feats):
    return metrics([(a, max(0.0, float(C.combine(f)))) for f, a in feats])


def snapshot():
    return {k: getattr(C, k) for k in C_PARAMS + E_PARAMS}


def restore(snap):
    for k, v in snap.items():
        setattr(C, k, v)


def descend(feats, grid, best, rebuild=None):
    """One coordinate-descent pass over grid [(name, values)]."""
    for name, vals in grid:
        cur = getattr(C, name)
        for v in vals:
            if v == cur:
                continue
            setattr(C, name, v)
            feats2 = rebuild() if rebuild else feats
            sc = run(feats2)
            if (sc[0], sc[2]) > (best[0], best[2]):
                best = sc
                cur = v
                if rebuild:
                    feats = feats2
            else:
                setattr(C, name, cur)
        print(f"  after {name:16s}: ACC={best[0]} MAE={best[1]} HIT10={best[2]} {name}={cur}",
              flush=True)
    return best, feats


def main():
    feats = build_tasks()
    print("tasks:", len(feats))
    best = run(feats)
    print("start ", best)

    grid_c = [("PHI_KNOTS", None)]  # placeholder, handled separately below
    phi_vals = {
        0: [0.8, 0.9, 1.0], 1: [0.5, 0.6, 0.7, 0.78], 2: [0.55, 0.65, 0.75],
        3: [0.2, 0.3, 0.4, 0.5], 4: [0.25, 0.4, 0.55], 5: [0.0, 0.1, 0.2, 0.3],
        6: [0.4, 0.55, 0.7], 7: [0.35, 0.45, 0.6],
    }

    class PhiRow:
        pass

    def phi_get(i):
        return C.PHI_KNOTS[i]

    def phi_set(i, v):
        ph = list(C.PHI_KNOTS)
        ph[i] = v
        C.PHI_KNOTS = tuple(ph)

    # build a generic grid where each row is (getter, setter, values, label)
    rows = []
    for i, vals in phi_vals.items():
        rows.append((f"PHI[{i}]", vals,
                     lambda i=i: C.PHI_KNOTS[i],
                     lambda v, i=i: phi_set(i, v)))
    for name, vals in [
        ("SPIKE_D1", [10.0, 12.0, 15.0, 18.0, 24.0]),
        ("SPIKE_KEEP", [0.6, 0.7, 0.8, 0.9, 1.0]),
        ("SPIKE_BLEND", [0.2, 0.4, 0.6, 0.8]),
        ("DECAY_AN", [1.2, 1.3, 1.4, 1.6]),
        ("DECAY_D1", [-3.0, -1.0, 0.0]),
        ("DECAY_GAIN", [0.0, 0.1, 0.2]),
        ("RISE_AN_MAX", [1.1, 1.2, 1.35]),
        ("RISE_GAIN", [0.0, 0.1, 0.2]),
        ("LAM_LAST", [0.05, 0.1, 0.15, 0.2, 0.3]),
        ("REVERT", [0.1, 0.2, 0.3]),
        ("DRIFT_SCALE", [1.6, 2.0, 2.2, 2.6, 3.2]),
        ("W_NEIGHBOR", [0.0, 0.05, 0.1, 0.15, 0.2]),
        ("NEIGH_AN_BAND", [0.2, 0.35, 0.5]),
        ("NEIGH_D1_BAND", [5.0, 8.0, 12.0]),
        ("STALE_TAU", [3.0, 6.0, 12.0]),
        ("CLAMP_LO_M", [0.2, 0.3, 0.5]),
        ("CLAMP_HI_M", [1.3, 1.5, 2.0]),
        ("CLAMP_ADD", [2.0, 5.0, 10.0]),
        ("W_COMBO", [(1, 1, 1), (2, 1, 1), (1, 2, 1), (1, 1, 2), (2, 2, 1),
                     (2, 1, 2), (1, 2, 2), (3, 2, 2), (2, 3, 2), (2, 2, 3)]),
    ]:
        rows.append((name, vals,
                     (lambda n=name: getattr(C, n)),
                     (lambda v, n=name: setattr(C, n, v))))

    for rnd in range(3):
        improved = False
        for label, vals, getter, setter in rows:
            cur = getter()
            for v in vals:
                if v == cur:
                    continue
                setter(v)
                sc = run(feats)
                if (sc[0], sc[2]) > (best[0], best[2]):
                    best = sc
                    cur = v
                    improved = True
                else:
                    setter(cur)
            print(f"A{rnd} {label:16s}: ACC={best[0]} MAE={best[1]} HIT10={best[2]} {label}={cur}",
                  flush=True)
        if not improved:
            break

    best_snap = snapshot()
    print("phase A done:", best)

    # phase B: extract-level params (rebuild features per trial)
    grid_e = [
        ("SMOOTH_LV", [0.2, 0.35, 0.5]),
        ("LEVEL_WIN", [18, 24, 36]),
        ("W_YDAY", [0.0, 0.1, 0.2]),
        ("DAY_DECAY", [0.8, 0.85, 0.9]),
        ("HOUR_SPREAD", [1, 2]),
        ("DIURNAL_SHRINK", [0.3, 0.4, 0.5]),
        ("SMOOTH", [0, 1, 2]),
        ("DRIFT_OWN_W", [0.1, 0.2, 0.35]),
        ("NEIGHBOR_MAX", [6, 8, 12]),
        ("NEIGHBOR_FRESH_H", [2.0, 3.0, 4.0]),
        ("DESPIKE_K", [1.5, 2.0, 3.0]),
    ]
    print("phase B (extract-level, slow)...")
    for name, vals in grid_e:
        cur = getattr(C, name)
        for v in vals:
            if v == cur:
                continue
            setattr(C, name, v)
            f2 = build_tasks()
            sc = run(f2)
            if (sc[0], sc[2]) > (best[0], best[2]):
                best = sc
                cur = v
                feats = f2
            else:
                setattr(C, name, cur)
        print(f"B  {name:16s}: ACC={best[0]} MAE={best[1]} HIT10={best[2]} {name}={cur}",
              flush=True)

    # verify final state reproduces best
    verify = run(build_tasks())
    print("verify:", verify, "best:", best)
    print("FINAL PARAMS:")
    for k in C_PARAMS + E_PARAMS:
        print(f"  {k} = {getattr(C, k)!r}")


if __name__ == "__main__":
    main()
