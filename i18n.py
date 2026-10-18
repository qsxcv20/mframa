"""Bilingual (English/中文) UI strings for the Mframa Streamlit app.

Static UI copy lives in S as {"key": {"en": ..., "zh": ...}} and is rendered
via t(key, **kwargs). Whole-sentence English text produced by analytics.py
(advice bullets, dust/smoke cards, chart labels) is mapped through ZH_MAP
and rendered via tt(text). Push messages (ntfy/Telegram) stay English-only.
"""

S = {
    # --- App shell / navigation -------------------------------------------
    "language_label": {"en": "Language / 语言", "zh": "Language / 语言"},
    "tagline": {
        "en": "Know your air, Accra — TechHub Africa Hackathon 2026",
        "zh": "了解阿克拉的空气 —— TechHub Africa 黑客松 2026",
    },
    "navigate": {"en": "Navigate", "zh": "导航"},
    "nav_page": {"en": "Page", "zh": "页面"},
    "nav_my_air": {"en": "My Air", "zh": "我的空气"},
    "nav_best_hours": {"en": "Best Hours Today", "zh": "今日最佳时段"},
    "nav_breathe": {"en": "What Did I Breathe?", "zh": "我吸入了什么？"},
    "nav_map": {"en": "Live Map", "zh": "实时地图"},
    "nav_alerts": {"en": "Get Air Alerts", "zh": "订阅空气提醒"},
    "station_header": {"en": "Station", "zh": "监测站"},
    "monitoring_station": {"en": "Monitoring station", "zh": "监测站"},
    "reference_station": {"en": "Reference station", "zh": "参考站点"},
    "load_error": {
        "en": "Air quality data could not be loaded. Please refresh in a moment.",
        "zh": "空气质量数据暂时无法加载，请稍后刷新。",
    },
    "no_stations": {
        "en": "No stations with current PM2.5 readings are available right now. "
              "Please check back shortly.",
        "zh": "目前没有可用的 PM2.5 实时读数站点，请稍后再查看。",
    },
    "snag_error": {
        "en": "This view hit a snag while processing the data. "
              "Try another page or refresh the app.",
        "zh": "这个页面在处理数据时出了点问题，请换个页面或刷新应用。",
    },
    "data_cached": {
        "en": "Showing recently cached OpenAQ data (live API unavailable)",
        "zh": "正在显示最近缓存的 OpenAQ 数据（实时 API 暂不可用）",
    },
    "footer": {
        "en": "Data: OpenAQ (api.openaq.org) · AfriqAir & community sensors · Not medical advice",
        "zh": "数据来源：OpenAQ (api.openaq.org) · AfriqAir 及社区传感器 · 不构成医疗建议",
    },

    # --- My Air ------------------------------------------------------------
    "health_profile": {"en": "Health profile", "zh": "健康档案"},
    "profile_general": {"en": "general", "zh": "普通人群"},
    "profile_child": {"en": "child", "zh": "儿童"},
    "profile_asthma": {"en": "asthma", "zh": "哮喘患者"},
    "profile_pregnant": {"en": "pregnant", "zh": "孕妇"},
    "profile_senior": {"en": "senior", "zh": "老年人"},
    "profile_athlete": {"en": "athlete", "zh": "运动爱好者"},
    "no_readings": {
        "en": "No recent readings for this station and not enough data to estimate — "
              "try another station in the sidebar.",
        "zh": "该站点暂无近期读数，也没有足够数据进行估算——请在侧边栏换个站点试试。",
    },
    "estimated_suffix": {"en": " (estimated)", "zh": "（估算）"},
    "updated_source": {
        "en": "Updated {ts} · Source: {provider}",
        "zh": "更新于 {ts} · 来源：{provider}",
    },
    "est_warn": {
        "en": "Estimated (station offline) — based on diurnal pattern + "
              "{n} nearby stations{stats}. Last reading {stale} h ago · "
              "confidence: {conf}.",
        "zh": "估算值（站点离线）——基于昼夜变化规律 + {n} 个邻近站点{stats}。"
              "最近一次读数为 {stale} 小时前 · 置信度：{conf}。",
    },
    "est_mae": {
        "en": "backtest MAE ≈ {mae} µg/m³",
        "zh": "回测 MAE ≈ {mae} µg/m³",
    },
    "est_acc": {
        "en": ", typical relative error ≈ {rel}% (n={n}, vs {base}% naive baseline)",
        "zh": "，典型相对误差 ≈ {rel}%（n={n}，朴素基线为 {base}%）",
    },
    "advice_header": {
        "en": "What this means for you ({profile})",
        "zh": "这对您意味着什么（{profile}）",
    },

    # --- Dust or Smoke? card / forecast chart -------------------------------
    "dust_unavailable": {
        "en": "Dust/smoke forecast temporarily unavailable.",
        "zh": "沙尘/烟雾预报暂时不可用。",
    },
    "dust_or_smoke": {"en": "Dust or Smoke?", "zh": "沙尘还是烟雾？"},
    "harmattan_badge": {
        "en": "🏜️ Harmattan conditions",
        "zh": "🏜️ 哈马丹沙尘天气",
    },
    "dust_line": {
        "en": "Dust ≈ <b>{dust}</b> of <b>{pm25}</b> µg/m³ PM2.5 "
              "({pct}% dust share · dust risk: {risk}{aod}).",
        "zh": "PM2.5 共 <b>{pm25}</b> µg/m³，其中沙尘 ≈ <b>{dust}</b>"
              "（沙尘占比 {pct}% · 沙尘风险：{risk}{aod}）。",
    },
    "harmattan_body": {
        "en": "Saharan dust is elevated. Keep windows closed and wear a mask outdoors.",
        "zh": "撒哈拉沙尘浓度偏高。请关好门窗，外出佩戴口罩。",
    },
    "forecast_src": {
        "en": "Forecast: CAMS/ECMWF via Open-Meteo (free)",
        "zh": "预报：CAMS/ECMWF，由 Open-Meteo 提供（免费）",
    },
    "cached_suffix": {"en": " (cached)", "zh": "（缓存）"},
    "showing_cached": {
        "en": " — showing cached forecast",
        "zh": "——当前显示的是缓存预报",
    },
    "trace_dust": {"en": "Dust (Saharan)", "zh": "沙尘（撒哈拉）"},
    "harmattan_threshold": {
        "en": "Harmattan dust threshold (50)",
        "zh": "哈马丹沙尘阈值（50）",
    },
    "dust_chart_title": {
        "en": "Next {hours} h: dust & PM2.5 forecast",
        "zh": "未来 {hours} 小时：沙尘与 PM2.5 预报",
    },

    # --- Best Hours Today ---------------------------------------------------
    "no_hourly": {
        "en": "No recent hourly measurements for this station yet — "
              "try another station in the sidebar.",
        "zh": "该站点暂无近期逐小时测量数据——请在侧边栏换个站点试试。",
    },
    "no_pattern": {
        "en": "Today's pattern could not be computed for this station.",
        "zh": "无法计算该站点今日的变化规律。",
    },
    "trace_typical": {"en": "Typical (7-day)", "zh": "典型水平（7 天）"},
    "trace_today": {"en": "Today", "zh": "今天"},
    "xaxis_hour": {"en": "Hour of day (local)", "zh": "一天中的时刻（当地时间）"},
    "good_windows": {
        "en": "Good for jogging / outdoor time: {slots}",
        "zh": "适合慢跑 / 户外活动：{slots}",
    },
    "no_green": {
        "en": "No clear low-pollution window today — consider indoor exercise.",
        "zh": "今天没有明显的低污染时段——建议改为室内锻炼。",
    },
    "bad_windows": {
        "en": "Avoid prolonged outdoor exertion: {slots}",
        "zh": "避免长时间户外剧烈活动：{slots}",
    },
    "windows_caption": {
        "en": "Windows are runs of 2+ hours in the Good (green) or Unhealthy (red) "
              "PM2.5 range, judged on today's readings where available, otherwise "
              "the station's 7-day average.",
        "zh": "时段指连续 2 小时以上处于良好（绿色）或不健康（红色）PM2.5 区间的时间；"
              "优先依据今天的实测读数，缺失时用该站点的 7 天平均值。",
    },

    # --- What Did I Breathe? -------------------------------------------------
    "pollution_levels": {
        "en": "Pollution levels used (µg/m³)",
        "zh": "使用的污染水平（µg/m³）",
    },
    "outdoor_level": {
        "en": "Outdoor level (default: selected station)",
        "zh": "户外水平（默认：所选站点）",
    },
    "commute_level": {
        "en": "Commute level (default: city average)",
        "zh": "通勤水平（默认：全市平均）",
    },
    "commute_time": {"en": "Commute time (h/day)", "zh": "通勤时间（小时/天）"},
    "outdoor_time": {"en": "Outdoor time (h/day)", "zh": "户外时间（小时/天）"},
    "activity_intensity": {"en": "Activity intensity", "zh": "活动强度"},
    "activity_rest": {"en": "rest", "zh": "休息"},
    "activity_light": {"en": "light", "zh": "轻度"},
    "activity_moderate": {"en": "moderate", "zh": "中度"},
    "activity_heavy": {"en": "heavy", "zh": "高强度"},
    "cig_equiv": {
        "en": "cigarette-equivalent per day",
        "zh": "相当于每天吸的香烟数",
    },
    "cig_headline": {
        "en": "A day in Accra today ≈ smoking {cigs} cigarettes "
              "(inhaled ≈ {ug} µg of PM2.5)",
        "zh": "今天在阿克拉待一天 ≈ 吸了 {cigs} 支香烟（吸入 PM2.5 约 {ug} µg）",
    },
    "cigs_lt": {"en": "less than 0.1", "zh": "不到 0.1"},
    "exposure_breakdown": {"en": "Exposure breakdown", "zh": "暴露量构成"},
    "yaxis_inhaled": {"en": "PM2.5 inhaled (µg)", "zh": "吸入的 PM2.5（µg）"},
    "cig_method": {
        "en": "Methodology: cigarette equivalence follows the Berkeley Earth rule of thumb — "
              "inhaling ≈253 µg PM2.5 (22 µg/m³ over a day's breathing) ≈ 1 cigarette; "
              "commute and outdoor doses are weighted by breathing rate for the chosen activity.",
        "zh": "方法说明：香烟等效值采用 Berkeley Earth 的经验法则——吸入 ≈253 µg PM2.5"
              "（按一天呼吸量、22 µg/m³ 计）≈ 1 支香烟；通勤与户外剂量按所选活动强度"
              "对应的呼吸速率加权。",
    },

    # --- Get Air Alerts -------------------------------------------------------
    "alerts_intro": {
        "en": "Mframa can **push the air to you** instead of you checking the app. "
              "Two free channels, powered by scheduled checks of the same OpenAQ "
              "data you see here:",
        "zh": "Mframa 可以**把空气状况主动推给你**，不用你反复打开应用查看。"
              "两个免费渠道，背后是定时检查你在这里看到的同一套 OpenAQ 数据：",
    },
    "alerts_morning": {
        "en": "**🌅 Morning briefing (daily, ~05:45)**\n\n"
              "Your station's current PM2.5 and AQI, today's cleanest hours,\n"
              "commute guidance for the 06:00–09:00 / 17:00–20:00 rush peaks,\n"
              "and a laundry & windows tip — before you leave home.",
        "zh": "**🌅 晨间简报（每天约 05:45）**\n\n"
              "在你出门前送达：你所在站点的当前 PM2.5 和 AQI、今天最干净的时段、"
              "06:00–09:00 / 17:00–20:00 早晚高峰的通勤建议，以及晾晒和开窗小贴士。",
    },
    "alerts_burst": {
        "en": "**🚨 Burst alerts (checked every 15 min)**\n\n"
              "When your station — or the whole city — crosses AQI 151\n"
              "(*Unhealthy*), you get an immediate warning with concrete\n"
              "protective steps. No repeats within 12 hours.",
        "zh": "**🚨 突发警报（每 15 分钟检查一次）**\n\n"
              "当你的站点——或整个城市——的 AQI 超过 151（*不健康*）时，"
              "你会立即收到带有具体防护措施的警告。12 小时内不会重复推送。",
    },
    "subscribe_line": {
        "en": "👉 **Subscribe free in 10 seconds — no account, no phone number:** open "
              "**[ntfy.sh/{topic}](https://ntfy.sh/{topic})** in any browser and tap "
              "*Subscribe to topic*, or install the **ntfy** app (Android / iOS) and "
              "add the topic `{topic}`. You will get the daily morning briefing and "
              "every city-wide burst alert as a phone notification.",
        "zh": "👉 **10 秒免费订阅——无需账号、无需手机号：** 在任意浏览器打开 "
              "**[ntfy.sh/{topic}](https://ntfy.sh/{topic})**，点击 *Subscribe to topic*；"
              "或安装 **ntfy** 应用（Android / iOS）并添加主题 `{topic}`。"
              "每日晨间简报和每次全市突发警报都会以手机通知送达。",
    },
    "telegram_line": {
        "en": "📮 **Station-level personal alerts on Telegram: "
              "[@{bot}](https://t.me/{bot})** — send `/subscribe nearest` and share "
              "your location, or `/subscribe <station name>`.",
        "zh": "📮 **Telegram 上的站点级个人提醒：[@{bot}](https://t.me/{bot})** —— "
              "发送 `/subscribe nearest` 并分享你的位置，或 `/subscribe <站点名称>`。",
    },
    "telegram_soon": {
        "en": "A Telegram bot with station-level personal alerts (/subscribe your "
              "street's sensor) is launching soon — the ntfy channel above already "
              "works today.",
        "zh": "提供站点级个人提醒的 Telegram 机器人（/subscribe 你街上的传感器）"
              "即将上线——上面的 ntfy 渠道现在已经可用。",
    },
    "sms_expander": {
        "en": "No smartphone? SMS / USSD is the scale path",
        "zh": "没有智能手机？短信 / USSD 才是规模化路径",
    },
    "sms_body": {
        "en": "ntfy covers smartphone users first. To reach feature-phone users — "
              "often the people most exposed — the same engine plugs into "
              "**[Africa's Talking](https://africastalking.com/)** for SMS and USSD "
              "delivery across MTN, Vodafone and AirtelTigo. The alert logic, "
              "thresholds and de-duplication stay identical; only the transport changes.",
        "zh": "ntfy 先覆盖智能手机用户。要触达功能机用户——他们往往暴露最严重——"
              "同一套引擎可以接入 **[Africa's Talking](https://africastalking.com/)**，"
              "通过 MTN、Vodafone 和 AirtelTigo 发送短信和 USSD。警报逻辑、阈值和"
              "去重机制完全不变，只换投递通道。",
    },
    "alerts_footer": {
        "en": "Free to use, always. Data: OpenAQ · mute the ntfy topic any time to unsubscribe.",
        "zh": "永久免费。数据来源：OpenAQ · 随时静音 ntfy 主题即可退订。",
    },

    # --- Live Map -------------------------------------------------------------
    "map_header": {
        "en": "Live Map — PM2.5 across Accra",
        "zh": "实时地图 —— 阿克拉各地 PM2.5",
    },
    "map_caption": {
        "en": "Heatmap interpolated from station readings (IDW); dots are monitoring "
              "stations colored by AQI category.",
        "zh": "热力图由站点读数插值（IDW）生成；圆点为监测站，按 AQI 等级着色。",
    },
}


def current_lang():
    """'en' or 'zh' from st.session_state; 'en' outside a Streamlit run."""
    try:
        import streamlit as st
        lang = st.session_state.get("lang", "en")
    except Exception:
        return "en"
    return lang if lang in ("en", "zh") else "en"


def t(key, **kwargs):
    """Look up UI copy for the current language; fall back to English, then the key."""
    entry = S.get(key)
    if entry is None:
        text = key
    else:
        text = entry.get(current_lang()) or entry.get("en") or key
    if kwargs:
        try:
            return text.format(**kwargs)
        except Exception:
            return text
    return text


# Whole-sentence English -> 中文 mapping for text produced by analytics.py and
# openmeteo_client.py (advice bullets, dust/smoke card copy, category labels).
ZH_MAP = {
    # AQI category labels: English kept, Chinese gloss appended.
    "Good": "Good 优",
    "Moderate": "Moderate 中等",
    "Unhealthy for Sensitive Groups": "Unhealthy for Sensitive Groups 对敏感人群不健康",
    "Unhealthy": "Unhealthy 不健康",
    "Very Unhealthy": "Very Unhealthy 非常不健康",
    "Hazardous": "Hazardous 危险",
    "No data": "No data 无数据",
    # Dust risk labels (openmeteo_client.dust_risk_level).
    "Low": "Low 低",
    "Medium": "Medium 中",
    "High": "High 高",
    "Unknown": "Unknown 未知",
    # Exposure breakdown legs (analytics.exposure_report).
    "Commute": "通勤",
    "Outdoor activity": "户外活动",
    # Dust/smoke split titles (app.dust_smoke_split).
    "Dust-dominated": "以沙尘为主",
    "Smoke-dominated": "以烟雾为主",
    "Mixed dust & smoke": "沙尘与烟雾混合",
    # Dust/smoke split advice.
    "Saharan dust is carrying most of the pollution. Keep windows closed and wear "
    "a well-fitting mask (N95/KN95 if you have one) outdoors.":
        "目前的污染主要来自撒哈拉沙尘。请关好门窗，外出佩戴贴合的口罩（有 N95/KN95 最好）。",
    "Local burning/smoke is the main source. Avoid the morning and evening burning "
    "peaks; people with asthma should stay indoors.":
        "主要污染源是本地焚烧/烟雾。请避开早晚焚烧高峰时段；哮喘患者应留在室内。",
    "A blend of Harmattan dust and local smoke. Combine both precautions: limit "
    "time outdoors at peak burning hours and wear a mask outside.":
        "哈马丹沙尘与本地烟雾混合。两种防护都要做：焚烧高峰时段减少户外活动，外出佩戴口罩。",

    # --- analytics.profile_advice -------------------------------------------
    "Air quality is good — a great day for outdoor errands or a walk along the coast.":
        "空气质量很好——非常适合出门办事或到海边散步。",
    "If you cook with a charcoal stove, light it outdoors to keep your home's air clean.":
        "如果你用炭炉做饭，请在室外生火，保持家里空气清新。",
    "Good air today — children can play outside freely.":
        "今天空气不错——孩子们可以在户外尽情玩耍。",
    "Keep kids away from charcoal stoves and trash-burning spots even on clean days.":
        "即使空气干净，也要让孩子远离炭炉和焚烧垃圾的地方。",
    "Conditions look safe for outdoor activity; still carry your reliever inhaler.":
        "目前状况适合户外活动；但仍请随身携带缓解型吸入器。",
    "Avoid standing near charcoal braziers or burning refuse — smoke can spike locally.":
        "不要站在炭火盆或焚烧垃圾附近——局部烟雾可能骤升。",
    "Air is clean today; normal outdoor activity is fine.":
        "今天空气干净，正常户外活动没有问题。",
    "Cook in a well-ventilated space, away from charcoal smoke.":
        "请在通风良好的地方做饭，远离炭火烟雾。",
    "A good day for a gentle walk or sitting outside.":
        "今天适合悠闲散步或在户外坐坐。",
    "Avoid smoke from neighbourhood waste burning even when the index is low.":
        "即使指数不高，也要避开邻里焚烧垃圾产生的烟雾。",
    "Great window for outdoor training, running, or football.":
        "非常适合户外训练、跑步或踢足球。",
    "Train away from busy roads like the N1 highway to avoid exhaust hotspots.":
        "训练时避开 N1 高速等繁忙道路，远离尾气重灾区。",
    "Acceptable air, but unusually sensitive people should watch for symptoms.":
        "空气尚可，但特别敏感的人要留意身体症状。",
    "During Harmattan season dust can build through the day — check again before evening outings.":
        "哈马丹季节沙尘会在一天中逐渐累积——傍晚出门前请再查看一次。",
    "Outdoor play is fine, but cut it short if children start coughing.":
        "户外玩耍可以，但如果孩子开始咳嗽就早点结束。",
    "Keep children away from burning waste and smoky charcoal stoves.":
        "让孩子远离焚烧的垃圾和烟雾大的炭炉。",
    "Limit prolonged outdoor exertion and keep your inhaler within reach.":
        "减少长时间户外剧烈活动，吸入器放在随手可及的地方。",
    "Harmattan dust and burn smoke can trigger attacks — stay indoors if you smell smoke.":
        "哈马丹沙尘和焚烧烟雾可能诱发发作——闻到烟味就待在室内。",
    "Moderate air — take breaks indoors if you feel short of breath.":
        "空气一般——如果感觉气短，就回室内休息一下。",
    "Avoid smoky cooking areas; use LPG or a well-ventilated kitchen where possible.":
        "避开烟雾大的烹饪区；尽量使用液化气或通风良好的厨房。",
    "Short walks are fine; avoid long exposure along busy roads like the N1.":
        "短时间散步可以；避免在 N1 等繁忙道路旁长时间停留。",
    "Stay indoors if dust haze thickens during Harmattan.":
        "哈马丹期间如果沙尘霾加重，请留在室内。",
    "Reduce intensity of long outdoor workouts; move sessions indoors if possible.":
        "降低长时间户外训练的强度；有条件的话改到室内进行。",
    "Avoid training beside heavy traffic — exposure rises sharply on congested corridors.":
        "避免在拥堵路段旁训练——拥堵走廊上的暴露量会急剧上升。",
    "Sensitive groups should reduce prolonged outdoor exertion.":
        "敏感人群应减少长时间户外剧烈活动。",
    "Close windows against dust and smoke, especially during Harmattan or nearby burning.":
        "关窗阻挡沙尘和烟雾，尤其在哈马丹季节或附近有焚烧时。",
    "Keep children indoors for strenuous play; short quiet outdoor time is okay.":
        "剧烈的玩耍让孩子在室内进行；短时间、安静的户外活动可以。",
    "Watch for coughing or wheezing and move inside at the first sign.":
        "留意咳嗽或喘息，一有苗头就回到室内。",
    "Stay indoors as much as possible and pre-medicate as advised by your doctor.":
        "尽量待在室内，并按医生建议提前用药。",
    "Avoid commute-time traffic on the N1 highway — exhaust plus dust worsens attacks.":
        "避开通勤高峰的 N1 高速——尾气加沙尘会加重发作。",
    "Limit time outdoors and avoid smoky or dusty areas entirely.":
        "减少户外时间，完全避开有烟或有沙尘的地方。",
    "If you must travel, go outside rush hours and keep car windows up.":
        "如果必须出行，请避开高峰时段，并关好车窗。",
    "Remain indoors with windows closed against dust and smoke.":
        "留在室内，关好门窗，阻挡沙尘和烟雾。",
    "Postpone outdoor errands until air improves.":
        "户外的事情等空气好转后再去办。",
    "Move training indoors today; outdoor exertion multiplies pollutant intake.":
        "今天把训练改到室内；户外剧烈运动会让污染物摄入成倍增加。",
    "If you must train outside, keep it short and far from traffic and burn sites.":
        "如果必须在户外训练，时间要短，并远离车流和焚烧点。",
    "Everyone should avoid prolonged outdoor exertion; sensitive groups stay indoors.":
        "所有人都应避免长时间户外剧烈活动；敏感人群请留在室内。",
    "Wear a well-fitting mask if you must commute, and keep windows shut against smoke and dust.":
        "必须通勤时请佩戴贴合的口罩，并关好门窗挡住烟雾和沙尘。",
    "Avoid areas with active waste burning — local smoke can be far worse than the city average.":
        "避开正在焚烧垃圾的区域——局部烟雾可能比全市平均严重得多。",
    "Keep children indoors; no outdoor play or sports today.":
        "让孩子留在室内；今天不要户外玩耍或运动。",
    "Seal windows against Harmattan dust and smoke, and watch closely for coughing.":
        "封好门窗挡住哈马丹沙尘和烟雾，并密切留意是否咳嗽。",
    "Stay indoors, keep medication close, and seek care if symptoms escalate.":
        "待在室内，药物放在身边，症状加重时及时就医。",
    "Do not travel during rush hour — N1 traffic fumes sharply raise exposure.":
        "不要在高峰时段出行——N1 的车流尾气会显著升高暴露量。",
    "Stay indoors as much as possible; avoid all smoke and dust exposure.":
        "尽量待在室内；避免一切烟雾和沙尘暴露。",
    "Delegate outdoor errands; if travel is essential, use a mask and closed car windows.":
        "户外的事交给别人代办；必须出行时戴口罩、关车窗。",
    "Remain indoors with windows closed; avoid any outdoor exertion.":
        "留在室内并关好门窗；避免任何户外体力活动。",
    "Seek medical advice promptly if you feel chest tightness or breathlessness.":
        "如果感到胸闷或呼吸困难，请及时就医。",
    "Cancel outdoor training — exercising in this air multiplies your dose several-fold.":
        "取消户外训练——在这种空气中运动会让吸入剂量翻好几倍。",
    "Train indoors with filtered or conditioned air instead.":
        "改在有过滤或空调空气的室内训练。",
}


def tt(text):
    """Translate a whole English string to 中文 in zh mode; pass through otherwise."""
    if current_lang() != "zh":
        return text
    return ZH_MAP.get(text, text)
