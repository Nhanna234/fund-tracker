"""Pure-pandas accounting: FIFO lots, position summaries, cash ledger, validation.

No Streamlit imports here, so it can be unit-tested directly.
"""
from collections import deque
import datetime as dt

import pandas as pd

KIND_ORDER = {"BUY": 0, "DIVIDEND": 1, "SELL": 2}
EPS = 1e-9


def ticker_for(symbol: str, exchange: str = "NSE") -> str:
    s = (symbol or "").strip().upper()
    if s.startswith("^") or "." in s:
        return s
    return s + (".BO" if exchange == "BSE" else ".NS")


def sort_txns(txns: pd.DataFrame) -> pd.DataFrame:
    if txns.empty:
        return txns
    t = txns.copy()
    t["_o"] = t["kind"].map(KIND_ORDER).fillna(9)
    t["_id"] = pd.to_numeric(t["id"], errors="coerce").fillna(10**12)
    return t.sort_values(["date", "_o", "_id"]).drop(columns=["_o", "_id"])


# ---------------------------------------------------------------------- FIFO
def fifo(txns: pd.DataFrame) -> dict:
    """Run FIFO over one position's transactions."""
    lots = deque()
    realized = []
    dividends = 0.0
    oversold = False
    buy_qty = buy_val = charges = 0.0
    sell_qty = sell_val = 0.0
    buys = []
    for t in sort_txns(txns).itertuples(index=False):
        qty, price, ch = float(t.qty), float(t.price), float(t.charges or 0)
        if t.kind == "BUY":
            lots.append({"qty": qty, "price": price, "cpu": ch / qty if qty else 0, "date": t.date, "txn_id": t.id})
            buy_qty += qty
            buy_val += qty * price
            charges += ch
            buys.append({"txn_id": t.id, "date": t.date, "qty": qty, "price": price})
        elif t.kind == "SELL":
            charges += ch
            sell_qty += qty
            sell_val += qty * price
            remaining, scpu = qty, (ch / qty if qty else 0)
            while remaining > EPS and lots:
                lot = lots[0]
                m = min(lot["qty"], remaining)
                pnl = m * (price - lot["price"]) - m * lot["cpu"] - m * scpu
                realized.append({
                    "sell_txn_id": t.id, "buy_txn_id": lot["txn_id"], "buy_date": lot["date"], "sell_date": t.date,
                    "qty": m, "buy_price": lot["price"], "sell_price": price,
                    "charges": m * lot["cpu"] + m * scpu, "pnl": pnl,
                    "days": (t.date - lot["date"]).days,
                })
                lot["qty"] -= m
                remaining -= m
                if lot["qty"] <= EPS:
                    lots.popleft()
            if remaining > EPS:
                oversold = True
        elif t.kind == "DIVIDEND":
            dividends += qty * price
    open_qty = sum(l["qty"] for l in lots)
    open_cost = sum(l["qty"] * l["price"] for l in lots)
    open_charges = sum(l["qty"] * l["cpu"] for l in lots)
    return {
        "open_qty": open_qty, "open_cost": open_cost, "open_charges": open_charges,
        "open_lots": list(lots), "realized_lots": realized, "dividends": dividends,
        "oversold": oversold, "buy_qty": buy_qty, "buy_val": buy_val, "sell_qty": sell_qty,
        "sell_val": sell_val, "charges": charges, "buys": buys,
    }


# ---------------------------------------------------------------------- summaries
def summarize(positions: pd.DataFrame, txns: pd.DataFrame, quotes: dict, today: dt.date = None):
    """Return (summary_df, realized_lots_df).

    quotes: {ticker: {"price": float, "prev_close": float|None, "source": str}}
    """
    today = today or dt.date.today()
    rows, lots_all = [], []
    for p in positions.itertuples(index=False):
        pt = txns[txns["position_id"] == p.id] if not txns.empty else txns
        trades = pt[pt["kind"].isin(["BUY", "SELL"])] if not pt.empty else pt
        if trades.empty:
            continue
        f = fifo(pt)
        tk = ticker_for(p.symbol, p.exchange)
        q = quotes.get(tk) or {}
        last_trade_price = float(sort_txns(trades).iloc[-1]["price"])
        if p.cmp_override is not None and not pd.isna(p.cmp_override):
            cmp, prev, src = float(p.cmp_override), None, "manual"
        elif q.get("price"):
            cmp, prev, src = q["price"], q.get("prev_close"), q.get("source", "live")
        else:
            cmp, prev, src = last_trade_price, None, "last trade"
        qty = f["open_qty"]
        status = "Active" if qty > EPS else "Closed"
        realized = sum(l["pnl"] for l in f["realized_lots"])
        avg_cost = f["open_cost"] / qty if qty > EPS else 0.0
        value = qty * cmp
        unreal = value - f["open_cost"] if status == "Active" else 0.0
        total_pnl = realized + f["dividends"] + unreal - f["open_charges"]
        buy_dates = [b["date"] for b in f["buys"]]
        sell_dates = pt[pt["kind"] == "SELL"]["date"].tolist()
        first_buy = min(buy_dates) if buy_dates else None
        exit_date = max(sell_dates) if (status == "Closed" and sell_dates) else None
        end = exit_date or today
        sl = None if p.stop_loss is None or pd.isna(p.stop_loss) else float(p.stop_loss)
        first_price = f["buys"][0]["price"] if f["buys"] else None
        r_mult = None
        if sl and first_price and sl < first_price and f["buy_qty"] > 0:
            r_mult = total_pnl / ((first_price - sl) * f["buy_qty"])
        rows.append({
            "id": p.id, "symbol": p.symbol, "ticker": tk, "exchange": p.exchange, "name": p.name or p.symbol,
            "sector": p.sector or "Unclassified", "mcap": p.mcap or "Unknown", "strategy": p.strategy or "Other",
            "conviction": p.conviction, "status": status, "qty": qty, "avg_cost": avg_cost,
            "wavg_buy": f["buy_val"] / f["buy_qty"] if f["buy_qty"] else 0.0,
            "avg_sell": f["sell_val"] / f["sell_qty"] if f["sell_qty"] else None,
            "invested": f["open_cost"], "cmp": cmp, "cmp_source": src, "prev_close": prev,
            "value": value, "unreal": unreal,
            "unreal_pct": unreal / f["open_cost"] * 100 if f["open_cost"] else 0.0,
            "day_chg": (cmp - prev) * qty if prev else 0.0,
            "day_chg_pct": (cmp / prev - 1) * 100 if prev else 0.0,
            "realized": realized, "dividends": f["dividends"], "charges": f["charges"],
            "total_pnl": total_pnl, "total_bought": f["buy_val"],
            "ret_pct": total_pnl / f["buy_val"] * 100 if f["buy_val"] else 0.0,
            "first_buy": first_buy, "exit_date": exit_date,
            "holding_days": (end - first_buy).days if first_buy else 0,
            "n_buys": len(f["buys"]), "n_sells": len(sell_dates),
            "stop_loss": sl, "target1": p.target1, "target2": p.target2, "review_by": p.review_by,
            "sl_dist_pct": (cmp - sl) / cmp * 100 if (sl and cmp) else None,
            "risk_to_sl": max(cmp - sl, 0) * qty if sl else None,
            "r_multiple": r_mult, "oversold": f["oversold"],
        })
        for l in f["realized_lots"]:
            lots_all.append({**l, "position_id": p.id, "symbol": p.symbol})
    summary = pd.DataFrame(rows)
    lots_df = pd.DataFrame(lots_all)
    return summary, lots_df


# ---------------------------------------------------------------------- cash ledger
def cash_events(flows: pd.DataFrame, txns: pd.DataFrame) -> pd.DataFrame:
    """Every cash movement. order 0 = inflow (processed first in a day), 1 = outflow."""
    ev = []
    for f in flows.itertuples(index=False):
        amt = float(f.amount) * (-1 if f.kind == "WITHDRAWAL" else 1)
        ev.append({"date": f.date, "order": 0 if amt >= 0 else 1, "amount": amt, "external": amt})
    for t in txns.itertuples(index=False):
        gross = float(t.qty) * float(t.price)
        ch = float(t.charges or 0)
        if t.kind == "BUY":
            ev.append({"date": t.date, "order": 1, "amount": -(gross + ch), "external": 0.0})
        elif t.kind == "SELL":
            ev.append({"date": t.date, "order": 0, "amount": gross - ch, "external": 0.0})
        elif t.kind == "DIVIDEND":
            ev.append({"date": t.date, "order": 0, "amount": gross, "external": 0.0})
    df = pd.DataFrame(ev, columns=["date", "order", "amount", "external"])
    return df.sort_values(["date", "order"]) if not df.empty else df


def cash_balance(flows, txns, as_of: dt.date = None) -> float:
    ev = cash_events(flows, txns)
    if ev.empty:
        return 0.0
    if as_of:
        ev = ev[ev["date"] <= as_of]
    return float(ev["amount"].sum())


def check_ledger(flows: pd.DataFrame, txns: pd.DataFrame, positions: pd.DataFrame = None) -> list:
    """Validate a (possibly hypothetical) ledger. Returns a list of human-readable errors."""
    errors = []
    ev = cash_events(flows, txns)
    if not ev.empty:
        ev = ev.copy()
        ev["bal"] = ev["amount"].cumsum()
        neg = ev[ev["bal"] < -0.5]
        if not neg.empty:
            first = neg.iloc[0]
            worst = neg["bal"].min()
            errors.append({"type": "cash", "date": first["date"], "shortfall": -worst,
                           "msg": f"Insufficient cash: balance would go negative on {first['date']:%d %b %Y} "
                                  f"(shortfall up to ₹{-worst:,.0f})."})
    if not txns.empty:
        names = dict(zip(positions["id"], positions["symbol"])) if positions is not None and not positions.empty else {}
        for pid, g in txns.groupby("position_id"):
            run = 0.0
            for t in sort_txns(g).itertuples(index=False):
                if t.kind == "BUY":
                    run += float(t.qty)
                elif t.kind == "SELL":
                    run -= float(t.qty)
                    if run < -EPS:
                        errors.append({"type": "qty", "date": t.date,
                                       "msg": f"{names.get(pid, 'Position')}: selling more than held on "
                                              f"{t.date:%d %b %Y} (short by {-run:g})."})
                        break
    return errors


def held_qty(txns: pd.DataFrame, position_id, as_of: dt.date = None) -> float:
    g = txns[txns["position_id"] == position_id]
    if as_of:
        g = g[g["date"] <= as_of]
    return float(g.loc[g["kind"] == "BUY", "qty"].sum() - g.loc[g["kind"] == "SELL", "qty"].sum())


def with_txn(txns: pd.DataFrame, new: dict = None, replace_id=None, remove_id=None) -> pd.DataFrame:
    """Return a hypothetical copy of txns with a change applied (for validation)."""
    t = txns.copy()
    if remove_id is not None:
        t = t[t["id"] != remove_id]
    if replace_id is not None:
        t = t[t["id"] != replace_id]
    if new is not None:
        row = {"id": replace_id if replace_id is not None else 10**12, "charges_auto": True, "reason": "", **new}
        t = pd.concat([t, pd.DataFrame([row])], ignore_index=True) if not t.empty else pd.DataFrame([row])
    return t


def with_flow(flows: pd.DataFrame, new: dict = None, remove_id=None, replace_id=None) -> pd.DataFrame:
    f = flows.copy()
    if remove_id is not None:
        f = f[f["id"] != remove_id]
    if replace_id is not None:
        f = f[f["id"] != replace_id]
    if new is not None:
        row = {"id": replace_id if replace_id is not None else 10**12, "note": "", "nav_manual": False, **new}
        f = pd.concat([f, pd.DataFrame([row])], ignore_index=True) if not f.empty else pd.DataFrame([row])
    return f
