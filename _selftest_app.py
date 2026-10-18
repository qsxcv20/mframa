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
        lang = next(p for p in at.pills if "中文" in list(p.options))
        lang.set_value("中文").run()
        return at
    ok = run_case(make_zh, "switch to 中文 after navigating") and ok
    print("ALL PAGES OK" if ok else "SOME PAGES FAILED")
    sys.exit(0 if ok else 1)


main()
