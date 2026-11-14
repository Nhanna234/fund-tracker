import datetime as dt

import streamlit as st

from core import db, dialogs, ledger, prices, state
from core.config import EXCHANGES
from core.ui import page_link, card, inr, page_header

c = state.ctx()
page_header("New position", "Record a fresh buy. For a 2nd buy in a stock you already hold, use **Add-on** in Holdings.")

if c.flows.empty:
    st.warning("Set up the fund and record the starting capital first, so there is cash to buy with.",
               icon=":material/account_balance_wallet:")
    page_link("views/dashboard.py", "Set up the fund", ":material/arrow_forward:")
    st.stop()

pre = st.session_state.pop("prefill", None)
if pre:  # coming from Watchlist "Buy"
    for k, val in pre.items():
        st.session_state[("npf_" if k in ("name", "sector", "mcap") else "np_") + k] = val

with card("new_position_1"):
    st.markdown("**1 · Stock**")
    a, b, d = st.columns([2, 1, 1])
    symbol = a.text_input("NSE/BSE symbol", key="np_symbol", placeholder="e.g. TATAPOWER").strip().upper()
    exchange = b.selectbox("Exchange", EXCHANGES, key="np_exchange")
    d.write("")
    d.write("")
    if d.button("Look up", icon=":material/search:", width="stretch", disabled=not symbol):
        info = prices.lookup_info(ledger.ticker_for(symbol, exchange))
        if info:
            st.session_state["npf_name"] = info["name"]
            st.session_state["npf_sector"] = info["sector"]
            st.session_state["npf_mcap"] = info["mcap"]
            if info.get("price"):
                st.session_state["np_price"] = float(info["price"])
            st.rerun()
        else:
            st.warning("Couldn't find that symbol on Yahoo. Check the symbol, or fill details manually.")
    existing = c.summary[(c.summary["symbol"] == symbol) & (c.summary["status"] == "Active")] if (symbol and not c.summary.empty) else None
    if existing is not None and not existing.empty:
        st.info(f"You already hold **{symbol}** ({existing.iloc[0]['qty']:g} shares). Consider using **Add-on** "
                "from Holdings so it stays one position.", icon=":material/info:")
    fields = dialogs.position_form({}, "npf")

with card("new_position_2"):
    st.markdown("**2 · First buy**")
    a, b, d = st.columns(3)
    qty = a.number_input("Quantity", min_value=1, value=10, step=1, key="np_qty")
    price = b.number_input("Entry price (₹)", min_value=0.01, value=st.session_state.get("np_price", 100.0),
                           step=0.05, format="%.2f")
    date = d.date_input("Entry date", value=dt.date.today(), max_value=dt.date.today(), format="DD/MM/YYYY",
                        key="np_date")
    charges, auto = dialogs.charges_block("BUY", qty, price, exchange, "np")
    thesis = st.text_area("Entry thesis / reasons", height=110, key="np_thesis",
                          placeholder="Why are you buying? Trigger, catalysts, what would make you exit…")

new = {"position_id": -1, "kind": "BUY", "qty": float(qty), "price": float(price), "date": date,
       "charges": charges, "charges_auto": auto, "reason": "Initial entry"}
hypo = ledger.with_txn(c.txns, new)
errors = ledger.check_ledger(c.flows, hypo)
cost = qty * price + charges
cash_after = ledger.cash_balance(c.flows, hypo)

m = st.columns(4)
m[0].metric("Total cost", inr(cost))
m[1].metric("Cash available", inr(c.cash))
m[2].metric("Cash after", inr(cash_after))
m[3].metric("Position size", f"{cost / c.total * 100:.1f}%" if c.total else "—",
            help="Cost as % of current fund value")
if fields["stop_loss"] and fields["stop_loss"] < price:
    risk = (price - fields["stop_loss"]) * qty
    st.caption(f"Risk to stop-loss: **{inr(risk)}** ({risk / c.total * 100:.2f}% of fund)"
               + (f" · Reward:Risk to T1 **{(fields['target1'] - price) / (price - fields['stop_loss']):.2f}**"
                  if fields["target1"] else ""))

dialogs.show_errors(errors)
dialogs.cash_hint(errors)
if any(e["type"] == "cash" for e in errors):
    page_link("views/investors.py", "Record an investor deposit", ":material/arrow_forward:")
dialogs.backdate_note(c.flows, date)

if st.button("Save position", type="primary", icon=":material/check:", disabled=bool(errors) or not symbol):
    pid = db.add_position(c.engine, c.owner, {"symbol": symbol, "exchange": exchange, **fields},
                          {k: v for k, v in new.items() if k != "position_id"}, thesis)
    for k in [k for k in st.session_state if k.startswith(("np_", "npf_"))]:
        del st.session_state[k]
    st.session_state["sel_pos"] = pid
    state.bump()
    st.session_state["flash"] = f"{symbol}: {qty} @ {inr(price, 2)} added."
    st.switch_page("views/holdings.py")
