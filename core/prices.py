"""Market data via yfinance, cached in Streamlit and backed by a DB price cache."""
import datetime as dt

import pandas as pd
import streamlit as st
import yfinance as yf

from . import db
from .config import MCAP_CUTOFFS


def _close_frame(df: pd.DataFrame, tickers) -> dict:
    """Extract {ticker: Close series} from a yf.download result (single or multi)."""
    out = {}
    if df is None or df.empty:
        return out
    multi = isinstance(df.columns, pd.MultiIndex)
    for t in tickers:
        try:
            if multi:
                lvl0 = df.columns.get_level_values(0)
                sub = df[t] if t in lvl0 else df.xs(t, axis=1, level=1)
            else:
                sub = df
            s = sub["Close"].dropna()
            if not s.empty:
                s.index = pd.to_datetime(s.index).tz_localize(None).normalize()
                out[t] = s.astype(float)
        except Exception:
            continue
    return out


@st.cache_data(ttl=300, show_spinner=False)
def _fetch_quotes(tickers: tuple) -> dict:
    if not tickers:
        return {}
    try:
        df = yf.download(list(tickers), period="10d", interval="1d", auto_adjust=False,
                         progress=False, group_by="ticker", threads=True)
    except Exception:
        return {}
    out = {}
    for t, s in _close_frame(df, tickers).items():
        out[t] = {"price": float(s.iloc[-1]),
                  "prev_close": float(s.iloc[-2]) if len(s) > 1 else None,
                  "asof": s.index[-1].date().isoformat()}
    return out


def get_quotes(engine, tickers) -> dict:
    """Live quotes with DB fallback. Each quote carries a `source` of live / cache."""
    tickers = tuple(sorted(set(t for t in tickers if t)))
    if not tickers:
        return {}
    live = _fetch_quotes(tickers)
    try:
        db.put_cached_prices(engine, live)
    except Exception:
        pass
    quotes = {t: {**q, "source": "live"} for t, q in live.items()}
    missing = [t for t in tickers if t not in quotes]
    if missing:
        try:
            for t, q in db.get_cached_prices(engine, missing).items():
                quotes[t] = {**q, "source": "cache"}
        except Exception:
            pass
    return quotes


def refresh_quotes():
    _fetch_quotes.clear()
    get_history.clear()


@st.cache_data(ttl=3600, show_spinner=False)
def get_history(tickers: tuple, start: str) -> pd.DataFrame:
    """Daily closes (columns = tickers) from `start` to today."""
    if not tickers:
        return pd.DataFrame()
    try:
        df = yf.download(list(tickers), start=start, interval="1d", auto_adjust=False,
                         progress=False, group_by="ticker", threads=True)
    except Exception:
        return pd.DataFrame()
    closes = _close_frame(df, tickers)
    return pd.DataFrame(closes) if closes else pd.DataFrame()


@st.cache_data(ttl=6 * 3600, show_spinner=False)
def get_monthly_ohlc(ticker: str, years: int = 10) -> pd.DataFrame:
    try:
        df = yf.Ticker(ticker).history(period=f"{years}y", interval="1mo", auto_adjust=False)
    except Exception:
        return pd.DataFrame()
    if df is None or df.empty:
        return pd.DataFrame()
    df.index = pd.to_datetime(df.index).tz_localize(None)
    return df[["Open", "High", "Low", "Close", "Volume"]].dropna(subset=["Close"])


def mcap_bucket(market_cap) -> str:
    if not market_cap:
        return "Unknown"
    for cut, name in MCAP_CUTOFFS:
        if market_cap >= cut:
            return name
    return "Unknown"


@st.cache_data(ttl=24 * 3600, show_spinner=False)
def lookup_info(ticker: str) -> dict:
    """Best-effort company details. Returns {} on failure."""
    try:
        info = yf.Ticker(ticker).info or {}
    except Exception:
        return {}
    if not info or not (info.get("longName") or info.get("shortName")):
        return {}
    return {"name": info.get("longName") or info.get("shortName"),
            "sector": info.get("sector") or "Unclassified",
            "industry": info.get("industry") or "",
            "mcap": mcap_bucket(info.get("marketCap")),
            "price": info.get("currentPrice") or info.get("regularMarketPrice")}
