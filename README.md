# Mframa — Know your air, Accra

[![Live app](https://img.shields.io/badge/live-mframa.streamlit.app-FF4B4B?logo=streamlit)](https://mframa.streamlit.app)
[![Data: OpenAQ v3](https://img.shields.io/badge/data-OpenAQ%20v3-blue)](https://api.openaq.org)
[![Android APK](https://img.shields.io/badge/Android-v0.2%20APK-3DDC84?logo=android)](dist/Mframa-v0.2-debug.apk)
[![License: MIT](https://img.shields.io/badge/license-MIT-green)](LICENSE)

*Mframa* means "air" in Twi. Most air-quality apps show you pollution. Mframa is built to protect a specific person: it tells a mother in Nima when to open her windows, a cyclist in Osu which hours to avoid, and a market trader at Agbogbloshie what yesterday's air actually did to her lungs.

Built for the **TechHub Africa Hackathon 2026**, track *Reducing Public Pollution*.

- **Live app:** [mframa.streamlit.app](https://mframa.streamlit.app) (Streamlit Community Cloud)
- **Repo:** [github.com/qsxcv20/mframa](https://github.com/qsxcv20/mframa) · entry point `app.py`
- **Android companion:** prebuilt APK at [`dist/Mframa-v0.2-debug.apk`](dist/Mframa-v0.2-debug.apk)

## The Problem

Air pollution is now the **number one cause of death in Ghana**. A 2025 study by PSS Urbania Consult and the Clean Air Fund estimates that polluted air kills more than **30,000 Ghanaians prematurely every year** — more than malaria, HIV/AIDS, and road accidents combined.

In Accra, the 2024 annual average PM2.5 concentration was approximately **36.3 µg/m³ — about seven times the WHO guideline** of 5 µg/m³. The main drivers:

- **Traffic congestion** — aging vehicle fleets idling on corridors like the N1 and through Makola
- **E-waste burning at Agbogbloshie** — open burning of cables and electronics releasing fine particulates and heavy metals
- **Charcoal and biomass cooking** — still the primary energy source for a large share of households
- **Harmattan dust** — seasonal Saharan dust that pushes PM2.5 far above average from December to March

Sources:

- [PSS Urbania Consult / Clean Air Fund — Air pollution: Ghana's leading cause of death (2025)](https://www.cleanairfund.org/news-item/air-pollution-ghana-leading-cause-of-death/)
- [WHO Global Air Quality Guidelines (2021)](https://www.who.int/publications/i/item/9789240034228)
- [State of Global Air](https://www.stateofglobalair.org/)

The cruel part: the pollution is invisible, hyper-local, and time-varying. Official averages describe a city; they do not protect a person.

## The Solution — five pages, five concrete answers

**My Air** — You pick a health profile (child, pregnant, asthma/respiratory condition, elderly, outdoor worker, healthy adult). Mframa reads the nearest live stations and gives plain-language action guidance tuned to that profile: whether to go out now, whether to keep windows open, whether today is a mask day. Advice is based on WHO-aligned PM2.5 breakpoints, not generic "moderate air" labels. The big AQI card wears a **universal emoji face for each pollution level** — 😊 on a good day, 😷 when the air turns unhealthy — so even a child can read the air at a glance; the same faces ride along in the alert messages. A **"Dust or Smoke?"** card on the same page attributes the pollution source — Saharan dust vs. combustion smoke — by combining live PM2.5 with the CAMS dust forecast (see Open-Meteo below).

**Best Hours Today** — A direct answer to the question everyone actually asks: *when should I go out?* A diurnal curve built from the last 7 days of hourly readings finds the historically cleanest hours, overlays today's live trend, and marks **green outdoor windows** for exercise, commuting with children, or drying laundry — plus a **48-hour dust & PM2.5 forecast**.

**What Did I Breathe?** — A cigarette-equivalent exposure calculator, using the well-known Berkeley Earth conversion (22 µg/m³ of PM2.5 over a day ≈ one cigarette). Enter your daily commute time, outdoor time, and activity level; Mframa combines them with the station's *current* real PM2.5 reading and the city-wide average, weights the dose by breathing rate, and translates it into a number anyone can feel — cigarettes, not micrograms. ([Berkeley Earth: air pollution and cigarettes](http://berkeleyearth.org/air-pollution-and-cigarette-equivalence/))

**Live Map** — An interactive map of all 85 monitoring stations across Accra, with an IDW (inverse-distance-weighted) interpolation heatmap so you can see the pollution *field*, not just dots. Hover any station dot for its live reading and AQI category.

**Get Air Alerts** — Subscribe in 10 seconds to a **daily morning briefing** and **burst alerts every 15 minutes** when the city's air turns unhealthy — no account, no phone number (details below).

## Data Authenticity

Every number in Mframa comes from the **[OpenAQ v3 API](https://api.openaq.org/v3)** ([api.openaq.org](https://api.openaq.org)), a non-profit open-data platform. We do not simulate, fabricate, or hand-tune readings.

- **85 real monitoring locations in Ghana** (OpenAQ country id 152), including the **AfriqAir / Carnegie Mellon University hybrid network** and **Clarity** low-cost sensors
- Stations sit at real, verifiable places: **Agbogbloshie, Makola, Osu Oxford Street**, and dozens more
- **~60 stations report fresh data daily**; the rest update less frequently and are flagged accordingly
- Every figure shown in the app is labeled with its **source station and timestamp** — you can always check where a number came from
- **Live-first, snapshot-fallback**: the app always tries the live API; `data/snapshot.json` — a build-time snapshot of real OpenAQ data regenerated with `fetch_snapshot.py` — is used **only** when the API is unreachable
- The API key is read only from the `OPENAQ_API_KEY` environment variable or Streamlit secrets. It is **never hardcoded or committed**

## Nowcast engine — filling Ghana's data gaps

Accra's low-cost sensors go quiet during power cuts and connectivity drops — exactly when people still need to know their air. `nowcast.py` predicts PM2.5 for **offline stations** from their own recent history plus the live city field.

- **Champion algorithm:** `candidates/cand_regime2.py` — regime-switching dynamics that classify each station's state as *calm / rising / spike / post-spike decay* and forecast accordingly. It was selected in a leak-free benchmark sweep (`bench_nowcast.py`) over a field of alternative candidates.
- **Benchmark (n = 684, leak-free):** accuracy **0.7049**, MAE **4.14 µg/m³** — vs. **0.58** for a naive persistence baseline
- **Blind holdout validation** on a fresh, never-trained-on OpenAQ pull (`_holdout_eval.py`, `data/snapshot_holdout.json`): accuracy **0.694** — confirming the benchmark is not overfit
- All metrics are committed at [`data/nowcast_metrics.json`](data/nowcast_metrics.json)

## Android companion app

A native Kotlin app under `android/` for the way Ghanaians actually live with air:

- **WebView UI** around the live web app
- **Foreground service** sampling GPS from the lock screen (15-minute, balanced-power intervals) so exposure tracking survives the screen being off
- **Dose accumulation** in `DoseLogic` — pure Kotlin, unit-tested — turning time-at-location into a daily PM2.5 dose
- **3-tier notifications** as your accumulated dose crosses thresholds
- **280 real hospitals** around Accra ([`data/hospitals_accra.json`](data/hospitals_accra.json), sourced from OpenStreetMap and bundled in app assets) so a bad-air alert can point to actual care
- **24 unit tests pass**; prebuilt APK: [`dist/Mframa-v0.3-debug.apk`](dist/Mframa-v0.3-debug.apk)

## field.json pipeline — offline air for the app

`publish_field.py` generates [`public/field.json`](public/field.json): a **31×51 IDW grid over Accra (96% valid cells)** — the whole pollution field in one small file. The GitHub Actions workflow [`.github/workflows/alert_and_poll.yml`](.github/workflows/alert_and_poll.yml) **refreshes it every 15 minutes** and commits it back, so it is publicly served via `raw.githubusercontent.com`. The Android app downloads it for **fully offline air-quality lookup** — no API key, no live connection needed on the phone.

## Saharan dust forecasting — Open-Meteo

`openmeteo_client.py` integrates the **free CAMS / ECMWF Saharan-dust forecast** from [Open-Meteo](https://open-meteo.com) — **no API key required**. This powers the **Harmattan season badge** and the **smoke-vs-dust source attribution** on the My Air page: during Harmattan, Accra's PM2.5 is dominated by dust rather than combustion, and the advice that protects you differs.

## Proactive Air Alerts

Checking an app is a habit most people don't have. Mframa's push engine flips the model: **the air report comes to you**, on two tracks.

- **Morning briefing** — every day at ~05:45 the city-wide briefing goes out: Accra's current PM2.5 and AQI, today's cleanest hours (same `best_hours` model as the app), commute guidance for the 06:00–09:00 / 17:00–20:00 rush peaks, and a laundry & windows tip. During Harmattan build-up (city 7-day median rising and above 35.5 µg/m³) an extra dust-season warning is added.
- **Burst alerts** — every 15 minutes the engine checks thresholds; when any station or the whole city crosses **AQI 151 (Unhealthy)**, an immediate alert goes out with protective steps. De-duplication guarantees at most one alert of the same type per 12 hours.

**Subscribe free, no account needed:** open **[ntfy.sh/mframa-accra-air](https://ntfy.sh/mframa-accra-air)** in any browser and tap *Subscribe*, or install the **ntfy** app (Android / iOS) and add the topic `mframa-accra-air`. ntfy is open-source and free; delivery is a normal phone notification. A Telegram bot with *station-level* personal alerts (`/subscribe` your street's sensor) is wired into the same engine and activates the moment a bot token is configured.

```
                 ┌──────────────────────────┐
                 │  GitHub Actions (cron)   │
                 │   */15 min, offset :07   │
                 └────────────┬─────────────┘
                              ▼
                 ┌──────────────────────────┐      fallback
                 │      push_engine.py      │────────────▶ data/snapshot.json
                 │ briefing · broadcast ·   │  ┌────────▶ OpenAQ v3 (live)
                 │ alerts · poll            │  │
                 └────────────┬─────────────┘  │
              ┌───────────────┼────────────────┘
              ▼               ▼               ▼
     ┌────────────────┐ ┌────────────┐ ┌──────────────────┐
     │  ntfy topic    │ │ Telegram   │ │ SMS / USSD       │
     │  (live today)  │ │ (token in) │ │ Africa's Talking │
     └────────────────┘ └────────────┘ └──────────────────┘
        subscribers.json + bot_state.json committed back to the repo by the workflow;
        publish_field.py refreshes public/field.json on the same 15-min cycle
```

**Cost model.** ntfy and Telegram delivery are free. SMS via [Africa's Talking](https://africastalking.com/) costs roughly **$0.01–0.05 per message** in Ghana; at one message per subscriber per day, **10,000 subscribers ≈ $300–500/month** — a line item sized for a corporate CSR sponsorship or an EPA Ghana / NGO partnership, which is the planned funding path. USSD session costs are in the same range and reach feature phones with no data plan at all.

**Running it yourself.** The engine needs one repository secret (repo → **Settings → Secrets and variables → Actions**), plus an optional one for Telegram:

| Secret | What for |
|---|---|
| `OPENAQ_API_KEY` | Live air-quality data (free key at [explore.openaq.org](https://explore.openaq.org)); without it the engine falls back to the bundled snapshot |
| `TELEGRAM_BOT_TOKEN` | Optional — enables station-level personal alerts via the Telegram Bot API (from [@BotFather](https://t.me/BotFather)); without it Telegram runs degrade to dry-run logs while ntfy keeps publishing |

No token is ever printed or committed. The ntfy topic is configurable via the `NTFY_TOPIC` / `NTFY_BASE` environment variables (self-hosting ntfy is the production path for a reserved, access-controlled topic).

## Why it works in Ghana today

- **Pure web app** — nothing to install; it runs in any phone browser, which is how most Ghanaians are online. Mobile-responsive layout throughout.
- **Deployable today** — live on Streamlit Community Cloud's free tier at [mframa.streamlit.app](https://mframa.streamlit.app); zero servers, zero ops, zero cost
- **Resilient to outages** — works on the cached snapshot when the API is unreachable; the Android app works fully offline from `field.json`
- **Light on bandwidth** — server-side data fetching and cached responses keep pages small on slow connections
- **Free data end-to-end** — OpenAQ for sensors, Open-Meteo CAMS for dust forecasts (no key), GitHub Actions free tier for the alert engine
- **Python + Kotlin ecosystem** — widely taught and used in Ghana's developer community, so the codebase is maintainable and forkable locally

Roadmap:

- **USSD/SMS alerts** via [Africa's Talking](https://africastalking.com/) for feature-phone users — the people most exposed often have no smartphone
- **Localization** into Twi and French
- **Partnerships** with EPA Ghana and schools for air-quality education programs

## Community Value & Replication

Mframa is not Accra-specific by design. To redeploy it for **any city covered by OpenAQ** — Lagos, Nairobi, Kampala, Dakar — you change exactly two things: the bounding box and the country code. The exposure calculator, best-hours model, nowcast engine, and interpolation pipeline are geography-agnostic.

The architecture also doubles as a reference implementation for African civic-tech teams: how to responsibly consume a rate-limited open API (caching, retries, snapshot fallback), how to benchmark a forecasting model honestly (leak-free splits plus a blind holdout), and how to turn raw sensor data into decisions a non-technical user can act on.

## Quick Start

```bash
pip install -r requirements.txt

# Free key after registering at https://explore.openaq.org
export OPENAQ_API_KEY=your_key_here   # Windows PowerShell: $env:OPENAQ_API_KEY="your_key_here"

streamlit run app.py
```

No key? The app still runs — it serves the bundled real-data snapshot instead of live readings.

To refresh the offline fallback snapshot:

```bash
python fetch_snapshot.py
```

## Deploy on Streamlit Cloud

1. Push this repository to GitHub
2. Go to [share.streamlit.io](https://share.streamlit.io), choose **New app**, select the repo and `app.py`
3. In the app's **Settings → Secrets**, add:

   ```toml
   OPENAQ_API_KEY = "your_key_here"
   ```

4. Deploy — the app will use live OpenAQ data with the bundled snapshot as fallback

## Android build

```bash
cd android
# Requires JDK 17 and the Android SDK; point local.properties at your SDK:
# sdk.dir=C:\\Users\\<you>\\AppData\\Local\\Android\\Sdk
./gradlew assembleDebug     # or gradlew.bat assembleDebug on Windows
./gradlew testDebugUnitTest # 24 unit tests
```

Or skip the build: sideload the prebuilt [`dist/Mframa-v0.2-debug.apk`](dist/Mframa-v0.2-debug.apk).

## Repo layout

```
app.py                  Streamlit entry point — 5 pages (My Air, Best Hours Today,
                        What Did I Breathe?, Live Map, Get Air Alerts)
analytics.py            AQI, exposure, best-hours, IDW interpolation
nowcast.py              PM2.5 nowcast engine for offline stations
candidates/             nowcast algorithm candidates; champion: cand_regime2.py
bench_nowcast.py        leak-free benchmark harness (n=684)
_holdout_eval.py        blind holdout validation on a fresh OpenAQ pull
openaq_client.py        OpenAQ v3 client: cache, retry, live-first + snapshot fallback
openmeteo_client.py     free CAMS/ECMWF dust forecast client (no API key)
fetch_snapshot.py       regenerates the offline fallback snapshot
push_engine.py          ntfy city broadcast + Telegram briefings + 15-min burst alerts
publish_field.py        generates public/field.json (31×51 IDW grid over Accra)
public/field.json       published pollution field, consumed by the Android app offline
data/                   snapshot, holdout, nowcast metrics, hospital list, caches
android/                Kotlin companion app (WebView + foreground GPS + DoseLogic)
dist/                   prebuilt APKs
.github/workflows/      alert_and_poll.yml — 15-min alerts, bot poll, field.json refresh
requirements.txt        web app dependencies
```

## Architecture

```
        ┌────────────────┐        ┌─────────────────────┐
        │  OpenAQ v3 API │        │  Open-Meteo CAMS    │
        │ (85 GH stations)│       │  dust forecast (free)│
        └───────┬────────┘        └──────────┬──────────┘
                │ X-API-Key                  │ no key
                ▼                            ▼
        ┌────────────────────────┐   ┌────────────────────┐
        │     openaq_client      │   │ openmeteo_client   │
        │ cache · retry · live-1st│  │ Harmattan · dust vs │
        └───┬──────────────┬─────┘   │ smoke attribution  │
   fallback │              │         └─────────┬──────────┘
            ▼              ▼                   │
   ┌─────────────────┐  ┌──────────────────────▼───────────┐
   │ data/snapshot.json│ │            analytics             │
   │ (offline backup) │  │ AQI · exposure · best-hours · IDW│
   └─────────────────┘  │ nowcast (regime-switching)       │
                        └───────────────┬──────────────────┘
                                        ▼
              ┌─────────────────────────────────────────┐
              │               Streamlit UI              │
              │ My Air · Best Hours · What Did I Breathe│
              │ Live Map · Get Air Alerts               │
              └───────────────────┬─────────────────────┘
                                  ▼
        ┌──────────────────────────────────────────────┐
        │   GitHub Actions — every 15 min              │
        │   push_engine (ntfy · Telegram) · publish_field.py  │
        └───────────────┬──────────────────────────────┘
                        ▼
        ┌──────────────────────────────────────────────┐
        │  public/field.json via raw.githubusercontent │
        │  → Android app offline mode (WebView + GPS   │
        │    dose tracking + 280 hospitals)            │
        └──────────────────────────────────────────────┘
```

## License & Attribution

Code: [MIT License](LICENSE).

Data: © [OpenAQ](https://openaq.org) contributors and the [AfriqAir](https://afriqair.org/) network (Carnegie Mellon University Africa and partners). Dust forecasts: CAMS / ECMWF via [Open-Meteo](https://open-meteo.com). Hospital locations: © [OpenStreetMap](https://www.openstreetmap.org/copyright) contributors. Mframa is grateful to the communities hosting sensors across Accra.
