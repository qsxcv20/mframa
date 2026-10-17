"""Strategy 4: regime-switching nowcast — final form after bench iteration.

What survived tuning (bench_nowcast.py, leak-free):

  pred = 0.2 * last_value + 0.8 * base
  base = 0.9 * wmed(same hour +/-1h, recency-decayed) + 0.1 * value_24h_ago

  * wmed: median of the station's own readings at the target hour of day
    (+/-1h), weighted by 0.85^(age in days) — the diurnal anchor.
  * The 0.2 weight on the last reading captures short-lived deviations;
    hourly diffs here have lag-1 autocorr ~ -0.28, i.e. the series is
    mean-reverting, so heavy damping beats persistence.

Regimes tried and rejected (measured, not guessed): Holt trend / EMA
smoothing, neighbor IDW / neighbor deviation blends, pooled ridge & LAD
regression fitted per-cutoff, spike-triggered hard reversion, raw
yesterday-same-hour anchoring — all equal or worse on ACC.  An oracle
using *future* data for the same-hour median only reaches ACC ~0.71, so
~0.68 is near this dataset's +1h ceiling (sensor noise + unpredictable
local spikes; neighbors show zero lead on spikes).

Pure stdlib. No network, no Streamlit.
"""

from datetime import timedelta
from statistics import median

LAM_LAST = 0.2      # weight on the last observed value
W_YDAY = 0.1        # weight of yesterday-same-hour inside the base
HOUR_SPREAD = 1     # +/- hours around target hour for the diurnal median
DAY_DECAY = 0.85    # recency weight per day of age for the diurnal median


def _wmed_hour(hist, target_time):
    """Recency-decayed median of readings at target hour +/- HOUR_SPREAD."""
    t0 = hist[-1][0]
    th = target_time.hour
    items = []
    for t, v in hist:
        dh = abs(((t.hour - th + 12) % 24) - 12)
        if dh <= HOUR_SPREAD:
            age_days = (t0 - t).total_seconds() / 86400.0
            items.append((v, DAY_DECAY ** age_days))
    if not items:
        return median([v for _, v in hist[-24:]])
    items.sort(key=lambda p: p[0])
    total = sum(w for _, w in items)
    acc = 0.0
    for v, w in items:
        acc += w
        if acc >= 0.5 * total:
            return v
    return items[-1][0]


def predict(station, neighbors, target_time):
    s = [(t, float(v)) for t, v in (station.get("series") or []) if v is not None]
    if not s:
        return None
    if len(s) < 26:
        # too short for a diurnal profile: damped persistence
        tail = [v for _, v in s]
        return 0.5 * tail[-1] + 0.5 * median(tail)

    base = _wmed_hour(s, target_time)
    yday = {t: v for t, v in s}.get(target_time - timedelta(hours=24))
    if yday is not None:
        base = (1.0 - W_YDAY) * base + W_YDAY * yday

    pred = LAM_LAST * s[-1][1] + (1.0 - LAM_LAST) * base
    return max(0.0, pred)
