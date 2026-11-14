"""Unit / NAV accounting for a pooled fund (pure pandas, no Streamlit).

The fund works like a mutual fund:

* Every rupee an investor puts in buys units at that day's NAV; every rupee taken
  out redeems units at that day's NAV. The first money in buys units at face value.
* NAV on a day = (fund value at that day's close - money that came in or went out
  that day) / units outstanding before that day's flows. So all flows on one day
  transact at the same NAV, and nobody's flow changes the NAV for anybody else.
* An investor's worth is simply units held x current NAV.

The NAV and units of each flow are stored with the flow (see db.CapitalFlow). `audit`
recomputes them from the trade ledger and price history so drift can be reviewed.
"""
import datetime as dt

import numpy as np
import pandas as pd

from .analytics import xirr
from .ledger import EPS, cash_balance, sort_txns, ticker_for

FACE_VALUE = 10.0
NAV_DP = 4          # NAV is kept to 4 decimals
UNIT_DP = 4         # units are kept to 4 decimals
DUST = 0.01         # a unit balance below this is treated as zero
DRIFT_PCT = 0.25    # audit flags a flow when stored and recomputed NAV differ by more than this


def _sign(kind) -> float:
    return -1.0 if kind == "WITHDRAWAL" else 1.0


def signed_units(flows: pd.DataFrame) -> pd.Series:
    if flows.empty:
        return pd.Series(dtype=float)
    return flows["units"].astype(float) * np.where(flows["kind"] == "WITHDRAWAL", -1.0, 1.0)


def signed_amount(flows: pd.DataFrame) -> pd.Series:
    if flows.empty:
        return pd.Series(dtype=float)
    return flows["amount"].astype(float) * np.where(flows["kind"] == "WITHDRAWAL", -1.0, 1.0)


def units_outstanding(flows: pd.DataFrame, as_of: dt.date = None, before: dt.date = None,
                      investor_id=None) -> float:
    """Units in issue. `as_of` includes that day's flows, `before` excludes them."""
    f = flows
    if f.empty:
        return 0.0
    if investor_id is not None:
        f = f[f["investor_id"] == investor_id]
    if as_of is not None:
        f = f[f["date"] <= as_of]
    if before is not None:
        f = f[f["date"] < before]
    u = float(signed_units(f).sum()) if not f.empty else 0.0
    return 0.0 if abs(u) < DUST else u


def units_for(amount: float, nav: float) -> float:
    return round(float(amount) / float(nav), UNIT_DP) if nav and nav > 0 else 0.0


# ====================================================================== fund value on a date
def _price_on(tk, trades, hist, quotes, d, today) -> float:
    q = (quotes or {}).get(tk)
    if d >= today and q and q.get("price"):
        return float(q["price"])
    if hist is not None and not hist.empty and tk in hist.columns:
        s = hist[tk].dropna()
        s = s[s.index <= pd.Timestamp(d)]
        if not s.empty:
            return float(s.iloc[-1])
    return float(sort_txns(trades).iloc[-1]["price"])  # no market data: last traded price


def holdings_value(txns, positions, hist, quotes, d: dt.date, today: dt.date = None) -> float:
    """Market value of shares held at the close of day `d`."""
    today = today or dt.date.today()
    if txns.empty or positions.empty:
        return 0.0
    tickers = {p.id: ticker_for(p.symbol, p.exchange) for p in positions.itertuples(index=False)}
    trades = txns[txns["kind"].isin(["BUY", "SELL"]) & (txns["date"] <= d)]
    total = 0.0
    for pid, g in trades.groupby("position_id"):
        qty = float(g.loc[g["kind"] == "BUY", "qty"].sum() - g.loc[g["kind"] == "SELL", "qty"].sum())
        if qty <= EPS or pid not in tickers:
            continue
        total += qty * _price_on(tickers[pid], g, hist, quotes, d, today)
    return total


def fund_value(flows, txns, positions, hist, quotes, d: dt.date, today: dt.date = None) -> float:
    """Cash + holdings at the close of day `d` (that day's flows included)."""
    return cash_balance(flows, txns, as_of=d) + holdings_value(txns, positions, hist, quotes, d, today)


def nav_on(flows, txns, positions, hist, quotes, d: dt.date, face: float = FACE_VALUE,
           today: dt.date = None, exclude_id=None) -> dict:
    """The NAV a flow dated `d` should transact at.

    Returns {nav, basis, units_before, value_before}. basis is "face" (first money in),
    "computed", or "carried" (every unit was redeemed earlier, so the last NAV is reused).
    """
    f = flows[flows["id"] != exclude_id] if (exclude_id is not None and not flows.empty) else flows
    units_before = units_outstanding(f, before=d)
    prior = f[f["date"] < d] if not f.empty else f
    if units_before <= DUST:
        if prior.empty:
            return {"nav": round(float(face), NAV_DP), "basis": "face", "units_before": 0.0, "value_before": 0.0}
        last = prior.sort_values(["date", "id"]).iloc[-1]
        return {"nav": round(float(last["nav"]), NAV_DP), "basis": "carried", "units_before": 0.0,
                "value_before": 0.0}
    same_day = f[f["date"] == d]
    day_net = float(signed_amount(same_day).sum()) if not same_day.empty else 0.0
    value_before = fund_value(f, txns, positions, hist, quotes, d, today) - day_net
    nav = value_before / units_before
    return {"nav": round(nav, NAV_DP) if nav > 0 else None, "basis": "computed",
            "units_before": units_before, "value_before": value_before}


# ====================================================================== validation
def _order(flows: pd.DataFrame) -> pd.DataFrame:
    """Chronological; within a day deposits are processed before withdrawals."""
    f = flows.copy()
    f["_o"] = np.where(f["kind"] == "WITHDRAWAL", 1, 0)
    f["_id"] = pd.to_numeric(f["id"], errors="coerce").fillna(10 ** 12)
    return f.sort_values(["date", "_o", "_id"]).drop(columns=["_o", "_id"])


def check_units(flows: pd.DataFrame, investors: pd.DataFrame = None) -> list:
    """An investor can never redeem more units than they hold on that date."""
    errors = []
    if flows.empty:
        return errors
    names = dict(zip(investors["id"], investors["name"])) if investors is not None and not investors.empty else {}
    for iid, g in flows.groupby("investor_id"):
        bal = 0.0
        for r in _order(g).itertuples(index=False):
            bal += _sign(r.kind) * float(r.units)
            if bal < -DUST:
                errors.append({"type": "units", "date": r.date,
                               "msg": f"{names.get(iid, 'Investor')} would redeem more units than they hold on "
                                      f"{r.date:%d %b %Y} (short by {-bal:,.4f} units)."})
                break
    return errors


# ====================================================================== investor views
def investor_summary(investors: pd.DataFrame, flows: pd.DataFrame, nav_now: float,
                     today: dt.date = None) -> pd.DataFrame:
    """One row per investor: units, share of the fund, money in/out, value, gain, XIRR."""
    today = today or dt.date.today()
    rows = []
    for inv in investors.itertuples(index=False):
        g = _order(flows[flows["investor_id"] == inv.id]) if not flows.empty else flows
        units = cost = deposits = withdrawals = realized = 0.0
        dates, amts = [], []
        for r in g.itertuples(index=False):
            amt, u = float(r.amount), float(r.units)
            if r.kind == "WITHDRAWAL":
                removed = cost * min(u / units, 1.0) if units > EPS else 0.0  # average-cost of the units redeemed
                cost -= removed
                realized += amt - removed
                units -= u
                withdrawals += amt
                amts.append(amt)
            else:
                units += u
                cost += amt
                deposits += amt
                amts.append(-amt)
            dates.append(r.date)
        if abs(units) < DUST:
            units, cost = 0.0, 0.0
        value = units * nav_now
        gain = value + withdrawals - deposits
        x = None
        if dates and (today - min(dates)).days >= 1:
            x = xirr(dates + [today], amts + [value]) if value > 0 else xirr(dates, amts)
        rows.append({
            "id": inv.id, "name": inv.name, "relation": inv.relation or "", "contact": inv.contact or "",
            "is_manager": bool(inv.is_manager), "notes": inv.notes or "",
            "units": units, "deposits": deposits, "withdrawals": withdrawals,
            "net_invested": deposits - withdrawals, "cost": cost,
            "avg_nav": cost / units if units > EPS else None,
            "value": value, "unreal": value - cost, "realized": realized, "gain": gain,
            "ret_pct": gain / deposits * 100 if deposits else None,
            "xirr": x, "first_date": min(dates) if dates else None, "last_date": max(dates) if dates else None,
            "n_flows": len(dates),
            "status": "Active" if units > 0 else ("Exited" if dates else "No capital yet"),
        })
    df = pd.DataFrame(rows)
    if not df.empty:
        total = df["units"].sum()
        df["share_pct"] = df["units"] / total * 100 if total > 0 else 0.0
    return df


def statement(flows: pd.DataFrame, investor_id=None) -> pd.DataFrame:
    """Unit ledger in date order with a running unit balance (one investor, or the whole fund)."""
    f = flows if investor_id is None else flows[flows["investor_id"] == investor_id]
    if f.empty:
        return f.assign(signed_units=[], signed_amount=[], balance=[])
    f = _order(f)
    f["signed_units"] = signed_units(f)
    f["signed_amount"] = signed_amount(f)
    f["balance"] = f["signed_units"].cumsum().round(UNIT_DP)
    f.loc[f["balance"].abs() < DUST, "balance"] = 0.0
    return f


# ====================================================================== daily NAV history
def _cum_on(idx: pd.DatetimeIndex, dates, values) -> pd.Series:
    """Cumulative sum of dated values, as it stands on each day of idx."""
    if len(values) == 0:
        return pd.Series(0.0, index=idx)
    s = pd.Series(list(values), index=pd.to_datetime(list(dates))).groupby(level=0).sum().sort_index().cumsum()
    return s.reindex(idx.union(s.index)).ffill().fillna(0.0).reindex(idx)


def attach_nav(daily: pd.DataFrame, flows: pd.DataFrame, face: float = FACE_VALUE) -> pd.DataFrame:
    """Add units / nav to the daily value history and make NAV the return series.

    twr, ret and drawdown are rewritten from NAV so every chart and statistic in the
    app agrees with the NAV investors actually transact at.
    """
    if daily.empty:
        return daily
    d = daily.copy()
    d["units"] = _cum_on(d.index, flows["date"], signed_units(flows)) if not flows.empty else 0.0
    nav = (d["value"] / d["units"]).where(d["units"] > DUST)
    d["nav"] = nav.ffill().fillna(face)
    d["twr"] = d["nav"] / face
    d["ret"] = d["twr"].pct_change().fillna(d["twr"].iloc[0] - 1)
    d["drawdown"] = d["twr"] / d["twr"].cummax() - 1
    return d


def investor_history(daily: pd.DataFrame, flows: pd.DataFrame, investor_id) -> pd.DataFrame:
    """Daily units, value and net money invested for one investor."""
    if daily.empty or "nav" not in daily:
        return pd.DataFrame()
    g = flows[flows["investor_id"] == investor_id] if not flows.empty else flows
    if g.empty:
        return pd.DataFrame()
    out = pd.DataFrame(index=daily.index)
    out["units"] = _cum_on(daily.index, g["date"], signed_units(g))
    out["invested"] = _cum_on(daily.index, g["date"], signed_amount(g))
    out["value"] = out["units"] * daily["nav"]
    first = pd.Timestamp(min(g["date"]))
    return out[out.index >= first - pd.Timedelta(days=3)]


# ====================================================================== audit / recompute
def audit(flows, txns, positions, hist, quotes, face: float = FACE_VALUE, today: dt.date = None) -> pd.DataFrame:
    """Recompute every flow's NAV and units from scratch, in date order.

    Locked flows (nav_manual) keep their stored NAV. A withdrawal that emptied the
    investor's account stays a full exit. Columns added: nav_new, units_new,
    nav_diff_pct, changed (stored and recomputed units differ), drift (NAV differs by
    more than DRIFT_PCT).
    """
    cols = list(flows.columns) + ["nav_new", "units_new", "nav_diff_pct", "changed", "drift"]
    if flows.empty:
        return pd.DataFrame(columns=cols)
    f = _order(flows)
    stored_bal, full_exit = {}, set()
    for r in f.itertuples(index=False):
        stored_bal[r.investor_id] = stored_bal.get(r.investor_id, 0.0) + _sign(r.kind) * float(r.units)
        if r.kind == "WITHDRAWAL" and abs(stored_bal[r.investor_id]) < DUST:
            full_exit.add(r.id)

    total_units, last_nav, bal, new = 0.0, None, {}, {}
    for d, g in f.groupby("date", sort=True):
        if total_units > DUST:
            day_net = float(signed_amount(g).sum())
            auto = (fund_value(flows, txns, positions, hist, quotes, d, today) - day_net) / total_units
        else:
            auto = last_nav if last_nav is not None else float(face)
        if not auto or auto <= 0:  # broken data: fall back to what was stored
            auto = None
        for r in g.itertuples(index=False):
            if r.nav_manual or auto is None:
                nav_new, units_new = float(r.nav), float(r.units)
            else:
                nav_new = round(auto, NAV_DP)
                units_new = units_for(r.amount, nav_new)
            held = bal.get(r.investor_id, 0.0)
            if r.kind == "WITHDRAWAL" and (r.id in full_exit or abs(held - units_new) < DUST):
                units_new = round(held, UNIT_DP)
            bal[r.investor_id] = held + _sign(r.kind) * units_new
            total_units += _sign(r.kind) * units_new
            new[r.id] = (nav_new, units_new)
        if auto is not None:
            last_nav = auto
    f["nav_new"] = [new[i][0] for i in f["id"]]
    f["units_new"] = [new[i][1] for i in f["id"]]
    f["nav_diff_pct"] = (f["nav_new"] / f["nav"].astype(float) - 1) * 100
    f["changed"] = ((f["units_new"] - f["units"].astype(float)).abs() > 10 ** -UNIT_DP / 2) | \
                   ((f["nav_new"] - f["nav"].astype(float)).abs() > 10 ** -NAV_DP / 2)
    units_diff_pct = ((f["units_new"] / f["units"].astype(float).replace(0, np.nan) - 1) * 100).fillna(0.0)
    f["drift"] = (f["nav_diff_pct"].abs() > DRIFT_PCT) | (units_diff_pct.abs() > DRIFT_PCT)
    return f
