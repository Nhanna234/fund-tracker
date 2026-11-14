"""Runs one view (or keeps one dialog open) outside st.navigation for AppTest smoke tests."""
import os
import runpy
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
import streamlit as st  # noqa: E402

from core import dialogs, state  # noqa: E402

st.session_state["owner"] = "local@dev"
c = state.build_ctx("local@dev")
st.session_state["ctx"] = c

dlg = st.session_state.get("_dialog")
if dlg:
    name, *args = dlg
    if name == "delete_flow_dialog":
        match = c.flows[c.flows["id"] == args[0]]
        if match.empty:  # e.g. just deleted
            st.stop()
        dialogs.delete_flow_dialog(match.iloc[0].to_dict())
    elif name in ("investor_dialog", "delete_investor_dialog") and args:
        getattr(dialogs, name)(c.inv_summary[c.inv_summary["id"] == args[0]].iloc[0].to_dict())
    elif name in ("trade_dialog", "delete_position_dialog"):
        match = c.summary[c.summary["id"] == args[0]]
        if match.empty:  # e.g. just deleted
            st.stop()
        pos = match.iloc[0].to_dict()
        getattr(dialogs, name)(pos, *args[1:])
    else:
        getattr(dialogs, name)(*args)
else:
    runpy.run_path(os.path.join(ROOT, "views", st.session_state.get("_view", "dashboard.py")), run_name="__main__")
