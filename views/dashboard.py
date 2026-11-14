import datetime as dt

import pandas as pd
import streamlit as st

from core import analytics as an
from core import charts, db, dialogs, nav, state
from core.config import BENCHMARK_NAME, DEFAULT_FUND_NAME
from core.ui import page_link, alert_rows, card, card_title, compact, inr, page_header, pct, style_table

c = state.ctx()
_live = {"live": ("#22c55e", "Live prices"), "partial": ("#f59e0b", "Partly cached prices"),
         "cache": ("#f97316", "Cached prices"), "none": ("#94a3b8", "No prices yet")}[c.price_status]
page_header(c.fund_name, "NAV, fund value, who owns what, and how the holdings are doing.", eyebrow="Fund overview",
            chip=f"<span class='pt-dot' style='background:{_live[0]}'></span>{_live[1]} · {dt.date.today():%a, %d %b %Y}")

# ------------------------------------------------------------------ first run: set up the fund
if c.investors.empty:
    with card("setup"):
        card_title("Set up your fund", "takes a minute")
        st.caption("Start with your own capital. You get units at the face value; everyone who joins later buys "
                   "units at the NAV of the day they put money in, so each person's gains are tracked fairly.")
        with st.form("setup_form", border=False):
            a, b = st.columns(2)
            fund_name = a.text_input("Fund name", value=DEFAULT_FUND_NAME, max_chars=60)
            my_name = b.text_input("Your name (the manager)", placeholder="e.g. Abdullah", max_chars=120)
            a, b, d = st.columns(3)
            amount = a.number_input("Your starting capital (₹)", min_value=0.0, value=1000000.0, step=50000.0,
                                    format="%.2f")
            start = b.date_input("Start date", value=dt.date.today(), max_value=dt.date.today(), format="DD/MM/YYYY")
            face = d.number_input("Face value per unit (₹)", min_value=1.0, value=nav.FACE_VALUE, step=1.0,
                                  format="%.2f", help="The NAV on day one. ₹10 is the usual convention.")
            go = st.form_submit_button("Create fund", type="primary", icon=":material/rocket_launch:")
        if go:
            if not my_name.strip() or amount <= 0:
                st.error("Enter your name and a starting capital above zero.", icon=":material/block:")
            else:
                db.set_setting(c.engine, c.owner, "fund_name", fund_name.strip() or DEFAULT_FUND_NAME)
                db.set_setting(c.engine, c.owner, "face_value", face)
                iid = db.add_investor(c.engine, c.owner, name=my_name.strip(), relation="Self", is_manager=True)
                db.add_flow(c.engine, c.owner, iid, start, "DEPOSIT", amount, face, nav.units_for(amount, face),
                            note="Starting capital")
                state.bump()
                st.session_state["flash"] = (f"{fund_name.strip() or DEFAULT_FUND_NAME} created: "
                                             f"{nav.units_for(amount, face):,.4f} units at ₹{face:g}.")
                st.rerun()
    page_link("views/settings.py", "Or load a sample fund to explore (Fund & settings)", ":material/science:")
    st.stop()

if c.flows.empty:
    with card("nocap"):
        st.info("No money has been recorded yet. Record the first deposit to issue units at face value.",
                icon=":material/account_balance_wallet:")
        if st.button("Record first deposit", type="primary", icon=":material/add:"):
            dialogs.funds_dialog(int(c.investors.sort_values("is_manager", ascending=False)["id"].iloc[0]))
    st.stop()

act = c.active
unreal = act["unreal"].sum() if not act.empty else 0.0
invested = act["invested"].sum() if not act.empty else 0.0
realized = c.summary["realized"].sum() + c.summary["dividends"].sum() if not c.summary.empty else 0.0
prev_val = c.total - c.day
total_ret = c.total - c.net_capital
day_pct = c.day / prev_val * 100 if prev_val else 0.0

daily = state.daily_for(c)
x = an.portfolio_xirr(c.flows, c.total)
nav_ret = c.nav / c.face - 1
bench_ret = daily["bench"].iloc[-1] - 1 if ("bench" in daily and not daily.empty) else None
holders = c.inv_summary[c.inv_summary["units"] > 0] if not c.inv_summary.empty else c.inv_summary

# ------------------------------------------------------------------ KPI tiles
r1 = st.columns(4)
r1[0].metric("Fund value", inr(c.total), delta=f"{inr(c.day, sign=True)} ({pct(day_pct)}) today", border=True,
             help="Cash + market value of everything the fund holds")
r1[1].metric("NAV per unit", f"₹{c.nav:,.4f}", delta=f"{pct(day_pct)} today", border=True,
             help=f"Fund value ÷ units outstanding. Started at the face value of ₹{c.face:g}.")
r1[2].metric("Units outstanding", f"{c.units:,.2f}", delta=f"{len(holders)} investor{'s' if len(holders) != 1 else ''}",
             delta_color="off", border=True)
r1[3].metric("Cash available", inr(c.cash), delta=f"{pct(c.cash_pct, 1, sign=False)} of fund", delta_color="off",
             border=True)

r2 = st.columns(4)
r2[0].metric("Unrealized P&L", inr(unreal, sign=True), delta=pct(unreal / invested * 100 if invested else 0),
             border=True, help=f"On {inr(invested)} invested in {len(act)} active holdings")
r2[1].metric("Realized P&L", inr(realized, sign=True), delta="net of charges, incl. dividends", delta_color="off",
             border=True)
r2[2].metric("Total gain", inr(total_ret, sign=True),
             delta=(f"XIRR {pct(x * 100)} p.a." if x is not None else f"on {compact(c.net_capital)} net capital"),
             delta_color="normal" if x is not None else "off", border=True,
             help=f"Fund value minus the net money investors have put in ({inr(c.net_capital)}). XIRR is the "
                  "money-weighted annual return across everyone's deposits and withdrawals.")
r2[3].metric("NAV since start", pct(nav_ret * 100),
             delta=(f"{(nav_ret - bench_ret) * 100:+.2f} pts vs {BENCHMARK_NAME}" if bench_ret is not None else None),
             border=True, help="Growth of one unit since day one. Deposits and withdrawals do not affect it, so "
                               "it is your true stock-picking record.")

# ------------------------------------------------------------------ alerts
al = an.alerts(c.summary, c.total, c.settings, c.watch, c.quotes)
try:
    n_drift = int(state.audit_for(c)["drift"].sum())
except Exception:
    n_drift = 0
if n_drift:
    al.insert(0, ("audit", "Units", f"{n_drift} investor entr{'y' if n_drift == 1 else 'ies'} no longer match the "
                                    "recomputed NAV. Review in Fund & settings → NAV audit."))
with st.expander(f"**Action alerts ({len(al)})**", expanded=bool(al), icon=":material/notifications:"):
    if not al:
        st.caption("Nothing needs your attention right now.")
    if al:
        st.html(alert_rows(al))

# ------------------------------------------------------------------ NAV curve + who owns the fund
left, right = st.columns([3, 2], gap="medium")
with left:
    with card("dashboard_1"):
        card_title("NAV per unit", f"vs {BENCHMARK_NAME} rebased · markers show money in / out")
        if daily.empty:
            st.caption("No history yet.")
        else:
            rng = st.segmented_control("Range", ["1M", "3M", "6M", "1Y", "All"], default="All",
                                       key="dash_rng", label_visibility="collapsed")
            days = {"1M": 31, "3M": 92, "6M": 183, "1Y": 366}.get(rng or "All")
            d = daily if not days else daily[daily.index >= pd.Timestamp(dt.date.today() - dt.timedelta(days=days))]
            if d.empty:
                d = daily
            st.plotly_chart(charts.nav_vs_bench(d, c.flows, dict(zip(c.investors["id"], c.investors["name"]))),
                            width="stretch", config={"displayModeBar": False})

with right:
    with card("dashboard_2"):
        card_title("Allocation")
        tabs = st.tabs(["Investors", "Stocks", "Sector", "Strategy", "Market cap"])
        with tabs[0]:
            if holders.empty:
                st.caption("No units outstanding.")
            else:
                s = charts.fold(holders.set_index("name")["value"], 7)
                st.plotly_chart(charts.donut(list(s.index), list(s.values), height=290), width="stretch",
                                config={"displayModeBar": False}, key="donut_inv")
        base = act[["symbol", "sector", "strategy", "mcap", "value"]] if not act.empty else pd.DataFrame(
            columns=["symbol", "sector", "strategy", "mcap", "value"])
        for tab, col in zip(tabs[1:], ["symbol", "sector", "strategy", "mcap"]):
            with tab:
                s = base.groupby(col)["value"].sum()
                s = charts.fold(s, 7)
                if c.cash > 0:
                    s = pd.concat([s, pd.Series({"Cash": c.cash})])
                if s.sum() <= 0:
                    st.caption("No holdings.")
                    continue
                fixed = charts.MCAP_COLORS if col == "mcap" else None
                st.plotly_chart(charts.donut(list(s.index), list(s.values), fixed=fixed, height=290),
                                width="stretch", config={"displayModeBar": False}, key=f"donut_{col}")

# ------------------------------------------------------------------ investors at a glance
with card("dashboard_inv"):
    card_title("Investors", "units × NAV = what each person's share is worth today")
    iv = c.inv_summary.sort_values(["value", "deposits"], ascending=False)
    tbl = iv[["name", "units", "share_pct", "net_invested", "value", "gain", "ret_pct", "xirr"]].copy()
    tbl["xirr"] = tbl["xirr"] * 100
    tbl.columns = ["Investor", "Units", "Share %", "Net invested", "Value", "Gain ₹", "Return %", "XIRR %"]
    st.dataframe(style_table(tbl, money=["Net invested", "Value", "Gain ₹"], pcts=["Return %", "XIRR %"],
                             pnl_cols=["Gain ₹", "Return %", "XIRR %"],
                             custom={"Units": lambda v: f"{v:,.4f}", "Share %": lambda v: f"{v:.2f}%"}),
                 hide_index=True, width="stretch", height=min(36 * len(tbl) + 40, 330))
    page_link("views/investors.py", "Open investor accounts", ":material/arrow_forward:")

# ------------------------------------------------------------------ movers & top holdings
if not act.empty:
    a, b = st.columns(2, gap="medium")
    with a:
        with card("dashboard_3"):
            card_title("Today's movers")
            mv = act[["symbol", "cmp", "day_chg_pct", "day_chg"]].sort_values("day_chg_pct", ascending=False)
            mv.columns = ["Stock", "CMP", "Day %", "Day ₹"]
            st.dataframe(style_table(mv, money2=["CMP"], money=["Day ₹"], pcts=["Day %"], pnl_cols=["Day %", "Day ₹"]),
                         hide_index=True, width="stretch", height=min(38 * len(mv) + 40, 320))
    with b:
        with card("dashboard_4"):
            card_title("Biggest unrealized P&L")
            tp = act.reindex(act["unreal"].abs().sort_values(ascending=False).index).head(8)
            st.plotly_chart(charts.hbar_signed(list(tp["symbol"]), list(tp["unreal"]),
                                               text=[pct(v, 1) for v in tp["unreal_pct"]]),
                            width="stretch", config={"displayModeBar": False})
