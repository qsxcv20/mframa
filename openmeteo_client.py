"""Open-Meteo data access layer for Mframa (free APIs, no key required).

CAMS/ECMWF air-quality forecast (dust, PM2.5, aerosol optical depth) and
weather forecast (wind, boundary layer, precipitation) for Accra, Ghana.

File cache with TTL 1h; on network failure, serve cache up to 24h old and
mark it stale. Never raises on network problems — returns None instead.
"""

import json
from datetime import datetime, timezone
from pathlib import Path

import requests

ACCRA_LAT = 5.6037
ACCRA_LON = -0.1870

AQ_URL = "https://air-quality-api.open-meteo.com/v1/air-quality"
AQ_PARAMS = {"hourly": "pm2_5,dust,aerosol_optical_depth", "forecast_days": 5}
WX_URL = "https://api.open-meteo.com/v1/forecast"
WX_PARAMS = {
    "hourly": "wind_speed_10m,wind_direction_10m,boundary_layer_height,precipitation",
    "forecast_days": 3,
}

CACHE_PATH = Path(__file__).parent / "data" / "openmeteo_cache.json"
REQUEST_TIMEOUT = 10
TTL_SECONDS = 3600        # refetch after 1h
STALE_MAX_SECONDS = 86400  # serve cache up to 24h old on network failure


def _fetch_json(url: str, params: dict) -> dict | None:
    try:
        resp = requests.get(
            url,
            params={**params, "latitude": ACCRA_LAT, "longitude": ACCRA_LON},
            timeout=REQUEST_TIMEOUT,
        )
        if resp.status_code == 200:
            return resp.json()
    except requests.RequestException:
        pass
    return None


def _parse_hours(payload: dict) -> list[dict]:
    """Hourly arrays -> [{time: datetime (UTC), <field>: value, ...}]."""
    hourly = payload.get("hourly") or {}
    times = hourly.get("time") or []
    fields = [k for k in hourly.keys() if k != "time"]
    rows = []
    for i, t in enumerate(times):
        try:
            dt = datetime.fromisoformat(str(t))
        except (TypeError, ValueError):
            continue
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)  # Open-Meteo default is GMT
        row = {"time": dt}
        for f in fields:
            vals = hourly.get(f) or []
            row[f] = vals[i] if i < len(vals) else None
        rows.append(row)
    return rows


def _cache_age_seconds(entry: dict) -> float | None:
    try:
        ts = datetime.fromisoformat(str(entry.get("fetched_at", "")))
    except (TypeError, ValueError):
        return None
    if ts.tzinfo is None:
        ts = ts.replace(tzinfo=timezone.utc)
    return (datetime.now(timezone.utc) - ts).total_seconds()


def _load_cache() -> dict:
    try:
        return json.loads(CACHE_PATH.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}


def _save_cache(cache: dict) -> None:
    try:
        CACHE_PATH.parent.mkdir(parents=True, exist_ok=True)
        CACHE_PATH.write_text(json.dumps(cache), encoding="utf-8")
    except OSError:
        pass


def _rows_to_json(rows: list[dict]) -> list[dict]:
    out = []
    for row in rows:
        r = dict(row)
        r["time"] = r["time"].isoformat()
        out.append(r)
    return out


def _rows_from_json(rows: list[dict]) -> list[dict]:
    out = []
    for row in rows or []:
        r = dict(row)
        try:
            dt = datetime.fromisoformat(str(r.get("time", "")))
        except (TypeError, ValueError):
            continue
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        r["time"] = dt
        out.append(r)
    return out


def _get(kind: str, url: str, params: dict) -> dict | None:
    """Fetch + cache. Returns {'hours': [...], 'fetched_at': iso, 'stale': bool} or None."""
    cache = _load_cache()
    entry = cache.get(kind) or {}
    age = _cache_age_seconds(entry)
    if age is not None and age < TTL_SECONDS and entry.get("hours"):
        return {"hours": _rows_from_json(entry["hours"]),
                "fetched_at": entry["fetched_at"], "stale": False}

    payload = _fetch_json(url, params)
    if payload is not None:
        rows = _parse_hours(payload)
        if rows:
            fetched_at = datetime.now(timezone.utc).isoformat()
            cache[kind] = {"fetched_at": fetched_at, "hours": _rows_to_json(rows)}
            _save_cache(cache)
            return {"hours": rows, "fetched_at": fetched_at, "stale": False}

    if age is not None and age < STALE_MAX_SECONDS and entry.get("hours"):
        return {"hours": _rows_from_json(entry["hours"]),
                "fetched_at": entry["fetched_at"], "stale": True}
    return None


def get_air_quality() -> dict | None:
    """CAMS dust/pm2_5/aerosol_optical_depth hours for Accra, or None."""
    try:
        return _get("air_quality", AQ_URL, AQ_PARAMS)
    except Exception:
        return None


def get_weather() -> dict | None:
    """Wind, boundary-layer height and precipitation hours for Accra, or None."""
    try:
        return _get("weather", WX_URL, WX_PARAMS)
    except Exception:
        return None


def dust_risk_level(dust_ugm3) -> dict:
    """Dust risk from CAMS dust (µg/m³): low <50, medium 50-150, high >150."""
    try:
        value = float(dust_ugm3)
    except (TypeError, ValueError):
        return {"level": "unknown", "label": "Unknown", "value": None}
    if value < 50:
        return {"level": "low", "label": "Low", "value": value}
    if value <= 150:
        return {"level": "medium", "label": "Medium", "value": value}
    return {"level": "high", "label": "High", "value": value}
