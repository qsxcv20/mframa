"""Mframa — Know your air, Accra.

TechHub Africa Hackathon 2026 · Air quality awareness for Accra, Ghana.
Data: OpenAQ v3 (live API with snapshot fallback via openaq_client).
"""

from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import quote
import json

import numpy as np
import pandas as pd
import plotly.graph_objects as go
import pydeck as pdk
import streamlit as st
import streamlit.components.v1 as components

import analytics
import nowcast
import openaq_client
import openmeteo_client
from i18n import t, tt

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
  /* Touch target >= 44px for the selectbox (baseweb was replaced by
     react-aria in new Streamlit, so target the stable testid). */
  [data-testid="stSelectbox"] input {
    min-height: 44px !important;
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

# Hide Streamlit Cloud free-tier chrome (the red "Hosted with Streamlit" badge
# and the Fork/deploy button) so demos and the Android WebView stay clean.
CHROME_CSS = """
<style>
div[class*="viewerBadge"], [class*="viewerBadge_container"] { display: none !important; }
.stAppDeployButton, [data-testid="stAppDeployButton"] { display: none !important; }
</style>
"""


def inject_responsive_css():
    try:
        st.markdown(MOBILE_CSS + CHROME_CSS, unsafe_allow_html=True)
        # Station/profile pickers are pure option lists: mark the inner input
        # readonly so tapping one on a phone never pops the soft keyboard.
        # Clicks still reach the input, so the dropdown opens as usual; only
        # baseweb "select" inputs are touched, number/text inputs keep focus.
        components.html(
            """
            <script>
            (function () {
              const doc = parent.document;
              const fix = () => doc
                .querySelectorAll('[data-testid="stSelectbox"] input')
                .forEach(i => {
                  if (!i.readOnly) i.readOnly = true;
                  if (i.getAttribute('inputmode') !== 'none') {
                    i.setAttribute('inputmode', 'none');
                  }
                });
              fix();
              new MutationObserver(fix).observe(doc.body, {childList: true, subtree: true});
            })();
            </script>
            """,
            height=0,
        )
    except Exception:
        pass


ACCRA_CENTER = (5.6037, -0.1870)
MAP_CENTER = (5.60, -0.20)
GRID_LAT = (5.45, 5.75)
GRID_LON = (-0.40, 0.10)
PROFILES = ["general", "child", "asthma", "pregnant", "senior", "athlete"]
ACTIVITIES = ["rest", "light", "moderate", "heavy"]
FALLBACK_COLOR = "#8a94a6"
# Ghana EPA national 24-hour PM2.5 standard (µg/m³), per 3News reporting.
EPA_PM25_24H = 35.0
DEMO_PATH = Path(__file__).parent / "data" / "demo_harmattan.json"
CLEANUP_PATH = Path(__file__).parent / "data" / "agbogbloshie_cleanup.json"


def load_demo_harmattan(path=None):
    """Static Harmattan replay dataset (?demo=harmattan); None if unavailable."""
    try:
        d = json.loads(Path(path or DEMO_PATH).read_text(encoding="utf-8"))
        if d.get("stations"):
            return d
    except (OSError, json.JSONDecodeError, TypeError):
        pass
    return None


def load_cleanup_status(path=None):
    """Static Agbogbloshie cleanup tracker; None if the JSON is missing/broken."""
    try:
        d = json.loads(Path(path or CLEANUP_PATH).read_text(encoding="utf-8"))
        if d.get("baseline_mean") is not None and d.get("current_mean") is not None:
            return d
    except (OSError, json.JSONDecodeError, TypeError):
        pass
    return None


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
    """Emoji face for the AQI level (empty string when unavailable)."""
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
        "inhaled_ug": rep.get("inhaled_ug"),
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
        st.caption(t("dust_unavailable"))
        return
    try:
        current = cams_current(aq) or {}
        dust = _float_or_none(current.get("dust"))
        pm25 = _float_or_none(current.get("pm2_5"))
        aod = _float_or_none(current.get("aerosol_optical_depth"))
        split = dust_smoke_split(dust, pm25)
        harmattan = is_harmattan(aq)
        if split is None and not harmattan:
            st.caption(t("dust_unavailable"))
            return

        badge = (
            '<span style="display:inline-block;background:#8A5A00;color:#fff;'
            'border-radius:999px;padding:2px 10px;font-size:.75rem;font-weight:700;'
            f'margin-left:8px;vertical-align:middle;">{t("harmattan_badge")}</span>'
            if harmattan else ""
        )
        risk = openmeteo_client.dust_risk_level(dust)
        stale_txt = t("cached_suffix") if aq.get("stale") else ""
        if split is not None:
            dust_line = t(
                "dust_line",
                dust=f"{dust:.0f}", pm25=f"{pm25:.0f}",
                pct=f"{split['ratio'] * 100:.0f}", risk=tt(risk["label"]),
                aod=f" · AOD {aod:.2f}" if aod is not None else "",
            )
            st.markdown(
                f"""
                <div style="background:#FBF7F0;border:1px solid #E5D9C3;border-radius:18px;
                            padding:20px 22px;color:#4A3A22;margin-bottom:8px;">
                  <div style="font-size:1.05rem;font-weight:800;margin-bottom:6px;">
                    {t("dust_or_smoke")} — {tt(split['title'])}{badge}
                  </div>
                  <div style="font-size:.95rem;line-height:1.5;">
                    {dust_line}
                  </div>
                  <div style="font-size:.95rem;margin-top:6px;">{tt(split['advice'])}</div>
                  <div style="font-size:.75rem;opacity:.75;margin-top:8px;">
                    {t("forecast_src")}{stale_txt}
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
                    {t("dust_or_smoke")}{badge}
                  </div>
                  <div style="font-size:.95rem;margin-top:6px;">
                    {t("harmattan_body")}
                  </div>
                  <div style="font-size:.75rem;opacity:.75;margin-top:8px;">
                    {t("forecast_src")}{stale_txt}
                  </div>
                </div>
                """,
                unsafe_allow_html=True,
            )
    except Exception:
        st.caption(t("dust_unavailable"))


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
            x=xs, y=dust, mode="lines", name=t("trace_dust"),
            line=dict(color="#C98A2D", width=2, dash="dash"), connectgaps=False,
        ))
        if is_harmattan(aq):
            fig.add_hline(y=50, line=dict(color="#C98A2D", width=1, dash="dot"),
                          annotation_text=t("harmattan_threshold"),
                          annotation_position="top left")
        fig.update_layout(
            height=320, margin=dict(l=10, r=10, t=44, b=10),
            legend=dict(orientation="h", yanchor="bottom", y=1.02, x=0, xanchor="left"),
        )
        st.markdown(f"**{t('dust_chart_title', hours=hours)} (µg/m³)**")
        st.plotly_chart(fig, width="stretch", config={"displayModeBar": False})
        st.caption(t("forecast_src")
                   + (t("showing_cached") if aq.get("stale") else ""))
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


def pick_station(stations, key, label=None, container=None):
    names = [s.get("name") or f"Station {s.get('id')}" for s in stations]
    c = container or st
    idx = c.selectbox(
        label or t("monitoring_station"), range(len(stations)),
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
        st.warning(t("data_cached"))


def footer():
    st.divider()
    st.caption(t("footer"))


# ---------------------------------------------------------------------------
# Pages
# ---------------------------------------------------------------------------

def render_my_air(stations, replay=False):
    profile_labels = [t(f"profile_{p}") for p in PROFILES]
    prev = st.session_state.get("health_profile_value", "general")
    c_prof, c_stat = st.columns(2)
    choice = c_prof.selectbox(
        t("health_profile"), profile_labels,
        index=PROFILES.index(prev) if prev in PROFILES else 0,
        key="health_profile")
    profile = PROFILES[profile_labels.index(choice)]
    st.session_state["health_profile_value"] = profile
    station = pick_station(stations, key="station_myair", container=c_stat)

    pm25 = pm25_of(station)
    stale_h = stale_hours_of(station)
    estimate = None
    # Replay mode shows the historical day as-is: no nowcast estimation.
    if not replay and (pm25 is None or (stale_h is not None and stale_h > 3.0)):
        try:
            estimate = nowcast.predict_station(
                station, [s for s in stations if s is not station])
        except Exception:
            estimate = None
        if estimate and estimate.get("value") is not None:
            pm25 = estimate["value"]

    if pm25 is None:
        st.info(t("no_readings"))
        return

    aqi = aqi_of(pm25)
    label, color = aqi_info(aqi) if aqi is not None else ("No data", FALLBACK_COLOR)
    face = aqi_kaomoji(aqi) if aqi is not None else ""
    fg = text_on(color)
    latest = station.get("latest_pm25") or {}
    ts = latest.get("datetime_utc") or station.get("last_updated_utc") or "unknown time"
    provider = station.get("provider") or "OpenAQ"
    est_suffix = t("estimated_suffix") if estimate and estimate.get("value") is not None else ""

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
          <div class="aqi-line" style="font-size:1.5rem;font-weight:700;">AQI {aqi} · {tt(label)}{est_suffix}</div>
          <div class="aqi-meta" style="font-size:.8rem;opacity:.8;margin-top:6px;">
            {t("updated_source", ts=ts, provider=provider)}
          </div>
        </div>
        """,
        unsafe_allow_html=True,
    )

    # Ghana EPA 24h national-standard benchmark, right under the AQI card.
    epa_color = "#d64545" if pm25 > EPA_PM25_24H else "#2E9E5B"
    st.markdown(
        f'<div style="text-align:center;font-size:.85rem;font-weight:600;'
        f'color:{epa_color};margin:-2px 0 8px;">'
        f'{t("epa_line", mult=f"{pm25 / EPA_PM25_24H:.1f}")}</div>',
        unsafe_allow_html=True,
    )

    if estimate and estimate.get("value") is not None:
        m = nowcast_metrics(load_locations()[0]) or {}
        mae_txt = t("est_mae", mae=m["mae"]) if m.get("mae") is not None else ""
        acc_txt = (
            t("est_acc", rel=round((1 - m["acc"]) * 100), n=m["n"],
              base=round((1 - m["baseline_persistence_acc"]) * 100))
            if m.get("acc") is not None and m.get("n") else ""
        )
        stats_txt = f" — {mae_txt}{acc_txt}" if mae_txt else ""
        st.warning(t(
            "est_warn",
            n=estimate.get("sources_used", 0), stats=stats_txt,
            stale=estimate.get("stale_hours"), conf=estimate.get("confidence"),
        ))

    # Wow lines: cigarette equivalent + today's first clean window, right
    # under the AQI card so they are visible without scrolling on a phone.
    # cigs_txt / best_slot are reused by the WhatsApp share text below.
    cigs_txt = None
    try:
        pm_vals = [v for v in (pm25_of(s) for s in stations) if v is not None]
        if pm_vals:
            pm_city = float(np.mean(pm_vals))
            rep = exposure(pm_city, 1.0, pm_city, 2.0, "light")
            cigs = rep.get("cigarettes")
            if cigs is not None:
                cigs_txt = f"{cigs:.1f}" if cigs >= 0.05 else t("cigs_lt")
                st.warning(t("home_cig_line", cigs=cigs_txt))
                st.caption(t("home_cig_method"))
    except Exception:
        pass

    best_slot = None
    try:
        plan = hourly_plan(get_hourly(station))
        green = (plan or {}).get("green_windows") or []
        if green:
            s, e = green[0]  # windows are half-open (start, end_exclusive)
            best_slot = f"{s:02d}:00–{e:02d}:00"
            st.success(t("home_best_window", slot=best_slot))
        else:
            st.info(t("home_no_window"))
    except Exception:
        pass

    # Quick jumps so mobile users can reach every page in one tap.
    def _goto(page_label, sub_label=None):
        st.session_state["nav_page"] = page_label
        if sub_label is not None:
            st.session_state["more_subpage"] = sub_label

    st.caption(t("quick_jump"))
    q1, q2 = st.columns(2)
    q3, q4 = st.columns(2)
    q1.button(f"🕐 {t('nav_best_hours')}", on_click=_goto,
              args=(t("nav_best_hours"),), key="qj_best", use_container_width=True)
    q2.button(f"🗺️ {t('nav_map')}", on_click=_goto,
              args=(t("nav_map"),), key="qj_map", use_container_width=True)
    q3.button(f"🫁 {t('nav_breathe')}", on_click=_goto,
              args=(t("nav_more"), t("nav_breathe")), key="qj_breathe",
              use_container_width=True)
    q4.button(f"🔔 {t('nav_alerts')}", on_click=_goto,
              args=(t("nav_more"), t("nav_alerts")), key="qj_alerts",
              use_container_width=True)

    # WhatsApp is Ghana's main sharing channel: one tap forwards today's air.
    share_url = ("https://mframa.streamlit.app/?lang="
                 f"{st.session_state.get('lang', 'en')}&page=my_air")
    share_text = t(
        "share_text",
        emoji=face, aqi=aqi if aqi is not None else "?", label=tt(label),
        cigs=cigs_txt or "?",
        slot=best_slot or t("share_no_slot"),
        url=share_url,
    )
    st.link_button(f"📲 {t('share_whatsapp')}",
                   "https://wa.me/?text=" + quote(share_text),
                   use_container_width=True)

    tips = advice_for(profile, aqi)
    if tips:
        st.markdown(f"#### {t('advice_header', profile=t(f'profile_{profile}'))}")
        for tip in tips:
            st.markdown(f"- {tt(tip)}")

    # Red-flag symptoms card: shown when the air is Unhealthy+, or always for
    # asthma/child profiles (Ghana Thoracic Society guidance + GINA control line).
    if (aqi is not None and aqi >= 151) or profile in ("asthma", "child"):
        redflag = t("redflag_card")
        if profile == "asthma":
            redflag += "\n\n" + t("redflag_gina")
        st.error(redflag)

    # The dust/smoke card is a live CAMS forecast — wrong era for a replay.
    if not replay:
        render_dust_smoke_card()


def render_best_hours(station):
    st.subheader(t("nav_best_hours"))
    hourly = get_hourly(station)
    if not hourly:
        st.info(t("no_hourly"))
        return

    plan = hourly_plan(hourly)
    if not plan:
        st.info(t("no_pattern"))
        return
    hours = plan["hours"]
    green = plan.get("green_windows") or []
    red = plan.get("red_windows") or []

    fig = go.Figure()
    xs = [h["hour"] for h in hours]
    fig.add_trace(go.Scatter(
        x=xs, y=[h["expected"] for h in hours], mode="lines",
        name=t("trace_typical"), line=dict(dash="dash", color="#9aa5b1"),
    ))
    today_x = [h["hour"] for h in hours if h.get("today") is not None]
    fig.add_trace(go.Scatter(
        x=today_x, y=[hours[h]["today"] for h in today_x], mode="lines+markers",
        name=t("trace_today"), line=dict(color="#2E9E5B", width=3),
    ))
    for s, e in green:  # windows are half-open (start, end_exclusive)
        fig.add_vrect(x0=s - 0.5, x1=e - 0.5, fillcolor="#2E9E5B", opacity=0.14, line_width=0)
    for s, e in red:
        fig.add_vrect(x0=s - 0.5, x1=e - 0.5, fillcolor="#d64545", opacity=0.10, line_width=0)
    fig.add_hline(y=EPA_PM25_24H, line_dash="dash", line_color="#C98A2D",
                  annotation_text="Ghana EPA 24h std", annotation_position="top left",
                  annotation_font_size=11)
    fig.update_layout(
        height=380, margin=dict(l=10, r=10, t=56, b=10),
        xaxis=dict(title=t("xaxis_hour"), dtick=2, range=[-0.5, 23.5]),
        legend=dict(orientation="h", yanchor="bottom", y=1.02),
    )
    # Plotly always renders y-axis titles vertically, which turns Chinese
    # labels into an unreadable rotated stack — use a horizontal annotation
    # above the axis instead.
    fig.add_annotation(
        text="PM2.5 µg/m³", xref="paper", yref="paper",
        x=0, y=1.14, showarrow=False, xanchor="left", font=dict(size=13),
    )
    st.plotly_chart(fig, width="stretch", config={"displayModeBar": False})

    if green:
        slots = " · ".join(f"**{s:02d}:00–{e:02d}:00**" for s, e in green)
        st.success(t("good_windows", slots=slots))
    else:
        st.info(t("no_green"))
    if red:
        slots = " · ".join(f"**{s:02d}:00–{e:02d}:00**" for s, e in red)
        st.error(t("bad_windows", slots=slots))
    st.caption(t("windows_caption"))

    render_dust_forecast_chart(hours=48)


def render_breathe(stations):
    st.subheader(t("nav_breathe"))
    station = pick_station(stations, key="station_breathe", label=t("reference_station"))
    pm_site = pm25_of(station)
    pm_city = float(np.mean([pm25_of(s) for s in stations]))

    with st.expander(t("pollution_levels")):
        pm_outdoor = st.number_input(
            t("outdoor_level"), 0.0, 500.0, float(pm_site), 1.0, key="breathe_pm_outdoor")
        pm_commute = st.number_input(
            t("commute_level"), 0.0, 500.0, float(pm_city), 1.0, key="breathe_pm_commute")

    c1, c2, c3 = st.columns(3)
    commute_h = c1.slider(t("commute_time"), 0.0, 4.0, 1.0, 0.25, key="breathe_commute_h")
    outdoor_h = c2.slider(t("outdoor_time"), 0.0, 12.0, 2.0, 0.5, key="breathe_outdoor_h")
    activity = c3.selectbox(
        t("activity_intensity"), ACTIVITIES, index=1,
        format_func=lambda a: t(f"activity_{a}"), key="breathe_activity")

    rep = exposure(pm_commute, commute_h, pm_outdoor, outdoor_h, activity)

    if rep["cigarettes"] is not None:
        headline = rep["headline"]
        if rep.get("inhaled_ug") is not None:
            cigs = rep["cigarettes"]
            cigs_txt = f"{cigs:.1f}" if cigs >= 0.05 else t("cigs_lt")
            headline = t("cig_headline", cigs=cigs_txt, ug=f"{rep['inhaled_ug']:.0f}")
        st.markdown(
            f"""
            <div class="cig-card"
                 style="background:#FFF6EC;border:1px solid #F0D9B8;border-radius:18px;
                        padding:26px;text-align:center;color:#5A3B12;">
              <div class="cig-value" style="font-size:3.8rem;font-weight:800;">🚬 {rep['cigarettes']:.1f}</div>
              <div style="font-size:1.15rem;font-weight:600;">{t("cig_equiv")}</div>
              <div style="font-size:.95rem;margin-top:6px;">{headline}</div>
            </div>
            """,
            unsafe_allow_html=True,
        )

    if rep["breakdown"]:
        bdf = pd.DataFrame(rep["breakdown"])
        fig = go.Figure(go.Bar(
            x=[tt(str(l)) for l in bdf["label"]], y=bdf["ug"],
            marker_color=["#F4A259", "#2E9E5B"][: len(bdf)],
            text=bdf["ug"], textposition="auto",
        ))
        fig.update_layout(
            height=320, margin=dict(l=10, r=10, t=56, b=10),
        )
        # Plotly always renders y-axis titles vertically, which turns Chinese
        # labels into an unreadable rotated stack — use a horizontal annotation
        # above the axis instead.
        fig.add_annotation(
            text=t("yaxis_inhaled"), xref="paper", yref="paper",
            x=0, y=1.14, showarrow=False, xanchor="left", font=dict(size=13),
        )
        st.markdown(f"**{t('exposure_breakdown')}**")
        st.plotly_chart(fig, width="stretch", config={"displayModeBar": False})

    st.caption(t("cig_method"))


def render_get_alerts():
    st.subheader(t("nav_alerts"))
    if st.session_state.get("is_app"):
        # Inside the Android app (URL has ?from=app): threshold alerts are
        # built in, so the ntfy/Telegram subscription guides don't apply.
        st.markdown(t("alerts_app_builtin"))
        st.caption(t("alerts_footer"))
        return
    st.markdown(t("alerts_intro"))
    c1, c2 = st.columns(2)
    with c1:
        st.markdown(t("alerts_morning"))
    with c2:
        st.markdown(t("alerts_burst"))

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
    st.markdown(t("subscribe_line", topic=ntfy_topic))

    if bot_username:
        st.markdown(t("telegram_line", bot=bot_username))
    else:
        st.caption(t("telegram_soon"))

    with st.expander(t("sms_expander")):
        st.markdown(t("sms_body"))

    st.caption(t("alerts_footer"))


def render_map(stations):
    st.subheader(t("map_header"))
    grid = idw_points(stations)

    sdf = pd.DataFrame([
        {
            "name": s.get("name") or f"Station {s.get('id')}",
            "lat": s.get("lat"), "lon": s.get("lon"),
            "pm25": round(pm25_of(s), 1),
            "label": tt(aqi_info(aqi_of(pm25_of(s)))[0]),
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
        get_radius=200, radius_min_pixels=12, pickable=True,
        stroked=True, get_line_color=[255, 255, 255], line_width_min_pixels=1,
    ))

    deck = pdk.Deck(
        layers=layers,
        initial_view_state=pdk.ViewState(latitude=MAP_CENTER[0], longitude=MAP_CENTER[1], zoom=10.5),
        map_style="https://basemaps.cartocdn.com/gl/positron-gl-style/style.json",
        tooltip={"html": "<b>{name}</b><br/>PM2.5: {pm25} µg/m³<br/>{label}"},
        views=[pdk.View(type="MapView", controller={
            "scrollZoom": True, "dragPan": True, "dragRotate": False,
            "touchZoom": True, "touchRotate": False, "doubleClickZoom": True,
            "keyboard": False,
        })],
    )
    st.pydeck_chart(deck, width="stretch", height=520)
    st.caption(t("map_caption"))
    render_cleanup_card()


def render_cleanup_card():
    """Agbogbloshie 90-day e-waste cleanup tracker; silent if the JSON is missing."""
    d = load_cleanup_status()
    if not d:
        return
    pct = d["change_pct"]
    arrow = "▼" if pct < 0 else "▲"
    color = "#2E9E5B" if pct < 0 else "#d64545"
    st.markdown(
        f"""
        <div style="background:#F2F7F4;border:1px solid #CBE0D4;border-radius:16px;
                    padding:20px 22px;margin-top:12px;color:#1E3B2C;">
          <div style="font-size:1.1rem;font-weight:700;">{t('cleanup_title')}</div>
          <div style="font-size:.95rem;margin-top:8px;">
            {t('cleanup_body', station=d['station_name'], dist=d['distance_km'],
               launch=d['launch_date'],
               base=d['baseline_mean'], bdays=d['baseline_days'],
               cur=d['current_mean'], cdays=d['current_days'])}
            <span style="font-weight:800;color:{color};">{arrow} {abs(pct)}%</span>
          </div>
          <div style="font-size:.9rem;margin-top:8px;font-style:italic;">
            {t('cleanup_point')}
          </div>
          <div style="font-size:.75rem;opacity:.7;margin-top:8px;">
            {t('cleanup_meta', ts=d.get('computed_at_utc', '?'))}
          </div>
        </div>
        """,
        unsafe_allow_html=True,
    )


# ---------------------------------------------------------------------------
# App shell
# ---------------------------------------------------------------------------

def main():
    inject_responsive_css()
    qp = st.query_params
    # The Android WebView loads the page with ?from=app (only on first load),
    # so remember it for the rest of the session.
    if "is_app" not in st.session_state:
        st.session_state["is_app"] = qp.get("from") == "app"
    # Deep links (?lang=zh&page=more&sub=alerts) apply once per session, using
    # stable English ids so shared links and WebView reloads land on the same
    # page and language regardless of the current UI language.
    if "deep_linked" not in st.session_state:
        st.session_state["deep_linked"] = True
        if qp.get("lang") in ("en", "zh"):
            st.session_state["lang"] = qp["lang"]
        page_keys = {"my_air": "nav_my_air", "best_hours": "nav_best_hours",
                     "map": "nav_map", "more": "nav_more"}
        if qp.get("page") in page_keys:
            st.session_state["nav_page"] = t(page_keys[qp["page"]])
        if qp.get("sub") in ("breathe", "alerts"):
            st.session_state["more_subpage"] = t(
                "nav_breathe" if qp["sub"] == "breathe" else "nav_alerts")
    head_l, head_r = st.columns([3, 2])
    with head_l:
        st.title("Mframa")
        st.caption(t("tagline"))
    with head_r:
        lang_options = ["English", "中文"]
        lang_choice = st.selectbox(
            t("language_label"), lang_options,
            index=0 if st.session_state.get("lang", "en") == "en" else 1,
            label_visibility="collapsed",
            key="lang_switch",
        )
        st.session_state["lang"] = "zh" if lang_choice == "中文" else "en"

    nav_options = [t("nav_my_air"), t("nav_best_hours"), t("nav_map"), t("nav_more")]
    sub_options = [t("nav_breathe"), t("nav_alerts")]

    # Quick-jump tiles (and stale sessions) may point at a "More" sub-page.
    if st.session_state.get("nav_page") in sub_options:
        st.session_state["more_subpage"] = st.session_state["nav_page"]
        st.session_state["nav_page"] = t("nav_more")
    # A language switch can leave a stored label that no longer matches the
    # options — fall back to the defaults instead of a blank selection.
    if st.session_state.get("nav_page") not in nav_options:
        st.session_state["nav_page"] = nav_options[0]
    if st.session_state.get("more_subpage") not in sub_options:
        st.session_state["more_subpage"] = sub_options[0]

    page = st.pills(
        t("nav_page"), nav_options,
        selection_mode="single",
        label_visibility="collapsed",
        key="nav_page",
    ) or nav_options[0]

    more_sub = None
    if page == t("nav_more"):
        more_sub = st.pills(
            t("nav_more"), sub_options,
            selection_mode="single",
            label_visibility="collapsed",
            key="more_subpage",
        ) or sub_options[0]

    # Reflect the current language/page back into the URL (stable English
    # ids, not translated labels) so WebView reloads keep ?lang=zh and shared
    # links deep-link correctly. ?from=app and any other params stay untouched.
    page_ids = {t("nav_my_air"): "my_air", t("nav_best_hours"): "best_hours",
                t("nav_map"): "map", t("nav_more"): "more"}
    sub_ids = {t("nav_breathe"): "breathe", t("nav_alerts"): "alerts"}
    desired_qp = {
        "lang": st.session_state.get("lang", "en"),
        "page": page_ids.get(page, "my_air"),
        "sub": sub_ids.get(more_sub) if page == t("nav_more") else None,
    }
    for k, v in desired_qp.items():
        if v is None:
            if k in qp:
                del qp[k]
        elif qp.get(k) != v:
            qp[k] = v

    try:
        locations, source = load_locations()
    except Exception:
        st.error(t("load_error"))
        footer()
        return

    data_banner(source)

    # Harmattan demo replay (?demo=harmattan): swap live stations for one real
    # historical peak day from OpenAQ. No demo param → completely unaffected.
    demo = load_demo_harmattan() if qp.get("demo") == "harmattan" else None
    if demo:
        live_link = f"?lang={st.session_state.get('lang', 'en')}&page=my_air"
        st.warning(t("demo_banner", date=demo.get("date", "?"),
                     mean=demo.get("city_mean_pm25", "?"), link=live_link))

    if more_sub == t("nav_alerts"):
        render_get_alerts()
        footer()
        return

    try:
        if demo:
            stations = demo["stations"]
        else:
            stations = stations_with_readings(locations or [])
    except Exception:
        stations = []
    if not stations:
        st.info(t("no_stations"))
        footer()
        return

    try:
        if page == t("nav_my_air"):
            pool = list(stations)
            if not demo:
                online_ids = {s.get("id") for s in pool}
                for loc in locations or []:
                    if loc.get("id") not in online_ids and (loc.get("hourly_pm25") or []):
                        pool.append(loc)  # offline but estimable via nowcast
            render_my_air(pool, replay=demo is not None)
        elif page == t("nav_best_hours"):
            render_best_hours(pick_station(stations, key="station_hours"))
        elif page == t("nav_more"):
            render_breathe(stations)
        else:
            render_map(stations)
    except Exception:
        st.error(t("snag_error"))

    footer()


if __name__ == "__main__":
    main()
