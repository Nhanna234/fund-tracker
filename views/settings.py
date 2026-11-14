import datetime as dt

import streamlit as st

from core import db, dialogs, nav, sample, state
from core.ui import card, card_title, inr, page_header, style_table

c = state.ctx()
page_header("Fund & settings", "Fund details, the unit ledger and NAV audit, alert thresholds, links and backups.",
            eyebrow="Account")
names = dict(zip(c.investors["id"], c.investors["name"])) if not c.investors.empty else {}

# ------------------------------------------------------------------ fund details
with card("settings_fund"):
    card_title("Fund details")
    a, b, d = st.columns([2, 1, 1], vertical_alignment="bottom")
    fund_name = a.text_input("Fund name", value=c.fund_name, max_chars=60)
    face = b.number_input("Face value per unit (₹)", min_value=1.0, value=float(c.face), step=1.0, format="%.2f",
                          disabled=not c.flows.empty,
                          help="The NAV on day one. It cannot change once units have been issued.")
    if d.button("Save fund details", width="stretch"):
        db.set_setting(c.engine, c.owner, "fund_name", fund_name.strip() or c.fund_name)
        if c.flows.empty:
            db.set_setting(c.engine, c.owner, "face_value", face)
        state.bump()
        st.session_state["flash"] = "Fund details saved."
        st.rerun()
    k = st.columns(5)
    k[0].metric("NAV per unit", f"₹{c.nav:,.4f}")
    k[1].metric("Units outstanding", f"{c.units:,.4f}")
    k[2].metric("Money put in", inr(c.deposits))
    k[3].metric("Money taken out", inr(c.withdrawals))
    k[4].metric("Cash available", inr(c.cash))

# ------------------------------------------------------------------ unit ledger
with card("settings_ledger"):
    card_title("Unit ledger", "every deposit and withdrawal, with the NAV it was done at")
    if c.flows.empty:
        st.caption("No money recorded yet.")
    else:
        b = st.columns([1.2, 1.2, 4])
        if b[0].button("Add money", type="primary", icon=":material/add:", width="stretch"):
            dialogs.funds_dialog(None, "DEPOSIT")
        if b[1].button("Withdraw", icon=":material/remove:", width="stretch"):
            dialogs.funds_dialog(None, "WITHDRAWAL")
        led = nav.statement(c.flows)
        show = led[["date", "investor_id", "kind", "signed_amount", "nav", "signed_units", "balance", "note"]].copy()
        show["investor_id"] = show["investor_id"].map(names)
        show["kind"] = show["kind"].map({"DEPOSIT": "Deposit", "WITHDRAWAL": "Withdrawal"})
        show.columns = ["Date", "Investor", "Type", "Amount", "NAV", "Units", "Units outstanding", "Note"]
        show = show.iloc[::-1]
        st.dataframe(style_table(show, money2=["Amount"], dates=["Date"], pnl_cols=["Amount", "Units"],
                                 custom={"NAV": lambda x: f"₹{x:,.4f}", "Units": lambda x: f"{x:+,.4f}",
                                         "Units outstanding": lambda x: f"{x:,.4f}"}),
                     hide_index=True, width="stretch", height=min(36 * len(show) + 40, 360))
        x1, x2, x3, x4 = st.columns([3, 1.2, 1.3, 1.3])
        labels = {int(r.id): f"{r.date:%d %b %Y} · {names.get(r.investor_id, '?')} · "
                             f"{'Deposit' if r.kind == 'DEPOSIT' else 'Withdrawal'} {inr(r.amount, 2)}"
                  for r in led.iloc[::-1].itertuples()}
        fid = x1.selectbox("Entry", list(labels), format_func=labels.get, index=None, key="led_entry",
                           placeholder="Choose an entry to delete…", label_visibility="collapsed")
        if x2.button("Delete entry", icon=":material/delete:", width="stretch", disabled=fid is None):
            dialogs.delete_flow_dialog(led[led["id"] == fid].iloc[0].to_dict())
        x3.download_button("Ledger (CSV)", show.assign(Date=[d.isoformat() for d in show["Date"]]).to_csv(index=False),
                           file_name="unit_ledger.csv", icon=":material/download:", width="stretch")
        daily = state.daily_for(c)
        if not daily.empty:
            navs = daily[["nav", "units", "value"]].round(4).rename_axis("date").reset_index()
            navs["date"] = navs["date"].dt.date
            x4.download_button("NAV history (CSV)", navs.to_csv(index=False), file_name="nav_history.csv",
                               icon=":material/show_chart:", width="stretch")

# ------------------------------------------------------------------ NAV audit
if not c.flows.empty:
    with card("settings_audit"):
        card_title("NAV audit", "re-prices every entry from the trade ledger and closing prices")
        st.caption("The NAV and units of each entry are frozen when you save it. If you later back-date a trade or "
                   "an entry, or an entry was saved during market hours, the stored NAV can differ from the "
                   "recomputed one. Review the differences here and choose what to do.")
        aud = state.audit_for(c)
        diff = aud[aud["changed"]]
        locked = int(aud["nav_manual"].sum())
        if diff.empty:
            st.success(f"All {len(aud)} entries match the recomputed NAV."
                       + (f" {locked} locked (manual NAV)." if locked else ""), icon=":material/verified:")
        else:
            t = diff[["date", "investor_id", "kind", "amount", "nav", "nav_new", "nav_diff_pct", "units",
                      "units_new"]].copy()
            t["investor_id"] = t["investor_id"].map(names)
            t["kind"] = t["kind"].map({"DEPOSIT": "Deposit", "WITHDRAWAL": "Withdrawal"})
            t.columns = ["Date", "Investor", "Type", "Amount", "Stored NAV", "Recomputed NAV", "NAV diff %",
                         "Stored units", "Recomputed units"]
            f4 = lambda x: f"{x:,.4f}"  # noqa: E731
            st.dataframe(style_table(t, money2=["Amount"], dates=["Date"], pnl_cols=["NAV diff %"],
                                     custom={"Stored NAV": f4, "Recomputed NAV": f4, "Stored units": f4,
                                             "Recomputed units": f4, "NAV diff %": lambda x: f"{x:+.3f}%"}),
                         hide_index=True, width="stretch")
            big = int(diff["drift"].sum())
            st.caption(f"{len(diff)} of {len(aud)} entries differ"
                       + (f"; {big} by more than {nav.DRIFT_PCT}%." if big else " (all within rounding / small drift)."))
            fixed = c.flows.copy()
            fixed = fixed.merge(aud[["id", "nav_new", "units_new"]], on="id")
            fixed["nav"], fixed["units"] = fixed["nav_new"], fixed["units_new"]
            errs = nav.check_units(fixed, c.investors)
            dialogs.show_errors(errs)
            a, b, _ = st.columns([1.8, 1.8, 3])
            if a.button("Apply recomputed NAV & units", type="primary", icon=":material/published_with_changes:",
                        width="stretch", disabled=bool(errs)):
                db.update_flows_bulk(c.engine, c.owner, {int(r.id): {"nav": float(r.nav_new), "units": float(r.units_new)}
                                                        for r in diff.itertuples()})
                state.bump()
                st.session_state["flash"] = f"{len(diff)} entries re-priced."
                st.rerun()
            if b.button("Keep stored values (lock them)", icon=":material/lock:", width="stretch",
                        help="Marks these entries as manual so the audit stops flagging them."):
                db.update_flows_bulk(c.engine, c.owner, {int(r.id): {"nav_manual": True} for r in diff.itertuples()})
                state.bump()
                st.session_state["flash"] = f"{len(diff)} entries locked."
                st.rerun()
        if locked:
            with st.popover(f"{locked} locked entr{'y' if locked == 1 else 'ies'}", icon=":material/lock:"):
                st.caption("Locked entries keep the NAV you entered. Unlocking lets the audit re-price them.")
                if st.button("Unlock all", icon=":material/lock_open:"):
                    db.update_flows_bulk(c.engine, c.owner,
                                         {int(i): {"nav_manual": False} for i in aud.loc[aud["nav_manual"], "id"]})
                    state.bump()
                    st.rerun()

# ------------------------------------------------------------------ settings
with card("settings_2"):
    card_title("Alert thresholds")
    a, b = st.columns(2)
    conc = a.number_input("Concentration alert above (% of fund)", 1.0, 100.0,
                          float(c.settings["concentration_pct"]), 1.0)
    near = b.number_input("Near stop-loss alert within (%)", 0.5, 50.0, float(c.settings["near_sl_pct"]), 0.5)
    if st.button("Save thresholds"):
        db.set_setting(c.engine, c.owner, "concentration_pct", conc)
        db.set_setting(c.engine, c.owner, "near_sl_pct", near)
        state.bump()
        st.session_state["flash"] = "Settings saved."
        st.rerun()

# ------------------------------------------------------------------ my app links
with card("settings_3"):
    card_title("My apps (sidebar links)")
    st.caption("Links to your other websites. They appear in the sidebar under MY APPS and open in a new tab. "
               "You can also manage them from the **Manage links** button in the sidebar.")
    dialogs.links_editor("lk", in_dialog=False)

# ------------------------------------------------------------------ backup
with card("settings_4"):
    card_title("Backup & restore")
    st.caption("Download a full JSON backup regularly: it holds investors, the unit ledger and all trades. "
               "Restoring replaces ALL your current data.")
    a, b = st.columns(2)
    a.download_button("Download full backup (JSON)", db.export_json(c.engine, c.owner),
                      file_name=f"fund_backup_{dt.date.today():%Y%m%d}.json", mime="application/json",
                      icon=":material/download:", width="stretch")
    if not c.txns.empty:
        t = c.txns.merge(c.positions[["id", "symbol", "exchange"]], left_on="position_id", right_on="id",
                         suffixes=("", "_p"))[["date", "symbol", "exchange", "kind", "qty", "price", "charges", "reason"]]
        b.download_button("Download trades (CSV)", t.sort_values("date").to_csv(index=False),
                          file_name="trades.csv", icon=":material/table:", width="stretch")
    up = st.file_uploader("Restore from JSON backup", type=["json"])
    if up is not None:
        ok = st.checkbox("I understand this replaces all my current data")
        if st.button("Restore now", type="primary", disabled=not ok):
            try:
                db.import_json(c.engine, c.owner, up.getvalue().decode("utf-8"))
                state.bump()
                for k in ("sel_pos", "sel_inv"):
                    st.session_state.pop(k, None)
                st.session_state["flash"] = "Backup restored."
                st.rerun()
            except Exception as e:
                st.error(f"Restore failed: {e}")

# ------------------------------------------------------------------ sample / reset
with card("settings_5"):
    card_title("Sample data & reset")
    if c.investors.empty and c.positions.empty:
        st.caption("Load a demo fund (4 investors joining at different times, a withdrawal, 9 stocks with add-ons "
                   "and exits) to explore the app. You can delete it afterwards.")
        if st.button("Load sample fund", icon=":material/science:"):
            with st.spinner("Loading sample and pricing each investor's units…"):
                sample.load_sample(c.engine, c.owner)
                state.bump()
                fresh = state.build_ctx(c.owner)
                aud = state.audit_for(fresh)
                db.update_flows_bulk(c.engine, c.owner, {int(r.id): {"nav": float(r.nav_new), "units": float(r.units_new)}
                                                        for r in aud.itertuples()})
                state.bump()
            st.session_state["flash"] = "Sample fund loaded."
            st.rerun()
    else:
        with st.popover("Delete ALL my data", icon=":material/delete_forever:"):
            st.warning("This permanently deletes every investor, capital entry, position, trade, watchlist item "
                       "and setting for your account. Download a backup first.")
            txt = st.text_input("Type DELETE to confirm")
            if st.button("Delete everything", type="primary", disabled=txt != "DELETE"):
                db.import_json(c.engine, c.owner, '{"version": 2}')
                state.bump()
                for k in ("sel_pos", "sel_inv"):
                    st.session_state.pop(k, None)
                st.session_state["flash"] = "All data deleted."
                st.rerun()

st.caption(f"Database: {'Supabase / Postgres' if not state.db_url().startswith('sqlite') else 'local SQLite file'}")
