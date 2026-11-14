"""Smoke-test every page against the local DB (load the sample fund first). Run: python tests/smoke_views.py"""
import os
import sys

from streamlit.testing.v1 import AppTest

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(HERE))

VIEWS = ["dashboard.py", "investors.py", "holdings.py", "new_position.py", "watchlist.py", "analytics.py",
         "tax.py", "settings.py"]
failed = 0
for v in VIEWS:
    for sel in ([None, 1, 3] if v == "holdings.py" else [None]):
        at = AppTest.from_file(os.path.join(HERE, "harness.py"), default_timeout=120)
        at.session_state["_view"] = v
        if sel:
            at.session_state["sel_pos"] = sel
        if v == "investors.py":
            at.session_state["sel_inv"] = 2
        at.run()
        label = v + (f" (sel_pos={sel})" if sel else "")
        if at.exception:
            failed += 1
            print("FAIL", label)
            for e in at.exception:
                print(e.message)
                print("\n".join(e.stack_trace[-12:]))
        else:
            print("ok  ", label, f"- {len(at.metric)} metrics, {len(at.dataframe)} tables")
sys.exit(1 if failed else 0)
