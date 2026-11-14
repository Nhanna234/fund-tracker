"""Shared app context: DB engine, cached data loading, derived fund numbers."""
import datetime as dt
import os
from types import SimpleNamespace

import pandas as pd
import streamlit as st

from . import analytics, db, ledger, nav, prices
from .config import BENCHMARK, DEFAULT_FUND_NAME, DEFAULT_SETTINGS

LOCAL_DB = "sqlite:///" + os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "fund.db")


def db_url() -> str:
    try:
        return st.secrets["database"]["url"]
    except Exception:
        return os.environ.get("DATABASE_URL", LOCAL_DB)


def engine():
    return db.get_engine(db_url())


@st.cache_resource
def _versions() -> dict:
    return {}


def bump():
    """Invalidate cached data for the current owner after any write."""
    v = _versions()
    owner = st.session_state.get("owner")
    v[owner] = v.get(owner, 0) + 1


@st.cache_data(show_spinner=False, max_entries=50)
def _load(url: str, owner: str, ver: int) -> dict:
    return db.load_all(db.get_engine(url), owner)


def load(owner: str) -> dict:
    return _load(db_url(), owner, _versions().get(owner, 0))


def face_value(raw_settings: dict) -> float:
    try:
        v = float(raw_settings.get("face_value", nav.FACE_VALUE))
        return v if v > 0 else nav.FACE_VALUE
    except (TypeError, ValueError):
        return nav.FACE_VALUE


def build_ctx(owner: str) -> SimpleNamespace:
    eng = engine()
    data = load(owner)
    settings = {**DEFAULT_SETTINGS, **{k: float(v) for k, v in data["settings"].items()
                                         if k in DEFAULT_SETTINGS}}
    positions, txns, flows, watch = data["positions"], data["txns"], data["flows"], data["watch"]
    investors = data["investors"]

    # quotes for positions that are (or might be) active + watchlist
    tickers = set()
    if not positions.empty:
        tickers |= {ledger.ticker_for(p.symbol, p.exchange) for p in positions.itertuples(index=False)}
    if not watch.empty:
        tickers |= {ledger.ticker_for(w.symbol, w.exchange) for w in watch.itertuples(index=False)}
    quotes = prices.get_quotes(eng, tickers) if tickers else {}

    summary, lots = ledger.summarize(positions, txns, quotes)
    cash = ledger.cash_balance(flows, txns)
    equity = float(summary.loc[summary["status"] == "Active", "value"].sum()) if not summary.empty else 0.0
    total = cash + equity
    if not summary.empty:
        summary["weight"] = summary["value"] / total * 100 if total > 0 else 0.0
    active = summary[summary["status"] == "Active"] if not summary.empty else summary
    deposits = float(flows.loc[flows["kind"] != "WITHDRAWAL", "amount"].sum()) if not flows.empty else 0.0
    withdrawals = float(flows.loc[flows["kind"] == "WITHDRAWAL", "amount"].sum()) if not flows.empty else 0.0
    sources = {q.get("source") for q in quotes.values()}

    # The price each holding is valued at today (manual override > live quote > last trade),
    # keyed by ticker, so NAV maths uses exactly the numbers shown on the dashboard.
    quotes_eff = dict(quotes)
    for s in active.itertuples(index=False) if not active.empty else []:
        quotes_eff[s.ticker] = {**quotes.get(s.ticker, {}), "price": float(s.cmp)}

    face = face_value(data["settings"])
    units = nav.units_outstanding(flows)
    nav_now = total / units if units > 0 else face
    day = float(active["day_chg"].sum()) if not active.empty else 0.0
    inv_summary = nav.investor_summary(investors, flows, nav_now) if not investors.empty else pd.DataFrame()
    return SimpleNamespace(
        owner=owner, engine=eng, data=data, settings=settings,
        positions=positions, txns=txns, flows=flows, watch=watch, thesis=data["thesis"],
        investors=investors, inv_summary=inv_summary,
        quotes=quotes, quotes_eff=quotes_eff, summary=summary, lots=lots, active=active,
        cash=cash, equity=equity, total=total, net_capital=deposits - withdrawals,
        deposits=deposits, withdrawals=withdrawals,
        cash_pct=(cash / total * 100) if total > 0 else None,
        face=face, units=units, nav=nav_now, day=day,
        nav_prev=(total - day) / units if units > 0 else face,
        fund_name=(data["settings"].get("fund_name") or DEFAULT_FUND_NAME),
        price_status="live" if sources == {"live"} else ("partial" if "live" in sources else ("cache" if sources else "none")),
    )


def history_for(ctx) -> tuple:
    """(daily closes DataFrame, benchmark Series) from the first ledger date."""
    dates = []
    if not ctx.flows.empty:
        dates.append(min(ctx.flows["date"]))
    if not ctx.txns.empty:
        dates.append(min(ctx.txns["date"]))
    if not dates:
        return pd.DataFrame(), pd.Series(dtype=float)
    start = (min(dates) - dt.timedelta(days=7)).isoformat()
    tickers = tuple(sorted({ledger.ticker_for(p.symbol, p.exchange) for p in ctx.positions.itertuples(index=False)}))
    hist = prices.get_history(tickers + (BENCHMARK,), start)
    bench = hist[BENCHMARK] if (not hist.empty and BENCHMARK in hist.columns) else pd.Series(dtype=float)
    return hist, bench


def daily_for(ctx) -> pd.DataFrame:
    """Daily fund history with units and NAV (NAV drives twr / drawdown)."""
    hist, bench = history_for(ctx)
    daily = analytics.build_daily(ctx.flows, ctx.txns, ctx.positions, hist, ctx.quotes_eff, bench)
    return nav.attach_nav(daily, ctx.flows, ctx.face)


def nav_quote(ctx, date: dt.date, flows: pd.DataFrame = None, exclude_id=None) -> dict:
    """The NAV a flow dated `date` should transact at (see nav.nav_on)."""
    hist, _ = history_for(ctx)
    return nav.nav_on(ctx.flows if flows is None else flows, ctx.txns, ctx.positions, hist, ctx.quotes_eff,
                      date, ctx.face, exclude_id=exclude_id)


def audit_for(ctx, flows: pd.DataFrame = None) -> pd.DataFrame:
    hist, _ = history_for(ctx)
    return nav.audit(ctx.flows if flows is None else flows, ctx.txns, ctx.positions, hist, ctx.quotes_eff, ctx.face)


def ctx() -> SimpleNamespace:
    return st.session_state["ctx"]
