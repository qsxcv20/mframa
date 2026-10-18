"""Mframa — Know your air, Accra.

TechHub Africa Hackathon 2026 · Air quality awareness for Accra, Ghana.
Data: OpenAQ v3 (live API with snapshot fallback via openaq_client).
"""

from datetime import datetime, timezone
from pathlib import Path
import json

import numpy as np
import pandas as pd
import plotly.graph_objects as go
import pydeck as pdk
import streamlit as st

import analytics
import nowcast
import openaq_client
import openmeteo_client

st.set_page_config(
    page_title="Mframa — Know your air, Accra",
    page_icon="🌬️",
    layout="wide",
)

# Responsive layer for small phones (~360-400 px). Everything is scoped to
# @media (max-width: 640px), so desktop rendering is byte-for-byte unchanged.
MOBILE_CSS = """
<style>
@media (max-width: 640px) {
  /* Tighter page margins so content uses the full phone width. */
  .stMainBlockContainer,
  [data-testid="stMainBlockContainer"],
  .block-container {
    padding-left: 0.9rem !important;
    padding-right: 0.9rem !important;
    padding-top: 1.4rem !important;
  }

  /* st.columns does not stack on narrow screens by itself — stack it. */
  [data-testid="stHorizontalBlock"] {
    flex-direction: column !important;
    row-gap: 0.4rem !important;
  }
  [data-testid="stHorizontalBlock"] > [data-testid="stColumn"] {
    width: 100% !important;
    flex: 1 1 100% !important;
    min-width: 0 !important;
  }

  /* Touch targets >= 44px (Android/WCAG guidance) for every control. */
  [data-testid="stButton"] button,
  [data-testid="stFormSubmitButton"] button,
  [data-testid="stExpander"] summary {
    min-height: 44px !important;
  }
  [data-baseweb="select"] > div {
    min-height: 44px !important;
  }
  [data-baseweb="select"] input {
    min-height: 30px !important;
  }
  [data-testid="stNumberInput"] input,
  [data-testid="stTextInput"] input {
    min-height: 44px !important;
  }
  [data-testid="stNumberInput"] button {
    min-width: 44px !important;
    min-height: 44px !important;
  }
  [data-testid="stRadio"] label {
    min-height: 44px !important;
    align-items: center !important;
  }
  [data-testid="stSlider"] [role="slider"] {
    width: 26px !important;
    height: 26px !important;
  }

  /* Hero cards: shrink typography and padding to fit 360px screens. */
  .aqi-card {
    padding: 20px 14px !important;
    border-radius: 14px !important;
  }
  .aqi-card .aqi-name { font-size: 0.9rem !important; }
  .aqi-card .aqi-value { font-size: 2.5rem !important; }
  .aqi-card .aqi-line { font-size: 1.1rem !important; }
  .cig-card { padding: 18px 14px !important; }
  .cig-card .cig-value { font-size: 2.6rem !important; }

  /* Charts get shorter so key content stays above the fold. */
  [data-testid="stDeckGlJsonChart"] {
    height: 340px !important;
  }
  [data-testid="stPlotlyChart"] {
    height: 300px !important;
    overflow: hidden !important;
  }

  /* Slightly smaller headings on phones. */
  h1 { font-size: 2rem !important; }
  h2, [data-testid="stMarkdownContainer"] h2 { font-size: 1.35rem !important; }
  h3, [data-testid="stMarkdownContainer"] h3 { font-size: 1.15rem !important; }
}
</style>
"""


def inject_responsive_css():
    try:
        st.markdown(MOBILE_CSS, unsafe_allow_html=True)
    except Exception:
        pass


ACCRA_CENTER = (5.6037, -0.1870)
MAP_CENTER = (5.60, -0.20)
GRID_LAT = (5.45, 5.75)
GRID_LON = (-0.40, 0.10)
PROFILES = ["general", "child", "asthma", "pregnant", "senior", "athlete"]
ACTIVITIES = ["rest", "light", "moderate", "heavy"]
FALLBACK_COLOR = "#8a94a6"


# ---------------------------------------------------------------------------
# Data access
# ---------------------------------------------------------------------------

@st.cache_data(ttl=300, show_spinner=False)
def load_locations():
    return openaq_client.get_locations()


@st.cache_data(ttl=1800, show_spinner=False)
def load_air_quality():
    """CAMS/ECMWF forecast via Open-Meteo (free, no key); None if unavailable."""
    try:
        return openmeteo_client.get_air_quality()
    except Exception:
        return None


@st.cache_data(ttl=3600, show_spinner=False)
def nowcast_metrics(locations):
    """Frozen leak-free holdout metrics for the nowcaster (bench_nowcast.py protocol).

    Returns a dict with mae/acc/hit10/n, or None on failure.
    """
    try:
        metrics_path = Path(__file__).parent / "data" / "nowcast_metrics.json"
        if metrics_path.exists():
            return json.loads(metrics_path.read_text(encoding="utf-8"))
    except Exception:
        pass
    try:
        mae = nowcast.backtest(locations or []).get("mae")
        return {"mae": mae} if mae is not None else None
    except Exception:
        return None


def stale_hours_of(station):
    """Hours since the station's most recent reading; None if no timestamp is known."""
    ts = (station.get("latest_pm25") or {}).get("datetime_utc") or station.get("last_updated_utc")
    if not ts:
        hourly = station.get("hourly_pm25") or []
        ts = hourly[-1].get("hour_utc") if hourly else None
    try:
        dt = datetime.fromisoformat(str(ts).replace("Z", "+00:00"))
    except (TypeError, ValueError):
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return max(0.0, (datetime.now(timezone.utc) - dt).total_seconds() / 3600.0)


def pm25_of(loc):
    latest = loc.get("latest_pm25") or {}
    value = latest.get("value")
    try:
        return float(value) if value is not None else None
    except (TypeError, ValueError):
        return None


def get_hourly(loc):
    hourly = loc.get("hourly_pm25") or []
    if hourly:
        return hourly
    try:
        hourly, _ = openaq_client.get_hourly_pm25(loc, days=7)
        return hourly or []
    except Exception:
        return []


def stations_with_readings(locations, enrich_limit=30):
    """Stations that have a current PM2.5 value.

    Live API responses may lack latest readings; in that case enrich the
    stations nearest Accra center from their hourly series.
    """
    ready = [l for l in locations if pm25_of(l) is not None]
    if ready:
        return ready
    def dist(loc):
        return (loc.get("lat", 0) - ACCRA_CENTER[0]) ** 2 + (loc.get("lon", 0) - ACCRA_CENTER[1]) ** 2
    enriched = []
    for loc in sorted(locations, key=dist)[:enrich_limit]:
        hourly = get_hourly(loc)
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
# Analytics adapters
# ---------------------------------------------------------------------------

def aqi_of(pm25):
    try:
        return int(round(analytics.pm25_to_aqi(pm25)))
    except Exception:
        return None


def aqi_info(aqi):
    """Return (label, hex_color) from analytics.aqi_category."""
    try:
        cat = analytics.aqi_category(aqi)
    except Exception:
        return "Unknown", FALLBACK_COLOR
    if isinstance(cat, dict):
        return str(cat.get("label", "")), str(cat.get("color_hex", cat.get("color", FALLBACK_COLOR)))
    if isinstance(cat, (tuple, list)) and len(cat) >= 2:
        return str(cat[0]), str(cat[1])
    return str(cat), FALLBACK_COLOR


def aqi_kaomoji(aqi):
    """Cute kaomoji face for the AQI level (empty string when unavailable)."""
    try:
        face = analytics.aqi_category(aqi).get("kaomoji")
    except Exception:
        return ""
    return str(face or "")


def advice_for(profile, aqi):
    try:
        tips = analytics.profile_advice(aqi, profile)
    except Exception:
        return []
    if isinstance(tips, str):
        return [tips]
    return [str(t) for t in (tips or [])]


def hourly_plan(hourly):
    """analytics.best_hours -> {hours: [{hour, expected, today, level}], green_windows, red_windows}."""
    try:
        plan = analytics.best_hours(hourly)
    except Exception:
        return None
    if not isinstance(plan, dict) or not plan.get("hours"):
        return None
    return plan


def exposure(pm_commute, commute_h, pm_outdoor, outdoor_h, activity):
    rep = analytics.exposure_report(pm_commute, commute_h, pm_outdoor, outdoor_h, activity)
    if not isinstance(rep, dict):
        return {"cigarettes": None, "headline": "", "breakdown": []}
    breakdown = rep.get("breakdown") or []
    if isinstance(breakdown, dict):
        breakdown = [{"label": k, "ug": v} for k, v in breakdown.items()]
    return {
        "cigarettes": rep.get("cigarettes"),
        "headline": str(rep.get("headline", "")),
        "breakdown": breakdown,
    }


def idw_points(stations, n=60):
    """Interpolate station PM2.5 over the Accra grid; returns DataFrame lat/lon/weight."""
    pts = [
        (s["lat"], s["lon"], pm25_of(s))
        for s in stations
        if s.get("lat") is not None and s.get("lon") is not None and pm25_of(s) is not None
    ]
    grid = np.asarray(analytics.idw_grid(pts, GRID_LAT, GRID_LON, n=n), dtype=float)
    lats = np.linspace(GRID_LAT[0], GRID_LAT[1], grid.shape[0])
    lons = np.linspace(GRID_LON[0], GRID_LON[1], grid.shape[1])
    glon, glat = np.meshgrid(lons, lats)  # rows = lat, cols = lon, matches grid indexing
    # normalize to 0..1 against 60 µg/m³ (~AQI 150) so colors track AQI severity
    df = pd.DataFrame({"lat": glat.ravel(), "lon": glon.ravel(),
                       "weight": np.clip(grid.ravel() / 60.0, 0.02, 1.0)})
    return df.dropna()


# ---------------------------------------------------------------------------
# Open-Meteo (CAMS dust / smoke) helpers
# ---------------------------------------------------------------------------

def _float_or_none(value):
    try:
        return float(value) if value is not None else None
    except (TypeError, ValueError):
        return None


def cams_current(aq):
    """Hour row closest to now; None values skipped per-field upstream."""
    if not aq or not aq.get("hours"):
        return None
    now = datetime.now(timezone.utc)
    return min(aq["hours"], key=lambda r: abs((r["time"] - now).total_seconds()))


def is_harmattan(aq, run_hours=24):
    """Harmattan conditions: AOD >0.6 now, or dust >50 µg/m³ for run_hours straight."""
    if not aq or not aq.get("hours"):
        return False
    current = cams_current(aq) or {}
    if (_float_or_none(current.get("aerosol_optical_depth")) or 0.0) > 0.6:
        return True
    run = 0
    for row in aq["hours"]:
        dust = _float_or_none(row.get("dust"))
        run = run + 1 if dust is not None and dust > 50 else 0
        if run >= run_hours:
            return True
    return False


def dust_smoke_split(dust, pm25):
    """Classify current PM into dust/smoke regimes from the CAMS dust:PM2.5 ratio."""
    dust, pm25 = _float_or_none(dust), _float_or_none(pm25)
    if dust is None or pm25 is None or pm25 <= 0:
        return None
    ratio = dust / pm25
    if ratio >= 0.6:
        return {
            "key": "dust", "title": "Dust-dominated", "ratio": ratio,
            "color": "#C98A2D",
            "advice": "Saharan dust is carrying most of the pollution. Keep windows "
                      "closed and wear a well-fitting mask (N95/KN95 if you have one) outdoors.",
        }
    if ratio <= 0.25:
        return {
            "key": "smoke", "title": "Smoke-dominated", "ratio": ratio,
            "color": "#B3402A",
            "advice": "Local burning/smoke is the main source. Avoid the morning and "
                      "evening burning peaks; people with asthma should stay indoors.",
        }
    return {
        "key": "mixed", "title": "Mixed dust & smoke", "ratio": ratio,
        "color": "#8A6A3B",
        "advice": "A blend of Harmattan dust and local smoke. Combine both precautions: "
                  "limit time outdoors at peak burning hours and wear a mask outside.",
    }


def render_dust_smoke_card():
    """'Dust or Smoke?' card for the My Air page; degrades silently to a caption."""
    aq = load_air_quality()
    if not aq:
        st.caption("Dust/smoke forecast temporarily unavailable.")
        return
    try:
        current = cams_current(aq) or {}
        dust = _float_or_none(current.get("dust"))
        pm25 = _float_or_none(current.get("pm2_5"))
        aod = _float_or_none(current.get("aerosol_optical_depth"))
        split = dust_smoke_split(dust, pm25)
        harmattan = is_harmattan(aq)
        if split is None and not harmattan:
            st.caption("Dust/smoke forecast temporarily unavailable.")
            return

        badge = (
            '<span style="display:inline-block;background:#8A5A00;color:#fff;'
            'border-radius:999px;padding:2px 10px;font-size:.75rem;font-weight:700;'
            'margin-left:8px;vertical-align:middle;">🏜️ Harmattan conditions</span>'
            if harmattan else ""
        )
        risk = openmeteo_client.dust_risk_level(dust)
        stale_txt = " (cached)" if aq.get("stale") else ""
        if split is not None:
            st.markdown(
                f"""
                <div style="background:#FBF7F0;border:1px solid #E5D9C3;border-radius:18px;
                            padding:20px 22px;color:#4A3A22;margin-bottom:8px;">
                  <div style="font-size:1.05rem;font-weight:800;margin-bottom:6px;">
                    Dust or Smoke? — {split['title']}{badge}
                  </div>
                  <div style="font-size:.95rem;line-height:1.5;">
                    Dust ≈ <b>{dust:.0f}</b> of <b>{pm25:.0f}</b> µg/m³ PM2.5
                    ({split['ratio'] * 100:.0f}% dust share · dust risk: {risk['label']}
                    {f" · AOD {aod:.2f}" if aod is not None else ""}).
                  </div>
                  <div style="font-size:.95rem;margin-top:6px;">{split['advice']}</div>
                  <div style="font-size:.75rem;opacity:.75;margin-top:8px;">
                    Forecast: CAMS/ECMWF via Open-Meteo (free){stale_txt}
                  </div>
                </div>
                """,
                unsafe_allow_html=True,
            )
        else:  # harmattan badge only, no ratio
            st.markdown(
                f"""
                <div style="background:#FBF7F0;border:1px solid #E5D9C3;border-radius:18px;
                            padding:20px 22px;color:#4A3A22;margin-bottom:8px;">
                  <div style="font-size:1.05rem;font-weight:800;">
                    Dust or Smoke?{badge}
                  </div>
                  <div style="font-size:.95rem;margin-top:6px;">
                    Saharan dust is elevated. Keep windows closed and wear a mask outdoors.
                  </div>
                  <div style="font-size:.75rem;opacity:.75;margin-top:8px;">
                    Forecast: CAMS/ECMWF via Open-Meteo (free){stale_txt}
                  </div>
                </div>
                """,
                unsafe_allow_html=True,
            )
    except Exception:
        st.caption("Dust/smoke forecast temporarily unavailable.")


def render_dust_forecast_chart(hours=48):
    """Next-N-hours CAMS dust & PM2.5 lines; renders nothing when unavailable."""
    aq = load_air_quality()
    if not aq or not aq.get("hours"):
        return False
    try:
        now = datetime.now(timezone.utc)
        cutoff = now + pd.Timedelta(hours=hours)
        rows = [
            r for r in aq["hours"]
            if now - pd.Timedelta(hours=6) <= r["time"] <= cutoff
        ]
        xs = [r["time"] for r in rows]
        dust = [_float_or_none(r.get("dust")) for r in rows]
        pm25 = [_float_or_none(r.get("pm2_5")) for r in rows]
        if not xs or not any(v is not None for v in dust + pm25):
            return False
        fig = go.Figure()
        fig.add_trace(go.Scatter(
            x=xs, y=pm25, mode="lines", name="PM2.5",
            line=dict(color="#B3402A", width=3), connectgaps=False,
        ))
        fig.add_trace(go.Scatter(
            x=xs, y=dust, mode="lines", name="Dust (Saharan)",
            line=dict(color="#C98A2D", width=2, dash="dash"), connectgaps=False,
        ))
        if is_harmattan(aq):
            fig.add_hline(y=50, line=dict(color="#C98A2D", width=1, dash="dot"),
                          annotation_text="Harmattan dust threshold (50)",
                          annotation_position="top left")
        fig.update_layout(
            height=320, margin=dict(l=10, r=10, t=30, b=10),
            title=f"Next {hours} h: dust & PM2.5 forecast",
            yaxis_title="µg/m³",
            legend=dict(orientation="h", yanchor="bottom", y=1.02),
        )
        st.plotly_chart(fig, width="stretch", config={"displayModeBar": False})
        st.caption("Forecast: CAMS/ECMWF via Open-Meteo (free)"
                   + (" — showing cached forecast" if aq.get("stale") else ""))
        return True
    except Exception:
        return False


# ---------------------------------------------------------------------------
# Presentation helpers
# ---------------------------------------------------------------------------

def hex_to_rgb(h):
    h = str(h).lstrip("#")
    if len(h) == 3:
        h = "".join(c * 2 for c in h)
    try:
        return [int(h[i:i + 2], 16) for i in (0, 2, 4)]
    except (ValueError, IndexError):
        return [138, 148, 166]


def text_on(bg_hex):
    r, g, b = hex_to_rgb(bg_hex)
    return "#1A2B21" if 0.299 * r + 0.587 * g + 0.114 * b > 150 else "#FFFFFF"


def nearest_index(stations):
    best_i, best_d = 0, float("inf")
    for i, s in enumerate(stations):
        d = (s.get("lat", 0) - ACCRA_CENTER[0]) ** 2 + (s.get("lon", 0) - ACCRA_CENTER[1]) ** 2
        if d < best_d:
            best_i, best_d = i, d
    return best_i


def pick_station(stations, key, label="Monitoring station"):
    names = [s.get("name") or f"Station {s.get('id')}" for s in stations]
    idx = st.sidebar.selectbox(
        label, range(len(stations)),
        format_func=lambda i: names[i], index=nearest_index(stations), key=key,
    )
    return stations[idx]


def data_banner(source):
    mode = ""
    try:
        mode = openaq_client.data_mode()
    except Exception:
        pass
    if source == "snapshot" or mode == "snapshot":
        st.warning("Showing recently cached OpenAQ data (live API unavailable)")


def footer():
    st.divider()
    st.caption("Data: OpenAQ (api.openaq.org) · AfriqAir & community sensors · Not medical advice")


# ---------------------------------------------------------------------------
# Pages
# ---------------------------------------------------------------------------

def render_my_air(stations):
    st.sidebar.markdown("### My Air")
    profile = st.sidebar.selectbox("Health profile", PROFILES)
    station = pick_station(stations, key="station_myair")

    pm25 = pm25_of(station)
    stale_h = stale_hours_of(station)
    estimate = None
    if pm25 is None or (stale_h is not None and stale_h > 3.0):
        try:
            estimate = nowcast.predict_station(
                station, [s for s in stations if s is not station])
        except Exception:
            estimate = None
        if estimate and estimate.get("value") is not None:
            pm25 = estimate["value"]

    if pm25 is None:
        st.info("No recent readings for this station and not enough data to estimate — "
                "try another station in the sidebar.")
        return

    aqi = aqi_of(pm25)
    label, color = aqi_info(aqi) if aqi is not None else ("No data", FALLBACK_COLOR)
    face = aqi_kaomoji(aqi) if aqi is not None else ""
    fg = text_on(color)
    latest = station.get("latest_pm25") or {}
    ts = latest.get("datetime_utc") or station.get("last_updated_utc") or "unknown time"
    provider = station.get("provider") or "OpenAQ"

    st.markdown(
        f"""
        <div class="aqi-card"
             style="background:{color};border-radius:18px;padding:30px 22px;
                    color:{fg};text-align:center;margin-bottom:8px;">
          <div class="aqi-name" style="font-size:1rem;opacity:.85;">{station.get('name', 'Station')}</div>
          <div class="aqi-face" style="font-size:2.2rem;line-height:1.2;margin-top:4px;">{face}</div>
          <div class="aqi-value" style="font-size:3.6rem;font-weight:800;line-height:1.1;">
            {pm25:.1f}<span style="font-size:1.1rem;font-weight:500;"> µg/m³ PM2.5</span>
          </div>
          <div class="aqi-line" style="font-size:1.5rem;font-weight:700;">AQI {aqi} · {label}{" (estimated)" if estimate and estimate.get("value") is not None else ""}</div>
          <div class="aqi-meta" style="font-size:.8rem;opacity:.8;margin-top:6px;">
            Updated {ts} · Source: {provider}
          </div>
        </div>
        """,
        unsafe_allow_html=True,
    )

    if estimate and estimate.get("value") is not None:
        m = nowcast_metrics(load_locations()[0]) or {}
        mae_txt = f"backtest MAE ≈ {m['mae']} µg/m³" if m.get("mae") is not None else ""
        acc_txt = (
            f", typical relative error ≈ {round((1 - m['acc']) * 100)}% "
            f"(n={m['n']}, vs {round((1 - m['baseline_persistence_acc']) * 100)}% naive baseline)"
            if m.get("acc") is not None and m.get("n") else ""
        )
        stats_txt = f" — {mae_txt}{acc_txt}" if mae_txt else ""
        st.warning(
            f"Estimated (station offline) — based on diurnal pattern + "
            f"{estimate.get('sources_used', 0)} nearby stations{stats_txt}. "
            f"Last reading {estimate.get('stale_hours')} h ago · confidence: "
            f"{estimate.get('confidence')}."
        )

    tips = advice_for(profile, aqi)
    if tips:
        st.markdown(f"#### What this means for you ({profile})")
        for tip in tips:
            st.markdown(f"- {tip}")

    render_dust_smoke_card()


def render_best_hours(station):
    st.subheader("Best Hours Today")
    hourly = get_hourly(station)
    if not hourly:
        st.info("No recent hourly measurements for this station yet — try another station in the sidebar.")
        return

    plan = hourly_plan(hourly)
    if not plan:
        st.info("Today's pattern could not be computed for this station.")
        return
    hours = plan["hours"]
    green = plan.get("green_windows") or []
    red = plan.get("red_windows") or []

    fig = go.Figure()
    xs = [h["hour"] for h in hours]
    fig.add_trace(go.Scatter(
        x=xs, y=[h["expected"] for h in hours], mode="lines",
        name="Typical (7-day)", line=dict(dash="dash", color="#9aa5b1"),
    ))
    today_x = [h["hour"] for h in hours if h.get("today") is not None]
    fig.add_trace(go.Scatter(
        x=today_x, y=[hours[h]["today"] for h in today_x], mode="lines+markers",
        name="Today", line=dict(color="#2E9E5B", width=3),
    ))
    for s, e in green:  # windows are half-open (start, end_exclusive)
        fig.add_vrect(x0=s - 0.5, x1=e - 0.5, fillcolor="#2E9E5B", opacity=0.14, line_width=0)
    for s, e in red:
        fig.add_vrect(x0=s - 0.5, x1=e - 0.5, fillcolor="#d64545", opacity=0.10, line_width=0)
    fig.update_layout(
        height=380, margin=dict(l=10, r=10, t=30, b=10),
        xaxis=dict(title="Hour of day (local)", dtick=2, range=[-0.5, 23.5]),
        yaxis_title="PM2.5 µg/m³",
        legend=dict(orientation="h", yanchor="bottom", y=1.02),
    )
    st.plotly_chart(fig, width="stretch", config={"displayModeBar": False})

    if green:
        slots = " · ".join(f"**{s:02d}:00–{e:02d}:00**" for s, e in green)
        st.success(f"Good for jogging / outdoor time: {slots}")
    else:
        st.info("No clear low-pollution window today — consider indoor exercise.")
    if red:
        slots = " · ".join(f"**{s:02d}:00–{e:02d}:00**" for s, e in red)
        st.error(f"Avoid prolonged outdoor exertion: {slots}")
    st.caption(
        "Windows are runs of 2+ hours in the Good (green) or Unhealthy (red) PM2.5 range, "
        "judged on today's readings where available, otherwise the station's 7-day average."
    )

    render_dust_forecast_chart(hours=48)


def render_breathe(stations):
    st.subheader("What Did I Breathe?")
    station = pick_station(stations, key="station_breathe", label="Reference station")
    pm_site = pm25_of(station)
    pm_city = float(np.mean([pm25_of(s) for s in stations]))

    with st.expander("Pollution levels used (µg/m³)"):
        pm_outdoor = st.number_input(
            "Outdoor level (default: selected station)", 0.0, 500.0, float(pm_site), 1.0)
        pm_commute = st.number_input(
            "Commute level (default: city average)", 0.0, 500.0, float(pm_city), 1.0)

    c1, c2, c3 = st.columns(3)
    commute_h = c1.slider("Commute time (h/day)", 0.0, 4.0, 1.0, 0.25)
    outdoor_h = c2.slider("Outdoor time (h/day)", 0.0, 12.0, 2.0, 0.5)
    activity = c3.selectbox("Activity intensity", ACTIVITIES, index=1)

    rep = exposure(pm_commute, commute_h, pm_outdoor, outdoor_h, activity)

    if rep["cigarettes"] is not None:
        st.markdown(
            f"""
            <div class="cig-card"
                 style="background:#FFF6EC;border:1px solid #F0D9B8;border-radius:18px;
                        padding:26px;text-align:center;color:#5A3B12;">
              <div class="cig-value" style="font-size:3.8rem;font-weight:800;">🚬 {rep['cigarettes']:.1f}</div>
              <div style="font-size:1.15rem;font-weight:600;">cigarette-equivalent per day</div>
              <div style="font-size:.95rem;margin-top:6px;">{rep['headline']}</div>
            </div>
            """,
            unsafe_allow_html=True,
        )

    if rep["breakdown"]:
        bdf = pd.DataFrame(rep["breakdown"])
        fig = go.Figure(go.Bar(
            x=bdf["label"], y=bdf["ug"],
            marker_color=["#F4A259", "#2E9E5B"][: len(bdf)],
            text=bdf["ug"], textposition="auto",
        ))
        fig.update_layout(
            height=320, margin=dict(l=10, r=10, t=30, b=10),
            yaxis_title="PM2.5 inhaled (µg)", title="Exposure breakdown",
        )
        st.plotly_chart(fig, width="stretch", config={"displayModeBar": False})

    st.caption(
        "Methodology: cigarette equivalence follows the Berkeley Earth rule of thumb — "
        "inhaling ≈253 µg PM2.5 (22 µg/m³ over a day's breathing) ≈ 1 cigarette; "
        "commute and outdoor doses are weighted by breathing rate for the chosen activity."
    )


def render_get_alerts():
    st.subheader("Get Air Alerts")
    st.markdown(
        "Mframa can **push the air to you** instead of you checking the app. "
        "Two free channels, powered by scheduled checks of the same OpenAQ data you see here:"
    )
    c1, c2 = st.columns(2)
    with c1:
        st.markdown(
            """
            **🌅 Morning briefing (daily, ~05:45)**

            Your station's current PM2.5 and AQI, today's cleanest hours,
            commute guidance for the 06:00–09:00 / 17:00–20:00 rush peaks,
            and a laundry & windows tip — before you leave home.
            """
        )
    with c2:
        st.markdown(
            """
            **🚨 Burst alerts (checked every 15 min)**

            When your station — or the whole city — crosses AQI 151
            (*Unhealthy*), you get an immediate warning with concrete
            protective steps. No repeats within 12 hours.
            """
        )

    bot_username = None
    try:
        bot_username = st.secrets.get("TELEGRAM_BOT_USERNAME")
    except Exception:
        pass
    if not bot_username:
        import os
        bot_username = os.environ.get("TELEGRAM_BOT_USERNAME")
    bot_username = (bot_username or "").strip().lstrip("@")

    ntfy_topic = "mframa-accra-air"
    st.markdown(
        f"👉 **Subscribe free in 10 seconds — no account, no phone number:** open "
        f"**[ntfy.sh/{ntfy_topic}](https://ntfy.sh/{ntfy_topic})** in any browser and tap "
        f"*Subscribe to topic*, or install the **ntfy** app (Android / iOS) and add the topic "
        f"`{ntfy_topic}`. You will get the daily morning briefing and every city-wide burst alert "
        "as a phone notification."
    )

    if bot_username:
        st.markdown(
            f"📮 **Station-level personal alerts on Telegram: [@{bot_username}](https://t.me/{bot_username})** — "
            "send `/subscribe nearest` and share your location, or `/subscribe <station name>`."
        )
    else:
        st.caption("A Telegram bot with station-level personal alerts (/subscribe your street's "
                   "sensor) is launching soon — the ntfy channel above already works today.")

    with st.expander("No smartphone? SMS / USSD is the scale path"):
        st.markdown(
            "ntfy covers smartphone users first. To reach feature-phone users — "
            "often the people most exposed — the same engine plugs into "
            "**[Africa's Talking](https://africastalking.com/)** for SMS and USSD delivery "
            "across MTN, Vodafone and AirtelTigo. The alert logic, thresholds and "
            "de-duplication stay identical; only the transport changes."
        )

    st.caption("Free to use, always. Data: OpenAQ · mute the ntfy topic any time to unsubscribe.")


def render_map(stations):
    st.subheader("Live Map — PM2.5 across Accra")
    grid = idw_points(stations)

    sdf = pd.DataFrame([
        {
            "name": s.get("name") or f"Station {s.get('id')}",
            "lat": s.get("lat"), "lon": s.get("lon"),
            "pm25": round(pm25_of(s), 1),
            "label": aqi_info(aqi_of(pm25_of(s)))[0],
            "color": hex_to_rgb(aqi_info(aqi_of(pm25_of(s)))[1]),
        }
        for s in stations
    ]).dropna(subset=["lat", "lon"])

    layers = []
    if not grid.empty:
        layers.append(pdk.Layer(
            "HeatmapLayer", grid,
            get_position="[lon, lat]", get_weight="weight",
            radiusPixels=70, intensity=1.0, threshold=0.05, opacity=0.55,
            colorDomain=[0, 1],
        ))
    layers.append(pdk.Layer(
        "ScatterplotLayer", sdf,
        get_position="[lon, lat]", get_fill_color="color",
        get_radius=200, radius_min_pixels=6, pickable=True,
        stroked=True, get_line_color=[255, 255, 255], line_width_min_pixels=1,
    ))

    deck = pdk.Deck(
        layers=layers,
        initial_view_state=pdk.ViewState(latitude=MAP_CENTER[0], longitude=MAP_CENTER[1], zoom=10.5),
        map_style="https://basemaps.cartocdn.com/gl/positron-gl-style/style.json",
        tooltip={"html": "<b>{name}</b><br/>PM2.5: {pm25} µg/m³<br/>{label}"},
    )
    st.pydeck_chart(deck, width="stretch", height=520)
    st.caption("Heatmap interpolated from station readings (IDW); dots are monitoring stations colored by AQI category.")


# ---------------------------------------------------------------------------
# App shell
# ---------------------------------------------------------------------------

def main():
    inject_responsive_css()
    st.title("Mframa")
    st.caption("Know your air, Accra — TechHub Africa Hackathon 2026")

    try:
        locations, source = load_locations()
    except Exception:
        st.error("Air quality data could not be loaded. Please refresh in a moment.")
        footer()
        return

    data_banner(source)

    st.sidebar.title("Navigate")
    page = st.sidebar.radio(
        "Page",
        ["My Air", "Best Hours Today", "What Did I Breathe?", "Live Map", "Get Air Alerts"],
        label_visibility="collapsed",
    )

    try:
        if page == "Get Air Alerts":
            render_get_alerts()
            footer()
            return

        stations = stations_with_readings(locations or [])
    except Exception:
        stations = []
    if not stations:
        st.info("No stations with current PM2.5 readings are available right now. Please check back shortly.")
        footer()
        return

    try:
        if page == "My Air":
            pool = list(stations)
            online_ids = {s.get("id") for s in pool}
            for loc in locations or []:
                if loc.get("id") not in online_ids and (loc.get("hourly_pm25") or []):
                    pool.append(loc)  # offline but estimable via nowcast
            render_my_air(pool)
        elif page == "Best Hours Today":
            st.sidebar.markdown("### Station")
            render_best_hours(pick_station(stations, key="station_hours"))
        elif page == "What Did I Breathe?":
            render_breathe(stations)
        else:
            render_map(stations)
    except Exception:
        st.error("This view hit a snag while processing the data. Try another page or refresh the app.")

    footer()


main()
