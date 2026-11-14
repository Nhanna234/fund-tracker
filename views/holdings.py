import pandas as pd
import streamlit as st

from core import charts, db, dialogs, ledger, prices, state
from core.ui import card, compact, empty_state, inr, page_header, pct, style_table

c = state.ctx()
page_header("Holdings", "Select a row to see its chart, trades and thesis — and to add-on, exit, edit or delete.")

if c.summary.empty:
    empty_state("No positions yet.", "views/new_position.py", "Add your first position")
    st.stop()

S = c.summary.copy()

# ------------------------------------------------------------------ filters
f1, f2, f3, f4, f5 = st.columns([1.3, 1.6, 1.4, 1.4, 1])
view = f1.segmented_control("Show", ["Active", "Closed", "All"], default="Active", key="h_view") or "Active"
q = f2.text_input("Search", placeholder="Symbol or name…", key="h_q", label_visibility="visible")
sectors = f3.multiselect("Sector", sorted(S["sector"].unique()), key="h_sec")
strategies = f4.multiselect("Strategy", sorted(S["strategy"].unique()), key="h_stg")
pl = f5.selectbox("P&L", ["All", "Profit", "Loss"], key="h_pl")

v = S if view == "All" else S[S["status"] == view]
if q:
    v = v[v["symbol"].str.contains(q, case=False) | v["name"].str.contains(q, case=False)]
if sectors:
    v = v[v["sector"].isin(sectors)]
if strategies:
    v = v[v["strategy"].isin(strategies)]
if pl != "All":
    v = v[(v["total_pnl"] > 0) if pl == "Profit" else (v["total_pnl"] <= 0)]

# ------------------------------------------------------------------ summary strip
m = st.columns(5)
m[0].metric("Positions", len(v))
if view == "Closed":
    m[1].metric("Realized P&L", inr(v["total_pnl"].sum(), sign=True))
    m[2].metric("Win rate", pct((v["total_pnl"] > 0).mean() * 100 if len(v) else None, 0, sign=False))
    m[3].metric("Avg return", pct(v["ret_pct"].mean() if len(v) else None))
    m[4].metric("Avg holding", f"{v['holding_days'].mean():.0f} d" if len(v) else "—")
else:
    m[1].metric("Market value", compact(v["value"].sum()))
    m[2].metric("Invested", compact(v["invested"].sum()))
    m[3].metric("Unrealized", inr(v["unreal"].sum(), sign=True),
                delta=pct(v["unreal"].sum() / v["invested"].sum() * 100 if v["invested"].sum() else 0))
    m[4].metric("Realized (incl. div)", inr((v["realized"] + v["dividends"]).sum(), sign=True))

# ------------------------------------------------------------------ table
if view == "Active":
    cols = {"symbol": "Stock", "name": "Name", "qty": "Qty", "avg_cost": "Avg cost", "cmp": "CMP",
            "invested": "Invested", "value": "Value", "unreal": "Unreal ₹", "unreal_pct": "Unreal %",
            "day_chg_pct": "Day %", "weight": "Weight %", "stop_loss": "SL", "sl_dist_pct": "To SL %",
            "strategy": "Strategy", "sector": "Sector", "holding_days": "Days"}
elif view == "Closed":
    cols = {"symbol": "Stock", "name": "Name", "wavg_buy": "Avg buy", "avg_sell": "Avg sell",
            "total_bought": "Bought ₹", "total_pnl": "P&L ₹", "ret_pct": "Return %", "first_buy": "Entry",
            "exit_date": "Exit", "holding_days": "Days", "r_multiple": "R", "strategy": "Strategy", "sector": "Sector"}
else:
    cols = {"symbol": "Stock", "status": "Status", "qty": "Qty", "avg_cost": "Avg cost", "cmp": "CMP",
            "value": "Value", "unreal": "Unreal ₹", "realized": "Realized ₹", "dividends": "Div ₹",
            "total_pnl": "Total P&L ₹", "ret_pct": "Return %", "strategy": "Strategy", "first_buy": "Entry"}
v = v.sort_values("value" if view != "Closed" else "exit_date", ascending=False).reset_index(drop=True)
tbl = v[list(cols)].rename(columns=cols)
if "R" in tbl:
    tbl["R"] = tbl["R"].round(2)
sty = style_table(tbl, money=["Invested", "Value", "Unreal ₹", "Realized ₹", "Div ₹", "Total P&L ₹", "P&L ₹", "Bought ₹"],
                  money2=["Avg cost", "CMP", "SL", "Avg buy", "Avg sell"],
                  pcts=["Unreal %", "Day %", "Return %", "To SL %"], nums=["Qty", "Days"], dates=["Entry", "Exit"],
                  pnl_cols=["Unreal ₹", "Unreal %", "Day %", "Total P&L ₹", "P&L ₹", "Return %", "Realized ₹"],
                  custom={"Weight %": lambda x: f"{x:.1f}%", "R": lambda x: "—" if pd.isna(x) else f"{x:.2f}R"})
ev = st.dataframe(sty, hide_index=True, width="stretch", on_select="rerun", selection_mode="single-row",
                  height=min(36 * len(tbl) + 40, 460), key=f"h_tbl_{view}")
st.download_button("Export view (CSV)", tbl.to_csv(index=False), file_name=f"holdings_{view.lower()}.csv",
                   icon=":material/download:", type="tertiary")

rows = ev.selection.rows if ev and ev.selection else []
if rows:
    st.session_state["sel_pos"] = int(v.iloc[rows[0]]["id"])
sel = st.session_state.get("sel_pos")
if sel is None or sel not in set(S["id"]):
    st.caption("👆 Select a row to open the position.")
    st.stop()

# ------------------------------------------------------------------ detail
p = S[S["id"] == sel].iloc[0].to_dict()
raw = c.positions[c.positions["id"] == sel].iloc[0].to_dict()
p.update({k: raw[k] for k in ("cmp_override", "notes", "exchange")})
pt = ledger.sort_txns(c.txns[c.txns["position_id"] == sel])

st.divider()
h1, h2 = st.columns([3, 2])
with h1:
    badge = "🟢 Active" if p["status"] == "Active" else "⚪ Closed"
    st.markdown(f"### {p['symbol']} <span style='font-size:0.9rem;opacity:.7'>· {p['name']} · {p['exchange']} · {badge}</span>",
                unsafe_allow_html=True)
    st.caption(f"{p['sector']} · {p['mcap']} cap · {p['strategy']} · Conviction {'★' * int(p['conviction'] or 0)}"
               f" · CMP source: {p['cmp_source']}")
with h2:
    b = st.columns(3)
    if b[0].button("Add-on", icon=":material/add_shopping_cart:", width="stretch", key="act_buy"):
        dialogs.trade_dialog(p, "BUY")
    if b[1].button("Exit", icon=":material/sell:", width="stretch", key="act_sell", disabled=p["status"] != "Active"):
        dialogs.trade_dialog(p, "SELL")
    if b[2].button("Dividend", icon=":material/payments:", width="stretch", key="act_div"):
        dialogs.dividend_dialog(p)
    b = st.columns(3)
    if b[0].button("Edit", icon=":material/edit:", width="stretch", key="act_edit"):
        dialogs.edit_position_dialog(p)
    if b[1].button("Thesis note", icon=":material/edit_note:", width="stretch", key="act_note"):
        dialogs.thesis_dialog(p)
    if b[2].button("Delete", icon=":material/delete:", width="stretch", key="act_del"):
        dialogs.delete_position_dialog(p)

k = st.columns(6)
if p["status"] == "Active":
    k[0].metric("Qty · Avg cost", f"{p['qty']:g} · {inr(p['avg_cost'], 2)}")
    k[1].metric("CMP", inr(p["cmp"], 2), delta=pct(p["day_chg_pct"]) if p["prev_close"] else None)
    k[2].metric("Value", inr(p["value"]), delta=f"{p.get('weight', 0):.1f}% of portfolio", delta_color="off")
    k[3].metric("Unrealized", inr(p["unreal"], sign=True), delta=pct(p["unreal_pct"]))
else:
    k[0].metric("Avg buy → sell", f"{inr(p['wavg_buy'], 2)} → {inr(p['avg_sell'], 2)}")
    k[1].metric("Bought", inr(p["total_bought"]))
    k[2].metric("Exit date", f"{p['exit_date']:%d %b %Y}" if p["exit_date"] else "—")
    k[3].metric("Return", pct(p["ret_pct"]))
k[4].metric("Realized + div", inr(p["realized"] + p["dividends"], sign=True), delta=f"charges {inr(p['charges'])}",
            delta_color="off")
k[5].metric("Total P&L", inr(p["total_pnl"], sign=True), delta=f"{p['holding_days']} days held", delta_color="off")

if p["status"] == "Active" and (p["stop_loss"] or p["target1"]):
    parts = []
    if p["stop_loss"]:
        parts.append(f"SL {inr(p['stop_loss'], 2)} ({pct(-p['sl_dist_pct'])} away, risk {inr(p['risk_to_sl'])})")
    for t in ("target1", "target2"):
        if p[t] and not pd.isna(p[t]):
            parts.append(f"{'T1' if t == 'target1' else 'T2'} {inr(p[t], 2)} ({pct((p[t] / p['cmp'] - 1) * 100)} away)")
    if p["stop_loss"] and p["target1"] and p["cmp"] > p["stop_loss"]:
        parts.append(f"Reward:Risk {(p['target1'] - p['cmp']) / (p['cmp'] - p['stop_loss']):.2f}")
    st.caption(" · ".join(parts))

tab_chart, tab_tx, tab_th, tab_lots = st.tabs(["📊 Monthly chart", "🧾 Transactions", "💡 Thesis log", "📦 FIFO lots"])

with tab_chart:
    ohlc = prices.get_monthly_ohlc(p["ticker"])
    if ohlc.empty:
        st.info("Chart data unavailable from Yahoo for this symbol right now.")
    else:
        st.plotly_chart(charts.candlestick(ohlc, f"{p['symbol']} — monthly", pt,
                                           avg_cost=p["avg_cost"] if p["status"] == "Active" else None,
                                           stop_loss=p["stop_loss"] if p["status"] == "Active" else None,
                                           target1=p["target1"] if p["status"] == "Active" else None,
                                           target2=p["target2"] if p["status"] == "Active" else None),
                        width="stretch", config={"displayModeBar": False})

with tab_tx:
    t = pt.copy()
    t["amount"] = t["qty"] * t["price"]
    show = t[["date", "kind", "qty", "price", "amount", "charges", "reason"]].rename(columns={
        "date": "Date", "kind": "Type", "qty": "Qty", "price": "Price", "amount": "Amount", "charges": "Charges",
        "reason": "Reason"})
    st.dataframe(style_table(show, money=["Amount"], money2=["Price", "Charges"], nums=["Qty"], dates=["Date"]),
                 hide_index=True, width="stretch")
    labels = {int(r.id): f"{r.date:%d %b %Y} · {r.kind} {r.qty:g} @ {inr(r.price, 2)}" for r in t.itertuples()}
    tc1, tc2, tc3 = st.columns([3, 1, 1])
    tid = tc1.selectbox("Transaction", list(labels), format_func=labels.get, key="tx_pick", label_visibility="collapsed")
    txn = t[t["id"] == tid].iloc[0].to_dict() if tid is not None else None
    if tc2.button("Edit", icon=":material/edit:", width="stretch", key="tx_edit", disabled=txn is None):
        dialogs.edit_txn_dialog(txn, p)
    if tc3.button("Delete", icon=":material/delete:", width="stretch", key="tx_del", disabled=txn is None):
        dialogs.delete_txn_dialog(txn, p)

with tab_th:
    th = c.thesis[c.thesis["position_id"] == sel].sort_values("date", ascending=False) if not c.thesis.empty else c.thesis
    reasons = pt[pt["reason"].fillna("").str.strip() != ""]
    if th.empty and reasons.empty and not (p.get("notes") or "").strip():
        st.caption("No thesis notes yet. Use **Thesis note** to record why you hold this.")
    if (p.get("notes") or "").strip():
        st.info(p["notes"], icon=":material/sticky_note_2:")
    for r in th.itertuples():
        with card(f"th_{r.id}"):
            x1, x2 = st.columns([12, 1])
            x1.markdown(f"**{r.date:%d %b %Y}**  \n{r.text}")
            if x2.button("", icon=":material/delete:", key=f"thdel_{r.id}", help="Delete note", type="tertiary"):
                db.delete_thesis(c.engine, c.owner, int(r.id))
                state.bump()
                st.rerun()
    if not reasons.empty:
        st.markdown("**Trade reasons**")
        for r in reasons.itertuples():
            st.markdown(f"- *{r.date:%d %b %Y} · {r.kind} {r.qty:g} @ {inr(r.price, 2)}* — {r.reason}")

with tab_lots:
    f = ledger.fifo(pt)
    if f["open_lots"]:
        st.markdown("**Open lots**")
        ol = pd.DataFrame(f["open_lots"])[["date", "qty", "price"]]
        ol["value"] = ol["qty"] * p["cmp"]
        ol["pnl"] = ol["qty"] * (p["cmp"] - ol["price"])
        ol["days"] = (pd.Timestamp.today().normalize() - pd.to_datetime(ol["date"])).dt.days
        ol.columns = ["Bought", "Qty", "Price", "Value", "Unreal ₹", "Days"]
        st.dataframe(style_table(ol, money=["Value", "Unreal ₹"], money2=["Price"], nums=["Qty", "Days"],
                                 dates=["Bought"], pnl_cols=["Unreal ₹"]), hide_index=True, width="stretch")
    if f["realized_lots"]:
        st.markdown("**Realized lots (FIFO)**")
        rl = pd.DataFrame(f["realized_lots"])[["buy_date", "sell_date", "qty", "buy_price", "sell_price", "charges", "pnl", "days"]]
        rl.columns = ["Bought", "Sold", "Qty", "Buy", "Sell", "Charges", "P&L ₹", "Days"]
        st.dataframe(style_table(rl, money=["P&L ₹"], money2=["Buy", "Sell", "Charges"], nums=["Qty", "Days"],
                                 dates=["Bought", "Sold"], pnl_cols=["P&L ₹"]), hide_index=True, width="stretch")
