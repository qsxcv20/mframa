"""Smoke test for app.py: render every page via Streamlit AppTest and fail on exceptions.

A fresh AppTest instance is used per page: this AppTest version keeps stale
widget nodes from previous pages in its element tree while dropping their
session state, so reusing one instance across page switches crashes inside
the framework (KeyError on stale widget ids) — not an app bug.
"""

import sys

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

    print("ALL PAGES OK" if ok else "SOME PAGES FAILED")
    sys.exit(0 if ok else 1)
main()
