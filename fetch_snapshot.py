"""Fetch a real-data snapshot of Accra air quality from OpenAQ v3.

Produces data/snapshot.json, which the Streamlit app uses as an offline
fallback so the demo never breaks (no API key / no network / rate limits).

Requires OPENAQ_API_KEY in the environment.
"""

import json
import os
import sys
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path

import requests

BASE = "https://api.openaq.org/v3"
ACCRA_BBOX = {"lat_min": 5.45, "lat_max": 5.75, "lon_min": -0.40, "lon_max": 0.10}
HOURLY_DAYS = 7
OUT = Path(__file__).parent / "data" / "snapshot.json"


def get(session, path, **params):
    r = session.get(f"{BASE}{path}", params=params, timeout=30)
    r.raise_for_status()
    return r.json()


def main():
    key = os.environ.get("OPENAQ_API_KEY")
    if not key:
        sys.exit("OPENAQ_API_KEY not set")
    s = requests.Session()
    s.headers["X-API-Key"] = key

    ghana = get(s, "/countries", limit=200)
    gh_id = next(c["id"] for c in ghana["results"] if c["code"] == "GH")

    locations = []
    page = 1
    while True:
        d = get(s, "/locations", countries_id=gh_id, limit=1000, page=page)
        locations.extend(d["results"])
        if len(locations) >= d["meta"]["found"]:
            break
        page += 1

    accra = []
    for loc in locations:
        co = loc.get("coordinates") or {}
        lat, lon = co.get("latitude"), co.get("longitude")
        if lat is None or not (ACCRA_BBOX["lat_min"] <= lat <= ACCRA_BBOX["lat_max"]
                               and ACCRA_BBOX["lon_min"] <= lon <= ACCRA_BBOX["lon_max"]):
            continue
        sensors = {s["parameter"]["name"]: s["id"] for s in loc.get("sensors", [])}
        if "pm25" not in sensors:
            continue
        last = (loc.get("datetimeLast") or {}).get("utc")
        accra.append({
            "id": loc["id"],
            "name": (loc.get("name") or f"Station {loc['id']}").strip(),
            "lat": lat,
            "lon": lon,
            "sensors": sensors,
            "last_updated_utc": last,
            "provider": (loc.get("provider") or {}).get("name"),
        })
    print(f"{len(accra)} Accra locations with pm25")

    now = datetime.now(timezone.utc)
    dt_from = (now - timedelta(days=HOURLY_DAYS)).strftime("%Y-%m-%dT%H:%M:%SZ")
    for i, loc in enumerate(accra):
        sid = loc["sensors"]["pm25"]
        try:
            d = get(s, f"/sensors/{sid}/hours", datetime_from=dt_from, limit=1000)
            hourly = [
                {"hour_utc": r["period"]["datetimeFrom"]["utc"], "value": r["value"]}
                for r in d["results"]
                if r.get("value") is not None
            ]
            hourly.sort(key=lambda h: h["hour_utc"])
            loc["hourly_pm25"] = hourly
            if hourly:
                loc["latest_pm25"] = {"value": hourly[-1]["value"],
                                      "datetime_utc": hourly[-1]["hour_utc"]}
        except Exception as e:
            print(f"  ! {loc['name']}: {e}")
            loc["hourly_pm25"] = []
        if i % 10 == 0:
            print(f"  {i}/{len(accra)}")
        time.sleep(0.15)

    OUT.parent.mkdir(exist_ok=True)
    OUT.write_text(json.dumps({
        "fetched_at_utc": now.strftime("%Y-%m-%dT%H:%M:%SZ"),
        "source": "OpenAQ v3 API (https://api.openaq.org)",
        "city": "Accra, Ghana",
        "bbox": ACCRA_BBOX,
        "locations": accra,
    }, ensure_ascii=False, indent=1))
    print(f"wrote {OUT} ({OUT.stat().st_size // 1024} KB, {len(accra)} locations)")


if __name__ == "__main__":
    main()
