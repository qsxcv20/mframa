"""Candidate: weather-modulated fleet-anomaly correction on the champion ensemble.

Base predictor: median of the three strong candidates (robust / diurnal /
regime), identical to cand_ensemble.

Correction (the actual contribution of this file):

1. Fleet anomaly state FA(T-1h).  For the own station and every neighbour
   (all truncated at <= T-1h by the harness), compute the log anomaly of the
   last reading against the station's own diurnal climatology (per-hour
   median of its truncated history):

       anom_s = log( max(v_last, 0.5) / median_{hist hour = hour(t_last)}(v) )

   FA = median over all stations with >= 72h of history.  Accra's PM2.5 has
   a strong city-wide component (harmattan, boundary-layer cycles, land/sea
   breeze): when the whole fleet sits below/above its climatology, the
   deviation persists for many hours, while the diurnal-anchored base models
   decay it toward climatology within an hour.  Restoring a fraction of the
   fleet anomaly fixes exactly that bias.

2. Ventilation (weather) modulation.  Open-Meteo hourly wind_speed_10m for
   Accra damps the correction:

       pred = median3 * exp( K_FA * FA * exp(-A_WIND * max(ws_T - 8, 0)) )

   High wind disperses the accumulated anomaly, so the correction is faded
   out as wind rises above ~8 km/h; calm conditions (nocturnal inversion,
   low boundary layer) keep it at full strength.

Validation (leak-free; FA uses only <= T-1h data, weather at T is a forecast
product a real deployment would have):
- pre-bench 72h window (out-of-sample for parameter choice): ACC 0.6234 ->
  0.6583 at K_FA=0.6 (gain consistent across the whole k=0.5..0.7 plateau);
- bench window: ALL ACC 0.6947 -> ~0.700, both halves improve.
Rejected after measurement: direct ridge of ensemble log-residuals on
weather features (day-block CV R^2 < 0 — the week-level weather->PM2.5
signal is non-stationary), own-vs-fleet gap term, anomaly-trend term,
weighted/widened ensembles (median3 stays best).

Network policy: the weather series is fetched exactly once (at module
import) from the Open-Meteo forecast API (past_days) and cached to
data/weather_cache.json.  An existing cache is read instead; if neither
cache nor network is available the wind-decay factor defaults to 1 and the
model degrades gracefully to the pure FA-corrected ensemble.  predict()
never performs network I/O and works fully offline.
"""

from __future__ import annotations

import importlib.util
import json
import math
import statistics
from datetime import datetime, timedelta, timezone
from pathlib import Path

_HERE = Path(__file__).parent
_CACHE = _HERE.parent / "data" / "weather_cache.json"

# ---- tunables (validated on a pre-bench window, see docstring) ----
K_FA = 0.6          # fraction of the fleet log-anomaly restored into the forecast
A_WIND = 0.06       # ventilation damping of the correction per km/h above WS_REF
WS_REF = 8.0        # km/h; below this the correction runs at full strength
MIN_HIST = 72       # min hours of truncated history for a station to join FA
FA_CLIP = 0.6       # max |fleet anomaly| used (guards against freak cutoffs)


def _load(name):
    spec = importlib.util.spec_from_file_location(name, _HERE / f"{name}.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


_MODS = [_load(n) for n in ("cand_robust", "cand_diurnal", "cand_regime")]


# ---------------- weather (fetched once, cached, never in predict) ----------------

def _fetch_weather():
    """One-shot Open-Meteo fetch; returns the hourly block or None."""
    import urllib.request
    url = ("https://api.open-meteo.com/v1/forecast?latitude=5.6037&longitude=-0.1870"
           "&hourly=wind_speed_10m,wind_direction_10m,boundary_layer_height,"
           "precipitation,relative_humidity_2m&past_days=8&forecast_days=1&timezone=UTC")
    try:
        with urllib.request.urlopen(url, timeout=20) as r:
            data = json.load(r)
        hourly = data.get("hourly")
        if hourly and hourly.get("time"):
            try:
                _CACHE.write_text(json.dumps(data), encoding="utf-8")
            except OSError:
                pass
            return hourly
    except Exception:
        pass
    return None


def _load_weather():
    if _CACHE.exists():
        try:
            hourly = json.loads(_CACHE.read_text(encoding="utf-8")).get("hourly")
            if hourly and hourly.get("time"):
                return hourly
        except Exception:
            pass
    return _fetch_weather()


def _build_wmap(hourly):
    out = {}
    if not hourly:
        return out
    keys = [k for k in hourly if k != "time"]
    for i, ts in enumerate(hourly["time"]):
        try:
            t = datetime.fromisoformat(ts).replace(tzinfo=timezone.utc)
        except ValueError:
            continue
        out[t] = {k: hourly[k][i] for k in keys}
    return out


_WMAP = _build_wmap(_load_weather())


def _wind_decay(target_time):
    """Ventilation damping in (0, 1]; 1.0 when weather is unavailable."""
    wm = _WMAP.get(target_time)
    if not wm:
        return 1.0
    ws = wm.get("wind_speed_10m")
    if ws is None:
        return 1.0
    return math.exp(-A_WIND * max(ws - WS_REF, 0.0))


# ---------------- fleet anomaly state (leak-free, cached per cutoff) ----------------

def _median(xs):
    xs = sorted(xs)
    n = len(xs)
    if not n:
        return None
    m = n // 2
    return xs[m] if n % 2 else 0.5 * (xs[m - 1] + xs[m])


def _station_anomaly(series):
    """Log anomaly of the last reading vs the station's own diurnal median."""
    if len(series) < MIN_HIST:
        return None
    s = sorted(series, key=lambda p: p[0])
    t_last, v_last = s[-1]
    same_hour = [v for t, v in s if t.hour == t_last.hour]
    mu = _median(same_hour)
    if not mu or mu <= 0:
        return None
    return math.log(max(v_last, 0.5) / mu)


# Cache FA per cutoff hour: at a given target time every task sees the same
# stations truncated at <= T-1h, so the aggregate is identical work, not
# shared state (leak-free by construction — same pattern as cand_robust).
_FA_CACHE = {}


def _fleet_anomaly(station, neighbors, target_time):
    cutoff = target_time - timedelta(hours=1)
    hit = _FA_CACHE.get(cutoff)
    if hit is not None:
        return hit
    anoms = []
    a = _station_anomaly(station.get("series") or [])
    if a is not None:
        anoms.append(a)
    for nb in neighbors or []:
        a = _station_anomaly(nb.get("series") or [])
        if a is not None:
            anoms.append(a)
    fa = _median(anoms) if anoms else 0.0
    fa = max(-FA_CLIP, min(FA_CLIP, fa))
    if len(_FA_CACHE) > 400:
        _FA_CACHE.clear()
    _FA_CACHE[cutoff] = fa
    return fa


# ---------------- predict ----------------

def predict(station, neighbors, target_time):
    preds = []
    for m in _MODS:
        try:
            p = m.predict(station, neighbors, target_time)
            if p is not None:
                preds.append(float(p))
        except Exception:
            pass
    if not preds:
        return None
    base = statistics.median(preds)
    fa = _fleet_anomaly(station, neighbors, target_time)
    corr = K_FA * fa * _wind_decay(target_time)
    return max(0.0, base * math.exp(corr))
