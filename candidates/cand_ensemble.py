"""Ensemble: median of the three best candidates (robust / diurnal / regime)."""

import importlib.util
import statistics
from pathlib import Path

_HERE = Path(__file__).parent


def _load(name):
    spec = importlib.util.spec_from_file_location(name, _HERE / f"{name}.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


_MODS = [_load(n) for n in ("cand_robust", "cand_diurnal", "cand_regime")]


def predict(station, neighbors, target_time):
    preds = []
    for m in _MODS:
        try:
            p = m.predict(station, neighbors, target_time)
            if p is not None:
                preds.append(float(p))
        except Exception:
            pass
    if not preds:
        return None
    return statistics.median(preds)
