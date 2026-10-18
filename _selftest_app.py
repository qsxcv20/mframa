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
              and app_mod.load_demo_harmattan() is not None)
    if silent:
        print("[OK] static-data loaders silent on missing files")
    else:
        ok = False
        print("[FAIL] static-data loaders silent on missing files")

    print("ALL PAGES OK" if ok else "SOME PAGES FAILED")
    sys.exit(0 if ok else 1)
main()
