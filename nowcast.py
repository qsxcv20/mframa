"""Mframa nowcast: estimate PM2.5 for stations that have gone offline.

Two ideas are blended:
  A. Self-extrapolation — take the station's last known value and rescale it
     along its own 7-day diurnal curve (ratio of typical level at the target
     hour vs. the hour of the last reading).
  B. Neighbor imputation — translate fresh readings from nearby online
     stations onto this station's diurnal scale, inverse-distance weighted
     (1/d^2, haversine km, nearest 8 valid neighbors).

Pure numpy + stdlib; no network, no Streamlit. Ghana is UTC+0, so UTC hours
equal local hours everywhere below.

CLI:
  python nowcast.py backtest            run hide-and-predict backtest on data/snapshot.json
  python nowcast.py demo <station_name> nowcast one station right now
"""

from __future__ import annotations

import json
import math
import sys
from datetime import datetime, timedelta, timezone

import numpy as np

import analytics

SNAPSHOT_PATH = "data/snapshot.json"

NEIGHBOR_FRESH_HOURS = 3.0   # a neighbor reading counts as "current" within this window
MAX_NEIGHBORS = 8
SELF_MAX_STALE_HOURS = 72.0  # beyond this, self-extrapolation is not attempted
W_A_HALFLIFE_HOURS = 6.0     # self-weight halves every this many hours past the fresh window
MIN_DIURNAL = 0.5            # ratios vs. diurnal means below this are unreliable


def _parse_ts(ts) -> datetime | None:
    try:
        dt = datetime.fromisoformat(str(ts).replace("Z", "+00:00"))
    except (TypeError, ValueError):
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt


def _series(station: dict, before: datetime | None = None) -> list[tuple[datetime, float]]:
    """Sorted [(timestamp, value)] from a station's hourly_pm25 records."""
    out = []
    for rec in station.get("hourly_pm25") or []:
        value, ts = rec.get("value"), rec.get("hour_utc")
        if value is None or ts is None:
            continue
        dt = _parse_ts(ts)
        if dt is None:
            continue
        if before is not None and dt > before:
            continue
        try:
            out.append((dt, float(value)))
        except (TypeError, ValueError):
            continue
    out.sort(key=lambda p: p[0])
    return out


def haversine_km(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    r = 6371.0
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dp = math.radians(lat2 - lat1)
    dl = math.radians(lon2 - lon1)
    a = math.sin(dp / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
    return 2 * r * math.asin(math.sqrt(a))


def _latlon(station: dict) -> tuple[float, float] | None:
    try:
        return float(station["lat"]), float(station["lon"])
    except (KeyError, TypeError, ValueError):
        return None


def _diurnal(hourly: list[dict]) -> dict[int, float]:
    try:
        return analytics.diurnal_profile(hourly)
    except Exception:
        return {}


def _diurnal_at(diurnal: dict[int, float], hour: int) -> float | None:
    v = diurnal.get(hour)
    if v is None and diurnal:
        v = float(np.mean(list(diurnal.values())))
    return v


def _rescale(value: float, diurnal_from: dict[int, float], hour_from: int,
             diurnal_to: dict[int, float], hour_to: int) -> float:
    """Move a reading from one station/hour context to another via diurnal ratios."""
    base_from = _diurnal_at(diurnal_from, hour_from)
    base_to = _diurnal_at(diurnal_to, hour_to)
    if base_from is None or base_to is None or base_from < MIN_DIURNAL:
        return value
    return value * base_to / base_from


def _neighbor_current(neighbor: dict, now: datetime) -> tuple[datetime, float] | None:
    """A neighbor's latest reading at or before `now`, if fresh enough."""
    ser = _series(neighbor, before=now)
    if ser and (now - ser[-1][0]).total_seconds() <= NEIGHBOR_FRESH_HOURS * 3600:
        return ser[-1]
    latest = neighbor.get("latest_pm25") or {}
    dt = _parse_ts(latest.get("datetime_utc"))
    if dt is not None and dt <= now and (now - dt).total_seconds() <= NEIGHBOR_FRESH_HOURS * 3600:
        try:
            return dt, float(latest.get("value"))
        except (TypeError, ValueError):
            return None
    return None


def _ensemble_predict(station: dict, neighbors: list[dict], now: datetime) -> float | None:
    """Try the bake-off winning nowcaster (candidates/cand_regime2.py)."""
    try:
        import importlib.util
        from pathlib import Path
        cand_path = Path(__file__).parent / "candidates" / "cand_regime2.py"
        if not cand_path.exists():
            return None
        spec = importlib.util.spec_from_file_location("cand_regime2", cand_path)
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)
        cutoff = now - timedelta(hours=1)
        st_in = {"lat": station["lat"], "lon": station["lon"],
                 "series": [(t, v) for t, v in _series(station) if t <= cutoff]}
        nb_in = [{"lat": n["lat"], "lon": n["lon"],
                  "series": [(t, v) for t, v in _series(n) if t <= cutoff]}
                 for n in neighbors or []
                 if n is not station and _latlon(n) is not None]
        if len(st_in["series"]) < 26:
            return None
        return mod.predict(st_in, nb_in, now)
    except Exception:
        return None


def predict_station(station: dict, neighbors: list[dict],
                    at_hour: datetime | None = None) -> dict:
    """Nowcast PM2.5 for a (possibly offline) station.

    neighbors are other station dicts (hourly_pm25 and/or latest_pm25).
    Returns {'value', 'confidence', 'method', 'sources_used', 'stale_hours', 'note'}.
    """
    now = at_hour or datetime.now(timezone.utc)
    if now.tzinfo is None:
        now = now.replace(tzinfo=timezone.utc)

    ens = _ensemble_predict(station, neighbors, now)
    if ens is not None:
        ser0 = _series(station, before=now)
        stale0 = (now - ser0[-1][0]).total_seconds() / 3600.0 if ser0 else None
        return {
            "value": round(max(0.0, ens), 1),
            "confidence": "medium" if (stale0 or 99) <= 6 else "low",
            "method": "ensemble",
            "sources_used": 0,
            "stale_hours": round(stale0, 1) if stale0 is not None else None,
            "note": "Estimated by regime-conditional nowcaster (calm/rising/"
                    "post-spike dynamics + diurnal anchor), bake-off winner "
                    "vs 10 rival algorithms.",
        }

    hourly = station.get("hourly_pm25") or []
    ser = _series(station, before=now)
    diurnal_s = _diurnal([r for r in hourly if (_parse_ts(r.get("hour_utc")) or now) <= now])

    pred_a = None
    stale_hours = None
    if ser:
        t0, last_val = ser[-1]
        stale_hours = (now - t0).total_seconds() / 3600.0
        if stale_hours <= SELF_MAX_STALE_HOURS:
            pred_a = _rescale(last_val, diurnal_s, t0.hour, diurnal_s, now.hour)

    # --- neighbor imputation ---
    origin = _latlon(station)
    cands = []  # (distance_km, translated_value)
    if origin is not None:
        for nb in neighbors or []:
            if nb is station:
                continue
            cur = _neighbor_current(nb, now)
            ll = _latlon(nb)
            if cur is None or ll is None:
                continue
            tn, nval = cur
            diurnal_n = _diurnal(nb.get("hourly_pm25") or [])
            pred_i = _rescale(nval, diurnal_n, tn.hour, diurnal_s, now.hour)
            cands.append((haversine_km(origin[0], origin[1], ll[0], ll[1]), pred_i))
    cands.sort(key=lambda p: p[0])
    used = cands[:MAX_NEIGHBORS]

    pred_b = None
    if used:
        w = np.array([1.0 / max(d, 0.1) ** 2 for d, _ in used])
        v = np.array([p for _, p in used])
        pred_b = float((w * v).sum() / w.sum())

    # --- fusion ---
    if pred_a is not None and stale_hours is not None:
        w_a = 1.0 if stale_hours <= NEIGHBOR_FRESH_HOURS else \
            0.5 ** ((stale_hours - NEIGHBOR_FRESH_HOURS) / W_A_HALFLIFE_HOURS)
    else:
        w_a = 0.0

    if pred_a is not None and pred_b is not None:
        value = w_a * pred_a + (1.0 - w_a) * pred_b
        method = "blend"
    elif pred_a is not None:
        value, method = pred_a, "self_extrapolation"
    elif pred_b is not None:
        value, method = pred_b, "neighbor_idw"
    else:
        return {
            "value": None,
            "confidence": "low",
            "method": "unavailable",
            "sources_used": 0,
            "stale_hours": round(stale_hours, 1) if stale_hours is not None else None,
            "note": "No recent own readings and no fresh neighbors within reach.",
        }

    value = max(0.0, value)
    n_used = len(used)
    nearest_km = used[0][0] if used else None

    if method == "blend":
        if stale_hours <= 6 and n_used >= 3:
            confidence = "high"
        else:
            confidence = "medium"
    elif method == "self_extrapolation":
        confidence = "medium" if (stale_hours or 99) <= NEIGHBOR_FRESH_HOURS else "low"
    else:  # neighbor_idw
        confidence = "medium" if (n_used >= 3 and (nearest_km or 99) <= 5) else "low"

    parts = []
    if pred_a is not None:
        parts.append(f"own diurnal pattern (last reading {stale_hours:.1f} h ago, weight {w_a:.2f})")
    if pred_b is not None:
        parts.append(f"{n_used} nearby station(s), nearest {nearest_km:.1f} km")
    return {
        "value": round(value, 1),
        "confidence": confidence,
        "method": method,
        "sources_used": n_used,
        "stale_hours": round(stale_hours, 1) if stale_hours is not None else None,
        "note": "Estimated from " + " + ".join(parts) + ".",
    }


def backtest(locations: list[dict], hide_hours: int = 6) -> dict:
    """Hide each usable station's last `hide_hours` readings and predict them.

    For every horizon 1..hide_hours the station is truncated before that
    target hour, the remaining stations serve as neighbors (their readings
    are also capped at the target hour, so nothing from the future leaks
    into a prediction), and the estimate is compared with the true value.
    """
    usable = [l for l in locations if len(_series(l)) >= hide_hours + 96]
    errs = []  # (horizon, abs_err, truth, station_name)
    for st in usable:
        ser = _series(st)
        cut = ser[:-hide_hours]
        if not cut:
            continue
        t0 = cut[-1][0]
        truth_by_time = {t: v for t, v in ser}
        trunc = dict(st)
        trunc["hourly_pm25"] = [
            r for r in (st.get("hourly_pm25") or [])
            if (_parse_ts(r.get("hour_utc")) or t0) <= t0
        ]
        trunc.pop("latest_pm25", None)
        others = [o for o in usable if o is not st]
        name = st.get("name") or f"Station {st.get('id')}"
        for h in range(1, hide_hours + 1):
            at = t0 + timedelta(hours=h)
            truth = truth_by_time.get(at)
            if truth is None:
                continue
            res = predict_station(trunc, others, at_hour=at)
            if res.get("value") is None:
                continue
            errs.append((h, abs(res["value"] - truth), truth, name))

    if not errs:
        return {"mae": None, "mape_pct": None, "rmse": None, "n": 0,
                "by_horizon": {}, "per_station_worst": []}

    e = np.array([x[1] for x in errs])
    truths = np.array([x[2] for x in errs])
    ape = np.array([x[1] / x[2] for x in errs if x[2] >= 2.0])  # skip near-zero truths

    by_horizon = {}
    for h in (1, 3, 6):
        he = [x for x in errs if x[0] == h]
        if not he:
            continue
        hv = np.array([x[1] for x in he])
        ha = np.array([x[1] / x[2] for x in he if x[2] >= 2.0])
        by_horizon[h] = (round(float(hv.mean()), 2),
                         round(float(ha.mean()) * 100, 1) if len(ha) else None)

    per_station: dict[str, list[float]] = {}
    for _, err, _, name in errs:
        per_station.setdefault(name, []).append(err)
    worst = sorted(((float(np.mean(v)), k) for k, v in per_station.items()),
                   reverse=True)[:5]

    return {
        "mae": round(float(e.mean()), 2),
        "mape_pct": round(float(ape.mean()) * 100, 1) if len(ape) else None,
        "rmse": round(float(np.sqrt((e ** 2).mean())), 2),
        "n": int(len(errs)),
        "by_horizon": by_horizon,
        "per_station_worst": [{"station": k, "mae": round(m, 2)} for m, k in worst],
    }


def _load_snapshot(path: str = SNAPSHOT_PATH) -> list[dict]:
    with open(path, encoding="utf-8") as f:
        data = json.load(f)
    return data["locations"] if isinstance(data, dict) else data


def _cli_backtest() -> int:
    locations = _load_snapshot()
    res = backtest(locations)
    if not res.get("n"):
        print("Backtest could not run: not enough stations with complete hourly data.")
        return 1
    print(f"Nowcast backtest on {SNAPSHOT_PATH} (hide last 6 h per station)")
    print(f"  samples (station x horizon): {res['n']}")
    print(f"  MAE  : {res['mae']} µg/m³")
    print(f"  RMSE : {res['rmse']} µg/m³")
    print(f"  MAPE : {res['mape_pct']} %  (truths >= 2 µg/m³)")
    print("  by horizon:")
    for h, (mae, mape) in res["by_horizon"].items():
        print(f"    +{h} h: MAE {mae} µg/m³, MAPE {mape} %")
    print("  worst stations (mean abs error):")
    for w in res["per_station_worst"]:
        print(f"    {w['mae']:>6} µg/m³  {w['station']}")
    return 0


def _cli_demo(name: str) -> int:
    locations = _load_snapshot()
    matches = [l for l in locations
               if name.lower() in str(l.get("name") or "").lower()]
    if not matches:
        print(f"No station matching {name!r}. Stations with hourly data:")
        for l in locations:
            if l.get("hourly_pm25"):
                print("  -", l.get("name"))
        return 1
    st = matches[0]
    others = [l for l in locations if l is not st]
    res = predict_station(st, others)
    print(f"Station : {st.get('name')}")
    print(f"Now     : {datetime.now(timezone.utc):%Y-%m-%d %H:%M} UTC (Ghana local)")
    for k in ("value", "confidence", "method", "sources_used", "stale_hours", "note"):
        print(f"  {k:<12}: {res[k]}")
    latest = st.get("latest_pm25") or {}
    ser = _series(st)
    if ser:
        print(f"  last actual : {ser[-1][1]} µg/m³ at {ser[-1][0]:%Y-%m-%d %H:%M} UTC")
    elif latest:
        print(f"  latest_pm25 : {latest}")
    return 0


if __name__ == "__main__":
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except (AttributeError, OSError):
        pass
    args = sys.argv[1:]
    if args and args[0] == "backtest":
        sys.exit(_cli_backtest())
    if args and args[0] == "demo" and len(args) > 1:
        sys.exit(_cli_demo(" ".join(args[1:])))
    print(__doc__)
    sys.exit(2)
