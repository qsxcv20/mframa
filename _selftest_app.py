"""Smoke test for app.py: render every page via Streamlit AppTest and fail on exceptions.

A fresh AppTest instance is used per page: this AppTest version keeps stale
widget nodes from previous pages in its element tree while dropping their
session state, so reusing one instance across page switches crashes inside
the framework (KeyError on stale widget ids) — not an app bug.
"""

import sys

sys.stdout.reconfigure(encoding="utf-8", errors="replace")

from streamlit.testing.v1 import AppTest

# Top-level pills navigation; "More" expands into its two sub-pages.
PAGES = ["My Air", "Best Hours Today", "Live Map", "More"]
MORE_SUBPAGES = ["What Did I Breathe?", "Get Air Alerts"]


def run_case(make_at, label):
    at = make_at()
    errors = [str(e.value) for e in at.exception]
    status = "OK" if not errors else "FAIL"
    print(f"[{status}] {label} (errors shown: {len(at.error)}, warnings: {len(at.warning)})")
    for e in errors:
        print("   ", e[:500])
    return not errors


def main():
    ok = True
    for page in PAGES:
        def make_at(page=page):
            at = AppTest.from_file("app.py", default_timeout=180)
            at.run()
            nav = next(p for p in at.pills if "My Air" in list(p.options))
            nav.set_value(page).run()
            return at
        ok = run_case(make_at, page) and ok
    for sub in MORE_SUBPAGES:
        def make_at(sub=sub):
            at = AppTest.from_file("app.py", default_timeout=180)
            at.run()
            nav = next(p for p in at.pills if "My Air" in list(p.options))
            nav.set_value("More").run()
            subnav = next(p for p in at.pills if "Get Air Alerts" in list(p.options))
            subnav.set_value(sub).run()
            return at
        ok = run_case(make_at, f"More > {sub}") and ok
    # Language switch must not break navigation (stored labels turn stale).
    def make_zh():
        at = AppTest.from_file("app.py", default_timeout=180)
        at.run()
        nav = next(p for p in at.pills if "My Air" in list(p.options))
        nav.set_value("Live Map").run()
        lang = next(s for s in at.selectbox if "中文" in list(s.options))
        lang.set_value("中文").run()
        return at
    ok = run_case(make_zh, "switch to 中文 after navigating") and ok

    # ?from=app (Android WebView): alerts page shows the built-in-alerts
    # guidance instead of the ntfy/Telegram subscription guides.
    def make_app_alerts():
        at = AppTest.from_file("app.py", default_timeout=180)
        at.query_params["from"] = "app"
        at.run()
        nav = next(p for p in at.pills if "My Air" in list(p.options))
        nav.set_value("More").run()
        subnav = next(p for p in at.pills if "Get Air Alerts" in list(p.options))
        subnav.set_value("Get Air Alerts").run()
        return at
    at = make_app_alerts()
    errors = [str(e.value) for e in at.exception]
    body = "\n".join(str(m.value) for m in at.markdown)
    if not errors and "My Exposure" in body and "ntfy.sh" not in body:
        print("[OK] More > Get Air Alerts (?from=app shows built-in guide)")
    else:
        ok = False
        print("[FAIL] More > Get Air Alerts (?from=app)")
        for e in errors:
            print("   ", e[:500])
        if "My Exposure" not in body:
            print("    built-in guide missing")
        if "ntfy.sh" in body:
            print("    ntfy subscribe guide still visible")

    # Browser-local alerts: the Telegram/ntfy subscription UI is gone; the
    # page offers a toggle plus a threshold slider using the same steps as
    # the Android app's AlertPrefs.THRESHOLD_STEPS (default 35 = Ghana EPA).
    def make_alerts_local():
        at = AppTest.from_file("app.py", default_timeout=180)
        at.run()
        nav = next(p for p in at.pills if "My Air" in list(p.options))
        nav.set_value("More").run()
        subnav = next(p for p in at.pills if "Get Air Alerts" in list(p.options))
        subnav.set_value("Get Air Alerts").run()
        return at
    at = make_alerts_local()
    errors = [str(e.value) for e in at.exception]
    body = "\n".join(str(m.value) for m in at.markdown)
    body += "\n".join(str(c.value) for c in at.caption)
    steps = [int(o) for o in at.select_slider[0].options] if at.select_slider else None
    checks = [
        ("toggle", len(at.toggle) >= 1),
        ("threshold steps", steps == [15, 25, 35, 55, 75, 100, 150]),
        ("threshold default", at.select_slider[0].value == 35 if at.select_slider else False),
        ("android briefing", "Android app" in body),
        ("no ntfy/telegram", "ntfy" not in body.lower() and "telegram" not in body.lower()),
    ]
    if not errors and all(c for _, c in checks):
        print("[OK] More > Get Air Alerts (browser-local alerts UI)")
    else:
        ok = False
        print("[FAIL] More > Get Air Alerts (browser-local alerts UI)")
        for e in errors:
            print("   ", e[:500])
        for name, c in checks:
            if not c:
                print("    failed:", name)

    # Deep link: ?lang=zh&page=more&sub=alerts lands on More > 订阅空气提醒
    # in Chinese, and the URL params are kept in sync.
    at = AppTest.from_file("app.py", default_timeout=180)
    at.query_params["lang"] = "zh"
    at.query_params["page"] = "more"
    at.query_params["sub"] = "alerts"
    at.run()
    errors = [str(e.value) for e in at.exception]
    checks = [
        ("lang session", at.session_state.get("lang") == "zh"),
        ("nav_page zh", at.session_state.get("nav_page") == "更多"),
        ("subpage zh", at.session_state.get("more_subpage") == "订阅空气提醒"),
        ("zh header", any(sh.value == "订阅空气提醒" for sh in at.subheader)),
        ("qp lang kept", at.query_params.get("lang") == "zh"),
        ("qp page kept", at.query_params.get("page") == "more"),
        ("qp sub kept", at.query_params.get("sub") == "alerts"),
    ]
    if not errors and all(c for _, c in checks):
        print("[OK] deep link ?lang=zh&page=more&sub=alerts")
    else:
        ok = False
        print("[FAIL] deep link ?lang=zh&page=more&sub=alerts")
        for e in errors:
            print("   ", e[:500])
        for name, c in checks:
            if not c:
                print("    failed:", name)

    # Write-back: navigating / switching language updates the URL params.
    at = AppTest.from_file("app.py", default_timeout=180)
    at.run()
    nav = next(p for p in at.pills if "My Air" in list(p.options))
    nav.set_value("Live Map").run()
    page_ok = at.query_params.get("page") == "map"
    lang = next(s for s in at.selectbox if "中文" in list(s.options))
    lang.set_value("中文").run()
    # (switching language resets the stale page label to the default page,
    # so only lang is asserted here)
    lang_ok = at.query_params.get("lang") == "zh"
    errors = [str(e.value) for e in at.exception]
    if not errors and page_ok and lang_ok:
        print("[OK] query params written back on nav/lang change")
    else:
        ok = False
        print("[FAIL] query params written back on nav/lang change")
        for e in errors:
            print("   ", e[:500])
        if not page_ok:
            print("    failed: qp page=map (got %r)" % at.query_params.get("page"))
        if not lang_ok:
            print("    failed: qp lang=zh (got %r)" % at.query_params.get("lang"))

    # Batch-1 features on My Air: EPA 35 µg/m³ benchmark line, red-flag card
    # (with GINA line for asthma), and the WhatsApp share button.
    at = AppTest.from_file("app.py", default_timeout=180)
    at.run()
    body = "\n".join(str(m.value) for m in at.markdown)
    epa_ok = "35 µg/m³" in body
    wa = [b for b in at.link_button if "wa.me" in str(b.url)]
    errors = [str(e.value) for e in at.exception]
    if not errors and epa_ok and wa:
        print("[OK] My Air: EPA 35 line + WhatsApp share button")
    else:
        ok = False
        print("[FAIL] My Air: EPA 35 line + WhatsApp share button")
        for e in errors:
            print("   ", e[:500])
        if not epa_ok:
            print("    EPA line (35 µg/m³) missing")
        if not wa:
            print("    wa.me link_button missing")

    at = AppTest.from_file("app.py", default_timeout=180)
    at.run()
    prof = next(s for s in at.selectbox if s.key == "health_profile")
    prof.set_value("asthma").run()
    err_body = "\n".join(str(e.value) for e in at.error)
    errors = [str(e.value) for e in at.exception]
    if not errors and "GINA" in err_body and "CHPS" in err_body:
        print("[OK] My Air (asthma): red-flag card with GINA line")
    else:
        ok = False
        print("[FAIL] My Air (asthma): red-flag card with GINA line")
        for e in errors:
            print("   ", e[:500])
        if "CHPS" not in err_body:
            print("    red-flag card missing")
        if "GINA" not in err_body:
            print("    GINA line missing")

    # Batch-2: Harmattan demo replay (?demo=harmattan) — banner shows, AQI
    # card renders the replay value for the default (nearest-center) station.
    import json as _json
    demo_data = _json.load(open("data/demo_harmattan.json", encoding="utf-8"))
    center = (5.6037, -0.1870)
    default_station = min(
        demo_data["stations"],
        key=lambda s: (s["lat"] - center[0]) ** 2 + (s["lon"] - center[1]) ** 2)
    expected_pm25 = default_station["latest_pm25"]["value"]
    at = AppTest.from_file("app.py", default_timeout=180)
    at.query_params["demo"] = "harmattan"
    at.run()
    body = "\n".join(str(m.value) for m in at.markdown)
    warn_body = "\n".join(str(w.value) for w in at.warning)
    errors = [str(e.value) for e in at.exception]
    checks = [
        ("banner", "Demo replay" in warn_body and demo_data["date"] in warn_body),
        ("replay value", f"{expected_pm25:.1f}" in body),
    ]
    if not errors and all(c for _, c in checks):
        print(f"[OK] demo=harmattan replay ({demo_data['date']}, "
              f"default station {expected_pm25:.1f} µg/m³)")
    else:
        ok = False
        print("[FAIL] demo=harmattan replay")
        for e in errors:
            print("   ", e[:500])
        for name, c in checks:
            if not c:
                print("    failed:", name)

    # Batch-2: Agbogbloshie cleanup card on Live Map; loaders go silent on
    # missing files (tested directly, app.py only runs main() under __main__).
    at = AppTest.from_file("app.py", default_timeout=180)
    at.run()
    nav = next(p for p in at.pills if "My Air" in list(p.options))
    nav.set_value("Live Map").run()
    body = "\n".join(str(m.value) for m in at.markdown)
    errors = [str(e.value) for e in at.exception]
    card_ok = "Agbogbloshie" in body and "90-day cleanup" in body
    if not errors and card_ok:
        print("[OK] Live Map: Agbogbloshie cleanup card")
    else:
        ok = False
        print("[FAIL] Live Map: Agbogbloshie cleanup card")
        for e in errors:
            print("   ", e[:500])
        if not card_ok:
            print("    cleanup card missing")

    import app as app_mod
    silent = (app_mod.load_cleanup_status("data/_missing_.json") is None
              and app_mod.load_demo_harmattan("data/_missing_.json") is None
              and app_mod.load_cleanup_status() is not None
              and app_mod.load_demo_harmattan() is not None
              and app_mod.load_fires("data/_missing_.json") is None
              and app_mod.load_fires() is not None)
    if silent:
        print("[OK] static-data loaders silent on missing files")
    else:
        ok = False
        print("[FAIL] static-data loaders silent on missing files")

    # Defensive helpers: negative PM2.5 clamps to 0, stations with missing
    # coordinates never crash station picking, and malformed demo JSON
    # (non-list stations, or every station lacking PM2.5) degrades to None.
    import os as _os
    import tempfile as _tempfile

    def demo_with(payload):
        fd, p = _tempfile.mkstemp(suffix=".json")
        _os.write(fd, _json.dumps(payload).encode())
        _os.close(fd)
        try:
            return app_mod.load_demo_harmattan(p)
        finally:
            _os.unlink(p)

    try:
        defensive = (
            app_mod.pm25_of({"latest_pm25": {"value": -3.2}}) == 0.0
            and app_mod.pm25_of({"latest_pm25": {"value": None}}) is None
            and app_mod.nearest_index(
                [{"lat": None, "lon": None}, {"lat": 5.6, "lon": -0.19}]) == 1
            and demo_with({"stations": "not-a-list"}) is None
            and demo_with({"stations": [{"latest_pm25": {"value": None}}]}) is None
            and demo_with({"stations": [{"latest_pm25": {"value": 12.3}}]}) is not None
        )
    except Exception:
        defensive = False
    if defensive:
        print("[OK] defensive helpers (pm25 clamp, None coords, demo filter)")
    else:
        ok = False
        print("[FAIL] defensive helpers (pm25 clamp, None coords, demo filter)")

    # Geolocation: ?lat=&lon= (written by the in-page "Use my location"
    # button or the Android WebView) must auto-select the nearest monitor and
    # show the confirmation line. Coordinates outside Greater Accra are
    # rejected by parse_user_loc.
    geo_helpers = (
        app_mod.parse_user_loc({"lat": "5.60", "lon": "-0.19"}) == (5.60, -0.19)
        and app_mod.parse_user_loc({"lat": "40.0", "lon": "-74.0"}) is None
        and app_mod.parse_user_loc({}) is None
        and app_mod.nearest_index(
            [{"lat": 5.50, "lon": -0.30}, {"lat": 5.601, "lon": -0.188}],
            (5.6037, -0.1870)) == 1
    )
    at = AppTest.from_file("app.py", default_timeout=180)
    at.query_params["lat"] = "5.5821"
    at.query_params["lon"] = "-0.1986"  # Nima Market
    at.run()
    geo_errors = [str(e.value) for e in at.exception]
    geo_sb = next(s for s in at.selectbox if getattr(s, "key", None) == "station_myair")
    geo_caps = "\n".join(str(c.value) for c in at.caption)
    geo_name = geo_sb.options[geo_sb.value] if geo_sb.options else ""
    geo_ok = (
        geo_helpers
        and not geo_errors
        and "Nima Market" in str(geo_name)
        and "Nearest monitor" in geo_caps
    )
    if geo_ok:
        print("[OK] geolocation ?lat/lon auto-selects nearest station")
    else:
        ok = False
        print("[FAIL] geolocation ?lat/lon auto-selects nearest station")
        for e in geo_errors:
            print("   ", e[:500])
        if not geo_helpers:
            print("    helper logic failed")
        if "Nima Market" not in str(geo_name):
            print("    selected station:", geo_name)
        if "Nearest monitor" not in geo_caps:
            print("    confirmation caption missing")

    # A polluted lang value (e.g. "fr" from a hand-edited URL) must self-heal
    # to English instead of silently showing the Chinese UI.
    at = AppTest.from_file("app.py", default_timeout=180)
    at.session_state["lang"] = "fr"
    at.run()
    errors = [str(e.value) for e in at.exception]
    if not errors and at.session_state.get("lang") == "en":
        print("[OK] polluted lang self-heals to English")
    else:
        ok = False
        print("[FAIL] polluted lang self-heals to English")
        for e in errors:
            print("   ", e[:500])
        if at.session_state.get("lang") != "en":
            print("    failed: lang is %r" % at.session_state.get("lang"))

    # FIRMS: Live Map carries the NASA FIRMS fire-source caption (static
    # data/fires_ghana.json); My Air's attribution card shows the VIIRS
    # observation line whenever the dust/smoke card itself renders.
    at = AppTest.from_file("app.py", default_timeout=180)
    at.run()
    nav = next(p for p in at.pills if "My Air" in list(p.options))
    nav.set_value("Live Map").run()
    cap = "\n".join(str(c.value) for c in at.caption)
    errors = [str(e.value) for e in at.exception]
    fires_cap_ok = "NASA FIRMS" in cap
    at2 = AppTest.from_file("app.py", default_timeout=180)
    at2.run()
    body2 = "\n".join(str(m.value) for m in at2.markdown)
    errors += [str(e.value) for e in at2.exception]
    dust_card = "Dust or Smoke?" in body2
    viirs_ok = ("VIIRS" in body2) if dust_card else True
    if not errors and fires_cap_ok and viirs_ok:
        note = "VIIRS line asserted" if dust_card else "dust card off, VIIRS skipped"
        print(f"[OK] FIRMS: map fire caption + attribution line ({note})")
    else:
        ok = False
        print("[FAIL] FIRMS: map fire caption + attribution line")
        for e in errors:
            print("   ", e[:500])
        if not fires_cap_ok:
            print("    NASA FIRMS caption missing on Live Map")
        if not viirs_ok:
            print("    VIIRS evidence line missing on My Air")

    # FIRMS: replay mode (?demo=harmattan) must hide the fire layer — a
    # historical day has no business showing today's fires.
    at = AppTest.from_file("app.py", default_timeout=180)
    at.query_params["demo"] = "harmattan"
    at.run()
    nav = next(p for p in at.pills if "My Air" in list(p.options))
    nav.set_value("Live Map").run()
    cap = "\n".join(str(c.value) for c in at.caption)
    errors = [str(e.value) for e in at.exception]
    if not errors and "NASA FIRMS" not in cap:
        print("[OK] FIRMS: fire layer hidden in demo replay")
    else:
        ok = False
        print("[FAIL] FIRMS: fire layer hidden in demo replay")
        for e in errors:
            print("   ", e[:500])
        if "NASA FIRMS" in cap:
            print("    NASA FIRMS caption visible during replay")

    print("ALL PAGES OK" if ok else "SOME PAGES FAILED")
    sys.exit(0 if ok else 1)
main()
