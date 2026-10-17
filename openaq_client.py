"""OpenAQ v3 data access layer for Mframa.

Live API first, local snapshot (data/snapshot.json) as silent fallback.
Never hardcode or print the API key.
"""

import json
import os
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path

import requests
import streamlit as st

API_BASE = "https://api.openaq.org/v3"
COUNTRIES_ID = 152  # Ghana
BBOX = {"lat_min": 5.45, "lat_max": 5.75, "lon_min": -0.40, "lon_max": 0.10}
SNAPSHOT_PATH = Path(__file__).parent / "data" / "snapshot.json"
REQUEST_TIMEOUT = 20
MAX_RETRIES = 3


def get_api_key() -> str | None:
    try:
        key = st.secrets.get("OPENAQ_API_KEY")
        if key:
            return key
    except Exception:
        pass
    return os.environ.get("OPENAQ_API_KEY") or None


def load_snapshot() -> dict:
    try:
        return json.loads(SNAPSHOT_PATH.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {"locations": []}


def data_mode() -> str:
    return "live" if get_api_key() else "snapshot"


def _get_with_retry(url: str, headers: dict, params: dict) -> dict | None:
    for attempt in range(MAX_RETRIES):
        try:
            resp = requests.get(url, headers=headers, params=params, timeout=REQUEST_TIMEOUT)
            if resp.status_code == 200:
                return resp.json()
            if resp.status_code < 500 and resp.status_code != 429:
                return None
        except requests.RequestException:
            pass
        time.sleep(2 ** attempt)
    return None


def _in_bbox(lat, lon) -> bool:
    try:
        return BBOX["lat_min"] <= float(lat) <= BBOX["lat_max"] and \
            BBOX["lon_min"] <= float(lon) <= BBOX["lon_max"]
    except (TypeError, ValueError):
        return False


def _normalize_location(raw: dict) -> dict | None:
    coords = raw.get("coordinates") or {}
    lat, lon = coords.get("latitude"), coords.get("longitude")
    if not _in_bbox(lat, lon):
        return None
    sensors = {}
    for s in raw.get("sensors") or []:
        pname = ((s.get("parameter") or {}).get("name") or "").lower()
        if pname and s.get("id") is not None:
            sensors[pname] = s["id"]
    if "pm25" not in sensors:
        return None
    return {
        "id": raw.get("id"),
        "name": raw.get("name"),
        "lat": float(lat),
        "lon": float(lon),
        "sensors": sensors,
        "last_updated_utc": ((raw.get("datetimeLast") or {}).get("utc")),
        "provider": ((raw.get("provider") or {}).get("name")),
        "latest_pm25": None,
        "hourly_pm25": [],
    }


def _snapshot_locations() -> list[dict]:
    return load_snapshot().get("locations") or []


@st.cache_data(ttl=3600, show_spinner=False)
def get_locations() -> tuple[list[dict], str]:
    key = get_api_key()
    if key:
        payload = _get_with_retry(
            f"{API_BASE}/locations",
            headers={"X-API-Key": key},
            params={"countries_id": COUNTRIES_ID, "limit": 1000},
        )
        if payload is not None:
            locations = [loc for loc in
                         (_normalize_location(r) for r in payload.get("results") or [])
                         if loc is not None]
            if locations:
                return locations, "live"
    return _snapshot_locations(), "snapshot"


@st.cache_data(ttl=900, show_spinner=False)
def get_hourly_pm25(location: dict, days: int = 7) -> tuple[list[dict], str]:
    key = get_api_key()
    sensor_id = (location.get("sensors") or {}).get("pm25")
    if key and sensor_id:
        dt_from = (datetime.now(timezone.utc) - timedelta(days=days)).strftime("%Y-%m-%dT%H:%M:%SZ")
        payload = _get_with_retry(
            f"{API_BASE}/sensors/{sensor_id}/hours",
            headers={"X-API-Key": key},
            params={"datetime_from": dt_from, "limit": 1000},
        )
        if payload is not None:
            hours = []
            for r in payload.get("results") or []:
                value = r.get("value")
                hour = (((r.get("period") or {}).get("datetimeFrom") or {}).get("utc"))
                if hour is not None and value is not None:
                    hours.append({"hour_utc": hour, "value": value})
            hours.sort(key=lambda h: h["hour_utc"])
            if hours:
                return hours, "live"
    return _snapshot_hourly(location, days), "snapshot"


def _snapshot_hourly(location: dict, days: int) -> list[dict]:
    hourly = location.get("hourly_pm25")
    if not hourly:
        for loc in _snapshot_locations():
            if loc.get("id") == location.get("id"):
                hourly = loc.get("hourly_pm25")
                break
    hourly = [h for h in (hourly or []) if h.get("value") is not None]
    hourly.sort(key=lambda h: h.get("hour_utc") or "")
    return hourly[-days * 24:] if hourly else []
