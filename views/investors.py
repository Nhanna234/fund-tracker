import datetime as dt

import pandas as pd
import streamlit as st

from core import charts, dialogs, nav, state
from core.ui import card, card_title, empty_state, inr, page_header, pct, style_table

c = state.ctx()
page_header("Investors", "Everyone's units, what they are worth today, and a statement for each person. "
                         "Select a row to add money, withdraw or see the account.", eyebrow="Fund")

if c.investors.empty:
    empty_state("Set up the fund first: your own starting capital creates the first units.",
                "views/dashboard.py", "Set up the fund")
    st.stop()

S = c.inv_summary.copy()
holders = S[S["units"] > 0]

# ------------------------------------------------------------------ actions + fund strip
b = st.columns([1.2, 1.2, 1.2, 4])
if b[0].button("Add investor", type="primary", icon=":material/person_add:", width="stretch"):
    dialogs.investor_dialog()
if b[1].button("Add money", icon=":material/add:", width="stretch"):
    dialogs.funds_dialog(st.session_state.get("sel_inv"), "DEPOSIT")
if b[2].button("Withdraw", icon=":material/remove:", width="stretch", disabled=c.flows.empty):
    dialogs.funds_dialog(st.session_state.get("sel_inv"), "WITHDRAWAL")

m = st.columns(5)
m[0].metric("Investors", f"{len(holders)}", delta=f"{len(S)} accounts in all", delta_color="off")
m[1].metric("NAV per unit", f"₹{c.nav:,.4f}", delta=pct((c.nav / c.face - 1) * 100) + " since start")
m[2].metric("Units outstanding", f"{c.units:,.4f}")
m[3].metric("Fund value", inr(c.total))
m[4].metric("Net money invested", inr(c.net_capital), delta=f"{inr(c.total - c.net_capital, sign=True)} gain",
            delta_color="normal")

# ------------------------------------------------------------------ table
view = st.segmented_control("Show", ["Active", "All"], default="Active", key="inv_view",
                            label_visibility="collapsed") or "Active"
v = (S[(S["units"] > 0) | (S["n_flows"] == 0)] if view == "Active" else S)
v = v.sort_values(["value", "deposits", "name"], ascending=[False, False, True]).reset_index(drop=True)
tbl = v[["name", "relation", "units", "share_pct", "avg_nav", "net_invested", "value", "gain", "ret_pct", "xirr",
         "first_date", "status"]].copy()
tbl["xirr"] = tbl["xirr"] * 100
tbl.columns = ["Investor", "Relation", "Units", "Share %", "Avg buy NAV", "Net invested", "Value", "Gain ₹",
               "Return %", "XIRR %", "Since", "Status"]
ev = st.dataframe(
    style_table(tbl, money=["Net invested", "Value", "Gain ₹"], pcts=["Return %", "XIRR %"], dates=["Since"],
                pnl_cols=["Gain ₹", "Return %", "XIRR %"],
                custom={"Units": lambda x: f"{x:,.4f}", "Share %": lambda x: f"{x:.2f}%",
                        "Avg buy NAV": lambda x: "—" if pd.isna(x) else f"₹{x:,.4f}"}),
    hide_index=True, width="stretch", on_select="rerun", selection_mode="single-row",
    height=min(36 * len(tbl) + 40, 420), key=f"inv_tbl_{view}")
st.download_button("Export investors (CSV)", tbl.to_csv(index=False), file_name="investors.csv",
                   icon=":material/download:", type="tertiary")

rows = ev.selection.rows if ev and ev.selection else []
if rows:
    st.session_state["sel_inv"] = int(v.iloc[rows[0]]["id"])
sel = st.session_state.get("sel_inv")
if sel is None or sel not in set(S["id"]):
    st.caption("👆 Select an investor to open their account.")
    st.stop()

# ------------------------------------------------------------------ account detail
p = S[S["id"] == sel].iloc[0].to_dict()
stmt = nav.statement(c.flows, sel)

st.divider()
h1, h2 = st.columns([3, 3])
with h1:
    badge = {"Active": "🟢 Active", "Exited": "⚪ Exited"}.get(p["status"], "🟡 No capital yet")
    tag = " · Manager" if p["is_manager"] else ""
    st.markdown(f"### {p['name']} <span style='font-size:0.9rem;opacity:.7'>· {p['relation'] or 'Investor'}{tag} · "
                f"{badge}</span>", unsafe_allow_html=True)
    bits = [f"Investor since {p['first_date']:%d %b %Y}" if p["first_date"] else "No money recorded yet"]
    if p["contact"]:
        bits.append(p["contact"])
    st.caption(" · ".join(bits))
with h2:
    a = st.columns(4)
    if a[0].button("Add money", icon=":material/add:", width="stretch", key="acc_dep", type="primary"):
        dialogs.funds_dialog(sel, "DEPOSIT")
    if a[1].button("Withdraw", icon=":material/remove:", width="stretch", key="acc_wd", disabled=p["units"] <= 0):
        dialogs.funds_dialog(sel, "WITHDRAWAL")
    if a[2].button("Edit", icon=":material/edit:", width="stretch", key="acc_edit"):
        dialogs.investor_dialog(p)
    if a[3].button("Remove", icon=":material/delete:", width="stretch", key="acc_del"):
        dialogs.delete_investor_dialog(p)

k = st.columns(6)
k[0].metric("Units held", f"{p['units']:,.4f}", delta=f"{p['share_pct']:.2f}% of fund", delta_color="off")
k[1].metric("Current value", inr(p["value"]), delta=f"NAV ₹{c.nav:,.4f}", delta_color="off")
k[2].metric("Money put in", inr(p["deposits"]),
            delta=f"avg NAV ₹{p['avg_nav']:,.4f}" if p["avg_nav"] else None, delta_color="off")
k[3].metric("Money taken out", inr(p["withdrawals"]))
k[4].metric("Gain", inr(p["gain"], sign=True), delta=pct(p["ret_pct"]) if p["ret_pct"] is not None else None,
            help="Current value + money taken out − money put in")
k[5].metric("XIRR", pct(p["xirr"] * 100 if p["xirr"] is not None else None),
            help="This person's own annualised return, using the dates of their deposits and withdrawals")
if p["withdrawals"]:
    st.caption(f"Of the gain, {inr(p['realized'], sign=True)} is realized on units already redeemed and "
               f"{inr(p['unreal'], sign=True)} is on the units still held.")

if stmt.empty:
    st.info("No money recorded for this investor yet. Use **Add money** to issue their first units.",
            icon=":material/account_balance_wallet:")
    st.stop()

tab_st, tab_val, tab_notes = st.tabs(["🧾 Statement", "📈 Value over time", "📝 Notes"])

with tab_st:
    show = stmt[["date", "kind", "signed_amount", "nav", "signed_units", "balance", "note"]].copy()
    show["kind"] = show["kind"].map({"DEPOSIT": "Deposit", "WITHDRAWAL": "Withdrawal"})
    show["worth"] = show["balance"] * c.nav
    show.loc[stmt["nav_manual"].values, "note"] = "🔒 " + show.loc[stmt["nav_manual"].values, "note"].fillna("")
    show.columns = ["Date", "Type", "Amount", "NAV", "Units", "Unit balance", "Note", "Balance at today's NAV"]
    show = show[["Date", "Type", "Amount", "NAV", "Units", "Unit balance", "Balance at today's NAV", "Note"]]
    st.dataframe(
        style_table(show, money2=["Amount"], money=["Balance at today's NAV"], dates=["Date"],
                    pnl_cols=["Amount", "Units"],
                    custom={"NAV": lambda x: f"₹{x:,.4f}", "Units": lambda x: f"{x:+,.4f}",
                            "Unit balance": lambda x: f"{x:,.4f}"}),
        hide_index=True, width="stretch")
    st.caption("🔒 = NAV entered manually (locked). Units carry 4 decimals, like a mutual-fund statement.")
    x1, x2, x3 = st.columns([3, 1.2, 1.4])
    labels = {int(r.id): f"{r.date:%d %b %Y} · {'Deposit' if r.kind == 'DEPOSIT' else 'Withdrawal'} "
                         f"{inr(r.amount, 2)} @ ₹{r.nav:,.4f}" for r in stmt.itertuples()}
    fid = x1.selectbox("Entry", list(labels), format_func=labels.get, index=None, key="inv_entry",
                       placeholder="Choose an entry to delete…", label_visibility="collapsed")
    if x2.button("Delete entry", icon=":material/delete:", width="stretch", disabled=fid is None, key="inv_entry_del"):
        dialogs.delete_flow_dialog(stmt[stmt["id"] == fid].iloc[0].to_dict())
    csv = show.assign(Date=[d.isoformat() for d in show["Date"]]).to_csv(index=False)
    x3.download_button("Statement (CSV)", csv, icon=":material/download:", width="stretch",
                       file_name=f"statement_{p['name'].replace(' ', '_')}_{dt.date.today():%Y%m%d}.csv")

with tab_val:
    hist = nav.investor_history(state.daily_for(c), c.flows, sel)
    if hist.empty or len(hist) < 2:
        st.caption("The chart appears once there are a couple of days of history.")
    else:
        with card("inv_value"):
            card_title("Value of units vs net money invested")
            st.plotly_chart(charts.investor_value(hist), width="stretch", config={"displayModeBar": False})

with tab_notes:
    st.write(p["notes"] or "_No notes. Use **Edit** to add some._")
