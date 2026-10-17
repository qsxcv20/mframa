# Mframa — Know your air, Accra

*Mframa* means "air" in Twi. Most air-quality apps show you pollution. Mframa is built to protect a specific person: it tells a mother in Nima when to open her windows, a cyclist in Osu which hours to avoid, and a market trader at Agbogbloshie what yesterday's air actually did to her lungs.

Built for the **TechHub Africa Hackathon 2026**, track *Reducing Public Pollution*.

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

## The Solution

Mframa turns Accra's dense low-cost sensor network into four concrete answers, each on its own page.

**My Air** — You pick a health profile (child, pregnant, asthma/respiratory condition, elderly, outdoor worker, healthy adult). Mframa reads the nearest live stations and gives plain-language action guidance tuned to that profile: whether to go out now, whether to keep windows open, whether today is a mask day. Advice is based on WHO-aligned PM2.5 breakpoints, not generic "moderate air" labels.

**Best Hours Today** — A direct answer to the question everyone actually asks: *when should I go out?* Using the last 7 days of hourly readings from nearby stations, Mframa finds the hours of day that are historically cleanest and overlays today's live trend, then recommends concrete time windows for exercise, commuting with children, or drying laundry outdoors.

**What Did I Breathe?** — A cigarette-equivalent exposure calculator, using the well-known Berkeley Earth conversion (22 µg/m³ of PM2.5 over a day ≈ one cigarette). Enter your daily commute time, outdoor time, and activity level; Mframa combines them with the station's *current* real PM2.5 reading and the city-wide average, weights the dose by breathing rate, and translates it into a number anyone can feel — cigarettes, not micrograms. ([Berkeley Earth: air pollution and cigarettes](http://berkeleyearth.org/air-pollution-and-cigarette-equivalence/))

**Live Map** — An interactive map of all 85+ monitoring stations across the Accra metropolitan area, with an IDW (inverse-distance-weighted) interpolation heatmap so you can see the pollution *field*, not just dots. Hover any station dot for its live reading and AQI category.

## Data Authenticity

Every number in Mframa comes from the **[OpenAQ v3 API](https://api.openaq.org/v3)** ([api.openaq.org](https://api.openaq.org)), a non-profit open-data platform. We do not simulate, fabricate, or hand-tune readings.

- **85+ real monitoring stations** across the Accra metropolitan area (bounding box 5.45–5.75°N, 0.40°W–0.10°E; Ghana is OpenAQ country id 152), from the **AfriqAir / Carnegie Mellon University hybrid network** and community sensors
- Stations sit at real, verifiable places: **Agbogbloshie, Makola, Osu Oxford Street**, and dozens more
- **~60 stations report fresh data daily**; the rest update less frequently and are flagged accordingly
- Every figure shown in the app is labeled with its **source station and timestamp** — you can always check where a number came from
- The API key is read only from the `OPENAQ_API_KEY` environment variable or Streamlit secrets. It is **never hardcoded or committed**
- `data/snapshot.json` is a build-time snapshot of real OpenAQ data, used **only as a fallback** when the live API is unreachable; it is regenerated with `fetch_snapshot.py`

## Why it works in Ghana today

- **Pure web app** — nothing to install; it runs in any phone browser, which is how most Ghanaians are online
- **Free to operate** — deploys on Streamlit Cloud's free tier; zero servers, zero ops, zero cost
- **Light on bandwidth** — server-side data fetching and cached responses keep pages small on slow connections
- **Python ecosystem** — widely taught and used in Ghana's developer community, so the codebase is maintainable and forkable locally

Roadmap:

- **USSD/SMS alerts** via [Africa's Talking](https://africastalking.com/) for feature-phone users — the people most exposed often have no smartphone
- **Localization** into Twi and French
- **Partnerships** with EPA Ghana and schools for air-quality education programs

## Community Value & Replication

Mframa is not Accra-specific by design. To redeploy it for **any city covered by OpenAQ** — Lagos, Nairobi, Kampala, Dakar — you change exactly two things: the bounding box and the country code. The exposure calculator, best-hours model, and interpolation engine are geography-agnostic.

The architecture also doubles as a reference implementation for African civic-tech teams: how to responsibly consume a rate-limited open API (caching, retries, snapshot fallback) and present raw sensor data as decisions.

## Quick Start

```bash
pip install -r requirements.txt

# Free key after registering at https://explore.openaq.org
export OPENAQ_API_KEY=your_key_here

streamlit run app.py
```

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

## Architecture

```
                  ┌────────────────────┐
                  │   OpenAQ v3 API    │
                  │  (api.openaq.org)  │
                  └─────────┬──────────┘
                            │ X-API-Key
                            ▼
                  ┌────────────────────┐      ┌────────────────────┐
                  │   openaq_client    │─────▶│  data/snapshot.json │
                  │  cache · retry ·   │fallback│  (offline backup) │
                  │  snapshot fallback │      └────────────────────┘
                  └─────────┬──────────┘
                            ▼
                  ┌────────────────────┐
                  │     analytics      │
                  │ AQI · exposure ·   │
                  │ best-hours · IDW   │
                  └─────────┬──────────┘
                            ▼
                  ┌────────────────────┐
                  │   Streamlit UI     │
                  │ My Air · Best Hours│
                  │ What Did I Breathe │
                  │ Live Map           │
                  └────────────────────┘
```

## Proactive Air Alerts

Checking an app is a habit most people don't have. Mframa's push engine flips the model: **the air report comes to you**, on two tracks.

- **Morning briefing** — every day at ~05:45, each subscriber gets their station's current PM2.5 and AQI, today's cleanest hours (same `best_hours` model as the app), commute guidance for the 06:00–09:00 / 17:00–20:00 rush peaks, and a laundry & windows tip. During Harmattan build-up (city 7-day median rising and above 35.5 µg/m³) an extra dust-season warning is added.
- **Burst alerts** — every 15 minutes the engine checks thresholds; when a subscriber's station or the whole city crosses **AQI 151 (Unhealthy)**, an immediate alert goes out with protective steps. De-duplication guarantees at most one alert of the same type per 12 hours.

```
                 ┌──────────────────────────┐
                 │  GitHub Actions (cron)   │
                 │ 05:45 daily · */15 min   │
                 └────────────┬─────────────┘
                              ▼
                 ┌──────────────────────────┐      fallback
                 │      push_engine.py      │────────────▶ data/snapshot.json
                 │ briefing · alerts · poll │  ┌────────▶ OpenAQ v3 (live)
                 └────────────┬─────────────┘  │
              ┌───────────────┼────────────────┘
              ▼               ▼
     ┌────────────────┐ ┌──────────────────┐
     │  Telegram bot  │ │ SMS / USSD       │
     │  (live today)  │ │ Africa's Talking │
     └────────────────┘ └──────────────────┘
        subscribers.json + bot_state.json committed back to the repo by the workflow
```

**Cost model.** Telegram delivery is free. SMS via [Africa's Talking](https://africastalking.com/) costs roughly **$0.01–0.05 per message** in Ghana; at one message per subscriber per day, **10,000 subscribers ≈ $300–500/month** — a line item sized for a corporate CSR sponsorship or an EPA Ghana / NGO partnership, which is the planned funding path. USSD session costs are in the same range and reach feature phones with no data plan at all.

**Running it yourself.** The engine needs two repository secrets (repo → **Settings → Secrets and variables → Actions**):

| Secret | What for |
|---|---|
| `OPENAQ_API_KEY` | Live air-quality data (free key at [explore.openaq.org](https://explore.openaq.org)); without it the engine falls back to the bundled snapshot |
| `TELEGRAM_BOT_TOKEN` | Sending messages via the Telegram Bot API (from [@BotFather](https://t.me/BotFather)); without it every run degrades to dry-run and only logs |

No token is ever printed or committed. Without `TELEGRAM_BOT_TOKEN` nothing crashes — the workflows simply produce dry-run logs.

## License & Attribution

Code: [MIT License](LICENSE).

Data: © [OpenAQ](https://openaq.org) contributors and the [AfriqAir](https://afriqair.org/) network (Carnegie Mellon University Africa and partners). Mframa is grateful to the communities hosting sensors across Accra.
