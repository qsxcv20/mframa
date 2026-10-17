"""Mframa analytics layer: AQI conversion, advice, diurnal patterns, exposure, IDW grid.

Pure Python + numpy. No network access, no Streamlit import.
All times are UTC, which equals Ghana local time (UTC+0).
"""

from __future__ import annotations

from datetime import datetime, timezone

import numpy as np

# US EPA PM2.5 breakpoints: (conc_low, conc_high, aqi_low, aqi_high)
_PM25_BREAKPOINTS = (
    (0.0, 12.0, 0, 50),
    (12.1, 35.4, 51, 100),
    (35.5, 55.4, 101, 150),
    (55.5, 150.4, 151, 200),
    (150.5, 250.4, 201, 300),
    (250.5, 500.4, 301, 500),
)

_AQI_CATEGORIES = (
    (50, "Good", "#00e400"),
    (100, "Moderate", "#ffff00"),
    (150, "Unhealthy for Sensitive Groups", "#ff7e00"),
    (200, "Unhealthy", "#ff0000"),
    (300, "Very Unhealthy", "#8f3f97"),
    (500, "Hazardous", "#7e0023"),
)

# Minute ventilation (L/min) by activity level; typical literature values
# (e.g. US EPA Exposure Factors Handbook).
_VENTILATION_L_PER_MIN = {"rest": 6.0, "light": 12.0, "moderate": 24.0, "heavy": 40.0}

# Berkeley Earth rule of thumb: 1 cigarette/day ≈ 22 µg/m³ PM2.5 inhaled over
# ~11.5 m³ of air per day ≈ 253 µg PM2.5.
_UG_PER_CIGARETTE = 253.0


def pm25_to_aqi(c: float) -> int:
    """Convert a PM2.5 concentration (µg/m³) to US EPA AQI via piecewise-linear interpolation."""
    if c < 0:
        c = 0.0
    c = float(int(c * 10) / 10)  # EPA truncates to 0.1 µg/m³
    for c_lo, c_hi, a_lo, a_hi in _PM25_BREAKPOINTS:
        if c_lo <= c <= c_hi:
            return round((a_hi - a_lo) / (c_hi - c_lo) * (c - c_lo) + a_lo)
    return 500


def aqi_category(aqi: int) -> dict:
    """Return {'label', 'color_hex'} for an AQI value (six US EPA categories)."""
    for upper, label, color in _AQI_CATEGORIES:
        if aqi <= upper:
            return {"label": label, "color_hex": color}
    return {"label": "Hazardous", "color_hex": "#7e0023"}


def _level_key(aqi: int) -> str:
    """Map AQI to an advice band."""
    if aqi <= 50:
        return "good"
    if aqi <= 100:
        return "moderate"
    if aqi <= 150:
        return "usg"
    return "bad"  # unhealthy and above

_ADVICE: dict[str, dict[str, list[str]]] = {
    "good": {
        "general": [
            "Air quality is good — a great day for outdoor errands or a walk along the coast.",
            "If you cook with a charcoal stove, light it outdoors to keep your home's air clean.",
        ],
        "child": [
            "Good air today — children can play outside freely.",
            "Keep kids away from charcoal stoves and trash-burning spots even on clean days.",
        ],
        "asthma": [
            "Conditions look safe for outdoor activity; still carry your reliever inhaler.",
            "Avoid standing near charcoal braziers or burning refuse — smoke can spike locally.",
        ],
        "pregnant": [
            "Air is clean today; normal outdoor activity is fine.",
            "Cook in a well-ventilated space, away from charcoal smoke.",
        ],
        "senior": [
            "A good day for a gentle walk or sitting outside.",
            "Avoid smoke from neighbourhood waste burning even when the index is low.",
        ],
        "athlete": [
            "Great window for outdoor training, running, or football.",
            "Train away from busy roads like the N1 highway to avoid exhaust hotspots.",
        ],
    },
    "moderate": {
        "general": [
            "Acceptable air, but unusually sensitive people should watch for symptoms.",
            "During Harmattan season dust can build through the day — check again before evening outings.",
        ],
        "child": [
            "Outdoor play is fine, but cut it short if children start coughing.",
            "Keep children away from burning waste and smoky charcoal stoves.",
        ],
        "asthma": [
            "Limit prolonged outdoor exertion and keep your inhaler within reach.",
            "Harmattan dust and burn smoke can trigger attacks — stay indoors if you smell smoke.",
        ],
        "pregnant": [
            "Moderate air — take breaks indoors if you feel short of breath.",
            "Avoid smoky cooking areas; use LPG or a well-ventilated kitchen where possible.",
        ],
        "senior": [
            "Short walks are fine; avoid long exposure along busy roads like the N1.",
            "Stay indoors if dust haze thickens during Harmattan.",
        ],
        "athlete": [
            "Reduce intensity of long outdoor workouts; move sessions indoors if possible.",
            "Avoid training beside heavy traffic — exposure rises sharply on congested corridors.",
        ],
    },
    "usg": {
        "general": [
            "Sensitive groups should reduce prolonged outdoor exertion.",
            "Close windows against dust and smoke, especially during Harmattan or nearby burning.",
        ],
        "child": [
            "Keep children indoors for strenuous play; short quiet outdoor time is okay.",
            "Watch for coughing or wheezing and move inside at the first sign.",
        ],
        "asthma": [
            "Stay indoors as much as possible and pre-medicate as advised by your doctor.",
            "Avoid commute-time traffic on the N1 highway — exhaust plus dust worsens attacks.",
        ],
        "pregnant": [
            "Limit time outdoors and avoid smoky or dusty areas entirely.",
            "If you must travel, go outside rush hours and keep car windows up.",
        ],
        "senior": [
            "Remain indoors with windows closed against dust and smoke.",
            "Postpone outdoor errands until air improves.",
        ],
        "athlete": [
            "Move training indoors today; outdoor exertion multiplies pollutant intake.",
            "If you must train outside, keep it short and far from traffic and burn sites.",
        ],
    },
    "bad": {
        "general": [
            "Everyone should avoid prolonged outdoor exertion; sensitive groups stay indoors.",
            "Wear a well-fitting mask if you must commute, and keep windows shut against smoke and dust.",
            "Avoid areas with active waste burning — local smoke can be far worse than the city average.",
        ],
        "child": [
            "Keep children indoors; no outdoor play or sports today.",
            "Seal windows against Harmattan dust and smoke, and watch closely for coughing.",
        ],
        "asthma": [
            "Stay indoors, keep medication close, and seek care if symptoms escalate.",
            "Do not travel during rush hour — N1 traffic fumes sharply raise exposure.",
        ],
        "pregnant": [
            "Stay indoors as much as possible; avoid all smoke and dust exposure.",
            "Delegate outdoor errands; if travel is essential, use a mask and closed car windows.",
        ],
        "senior": [
            "Remain indoors with windows closed; avoid any outdoor exertion.",
            "Seek medical advice promptly if you feel chest tightness or breathlessness.",
        ],
        "athlete": [
            "Cancel outdoor training — exercising in this air multiplies your dose several-fold.",
            "Train indoors with filtered or conditioned air instead.",
        ],
    },
}


def profile_advice(aqi: int, profile: str = "general") -> list[str]:
    """Return 2-4 Ghana-contextual advice strings for an AQI value and user profile.

    profile is one of: general, child, asthma, pregnant, senior, athlete.
    """
    band = _ADVICE[_level_key(aqi)]
    return list(band.get(profile, band["general"]))


def diurnal_profile(hourly: list[dict]) -> dict[int, float]:
    """Mean PM2.5 per hour of day (0-23) from 7-day hourly records.

    Each record needs 'hour_utc' (ISO 8601) and 'value'. Ghana is UTC+0,
    so UTC hours equal local hours. Hours with no data are omitted.
    """
    sums: dict[int, float] = {}
    counts: dict[int, int] = {}
    for rec in hourly:
        value = rec.get("value")
        ts = rec.get("hour_utc")
        if value is None or ts is None:
            continue
        hour = datetime.fromisoformat(str(ts).replace("Z", "+00:00")).hour
        sums[hour] = sums.get(hour, 0.0) + float(value)
        counts[hour] = counts.get(hour, 0) + 1
    return {h: sums[h] / counts[h] for h in sorted(sums)}


def best_hours(hourly: list[dict]) -> dict:
    """Rank hours of the day by air quality for planning outdoor activity.

    For each hour 0-23: 'expected' is the 7-day diurnal mean, 'today' is the
    measured value if that hour has already occurred today (else None), and
    'level' is good (<12), moderate (<35.5) or unhealthy, judged on today's
    measurement when available else the expected mean. Consecutive runs of
    >=2 good hours merge into green_windows, unhealthy hours into red_windows.
    Windows are half-open (start_hour, end_hour_exclusive); runs wrapping
    midnight are kept as-is within the 0-23 axis.
    """
    profile = diurnal_profile(hourly)
    today = datetime.now(timezone.utc).date()

    today_vals: dict[int, list[float]] = {}
    for rec in hourly:
        value, ts = rec.get("value"), rec.get("hour_utc")
        if value is None or ts is None:
            continue
        dt = datetime.fromisoformat(str(ts).replace("Z", "+00:00"))
        if dt.date() == today:
            today_vals.setdefault(dt.hour, []).append(float(value))

    hours = []
    for h in range(24):
        expected = profile.get(h)
        measured = (
            sum(today_vals[h]) / len(today_vals[h]) if h in today_vals else None
        )
        basis = measured if measured is not None else expected
        if basis is None:
            level = "unknown"
        elif basis < 12.0:
            level = "good"
        elif basis < 35.5:
            level = "moderate"
        else:
            level = "unhealthy"
        hours.append(
            {
                "hour": h,
                "expected": round(expected, 2) if expected is not None else None,
                "today": round(measured, 2) if measured is not None else None,
                "level": level,
            }
        )

    def _windows(target: str, min_run: int = 2) -> list[tuple[int, int]]:
        windows, start = [], None
        for h in range(24):
            if hours[h]["level"] == target:
                if start is None:
                    start = h
            elif start is not None:
                if h - start >= min_run:
                    windows.append((start, h))
                start = None
        if start is not None and 24 - start >= min_run:
            windows.append((start, 24))
        return windows

    return {
        "hours": hours,
        "green_windows": _windows("good"),
        "red_windows": _windows("unhealthy"),
    }


def exposure_report(
    pm25_commute: float,
    hours_commute: float,
    pm25_outdoor: float,
    hours_outdoor: float,
    activity: str = "light",
) -> dict:
    """Estimate inhaled PM2.5 dose (µg) and cigarette equivalents for a day.

    Minute ventilation by activity (typical literature values, e.g. US EPA
    Exposure Factors Handbook): rest 6, light 12, moderate 24, heavy 40 L/min.
    The commute leg uses 'moderate' ventilation (walking/cycling/trotro),
    the outdoor leg uses the given activity. Dose = concentration x
    ventilation (m³/min) x 60 x hours. Cigarette equivalents use the
    Berkeley Earth rule: 1 cigarette ≈ 22 µg/m³ x 11.5 m³/day ≈ 253 µg.
    """
    vent_out = _VENTILATION_L_PER_MIN.get(activity, 12.0)
    legs = [
        ("Commute", pm25_commute, _VENTILATION_L_PER_MIN["moderate"], hours_commute),
        ("Outdoor activity", pm25_outdoor, vent_out, hours_outdoor),
    ]
    breakdown = []
    total = 0.0
    for label, conc, vent_l, hrs in legs:
        ug = float(conc) * (vent_l / 1000.0) * 60.0 * float(hrs)
        breakdown.append({"label": label, "ug": round(ug, 1)})
        total += ug
    cigarettes = total / _UG_PER_CIGARETTE
    cigs_txt = f"{cigarettes:.1f}" if cigarettes >= 0.05 else "less than 0.1"
    headline = (
        f"A day in Accra today ≈ smoking {cigs_txt} cigarettes "
        f"(inhaled ≈ {total:.0f} µg of PM2.5)"
    )
    return {
        "inhaled_ug": round(total, 1),
        "cigarettes": round(cigarettes, 2),
        "headline": headline,
        "breakdown": breakdown,
    }


def idw_grid(
    points: list[tuple[float, float, float]],
    lat_range: tuple[float, float],
    lon_range: tuple[float, float],
    n: int = 60,
    power: float = 2.0,
) -> np.ndarray:
    """Inverse-distance-weighted interpolation of station values onto a grid.

    points are (lat, lon, value) tuples. Returns an (n, n) array indexed
    [row, col] = [lat, lon], ascending from the low end of each range —
    suitable for a map heat layer. Exact station hits keep their own value.
    Degenerate inputs (no points, or a zero-size range) return an n x n NaN
    grid.
    """
    grid = np.full((n, n), np.nan)
    if not points or n < 1:
        return grid
    lat_lo, lat_hi = lat_range
    lon_lo, lon_hi = lon_range
    if lat_hi == lat_lo or lon_hi == lon_lo:
        return grid

    lats = np.linspace(lat_lo, lat_hi, n)
    lons = np.linspace(lon_lo, lon_hi, n)
    plats = np.array([p[0] for p in points])
    plons = np.array([p[1] for p in points])
    pvals = np.array([p[2] for p in points], dtype=float)

    glat, glon = np.meshgrid(lats, lons, indexing="ij")  # (n, n)
    # distances: (n, n, n_points)
    d2 = (glat[..., None] - plats) ** 2 + (glon[..., None] - plons) ** 2
    exact = d2 <= 0.0
    with np.errstate(divide="ignore"):
        w = 1.0 / np.power(np.sqrt(d2), power)
    w = np.where(exact, np.inf, w)
    wsum = w.sum(axis=-1)
    out = (w * pvals).sum(axis=-1) / wsum
    # Where a grid node coincides with a station, inf/inf is NaN; restore it.
    if exact.any():
        rows, cols, ks = np.nonzero(exact)
        out[rows, cols] = pvals[ks]
    return out
