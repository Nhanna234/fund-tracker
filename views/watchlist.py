import datetime as dt

import pandas as pd
import streamlit as st

from core import charts, db, ledger, prices, state
from core.config import EXCHANGES
from core.ui import empty_state, inr, page_header, pct, style_table

c = state.ctx()
page_header("Watchlist", "Stocks you're tracking but haven't bought. Set a trigger to get an alert on the dashboard.")

with st.expander("Add to watchlist", icon=":material/add:", expanded=c.watch.empty):
    a, b, d, e = st.columns([2, 1, 1.2, 1])
    sym = a.text_input("Symbol", key="w_sym", placeholder="e.g. TITAN").strip().upper()
    exch = b.selectbox("Exchange", EXCHANGES, key="w_exch")
    trig = d.number_input("Trigger price (₹)", min_value=0.0, value=None, step=0.5, format="%.2f", key="w_trig")
    tdir = e.selectbox("Alert when price is", ["below", "above"], key="w_dir")
    thesis = st.text_area("Why are you watching it?", key="w_thesis", height=80)
    tags = st.text_input("Tags (comma separated)", key="w_tags", placeholder="breakout, capex, results")
    if st.button("Add", type="primary", disabled=not sym, key="w_add"):
        tk = ledger.ticker_for(sym, exch)
        info = prices.lookup_info(tk)
        q = prices.get_quotes(c.engine, [tk]).get(tk, {})
        db.add_watch(c.engine, c.owner, symbol=sym, exchange=exch, name=info.get("name", sym),
                     added_on=dt.date.today(), price_added=q.get("price") or info.get("price"),
                     trigger_price=trig, trigger_dir=tdir, thesis=thesis, tags=tags)
        state.bump()
        for k in ("w_sym", "w_trig", "w_thesis", "w_tags"):
            st.session_state.pop(k, None)
        st.session_state["flash"] = f"{sym} added to watchlist."
        st.rerun()

if c.watch.empty:
    empty_state("Your watchlist is empty.")
    st.stop()

rows = []
for w in c.watch.itertuples(index=False):
    tk = ledger.ticker_for(w.symbol, w.exchange)
    q = c.quotes.get(tk, {})
    px = q.get("price")
    trig = None if (w.trigger_price is None or pd.isna(w.trigger_price)) else w.trigger_price
    rows.append({"id": w.id, "Stock": w.symbol, "Name": w.name, "CMP": px,
                 "Day %": (px / q["prev_close"] - 1) * 100 if (px and q.get("prev_close")) else None,
                 "Added": w.added_on, "Price added": w.price_added,
                 "Since added %": (px / w.price_added - 1) * 100 if (px and w.price_added) else None,
                 "Trigger": trig, "Dir": w.trigger_dir,
                 "To trigger %": (trig / px - 1) * 100 if (px and trig) else None,
                 "Hit": ("✅" if (px and trig and ((px <= trig) if w.trigger_dir == "below" else (px >= trig))) else ""),
                 "Tags": w.tags})
W = pd.DataFrame(rows)
ev = st.dataframe(style_table(W.drop(columns=["id"]), money2=["CMP", "Price added", "Trigger"],
                              pcts=["Day %", "Since added %", "To trigger %"], dates=["Added"],
                              pnl_cols=["Day %", "Since added %"]),
                  hide_index=True, width="stretch", on_select="rerun", selection_mode="single-row", key="w_tbl")
sel_rows = ev.selection.rows if ev and ev.selection else []
if not sel_rows:
    st.caption("👆 Select a stock to see its chart, edit, buy or remove it.")
    st.stop()

wid = int(W.iloc[sel_rows[0]]["id"])
w = c.watch[c.watch["id"] == wid].iloc[0].to_dict()
r = W[W["id"] == wid].iloc[0]
st.divider()
h1, h2 = st.columns([3, 2])
h1.markdown(f"### {w['symbol']} <span style='font-size:.9rem;opacity:.7'>· {w['name']}</span>", unsafe_allow_html=True)
if w.get("thesis"):
    h1.info(w["thesis"], icon=":material/lightbulb:")
b = h2.columns(3)
if b[0].button("Buy", type="primary", icon=":material/shopping_cart:", width="stretch"):
    st.session_state["prefill"] = {"symbol": w["symbol"], "exchange": w["exchange"], "name": w["name"],
                                   **({"price": float(r["CMP"])} if pd.notna(r["CMP"]) else {}),
                                   "thesis": w.get("thesis") or ""}
    st.switch_page("views/new_position.py")
with b[1].popover("Edit", icon=":material/edit:", width="stretch"):
    nt = st.number_input("Trigger (₹)", min_value=0.0, value=float(w["trigger_price"]) if pd.notna(w["trigger_price"]) else None,
                         format="%.2f", key="we_trig")
    nd = st.selectbox("Direction", ["below", "above"], index=0 if w["trigger_dir"] != "above" else 1, key="we_dir")
    nth = st.text_area("Thesis", value=w.get("thesis") or "", key="we_th")
    ntg = st.text_input("Tags", value=w.get("tags") or "", key="we_tags")
    if st.button("Save", type="primary", key="we_save"):
        db.update_watch(c.engine, c.owner, wid, trigger_price=nt, trigger_dir=nd, thesis=nth, tags=ntg)
        state.bump()
        st.rerun()
with b[2].popover("Remove", icon=":material/delete:", width="stretch"):
    st.write(f"Remove **{w['symbol']}** from the watchlist?")
    if st.button("Yes, remove", type="primary", key="we_del"):
        db.delete_watch(c.engine, c.owner, wid)
        state.bump()
        st.rerun()

ohlc = prices.get_monthly_ohlc(ledger.ticker_for(w["symbol"], w["exchange"]))
if ohlc.empty:
    st.info("Chart data unavailable right now.")
else:
    st.plotly_chart(charts.candlestick(ohlc, f"{w['symbol']} — monthly",
                                       trigger=w["trigger_price"] if pd.notna(w["trigger_price"]) else None),
                    width="stretch", config={"displayModeBar": False})
