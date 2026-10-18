"""Build the static demo/tracking datasets for Mframa (run manually, commit output).

1. data/demo_harmattan.json — one real Harmattan-season peak day (Jan-Feb 2026,
   OpenAQ history) used by the ?demo=harmattan replay mode.
2. data/agbogbloshie_cleanup.json — Agbogbloshie e-waste cleanup tracker:
   30-day baseline before the 2026-09-18 launch vs. since-launch PM2.5 means.

Never hardcode or print the API key. Output files are static: the app reads
them without touching the live API.
"""

import json
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

import requests

import openaq_client

sys.stdout.reconfigure(encoding="utf-8", errors="replace")

ROOT = Path(__file__).parent
DEMO_PATH = ROOT / "data" / "demo_harmattan.json"
CLEANUP_PATH = ROOT / "data" / "agbogbloshie_cleanup.json"

AGBO_SITE = (5.5567, -0.2283)
LAUNCH_DATE = "2026-09-18"
# Harmattan search window (Accra's worst-air months, per IQAir history).
PEAK_FROM, PEAK_TO = "2026-01-01T00:00:00Z", "2026-03-01T00:00:00Z"


def fetch_hours(sensor_id, dt_from, dt_to, limit=1000):
    key = openaq_client.get_api_key()
    if not key:
        sys.exit("OPENAQ_API_KEY not available")
    payload = openaq_client._get_with_retry(
        f"{openaq_client.API_BASE}/sensors/{sensor_id}/hours",
        headers={"X-API-Key": key},
        params={"datetime_from": dt_from, "datetime_to": dt_to, "limit": limit},
    )
    hours = {}
    for r in (payload or {}).get("results") or []:
        value = r.get("value")
        hour = (((r.get("period") or {}).get("datetimeFrom") or {}).get("utc"))
        if hour is not None and value is not None:
            hours[hour] = float(value)
    return hours  # {hour_utc: value}


def day_of(hour_utc):
    return hour_utc[:10]


def build_demo_harmattan(locations):
    """Pick the Jan-Feb 2026 date with the highest cross-station daily mean."""
    pool = sorted(
        (l for l in locations if (l.get("sensors") or {}).get("pm25")),
        key=lambda l: (l.get("lat", 0) - openaq_client.BBOX["lat_min"]) ** 2
        + (l.get("lon", 0) - openaq_client.BBOX["lon_min"]) ** 2,
    )[:40]  # city-center coverage is what the demo shows
    # Split the window monthly: Jan+Feb exceeds the 1000-row API limit.
    ranges = [("2026-01-01T00:00:00Z", "2026-02-01T00:00:00Z"),
              ("2026-02-01T00:00:00Z", PEAK_TO)]
    per_station = {}
    for i, loc in enumerate(pool):
        hours = {}
        for dt_from, dt_to in ranges:
            hours.update(fetch_hours(loc["sensors"]["pm25"], dt_from, dt_to))
        if hours:
            per_station[loc["id"]] = (loc, hours)
        print(f"  [{i + 1}/{len(pool)}] {loc['name']}: {len(hours)} h")
        time.sleep(0.3)
    # daily mean per date across stations (need decent coverage that day)
    daily = {}
    for loc, hours in per_station.values():
        by_day = {}
        for hour, value in hours.items():
            by_day.setdefault(day_of(hour), []).append(value)
        for day, vals in by_day.items():
            if len(vals) >= 12:
                daily.setdefault(day, []).append(sum(vals) / len(vals))
    candidates = {
        d: (sum(m) / len(m), len(m)) for d, m in daily.items() if len(m) >= 5
    }
    if not candidates:
        sys.exit("no Harmattan day with enough coverage found")
    peak_day = max(candidates, key=lambda d: candidates[d][0])
    city_mean, n_stations = candidates[peak_day]
    print(f"peak day: {peak_day}  city mean {city_mean:.1f} µg/m³  ({n_stations} stations)")

    stations = []
    for loc, hours in per_station.values():
        day_hours = {h: v for h, v in hours.items() if day_of(h) == peak_day}
        if len(day_hours) < 12:
            continue
        replay_hour = max(day_hours, key=day_hours.get)  # station's own peak hour
        stations.append({
            "id": loc["id"], "name": loc["name"],
            "lat": loc["lat"], "lon": loc["lon"],
            "provider": loc.get("provider") or "OpenAQ",
            "sensors": loc["sensors"],
            "latest_pm25": {"value": day_hours[replay_hour], "datetime_utc": replay_hour},
            "hourly_pm25": [
                {"hour_utc": h, "value": day_hours[h]} for h in sorted(day_hours)
            ],
        })
    out = {
        "date": peak_day,
        "city_mean_pm25": round(city_mean, 1),
        "source": "OpenAQ v3 historical hourly data (api.openaq.org)",
        "generated_at_utc": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "stations": stations,
    }
    DEMO_PATH.write_text(json.dumps(out, ensure_ascii=False, indent=1), encoding="utf-8")
    print(f"wrote {DEMO_PATH} ({len(stations)} stations)")


def build_agbogbloshie_cleanup(locations):
    def dist(l):
        return ((l["lat"] - AGBO_SITE[0]) ** 2 + (l["lon"] - AGBO_SITE[1]) ** 2) ** 0.5
    named = [l for l in locations if "agbogbloshie" in (l.get("name") or "").lower()]
    loc = named[0] if named else min(locations, key=dist)
    sensor = (loc.get("sensors") or {}).get("pm25")
    print(f"tracking station: {loc['name']} ({dist(loc) * 111:.2f} km, sensor {sensor})")

    baseline = fetch_hours(sensor, "2026-08-19T00:00:00Z", "2026-09-18T00:00:00Z")
    now_iso = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    current = fetch_hours(sensor, "2026-09-18T00:00:00Z", now_iso)
    if not baseline or not current:
        sys.exit(f"insufficient data: baseline {len(baseline)} h, current {len(current)} h")
    base_mean = sum(baseline.values()) / len(baseline)
    cur_mean = sum(current.values()) / len(current)
    out = {
        "station_name": loc["name"],
        "station_id": loc["id"],
        "distance_km": round(dist(loc) * 111, 2),
        "launch_date": LAUNCH_DATE,
        "baseline_from": "2026-08-19", "baseline_to": "2026-09-17",
        "baseline_days": len({day_of(h) for h in baseline}),
        "baseline_mean": round(base_mean, 1),
        "current_from": "2026-09-18",
        "current_to": sorted(current)[-1][:10],
        "current_days": len({day_of(h) for h in current}),
        "current_mean": round(cur_mean, 1),
        "change_pct": round((cur_mean - base_mean) / base_mean * 100, 1),
        "source": "OpenAQ v3 historical hourly data (api.openaq.org)",
        "computed_at_utc": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
    }
    CLEANUP_PATH.write_text(json.dumps(out, ensure_ascii=False, indent=1), encoding="utf-8")
    print(f"wrote {CLEANUP_PATH}: baseline {out['baseline_mean']} -> "
          f"current {out['current_mean']} ({out['change_pct']}%)")


def main():
    locations = openaq_client.load_snapshot().get("locations") or []
    if not locations:
        sys.exit("no snapshot locations")
    which = sys.argv[1] if len(sys.argv) > 1 else "all"
    if which in ("demo", "all"):
        build_demo_harmattan(locations)
    if which in ("cleanup", "all"):
        build_agbogbloshie_cleanup(locations)


main()
