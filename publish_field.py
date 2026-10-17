"""Publish the Accra PM2.5 field as public/field.json for the Android app.

Key-free JSON the app can fetch directly: an IDW-interpolated grid over the
city bbox plus the raw station list. Live OpenAQ first (via openaq_client),
local snapshot with --offline (or as the client's own fallback).
"""

import argparse
import json
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

import numpy as np

from openaq_client import get_hourly_pm25, get_locations, load_snapshot

LAT0, LAT1 = 5.45, 5.75
LON0, LON1 = -0.40, 0.10
STEP = 0.01
IDW_POWER = 2
MAX_DIST_DEG = 0.15
FRESH_HOURS = 24
OUT_PATH = Path(__file__).parent / "public" / "field.json"


def _parse_ts(s):
    if not s:
        return None
    try:
        return datetime.fromisoformat(str(s).replace("Z", "+00:00"))
    except ValueError:
        return None


def _fmt_ts(dt):
    return dt.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _station_reading(loc, offline):
    reading = loc.get("latest_pm25") or {}
    if reading.get("value") is not None:
        ts = _parse_ts(reading.get("datetime_utc"))
        if ts is not None:
            return float(reading["value"]), ts
    if offline:
        hourly = loc.get("hourly_pm25") or []
    else:
        hourly, _ = get_hourly_pm25(loc, days=2)
    hourly = [h for h in hourly if h.get("value") is not None and _parse_ts(h.get("hour_utc"))]
    if not hourly:
        return None
    latest = max(hourly, key=lambda h: _parse_ts(h["hour_utc"]))
    return float(latest["value"]), _parse_ts(latest["hour_utc"])


def collect_stations(offline):
    if offline:
        locations, source = (load_snapshot().get("locations") or []), "snapshot"
    else:
        locations, source = get_locations()
    stations = []
    for loc in locations:
        got = _station_reading(loc, offline)
        if got is None:
            continue
        value, ts = got
        stations.append({
            "name": loc.get("name") or f"Station {loc.get('id')}",
            "lat": float(loc["lat"]),
            "lon": float(loc["lon"]),
            "pm25": value,
            "updated_utc": ts,
        })
    return stations, source


def build_field(stations):
    now = datetime.now(timezone.utc)
    fresh = [s for s in stations if now - s["updated_utc"] <= timedelta(hours=FRESH_HOURS)]
    if not fresh and stations:
        # Stale snapshot: anchor the 24h window on the newest reading instead.
        newest = max(s["updated_utc"] for s in stations)
        fresh = [s for s in stations if newest - s["updated_utc"] <= timedelta(hours=FRESH_HOURS)]
    if not fresh:
        sys.exit("no stations with readings inside the freshness window")

    lats = np.round(np.arange(LAT0, LAT1 + STEP / 2, STEP), 6)
    lons = np.round(np.arange(LON0, LON1 + STEP / 2, STEP), 6)
    glat, glon = np.meshgrid(lats, lons, indexing="ij")
    pts = np.stack([glat.ravel(), glon.ravel()], axis=1)

    sc = np.array([[s["lat"], s["lon"]] for s in fresh])
    sv = np.array([s["pm25"] for s in fresh])
    dist = np.sqrt(((pts[:, None, :] - sc[None, :, :]) ** 2).sum(axis=2))
    w = 1.0 / np.maximum(dist, 1e-9) ** IDW_POWER
    grid = (w * sv[None, :]).sum(axis=1) / w.sum(axis=1)
    grid = np.where(dist.min(axis=1) > MAX_DIST_DEG, np.nan, grid)
    pm25 = [[round(float(v), 1) if np.isfinite(v) else None for v in row]
            for row in grid.reshape(len(lats), len(lons))]

    return {
        "generated_at_utc": _fmt_ts(now),
        "bbox": {"lat0": LAT0, "lat1": LAT1, "lon0": LON0, "lon1": LON1},
        "grid": {"step": STEP, "pm25": pm25},
        "stations": [
            {"name": s["name"], "lat": round(s["lat"], 5), "lon": round(s["lon"], 5),
             "pm25": round(s["pm25"], 1), "updated_utc": _fmt_ts(s["updated_utc"])}
            for s in sorted(stations, key=lambda s: s["name"])
        ],
        "city_mean": round(float(sv.mean()), 1),
    }, len(fresh)


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--offline", action="store_true",
                    help="skip the network and use data/snapshot.json only")
    args = ap.parse_args()

    stations, source = collect_stations(args.offline)
    field, n_fresh = build_field(stations)

    OUT_PATH.parent.mkdir(exist_ok=True)
    payload = json.dumps(field, ensure_ascii=False, separators=(",", ":"))
    OUT_PATH.write_text(payload, encoding="utf-8")
    size_kb = OUT_PATH.stat().st_size / 1024
    grid = field["grid"]["pm25"]
    n_cells = sum(len(r) for r in grid)
    n_valid = sum(1 for r in grid for v in r if v is not None)
    print(f"source={source} stations={len(stations)} fresh={n_fresh} "
          f"grid={len(grid)}x{len(grid[0])} valid={n_valid}/{n_cells} "
          f"({n_valid / n_cells:.0%}) city_mean={field['city_mean']} "
          f"-> {OUT_PATH} ({size_kb:.1f} KB)")


if __name__ == "__main__":
    main()
