"""Modal dialogs for every write action. Validation runs live on each rerun so
blocking messages (and the 'add funds' shortcut) are always visible before submit."""
import datetime as dt
import html
import math

import pandas as pd
import streamlit as st

from . import db, ledger, links, nav, state
from .charges import zerodha_charges
from .config import EXCHANGES, MCAP_BUCKETS, RELATIONS, STRATEGIES
from .ui import inr, pct


def _done(msg: str):
    state.bump()
    st.session_state["flash"] = msg
    st.rerun()


def charges_block(kind, qty, price, exchange, key, current=None, auto_default=True):
    """Auto Zerodha charges with optional manual override. Returns (charges, auto_flag)."""
    auto = st.checkbox("Auto-calculate Zerodha charges", value=auto_default, key=f"{key}_auto")
    br = zerodha_charges(kind, qty, price, exchange)
    if auto:
        parts = [f"STT {inr(br['stt'])}", f"Txn {inr(br['txn'], 2)}", f"SEBI {inr(br['sebi'], 2)}",
                 f"GST {inr(br['gst'], 2)}"]
        if br["stamp"]:
            parts.append(f"Stamp {inr(br['stamp'], 2)}")
        if br["dp"]:
            parts.append(f"DP {inr(br['dp'], 2)}")
        st.caption(f"Charges **{inr(br['total'], 2)}** · " + " · ".join(parts))
        return br["total"], True
    val = st.number_input("Charges (₹)", min_value=0.0, step=1.0, key=f"{key}_manual",
                          value=float(current if current is not None else br["total"]))
    return float(val), False


def cash_hint(errors):
    """Cash can only come from investors (who get units for it) or from selling, so there is no
    one-click top-up here: point the manager at the two real fixes."""
    if any(e["type"] == "cash" for e in errors):
        st.caption("To free up cash, record an investor deposit on the **Investors** page (dated on or before "
                   "this trade) or sell a holding first.")


def backdate_note(flows, date, what="trade"):
    """Warn when a new entry is dated before investor flows that were already priced without it."""
    later = flows[flows["date"] > date] if not flows.empty else flows
    if not later.empty:
        n = len(later)
        st.warning(f"{n} investor {'entry is' if n == 1 else 'entries are'} dated after this {what} and "
                   f"{'was' if n == 1 else 'were'} priced without it. After saving, open **Fund & settings → "
                   "NAV audit** to re-price them.", icon=":material/history:")


def show_errors(errors):
    for e in errors:
        st.error(e["msg"], icon=":material/block:")


# ====================================================================== trades
@st.dialog("Add-on / Exit", width="large")
def trade_dialog(pos: dict, kind: str):
    c = state.ctx()
    flows, txns = state.load(c.owner)["flows"], state.load(c.owner)["txns"]
    held = ledger.held_qty(txns, pos["id"])
    verb = "Add-on buy" if kind == "BUY" else "Exit (sell)"
    st.markdown(f"#### {verb} · {pos['symbol']}")
    st.caption(f"Held **{held:g}** @ avg {inr(pos['avg_cost'], 2)} · CMP {inr(pos['cmp'], 2)} "
               f"({pos['cmp_source']}) · Cash available {inr(ledger.cash_balance(flows, txns))}")
    a, b, d = st.columns(3)
    if kind == "SELL":
        full = st.toggle("Exit full position", value=True, key="td_full")
        qty = held if full else a.number_input("Quantity", min_value=1, max_value=max(int(held), 1),
                                               value=max(int(held // 2), 1), step=1, key="td_qty")
        if full:
            a.metric("Quantity", f"{held:g}")
    else:
        qty = a.number_input("Quantity", min_value=1, value=10, step=1, key="td_qty")
    price = b.number_input("Price (₹)", min_value=0.01, value=float(round(pos["cmp"], 2)), step=0.05,
                           format="%.2f", key="td_price")
    date = d.date_input("Date", value=dt.date.today(), max_value=dt.date.today(), key="td_date",
                        format="DD/MM/YYYY")
    charges, auto = charges_block(kind, qty, price, pos["exchange"], "td")
    reason = st.text_area("Reason for this trade", key="td_reason",
                          placeholder="e.g. Breakout retest held / Booking partial at target 1 / Thesis broken")
    gross = qty * price
    new = {"position_id": pos["id"], "kind": kind, "qty": float(qty), "price": float(price), "date": date,
           "charges": charges, "charges_auto": auto, "reason": reason}
    hypo = ledger.with_txn(txns, new)
    errors = ledger.check_ledger(flows, hypo, c.positions)
    metrics_slot, err_slot = st.container(), st.container()
    with metrics_slot:
        m1, m2, m3 = st.columns(3)
        if kind == "BUY":
            m1.metric("Total cost", inr(gross + charges))
            new_avg = (pos["avg_cost"] * held + gross) / (held + qty) if held + qty else 0
            m2.metric("New avg cost", inr(new_avg, 2),
                      delta=pct((new_avg / pos["avg_cost"] - 1) * 100) if pos["avg_cost"] else None,
                      delta_color="inverse")
        else:
            m1.metric("Net proceeds", inr(gross - charges))
            f = ledger.fifo(hypo[hypo["position_id"] == pos["id"]])
            est = sum(l["pnl"] for l in f["realized_lots"] if l["sell_txn_id"] == 10**12)
            m2.metric("Realized P&L (FIFO, net)", inr(est, sign=True))
        m3.metric("Cash after", inr(ledger.cash_balance(flows, hypo)))
    with err_slot:
        show_errors(errors)
        cash_hint(errors)
        backdate_note(flows, date)
    if st.button("Place buy" if kind == "BUY" else "Confirm exit", type="primary", disabled=bool(errors),
                 width="stretch", key="td_go"):
        db.add_txn(c.engine, c.owner, pos["id"], **new)
        _done(f"{verb}: {qty:g} {pos['symbol']} @ {inr(price, 2)} saved.")


@st.dialog("Record dividend")
def dividend_dialog(pos: dict):
    c = state.ctx()
    txns = state.load(c.owner)["txns"]
    st.markdown(f"#### Dividend · {pos['symbol']}")
    date = st.date_input("Record / payment date", value=dt.date.today(), max_value=dt.date.today(), format="DD/MM/YYYY")
    held = ledger.held_qty(txns, pos["id"], date)
    qty = st.number_input("Shares eligible", min_value=0, value=int(max(held, 0)), step=1)
    dps = st.number_input("Dividend per share (₹)", min_value=0.0, value=1.0, step=0.5, format="%.2f")
    note = st.text_input("Note", placeholder="Final dividend FY25")
    st.metric("Amount credited", inr(qty * dps, 2))
    if st.button("Save dividend", type="primary", disabled=qty * dps <= 0, width="stretch"):
        db.add_txn(c.engine, c.owner, pos["id"], kind="DIVIDEND", qty=float(qty), price=float(dps), date=date,
                   charges=0.0, charges_auto=False, reason=note)
        _done(f"Dividend of {inr(qty * dps, 2)} recorded for {pos['symbol']}.")


@st.dialog("Edit transaction", width="large")
def edit_txn_dialog(txn: dict, pos: dict):
    c = state.ctx()
    data = state.load(c.owner)
    flows, txns = data["flows"], data["txns"]
    st.markdown(f"#### Edit {txn['kind']} · {pos['symbol']}")
    a, b, d = st.columns(3)
    kinds = ["BUY", "SELL", "DIVIDEND"]
    kind = a.selectbox("Type", kinds, index=kinds.index(txn["kind"]), key="et_kind")
    qty = b.number_input("Quantity", min_value=1.0 if kind != "DIVIDEND" else 0.0, value=float(txn["qty"]),
                         step=1.0, key="et_qty")
    price = d.number_input("Price (₹)" if kind != "DIVIDEND" else "Dividend / share (₹)", min_value=0.0,
                           value=float(txn["price"]), step=0.05, format="%.2f", key="et_price")
    date = st.date_input("Date", value=txn["date"], max_value=dt.date.today(), key="et_date", format="DD/MM/YYYY")
    if kind == "DIVIDEND":
        charges, auto = 0.0, False
    else:
        charges, auto = charges_block(kind, qty, price, pos["exchange"], "et", current=txn["charges"],
                                      auto_default=bool(txn.get("charges_auto", True)))
    reason = st.text_area("Reason", value=txn.get("reason") or "", key="et_reason")
    new = {"position_id": txn["position_id"], "kind": kind, "qty": qty, "price": price, "date": date,
           "charges": charges, "charges_auto": auto, "reason": reason}
    hypo = ledger.with_txn(txns, new, replace_id=txn["id"])
    errors = ledger.check_ledger(flows, hypo, c.positions)
    show_errors(errors)
    cash_hint(errors)
    backdate_note(flows, min(date, txn["date"]))
    if st.button("Save changes", type="primary", disabled=bool(errors), width="stretch"):
        db.update_txn(c.engine, c.owner, txn["id"], **{k: v for k, v in new.items() if k != "position_id"})
        _done("Transaction updated.")


@st.dialog("Delete transaction")
def delete_txn_dialog(txn: dict, pos: dict):
    c = state.ctx()
    data = state.load(c.owner)
    st.warning(f"Delete **{txn['kind']} {txn['qty']:g} @ {inr(txn['price'], 2)}** on {txn['date']:%d %b %Y} "
               f"from {pos['symbol']}? This cannot be undone.", icon=":material/delete:")
    errors = ledger.check_ledger(data["flows"], ledger.with_txn(data["txns"], remove_id=txn["id"]), c.positions)
    only = (data["txns"]["position_id"] == txn["position_id"]).sum() == 1
    if only:
        st.caption("This is the only transaction — the position will be deleted too.")
    show_errors(errors)
    if errors:
        st.caption("Fix the dependent trades first (e.g. delete the later sell, or record an investor deposit).")
    backdate_note(data["flows"], txn["date"])
    if st.button("Delete", type="primary", disabled=bool(errors), width="stretch"):
        db.delete_txn(c.engine, c.owner, txn["id"])
        if only:
            st.session_state.pop("sel_pos", None)
        _done("Transaction deleted.")


# ====================================================================== positions
def _kw(k, **default):
    """Pass a default only if the widget's state wasn't already set via session_state."""
    return {} if k in st.session_state else default


def position_form(pos: dict, key: str) -> dict:
    a, b, d = st.columns(3)
    name = a.text_input("Company name", key=f"{key}_name", **_kw(f"{key}_name", value=pos.get("name") or ""))
    sector = b.text_input("Sector", key=f"{key}_sector",
                          **_kw(f"{key}_sector", value=pos.get("sector") or "Unclassified"))
    mc = pos.get("mcap") or "Unknown"
    mcap = d.selectbox("Market cap", MCAP_BUCKETS, key=f"{key}_mcap",
                       **_kw(f"{key}_mcap", index=MCAP_BUCKETS.index(mc) if mc in MCAP_BUCKETS else 4))
    a, b, d = st.columns(3)
    stg = pos.get("strategy") or "Positional"
    strategy = a.selectbox("Strategy", STRATEGIES, index=STRATEGIES.index(stg) if stg in STRATEGIES else 0,
                           key=f"{key}_strategy")
    conviction = b.slider("Conviction", 1, 5, int(pos.get("conviction") or 3), key=f"{key}_conv")
    rv = pos.get("review_by")
    review_by = d.date_input("Review thesis by", value=rv if rv and not pd.isna(rv) else None,
                             key=f"{key}_review", format="DD/MM/YYYY")
    a, b, d = st.columns(3)

    def _opt(v):
        return None if v is None or pd.isna(v) else float(v)

    sl = a.number_input("Stop-loss (₹)", min_value=0.0, value=_opt(pos.get("stop_loss")), step=0.5,
                        format="%.2f", key=f"{key}_sl")
    t1 = b.number_input("Target 1 (₹)", min_value=0.0, value=_opt(pos.get("target1")), step=0.5,
                        format="%.2f", key=f"{key}_t1")
    t2 = d.number_input("Target 2 (₹)", min_value=0.0, value=_opt(pos.get("target2")), step=0.5,
                        format="%.2f", key=f"{key}_t2")
    return {"name": name.strip(), "sector": sector.strip() or "Unclassified", "mcap": mcap, "strategy": strategy,
            "conviction": int(conviction), "review_by": review_by,
            "stop_loss": sl or None, "target1": t1 or None, "target2": t2 or None}


@st.dialog("Edit position", width="large")
def edit_position_dialog(pos: dict):
    c = state.ctx()
    st.markdown(f"#### {pos['symbol']}")
    a, b = st.columns([2, 1])
    symbol = a.text_input("Symbol", value=pos["symbol"], key="ep_symbol").strip().upper()
    exchange = b.selectbox("Exchange", EXCHANGES, index=EXCHANGES.index(pos.get("exchange") or "NSE"), key="ep_exch")
    fields = position_form(pos, "ep")
    ov = pos.get("cmp_override")
    use_ov = st.toggle("Manual CMP override (use if live price is unavailable)",
                       value=ov is not None and not pd.isna(ov), key="ep_ov_on")
    cmp_override = None
    if use_ov:
        cmp_override = st.number_input("Manual CMP (₹)", min_value=0.01,
                                       value=float(ov) if ov and not pd.isna(ov) else float(pos.get("cmp") or 1),
                                       format="%.2f", key="ep_ov")
    notes = st.text_area("Notes", value=pos.get("notes") or "", key="ep_notes")
    if st.button("Save", type="primary", width="stretch", disabled=not symbol):
        db.update_position(c.engine, c.owner, pos["id"], symbol=symbol, exchange=exchange,
                           cmp_override=cmp_override, notes=notes, **fields)
        _done(f"{symbol} updated.")


@st.dialog("Add thesis note")
def thesis_dialog(pos: dict):
    c = state.ctx()
    st.markdown(f"#### {pos['symbol']} — update your reasoning")
    date = st.date_input("Date", value=dt.date.today(), format="DD/MM/YYYY")
    text = st.text_area("What changed? Why are you still holding / why exit?", height=160)
    if st.button("Save note", type="primary", disabled=not text.strip(), width="stretch"):
        db.add_thesis(c.engine, c.owner, pos["id"], date, text)
        _done("Thesis note added.")


@st.dialog("Delete position")
def delete_position_dialog(pos: dict):
    c = state.ctx()
    data = state.load(c.owner)
    t = data["txns"]
    n = (t["position_id"] == pos["id"]).sum()
    st.warning(f"Permanently delete **{pos['symbol']}** with all **{n}** transactions and its thesis log? "
               "Its cash effects will be removed from the ledger. This cannot be undone.", icon=":material/delete_forever:")
    errors = ledger.check_ledger(data["flows"], t[t["position_id"] != pos["id"]], c.positions)
    show_errors(errors)
    confirm = st.text_input(f"Type {pos['symbol']} to confirm")
    if st.button("Delete position", type="primary", width="stretch",
                 disabled=bool(errors) or confirm.strip().upper() != pos["symbol"].upper()):
        db.delete_position(c.engine, c.owner, pos["id"])
        st.session_state.pop("sel_pos", None)
        _done(f"{pos['symbol']} deleted.")


# ====================================================================== investors
@st.dialog("Investor")
def investor_dialog(inv: dict = None):
    """Add a new investor, or edit an existing one (pass the investor row)."""
    c = state.ctx()
    investors = state.load(c.owner)["investors"]
    inv = inv or {}
    name = st.text_input("Name", value=inv.get("name") or "", max_chars=120, key="iv_name",
                         placeholder="e.g. Ahmed (brother)")
    rel = inv.get("relation") or "Family"
    a, b = st.columns(2)
    relation = a.selectbox("Relation", RELATIONS, index=RELATIONS.index(rel) if rel in RELATIONS else 1, key="iv_rel")
    contact = b.text_input("Phone / e-mail (optional)", value=inv.get("contact") or "", key="iv_contact")
    notes = st.text_area("Notes (optional)", value=inv.get("notes") or "", key="iv_notes", height=80)
    clash = (not investors.empty and name.strip() and
             (investors.loc[investors["id"] != inv.get("id"), "name"].str.strip().str.lower()
              == name.strip().lower()).any())
    if clash:
        st.error("There is already an investor with this name.", icon=":material/block:")
    if st.button("Save investor", type="primary", width="stretch", disabled=not name.strip() or bool(clash),
                 key="iv_go"):
        fields = {"name": name.strip(), "relation": relation, "contact": contact.strip(), "notes": notes.strip()}
        if inv.get("id") is not None:
            db.update_investor(c.engine, c.owner, int(inv["id"]), **fields)
            _done(f"{fields['name']} updated.")
        iid = db.add_investor(c.engine, c.owner, is_manager=False, **fields)
        st.session_state["sel_inv"] = iid
        _done(f"{fields['name']} added. Record their first deposit to issue units.")


@st.dialog("Remove investor")
def delete_investor_dialog(inv: dict):
    c = state.ctx()
    if inv.get("n_flows"):
        st.info(f"**{inv['name']}** has {inv['n_flows']} capital entries, so the account is part of the fund's "
                "history and cannot be removed. Delete those entries first if they were recorded by mistake.",
                icon=":material/info:")
        return
    st.warning(f"Remove **{inv['name']}**? They have no capital entries.", icon=":material/delete:")
    if st.button("Remove investor", type="primary", width="stretch", key="ivd_go"):
        db.delete_investor(c.engine, c.owner, int(inv["id"]))
        st.session_state.pop("sel_inv", None)
        _done(f"{inv['name']} removed.")


# ====================================================================== funds (unit transactions)
FLOW_LABEL = {"DEPOSIT": "Add money", "WITHDRAWAL": "Withdraw"}


@st.dialog("Investor money in / out", width="large")
def funds_dialog(investor_id=None, default_kind="DEPOSIT"):
    """Record a deposit (issues units) or a withdrawal (redeems units) at the NAV of the chosen date."""
    c = state.ctx()
    data = state.load(c.owner)
    flows, txns, investors = data["flows"], data["txns"], data["investors"]
    if investors.empty:
        st.info("Add an investor first.", icon=":material/person_add:")
        return
    inv = investors.sort_values(["is_manager", "name"], ascending=[False, True])
    ids, names = list(inv["id"]), dict(zip(inv["id"], inv["name"]))
    a, b = st.columns([3, 2])
    iid = a.selectbox("Investor", ids, format_func=names.get, key="fd_inv",
                      index=ids.index(investor_id) if investor_id in ids else 0)
    kind = b.segmented_control("Type", list(FLOW_LABEL), format_func=FLOW_LABEL.get, key="fd_kind",
                               default=default_kind if default_kind in FLOW_LABEL else "DEPOSIT") or "DEPOSIT"
    a, b = st.columns(2)
    date = a.date_input("Date money moved", value=dt.date.today(), max_value=dt.date.today(), format="DD/MM/YYYY",
                        key="fd_date")
    q = state.nav_quote(c, date, flows=flows)
    held = nav.units_outstanding(flows, as_of=date, investor_id=iid)
    manual = st.toggle("Enter the NAV myself", key="fd_manual",
                       help="Use this if you settled with the investor at a NAV you worked out yourself. "
                            "A manual NAV is locked: the NAV audit never changes it.")
    if manual:
        nav_val = b.number_input("NAV per unit (₹)", min_value=0.0001, value=float(q["nav"] or c.face), step=0.01,
                                 format="%.4f", key="fd_nav")
    else:
        nav_val = q["nav"]
        b.metric(f"NAV on {date:%d %b %Y}", f"₹{nav_val:,.4f}" if nav_val else "—")
    if not manual:
        if q["basis"] == "face":
            st.caption(f"First money into the fund, so units are issued at the face value of ₹{c.face:g}.")
        elif q["basis"] == "carried":
            st.caption("No units were outstanding before this date, so the last transacted NAV is used.")
        else:
            st.caption(f"Fund value {inr(q['value_before'])} ÷ {q['units_before']:,.4f} units outstanding, before "
                       f"any money moved on this day."
                       + (" Based on current prices: if the closing NAV ends up different, the NAV audit "
                          "will offer to settle this entry at the close." if date >= dt.date.today() else ""))

    full = False
    if kind == "WITHDRAWAL":
        st.caption(f"{names[iid]} holds **{held:,.4f} units** on this date, worth "
                   f"**{inr(held * (nav_val or 0), 2)}**.")
        full = st.toggle("Withdraw everything (redeem all units)", key="fd_full", disabled=held <= 0)
    if full and nav_val:
        amount, units = round(held * nav_val, 2), round(held, nav.UNIT_DP)
    else:
        amount = st.number_input("Amount (₹)", min_value=0.0, value=100000.0, step=10000.0, format="%.2f",
                                 key="fd_amt")
        units = nav.units_for(amount, nav_val) if nav_val else 0.0
        if kind == "WITHDRAWAL" and abs(held - units) < nav.DUST:
            units = round(held, nav.UNIT_DP)      # don't leave a dust balance behind
    note = st.text_input("Note (optional)", key="fd_note", placeholder="e.g. UPI transfer, ref 1234")

    errors = []
    if not nav_val or nav_val <= 0:
        errors.append({"type": "nav", "msg": "The NAV for this date could not be worked out. Enter it manually."})
    new = {"investor_id": iid, "date": date, "kind": kind, "amount": float(amount), "nav": float(nav_val or 0),
           "units": float(units), "nav_manual": bool(manual)}
    hypo = ledger.with_flow(flows, new)
    if not errors:
        errors = nav.check_units(hypo, investors) + ledger.check_ledger(hypo, txns)

    sign = -1 if kind == "WITHDRAWAL" else 1
    units_after = held + sign * units
    fund_units_after = nav.units_outstanding(flows, as_of=date) + sign * units
    m = st.columns(4)
    m[0].metric("Amount", inr(amount, 2))
    m[1].metric("Units issued" if sign > 0 else "Units redeemed", f"{units:,.4f}")
    m[2].metric("Their units after", f"{max(units_after, 0):,.4f}")
    m[3].metric("Share of fund after", pct(units_after / fund_units_after * 100, 2, sign=False)
                if fund_units_after > nav.DUST and units_after > 0 else "—")
    show_errors(errors)
    if kind == "WITHDRAWAL" and any(e["type"] == "cash" for e in errors):
        st.caption("The fund does not hold enough cash on that date. Sell holdings first, then record the withdrawal.")
    backdate_note(flows, date, "entry")
    if st.button("Save", type="primary", width="stretch", disabled=amount <= 0 or units <= 0 or bool(errors),
                 key="fd_go"):
        db.add_flow(c.engine, c.owner, int(iid), date, kind, amount, nav_val, units, nav_manual=manual, note=note)
        st.session_state["sel_inv"] = int(iid)
        _done(f"{names[iid]}: {FLOW_LABEL[kind].lower()} {inr(amount, 2)} at NAV ₹{nav_val:,.4f} "
              f"({units:,.4f} units).")


@st.dialog("Delete capital entry")
def delete_flow_dialog(flow: dict):
    c = state.ctx()
    data = state.load(c.owner)
    flows, investors = data["flows"], data["investors"]
    who = dict(zip(investors["id"], investors["name"])).get(flow["investor_id"], "Investor")
    st.warning(f"Delete **{who}: {FLOW_LABEL.get(flow['kind'], flow['kind']).lower()} {inr(flow['amount'], 2)}** on "
               f"{flow['date']:%d %b %Y} ({flow['units']:,.4f} units at NAV ₹{flow['nav']:,.4f})? "
               "This cannot be undone.", icon=":material/delete:")
    hypo = ledger.with_flow(flows, remove_id=flow["id"])
    errors = nav.check_units(hypo, investors) + ledger.check_ledger(hypo, data["txns"], c.positions)
    show_errors(errors)
    if errors:
        st.caption("Later entries or trades depend on this money. Remove or change those first.")
    backdate_note(flows, flow["date"], "entry")
    if st.button("Delete entry", type="primary", disabled=bool(errors), width="stretch", key="fdel_go"):
        db.delete_flow(c.engine, c.owner, int(flow["id"]))
        _done("Capital entry deleted.")


# ====================================================================== sidebar links
def _links_rerun(in_dialog: bool):
    """Refresh after a change. Inside the dialog only the dialog re-runs, so it stays open."""
    if in_dialog:
        try:
            st.rerun(scope="fragment")
        except st.errors.StreamlitAPIException:
            pass
    st.rerun()


def links_editor(prefix: str, in_dialog: bool):
    """List of saved links with reorder / delete, plus an add form. Used on the settings page and in the dialog."""
    c = state.ctx()
    cur = links.get_links(state.load(c.owner)["settings"])
    for i, l in enumerate(cur):
        x1, x2, x3 = st.columns([6, 1, 1], vertical_alignment="center")
        x1.markdown(f"<b>{html.escape(l['name'])}</b><br>"
                    f"<span style='font-size:12px;opacity:.65'>{html.escape(l['url'])}</span>",
                    unsafe_allow_html=True)
        if x2.button("", icon=":material/arrow_upward:", key=f"{prefix}_up_{i}", help="Move up", disabled=i == 0,
                     type="tertiary"):
            cur[i - 1], cur[i] = cur[i], cur[i - 1]
            links.save_links(c.engine, c.owner, cur)
            state.bump()
            _links_rerun(in_dialog)
        if x3.button("", icon=":material/delete:", key=f"{prefix}_del_{i}", help=f"Delete {l['name']}",
                     type="tertiary"):
            links.save_links(c.engine, c.owner, cur[:i] + cur[i + 1:])
            state.bump()
            _links_rerun(in_dialog)
    if not cur:
        st.caption("No links yet. Add your first one below.")
    st.markdown("**Add a link**")
    with st.form(f"{prefix}_add", clear_on_submit=True, border=False):
        nm = st.text_input("Name", placeholder="e.g. Stock screener", max_chars=60)
        ur = st.text_input("Link (URL)", placeholder="https://your-app.streamlit.app")
        add = st.form_submit_button("Add link", type="primary", icon=":material/add:")
    if add:
        url = links.clean_url(ur)
        if not nm.strip() or not url:
            st.error("Enter a name and a valid web address (starting with https://).", icon=":material/block:")
        elif len(cur) >= links.MAX_LINKS:
            st.error(f"You can keep up to {links.MAX_LINKS} links.", icon=":material/block:")
        elif any(l["url"].rstrip("/") == url.rstrip("/") for l in cur):
            st.error("That link is already in the list.", icon=":material/block:")
        else:
            links.save_links(c.engine, c.owner, cur + [{"name": nm.strip(), "url": url}])
            state.bump()
            _links_rerun(in_dialog)


@st.dialog("Manage my app links", on_dismiss="rerun")
def links_dialog():
    st.caption("These appear in the sidebar under MY APPS and open in a new tab.")
    links_editor("lkd", in_dialog=True)
    if st.button("Done", width="stretch", key="lkd_done"):
        st.rerun()
