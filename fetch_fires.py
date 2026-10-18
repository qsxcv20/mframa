"""Fetch NASA FIRMS VIIRS near-real-time fire detections for Ghana.

Reads FIRMS_MAP_KEY from the environment (never hardcode it). Writes a static
data/fires_ghana.json the app and GitHub Actions can serve without the API.
On any failure the previous JSON is kept untouched.
"""

import csv
import io
import json
import os
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

import requests

sys.stdout.reconfigure(encoding="utf-8", errors="replace")

OUT_PATH = Path(__file__).parent / "data" / "fires_ghana.json"
AREA_URL = "https://firms.modaps.eosdis.nasa.gov/api/area/csv/{key}/VIIRS_NOAA21_NRT/-3.5,4.5,1.5,11.5/2"
ACCRA_CENTER = (5.6037, -0.1870)
NEAR_RADIUS_KM = 300.0
NEAR_WINDOW_H = 24
REQUEST_TIMEOUT = 30
MAX_FIRES = 2000  # keep the static file small; highest-FRP first


def _dist_km(lat1, lon1, lat2, lon2):
    import math
    r = 6371.0
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dp, dl = math.radians(lat2 - lat1), math.radians(lon2 - lon1)
    a = math.sin(dp / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
    return 2 * r * math.asin(math.sqrt(a))


def _acq_dt(row):
    try:
        return datetime.strptime(
            f"{row['acq_date']} {int(row['acq_time']):04d}", "%Y-%m-%d %H%M",
        ).replace(tzinfo=timezone.utc)
    except (KeyError, ValueError):
        return None


def main():
    key = os.environ.get("FIRMS_MAP_KEY")
    if not key:
        sys.exit("FIRMS_MAP_KEY not set; keeping previous JSON")
    try:
        resp = requests.get(AREA_URL.format(key=key), timeout=REQUEST_TIMEOUT)
        resp.raise_for_status()
        rows = list(csv.DictReader(io.StringIO(resp.text)))
    except Exception as e:
        sys.exit(f"FIRMS fetch failed ({e}); keeping previous JSON")

    now = datetime.now(timezone.utc)
    fires = []
    for r in rows:
        try:
            fires.append({
                "lat": round(float(r["latitude"]), 4),
                "lon": round(float(r["longitude"]), 4),
                "frp": round(float(r.get("frp") or 0), 1),
                "confidence": r.get("confidence") or "",
                "daynight": r.get("daynight") or "",
                "acq_date": r.get("acq_date") or "",
                "acq_time": r.get("acq_time") or "",
            })
        except (KeyError, ValueError):
            continue
    fires.sort(key=lambda f: -f["frp"])
    near = sum(
        1 for f, r in zip(fires, rows)
        if _dist_km(f["lat"], f["lon"], *ACCRA_CENTER) <= NEAR_RADIUS_KM
        and _acq_dt(r) is not None
        and now - _acq_dt(r) <= timedelta(hours=NEAR_WINDOW_H)
    )
    out = {
        "generated_at_utc": now.strftime("%Y-%m-%dT%H:%M:%SZ"),
        "source": "NASA FIRMS VIIRS_NOAA21_NRT (firms.modaps.eosdis.nasa.gov)",
        "total_fires": len(fires),
        "accra_300km_24h_fires": near,
        "fires": fires[:MAX_FIRES],
    }
    OUT_PATH.write_text(json.dumps(out, ensure_ascii=False, indent=1), encoding="utf-8")
    print(f"fires={len(fires)} near_accra_24h={near} -> {OUT_PATH}")


if __name__ == "__main__":
    main()
