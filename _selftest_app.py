"""Smoke test for app.py: render every page via Streamlit AppTest and fail on exceptions.

A fresh AppTest instance is used per page: this AppTest version keeps stale
widget nodes from previous pages in its element tree while dropping their
session state, so reusing one instance across page switches crashes inside
the framework (KeyError on stale widget ids) — not an app bug.
"""

import sys

from streamlit.testing.v1 import AppTest

PAGES = ["My Air", "Best Hours Today", "What Did I Breathe?", "Live Map", "Get Air Alerts"]


def main():
    ok = True
    for page in PAGES:
        at = AppTest.from_file("app.py", default_timeout=180)
        at.run()
        nav = next(r for r in at.radio if "My Air" in list(r.options))
        nav.set_value(page).run()
        errors = [str(e.value) for e in at.exception]
        status = "OK" if not errors else "FAIL"
        print(f"[{status}] {page} (errors shown: {len(at.error)}, warnings: {len(at.warning)})")
        if errors:
            ok = False
            for e in errors:
                print("   ", e[:500])
    print("ALL PAGES OK" if ok else "SOME PAGES FAILED")
    sys.exit(0 if ok else 1)


main()
