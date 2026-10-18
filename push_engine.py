"""Mframa proactive push engine: morning briefings and burst alerts.

Two free delivery channels:
- ntfy.sh topic broadcast (city-wide) — no account or token needed, users
  subscribe at https://ntfy.sh/mframa-accra-air or in the ntfy app.
- Telegram bot (per-subscriber) — activates when TELEGRAM_BOT_TOKEN is set.

Pure requests + numpy — never imports streamlit, so it can run in GitHub
Actions cron jobs. Live OpenAQ v3 first, data/snapshot.json as fallback,
same philosophy as the main app. API keys are read only from environment
variables and are never printed.

CLI:
    python push_engine.py briefing  [--dry-run]  # morning briefing to Telegram subscribers
    python push_engine.py broadcast [--dry-run]  # city-wide morning briefing to ntfy topic
    python push_engine.py alerts    [--dry-run]  # threshold check (AQI >= 151), Telegram + ntfy
    python push_engine.py poll      [--dry-run]  # handle Telegram getUpdates commands

All times are UTC, which equals Ghana local time (UTC+0).
"""

from __future__ import annotations

import argparse
import difflib
import json
import os
import sys
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path

import numpy as np
import requests

import analytics

API_BASE = "https://api.openaq.org/v3"
COUNTRIES_ID = 152  # Ghana
BBOX = {"lat_min": 5.45, "lat_max": 5.75, "lon_min": -0.40, "lon_max": 0.10}
ACCRA_CENTER = (5.6037, -0.1870)
REQUEST_TIMEOUT = 20
MAX_RETRIES = 3
ENRICH_LIMIT = 30  # stations nearest Accra center enriched with hourly data

ALERT_AQI_THRESHOLD = 151  # US EPA "Unhealthy" and above
ALERT_COOLDOWN_HOURS = 12

NTFY_BASE = os.environ.get("NTFY_BASE", "https://ntfy.sh").rstrip("/")
NTFY_TOPIC = os.environ.get("NTFY_TOPIC", "mframa-accra-air")

BASE_DIR = Path(__file__).parent
SNAPSHOT_PATH = BASE_DIR / "data" / "snapshot.json"
SUBSCRIBERS_PATH = BASE_DIR / "subscribers.json"
BOT_STATE_PATH = BASE_DIR / "bot_state.json"


# ---------------------------------------------------------------------------
# State files
# ---------------------------------------------------------------------------

def _load_json(path: Path, default: dict) -> dict:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        return data if isinstance(data, dict) else default
    except (OSError, json.JSONDecodeError):
        return default


def _save_json(path: Path, data: dict) -> None:
    path.write_text(json.dumps(data, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")


def load_subscribers() -> list[dict]:
    return _load_json(SUBSCRIBERS_PATH, {"subscribers": []}).get("subscribers") or []


def save_subscribers(subscribers: list[dict]) -> None:
    _save_json(SUBSCRIBERS_PATH, {"subscribers": subscribers})


def load_bot_state() -> dict:
    state = _load_json(BOT_STATE_PATH, {"last_update_id": 0})
    state.setdefault("last_update_id", 0)
    return state


def save_bot_state(state: dict) -> None:
    _save_json(BOT_STATE_PATH, state)


# ---------------------------------------------------------------------------
# OpenAQ data access (live first, snapshot fallback)
# ---------------------------------------------------------------------------

def get_api_key() -> str | None:
    return os.environ.get("OPENAQ_API_KEY") or None


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
    return _load_json(SNAPSHOT_PATH, {"locations": []}).get("locations") or []


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


def get_hourly_pm25(location: dict, days: int = 7) -> list[dict]:
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
                return hours
    # snapshot fallback
    hourly = location.get("hourly_pm25")
    if not hourly:
        for loc in _snapshot_locations():
            if loc.get("id") == location.get("id"):
                hourly = loc.get("hourly_pm25")
                break
    hourly = [h for h in (hourly or []) if h.get("value") is not None]
    hourly.sort(key=lambda h: h.get("hour_utc") or "")
    return hourly[-days * 24:] if hourly else []


def pm25_of(loc: dict) -> float | None:
    latest = loc.get("latest_pm25") or {}
    value = latest.get("value")
    try:
        return float(value) if value is not None else None
    except (TypeError, ValueError):
        return None


def stations_with_readings(locations: list[dict], extra_ids: set | None = None) -> list[dict]:
    """Stations that have a current PM2.5 value; enrich from hourly if needed.

    extra_ids: station ids that must be enriched even beyond ENRICH_LIMIT
    (e.g. stations subscribers are registered to).
    """
    ready = [l for l in locations if pm25_of(l) is not None]
    if ready:
        return ready

    def dist(loc):
        return (loc.get("lat", 0) - ACCRA_CENTER[0]) ** 2 + (loc.get("lon", 0) - ACCRA_CENTER[1]) ** 2

    ordered = sorted(locations, key=dist)
    targets = ordered[:ENRICH_LIMIT]
    target_ids = {l.get("id") for l in targets}
    if extra_ids:
        for loc in ordered:
            if loc.get("id") in extra_ids and loc.get("id") not in target_ids:
                targets.append(loc)
                target_ids.add(loc.get("id"))

    enriched = []
    for loc in targets:
        hourly = get_hourly_pm25(loc, days=7)
        if not hourly:
            continue
        loc = dict(loc)
        loc["hourly_pm25"] = hourly
        last = hourly[-1]
        loc["latest_pm25"] = {"value": last.get("value"), "datetime_utc": last.get("hour_utc")}
        if pm25_of(loc) is not None:
            enriched.append(loc)
    return enriched


# ---------------------------------------------------------------------------
# City-wide context
# ---------------------------------------------------------------------------

_CITY_CACHE: dict[int, dict] = {}


def city_hourly_series(locations: list[dict]) -> list[dict]:
    """City-mean hourly PM2.5 series across all stations, oldest first."""
    by_hour: dict[str, list[float]] = {}
    for loc in locations:
        for rec in loc.get("hourly_pm25") or []:
            ts, value = rec.get("hour_utc"), rec.get("value")
            if ts and value is not None:
                by_hour.setdefault(str(ts), []).append(float(value))
    return [{"hour_utc": ts, "value": float(np.mean(vals))}
            for ts, vals in sorted(by_hour.items())]


def city_context(locations: list[dict]) -> dict:
    """City-wide median PM2.5, 7-day median and rising/falling trend.

    Trend is a least-squares slope (µg/m³ per day) over the city-mean hourly
    series of the past 7 days. Cached per locations object so briefing
    generation for many subscribers stays cheap.
    """
    cache_key = id(locations)
    if cache_key in _CITY_CACHE:
        return _CITY_CACHE[cache_key]

    current = [pm25_of(l) for l in locations if pm25_of(l) is not None]
    city_median = float(np.median(current)) if current else None

    points = [
        (datetime.fromisoformat(rec["hour_utc"].replace("Z", "+00:00")), rec["value"])
        for rec in city_hourly_series(locations)
    ]

    trend, week_median = None, None
    if points:
        week_median = float(np.median([v for _, v in points]))
        if len(points) >= 24:
            t0 = points[0][0]
            xs = np.array([(t - t0).total_seconds() / 86400.0 for t, _ in points])
            ys = np.array([v for _, v in points])
            trend = float(np.polyfit(xs, ys, 1)[0])  # µg/m³ per day

    ctx = {
        "city_median": city_median,
        "week_median": week_median,
        "trend_per_day": trend,
        "harmattan_watch": bool(
            trend is not None and trend > 0.5 and week_median is not None and week_median > 35.5
        ),
    }
    _CITY_CACHE[cache_key] = ctx
    return ctx


def find_station(sub: dict, locations: list[dict]) -> dict | None:
    sid = sub.get("station_id")
    for loc in locations:
        if loc.get("id") == sid:
            return loc
    lat, lon = sub.get("lat"), sub.get("lon")
    if lat is not None and lon is not None and locations:
        return min(locations, key=lambda l: (l.get("lat", 0) - lat) ** 2 + (l.get("lon", 0) - lon) ** 2)
    return None


# ---------------------------------------------------------------------------
# Message builders
# ---------------------------------------------------------------------------

def _fmt_window(w: tuple[int, int]) -> str:
    return f"{w[0]:02d}:00–{w[1]:02d}:00"


def build_morning_message(sub: dict, locations: list[dict]) -> str:
    """Morning briefing for one subscriber (plain text, Telegram-safe)."""
    station = find_station(sub, locations)
    ctx = city_context(locations)
    name = sub.get("station_name") or (station or {}).get("name") or "your area"

    lines = [f"Good morning, Accra! Here is your Mframa air briefing for *{name}*.", ""]

    pm25 = pm25_of(station) if station else None
    aqi = analytics.pm25_to_aqi(pm25) if pm25 is not None else None
    if aqi is not None:
        cat = analytics.aqi_category(aqi)
        lines.append(f"Now: PM2.5 {pm25:.1f} µg/m³ — AQI {aqi} ({cat['label']}) {cat['kaomoji']}")
    else:
        lines.append("Your station has no fresh reading this morning; guidance below uses the 7-day pattern.")

    green, red = [], []
    hourly = (station or {}).get("hourly_pm25") or []
    if hourly:
        plan = analytics.best_hours(hourly)
        green = plan.get("green_windows") or []
        red = plan.get("red_windows") or []
    if green:
        lines.append("Cleanest hours today: " + " · ".join(_fmt_window(w) for w in green))
    else:
        lines.append("No clear low-pollution window today — prefer indoor exercise.")

    lines.append("")
    lines.append(
        "Commute: rush hours 06:00–09:00 and 17:00–20:00 push roadside pollution up. "
        "If you can, travel outside these windows; on a trotro keep windows up in jams."
    )
    if red:
        lines.append("Avoid heavy outdoor exertion: " + " · ".join(_fmt_window(w) for w in red))

    if green and (aqi is None or aqi <= 100):
        lines.append("Laundry & windows: good day to air the house and dry clothes outside during the clean window.")
    elif green:
        lines.append("Laundry & windows: open windows only during the clean window; dry clothes outside before the evening rush.")
    else:
        lines.append("Laundry & windows: keep windows shut and dry clothes indoors today.")

    if ctx.get("harmattan_watch"):
        lines.append("")
        lines.append(
            "Harmattan watch: city-wide PM2.5 has been climbing over the past week "
            f"(7-day median {ctx['week_median']:.1f} µg/m³). Dust season is building — expect hazy afternoons."
        )

    lines.append("")
    lines.append("Data: OpenAQ · /stop to unsubscribe")
    return "\n".join(lines)


def build_alert_message(station_info: dict, city_median: float | None) -> str:
    """Burst alert when a station or the whole city crosses AQI 151."""
    name = station_info.get("name") or "your station"
    pm25 = station_info.get("pm25")
    aqi = station_info.get("aqi")
    cat = analytics.aqi_category(aqi) if aqi is not None else {"label": "Unhealthy", "kaomoji": "(＞_＜)😷"}
    label = cat["label"]

    lines = [f"*AIR QUALITY ALERT — Accra* {cat['kaomoji']}", ""]
    if pm25 is not None and aqi is not None:
        lines.append(f"{name}: PM2.5 {pm25:.1f} µg/m³ — AQI {aqi} ({label}).")
    if city_median is not None:
        lines.append(f"City median right now: {city_median:.1f} µg/m³ (AQI {analytics.pm25_to_aqi(city_median)}).")
    lines.append("")
    lines.append("What to do now:")
    lines.append("- Stay indoors and keep windows closed.")
    lines.append("- Avoid the 06:00–09:00 / 17:00–20:00 rush corridors if you must travel; wear a well-fitting mask.")
    lines.append("- Move children, elderly and anyone with asthma away from smoke and dust.")
    lines.append("- Postpone outdoor exercise, laundry and burning of any waste.")
    lines.append("")
    lines.append("We will notify you again if conditions worsen. Data: OpenAQ · /stop to unsubscribe")
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# City-wide (ntfy) message builders — plain text, no Markdown
# ---------------------------------------------------------------------------

def build_city_briefing(stations: list[dict]) -> str:
    """City-wide morning briefing for the public ntfy topic."""
    ctx = city_context(stations)
    city_median = ctx.get("city_median")
    aqi = analytics.pm25_to_aqi(city_median) if city_median is not None else None

    lines = ["Good morning, Accra! Your Mframa city air briefing:", ""]
    if aqi is not None:
        cat = analytics.aqi_category(aqi)
        lines.append(f"City now: PM2.5 {city_median:.1f} µg/m³ — AQI {aqi} ({cat['label']}) {cat['kaomoji']}")
    else:
        lines.append("No fresh city reading this morning; guidance below uses the 7-day pattern.")

    series = city_hourly_series(stations)
    if series:
        plan = analytics.best_hours(series)
        green = plan.get("green_windows") or []
        red = plan.get("red_windows") or []
        if green:
            lines.append("Cleanest hours today: " + " · ".join(_fmt_window(w) for w in green))
        else:
            lines.append("No clear low-pollution window today — prefer indoor exercise.")
        if red:
            lines.append("Avoid heavy outdoor exertion: " + " · ".join(_fmt_window(w) for w in red))

    lines.append("")
    lines.append(
        "Commute: rush hours 06:00–09:00 and 17:00–20:00 push roadside pollution up. "
        "If you can, travel outside these windows; on a trotro keep windows up in jams."
    )
    if ctx.get("harmattan_watch"):
        lines.append("")
        lines.append(
            "Harmattan watch: city-wide PM2.5 has been climbing over the past week "
            f"(7-day median {ctx['week_median']:.1f} µg/m³). Dust season is building — expect hazy afternoons."
        )
    lines.append("")
    lines.append("Live map & personal advice: https://mframa.streamlit.app · Data: OpenAQ")
    return "\n".join(lines)


def build_city_alert(station_info: dict, city_median: float | None) -> str:
    """City-wide burst alert body for the ntfy topic (plain text)."""
    name = station_info.get("name") or "Accra"
    pm25 = station_info.get("pm25")
    aqi = station_info.get("aqi")
    cat = analytics.aqi_category(aqi) if aqi is not None else {"label": "Unhealthy", "kaomoji": "(＞_＜)😷"}
    label = cat["label"]

    lines = [f"{cat['kaomoji']} Air Quality Alert — Accra", ""]
    if pm25 is not None and aqi is not None:
        lines.append(f"{name}: PM2.5 {pm25:.1f} µg/m³ — AQI {aqi} ({label}).")
    if city_median is not None:
        lines.append(f"City median right now: {city_median:.1f} µg/m³ "
                     f"(AQI {analytics.pm25_to_aqi(city_median)}).")
    lines.append("")
    lines.append("What to do now:")
    lines.append("- Stay indoors and keep windows closed.")
    lines.append("- Avoid the 06:00–09:00 / 17:00–20:00 rush corridors if you must travel; wear a well-fitting mask.")
    lines.append("- Move children, elderly and anyone with asthma away from smoke and dust.")
    lines.append("- Postpone outdoor exercise, laundry and burning of any waste.")
    lines.append("")
    lines.append("Live map: https://mframa.streamlit.app · Data: OpenAQ")
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Telegram transport
# ---------------------------------------------------------------------------

def get_bot_token() -> str | None:
    return os.environ.get("TELEGRAM_BOT_TOKEN") or None


def send_message(token: str, chat_id, text: str, dry_run: bool = False) -> bool:
    if dry_run:
        print(f"--- [dry-run] message to chat_id={chat_id} ---")
        print(text)
        print("--- end message ---\n")
        return True
    try:
        resp = requests.post(
            f"https://api.telegram.org/bot{token}/sendMessage",
            json={"chat_id": chat_id, "text": text, "parse_mode": "Markdown"},
            timeout=REQUEST_TIMEOUT,
        )
        if resp.status_code != 200:
            # fall back to plain text if Markdown parsing failed
            resp = requests.post(
                f"https://api.telegram.org/bot{token}/sendMessage",
                json={"chat_id": chat_id, "text": text},
                timeout=REQUEST_TIMEOUT,
            )
        return resp.status_code == 200
    except requests.RequestException as exc:
        print(f"Telegram send failed for chat_id={chat_id}: {exc}", file=sys.stderr)
        return False


# ---------------------------------------------------------------------------
# ntfy transport (city-wide public topic)
# ---------------------------------------------------------------------------

def _header_ascii(s: str) -> str:
    """HTTP headers must be latin-1; fold common unicode punctuation to ASCII."""
    return (s.replace("\u2013", "-").replace("\u2014", "-")
             .encode("ascii", "replace").decode("ascii"))


def send_ntfy(title: str, text: str, priority: str = "default",
              tags: str = "", dry_run: bool = False) -> bool:
    """Publish a message to the public ntfy topic. No auth needed."""
    if dry_run:
        print(f"--- [dry-run] ntfy publish to {NTFY_BASE}/{NTFY_TOPIC} ---")
        print(f"Title: {title} | Priority: {priority} | Tags: {tags}")
        print(text)
        print("--- end message ---\n")
        return True
    try:
        resp = requests.post(
            f"{NTFY_BASE}/{NTFY_TOPIC}",
            data=text.encode("utf-8"),
            headers={"Title": _header_ascii(title), "Priority": priority, "Tags": tags},
            timeout=REQUEST_TIMEOUT,
        )
        if resp.status_code != 200:
            print(f"ntfy publish failed: HTTP {resp.status_code} {resp.text[:200]}", file=sys.stderr)
            return False
        return True
    except requests.RequestException as exc:
        print(f"ntfy publish failed: {exc}", file=sys.stderr)
        return False


def cmd_broadcast(dry_run: bool) -> int:
    """City-wide morning briefing to the ntfy topic."""
    locations, source = get_locations()
    stations = stations_with_readings(locations)
    print(f"Data source: {source}; stations with readings: {len(stations)}")
    if not stations:
        print("No station readings available — broadcast skipped.", file=sys.stderr)
        return 1
    msg = build_city_briefing(stations)
    ok = send_ntfy("Mframa morning briefing — Accra air", msg,
                   priority="default", tags="sunrise,ghana", dry_run=dry_run)
    print(f"City briefing {'printed' if dry_run else 'published'}: {'ok' if ok else 'FAILED'}.")
    return 0 if ok else 1


# ---------------------------------------------------------------------------
# Commands
# ---------------------------------------------------------------------------

def cmd_briefing(dry_run: bool) -> int:
    subscribers = load_subscribers()
    if not subscribers:
        print("No subscribers — nothing to send.")
        return 0
    token = get_bot_token()
    if not token and not dry_run:
        print("TELEGRAM_BOT_TOKEN not set — falling back to dry-run (no messages sent).")
        dry_run = True

    locations, source = get_locations()
    extra = {s.get("station_id") for s in subscribers if s.get("station_id") is not None}
    stations = stations_with_readings(locations, extra_ids=extra)
    print(f"Data source: {source}; stations with readings: {len(stations)}")
    if not stations:
        print("No station readings available — briefing skipped.", file=sys.stderr)
        return 1

    sent = 0
    for sub in subscribers:
        msg = build_morning_message(sub, stations)
        if send_message(token or "", sub.get("chat_id"), msg, dry_run=dry_run):
            sent += 1
    print(f"Briefing {'printed' if dry_run else 'sent'} for {sent}/{len(subscribers)} subscribers.")
    return 0


def _alert_due(sub: dict, alert_type: str, now: datetime) -> bool:
    if sub.get("last_alert_type") != alert_type:
        return True
    last = sub.get("last_alert_at")
    if not last:
        return True
    try:
        last_dt = datetime.fromisoformat(str(last).replace("Z", "+00:00"))
    except ValueError:
        return True
    return now - last_dt >= timedelta(hours=ALERT_COOLDOWN_HOURS)


def cmd_alerts(dry_run: bool) -> int:
    subscribers = load_subscribers()
    token = get_bot_token()
    tg_dry_run = dry_run
    if not token and not tg_dry_run:
        print("TELEGRAM_BOT_TOKEN not set — Telegram alerts in dry-run (ntfy still publishes).")
        tg_dry_run = True

    locations, source = get_locations()
    extra = {s.get("station_id") for s in subscribers if s.get("station_id") is not None}
    stations = stations_with_readings(locations, extra_ids=extra)
    print(f"Data source: {source}; stations with readings: {len(stations)}")
    if not stations:
        print("No station readings available — alert check skipped.", file=sys.stderr)
        return 1

    ctx = city_context(stations)
    city_median = ctx.get("city_median")
    city_aqi = analytics.pm25_to_aqi(city_median) if city_median is not None else None
    city_alarm = city_aqi is not None and city_aqi >= ALERT_AQI_THRESHOLD
    print(f"City median PM2.5: {city_median and round(city_median, 1)} (AQI {city_aqi}); "
          f"city alarm: {city_alarm}")

    now = datetime.now(timezone.utc)

    # --- city-wide ntfy burst alert (public topic, worst station or city median) ---
    worst, worst_aqi = None, None
    for loc in stations:
        v = pm25_of(loc)
        a = analytics.pm25_to_aqi(v) if v is not None else None
        if a is not None and (worst_aqi is None or a > worst_aqi):
            worst, worst_aqi = loc, a

    ntfy_type, ntfy_info = None, None
    if worst_aqi is not None and worst_aqi >= ALERT_AQI_THRESHOLD:
        ntfy_type = "station"
        ntfy_info = {"name": worst.get("name"), "pm25": pm25_of(worst), "aqi": worst_aqi}
    elif city_alarm:
        ntfy_type = "city"
        ntfy_info = {"name": "Accra", "pm25": None, "aqi": None}

    if ntfy_type:
        state = load_bot_state()
        if _alert_due(state, f"ntfy_{ntfy_type}", now):
            body = build_city_alert(ntfy_info, city_median)
            if send_ntfy("AIR QUALITY ALERT — Accra", body,
                         priority="urgent", tags="rotating_light,warning", dry_run=dry_run):
                state["last_alert_type"] = f"ntfy_{ntfy_type}"
                state["last_alert_at"] = now.strftime("%Y-%m-%dT%H:%M:%SZ")
                if not dry_run:
                    save_bot_state(state)
                print(f"ntfy city alert {'printed' if dry_run else 'published'} ({ntfy_type}).")
        else:
            print(f"ntfy alert ({ntfy_type}) within {ALERT_COOLDOWN_HOURS}h cooldown — skipped.")

    # --- per-subscriber Telegram alerts ---
    sent, changed = 0, False
    for sub in subscribers:
        station = find_station(sub, stations)
        pm25 = pm25_of(station) if station else None
        aqi = analytics.pm25_to_aqi(pm25) if pm25 is not None else None

        alert_type, info = None, None
        if aqi is not None and aqi >= ALERT_AQI_THRESHOLD:
            alert_type = "station"
            info = {"name": (station or {}).get("name") or sub.get("station_name"),
                    "pm25": pm25, "aqi": aqi}
        elif city_alarm:
            alert_type = "city"
            info = {"name": sub.get("station_name") or "Accra", "pm25": None, "aqi": None}

        if alert_type and _alert_due(sub, alert_type, now):
            msg = build_alert_message(info, city_median)
            if send_message(token or "", sub.get("chat_id"), msg, dry_run=tg_dry_run):
                sub["last_alert_type"] = alert_type
                sub["last_alert_at"] = now.strftime("%Y-%m-%dT%H:%M:%SZ")
                sent += 1
                changed = True

    if changed and not tg_dry_run:
        save_subscribers(subscribers)
    print(f"Alerts {'printed' if tg_dry_run else 'sent'}: {sent} (threshold AQI {ALERT_AQI_THRESHOLD}, "
          f"cooldown {ALERT_COOLDOWN_HOURS}h).")
    return 0


# --- poll ---

WELCOME = (
    "Welcome to Mframa air alerts for Accra!\n\n"
    "Commands:\n"
    "/subscribe <station name> — e.g. /subscribe Agbogbloshie\n"
    "/subscribe nearest — then share your location, or send your location any time\n"
    "/stations — list monitored stations\n"
    "/status — current air at your station\n"
    "/stop — unsubscribe"
)


def _match_station(query: str, stations: list[dict]) -> dict | None:
    names = {str(s.get("name") or f"Station {s.get('id')}"): s for s in stations}
    q = query.strip().lower()
    for name, s in names.items():
        if q in name.lower():
            return s
    close = difflib.get_close_matches(query.strip(), list(names), n=1, cutoff=0.4)
    return names[close[0]] if close else None


def _nearest_station(lat: float, lon: float, stations: list[dict]) -> dict | None:
    if not stations:
        return None
    return min(stations, key=lambda s: (s.get("lat", 0) - lat) ** 2 + (s.get("lon", 0) - lon) ** 2)


def _subscribe(subscribers: list[dict], chat_id, station: dict) -> tuple[list[dict], str]:
    subscribers = [s for s in subscribers if s.get("chat_id") != chat_id]
    subscribers.append({
        "chat_id": chat_id,
        "station_id": station.get("id"),
        "station_name": station.get("name") or f"Station {station.get('id')}",
        "lat": station.get("lat"),
        "lon": station.get("lon"),
        "subscribed_at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "last_alert_type": None,
        "last_alert_at": None,
    })
    return subscribers, (
        f"Subscribed to *{station.get('name')}*. "
        "You will get a morning briefing and alerts when the air turns unhealthy. /stop to unsubscribe."
    )


def _handle_message(msg: dict, subscribers: list[dict], stations: list[dict]) -> tuple[list[dict], str | None]:
    chat = msg.get("chat") or {}
    chat_id = chat.get("id")
    if chat_id is None:
        return subscribers, None
    text = (msg.get("text") or "").strip()

    loc = msg.get("location")
    if loc and loc.get("latitude") is not None:
        station = _nearest_station(float(loc["latitude"]), float(loc["longitude"]), stations)
        if station:
            return _subscribe(subscribers, chat_id, station)
        return subscribers, "No stations available right now — please try again later."

    if not text.startswith("/"):
        return subscribers, "Send /subscribe <station name> to get started, or /stations to browse."

    parts = text.split(maxsplit=1)
    cmd = parts[0].lower().lstrip("/").split("@")[0]
    arg = parts[1] if len(parts) > 1 else ""

    if cmd == "start":
        return subscribers, WELCOME
    if cmd == "stop":
        before = len(subscribers)
        subscribers = [s for s in subscribers if s.get("chat_id") != chat_id]
        if len(subscribers) < before:
            return subscribers, "You are unsubscribed. Stay safe — Mframa."
        return subscribers, "You were not subscribed. " + WELCOME
    if cmd == "stations":
        names = sorted(str(s.get("name") or f"Station {s.get('id')}") for s in stations)
        listing = "\n".join(f"- {n}" for n in names[:40])
        suffix = f"\n… and {len(names) - 40} more." if len(names) > 40 else ""
        return subscribers, f"Monitored stations ({len(names)}):\n{listing}{suffix}\n\nUse /subscribe <name>"
    if cmd == "status":
        sub = next((s for s in subscribers if s.get("chat_id") == chat_id), None)
        if not sub:
            return subscribers, "You are not subscribed yet. " + WELCOME
        station = find_station(sub, stations)
        pm25 = pm25_of(station) if station else None
        if pm25 is None:
            return subscribers, f"No fresh reading for {sub.get('station_name')} right now."
        aqi = analytics.pm25_to_aqi(pm25)
        label = analytics.aqi_category(aqi)["label"]
        return subscribers, f"{sub.get('station_name')}: PM2.5 {pm25:.1f} µg/m³ — AQI {aqi} ({label})."
    if cmd == "subscribe":
        if not arg:
            return subscribers, "Usage: /subscribe <station name> or /subscribe nearest (then share your location)."
        if arg.strip().lower() == "nearest":
            return subscribers, "Please share your location (paperclip → Location) and I will subscribe you to the nearest station."
        station = _match_station(arg, stations)
        if station:
            return _subscribe(subscribers, chat_id, station)
        return subscribers, f"No station matching '{arg}'. Try /stations to see the list."
    return subscribers, "Unknown command. " + WELCOME


def cmd_poll(dry_run: bool) -> int:
    token = get_bot_token()
    if not token:
        print("TELEGRAM_BOT_TOKEN not set — poll degraded to dry-run (no updates fetched).")
        return 0
    if dry_run:
        print("[dry-run] poll would call getUpdates and process /start /subscribe /stations /status /stop.")
        return 0

    state = load_bot_state()
    try:
        resp = requests.get(
            f"https://api.telegram.org/bot{token}/getUpdates",
            params={"offset": state["last_update_id"] + 1, "timeout": 0},
            timeout=REQUEST_TIMEOUT,
        )
        payload = resp.json() if resp.status_code == 200 else {}
    except requests.RequestException as exc:
        print(f"getUpdates failed: {exc}", file=sys.stderr)
        return 1

    updates = payload.get("result") or []
    if not updates:
        print("No new updates.")
        return 0

    locations, source = get_locations()
    stations = stations_with_readings(locations) or locations
    subscribers = load_subscribers()
    changed = False

    for upd in updates:
        state["last_update_id"] = max(state["last_update_id"], upd.get("update_id", 0))
        msg = upd.get("message") or {}
        if not msg:
            continue
        chat_id = (msg.get("chat") or {}).get("id")
        before = json.dumps(subscribers, sort_keys=True)
        subscribers, reply = _handle_message(msg, subscribers, stations)
        if json.dumps(subscribers, sort_keys=True) != before:
            changed = True
        if reply and chat_id is not None:
            send_message(token, chat_id, reply)

    if changed:
        save_subscribers(subscribers)
    save_bot_state(state)
    print(f"Processed {len(updates)} updates (data source: {source}); subscribers changed: {changed}.")
    return 0


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def main() -> int:
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8", errors="replace")
        except (AttributeError, ValueError):
            pass
    parser = argparse.ArgumentParser(description="Mframa proactive push engine")
    parser.add_argument("command", choices=["briefing", "broadcast", "alerts", "poll"])
    parser.add_argument("--dry-run", action="store_true",
                        help="print messages instead of sending them (no token needed)")
    args = parser.parse_args()

    if args.command == "briefing":
        return cmd_briefing(args.dry_run)
    if args.command == "broadcast":
        return cmd_broadcast(args.dry_run)
    if args.command == "alerts":
        return cmd_alerts(args.dry_run)
    return cmd_poll(args.dry_run)


if __name__ == "__main__":
    sys.exit(main())
