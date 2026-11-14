"""Fund Tracker (NAV / unit accounting for pooled money) - entry point.  Run:  streamlit run app.py"""
import html

import streamlit as st

st.set_page_config(page_title="Fund Tracker", page_icon="📈", layout="wide",
                   initial_sidebar_state="expanded")

from core import auth, dialogs, links, prices, state, theme  # noqa: E402
from core.ui import compact, inr, pct  # noqa: E402

theme.apply()
st.logo("assets/logo.svg", size="large", icon_image="assets/logo_mark.svg")
owner = auth.require_login()
st.session_state["owner"] = owner

try:
    with st.spinner("Loading fund…"):
        st.session_state["ctx"] = state.build_ctx(owner)
except Exception as e:  # DB unreachable, bad secrets, etc.
    st.error(f"Could not load data: {e}")
    st.info("Check the `[database]` url in secrets (Supabase: use the **Session pooler** connection string).")
    st.stop()

c = st.session_state["ctx"]

pages = {
    "Fund": [
        st.Page("views/dashboard.py", title="Dashboard", icon=":material/dashboard:", default=True),
        st.Page("views/investors.py", title="Investors", icon=":material/group:"),
    ],
    "Portfolio": [
        st.Page("views/holdings.py", title="Holdings", icon=":material/list_alt:"),
        st.Page("views/new_position.py", title="New position", icon=":material/add_circle:"),
        st.Page("views/watchlist.py", title="Watchlist", icon=":material/visibility:"),
    ],
    "Insights": [
        st.Page("views/analytics.py", title="Analytics", icon=":material/insights:"),
        st.Page("views/tax.py", title="Tax (estimate)", icon=":material/receipt_long:"),
    ],
    "Account": [
        st.Page("views/settings.py", title="Fund & settings", icon=":material/settings:"),
    ],
}
nav = st.navigation(pages)

with st.sidebar:
    _day = c.day
    _prev = c.total - _day
    _arrow = "▲" if _day >= 0 else "▼"
    _holders = int((c.inv_summary["units"] > 0).sum()) if not c.inv_summary.empty else 0
    st.html(f"""<div class='pt-wallet'>
      <div class='l'>{html.escape(c.fund_name)} · NAV</div>
      <div class='v'>₹{c.nav:,.4f}</div>
      <div class='d'>{_arrow} {abs(_day / _prev * 100) if _prev else 0:.2f}% today · {pct((c.nav / c.face - 1) * 100)} since start</div>
      <div class='row'><div><span>Fund value</span><b>{compact(c.total)}</b></div>
        <div><span>Cash</span><b>{compact(c.cash)}</b></div>
        <div><span>Investors</span><b>{_holders}</b></div></div>
    </div>""")
    b1, b2 = st.columns(2)
    if b1.button("Funds", icon=":material/account_balance_wallet:", width="stretch",
                 disabled=c.investors.empty, help="Record an investor deposit or withdrawal"):
        dialogs.funds_dialog()
    if b2.button("Prices", icon=":material/refresh:", width="stretch", help="Refresh live prices"):
        prices.refresh_quotes()
        st.rerun()
    _status = {"live": ("#34d399", "Live prices · Yahoo, ~5 min cache"), "partial": ("#fbbf24", "Some prices from cache"),
               "cache": ("#fb923c", "Yahoo unavailable · cached prices"), "none": ("#94a3b8", "No prices yet")}
    _col, _txt = _status.get(c.price_status, ("#94a3b8", ""))
    st.html(f"<div class='pt-status'><span class='pt-dot' style='background:{_col};box-shadow:0 0 0 3px {_col}33'></span>{_txt}</div>")
    my_links = links.get_links(c.data["settings"])
    st.html("<div class='pt-side-label' style='margin-top:.9rem'>My apps</div>")
    for l in my_links:
        st.link_button(l["name"], l["url"], icon=":material/open_in_new:", width="stretch", type="tertiary")
    if not my_links:
        st.caption("No links yet.")
    if st.button("Manage links", icon=":material/edit:", width="stretch", key="sb_links",
                 help="Add, delete or reorder the links above"):
        dialogs.links_dialog()
    auth.sidebar_user(owner)

if msg := st.session_state.pop("flash", None):
    st.toast(msg, icon="✅")

nav.run()
