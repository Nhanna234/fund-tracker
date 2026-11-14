"""Portfolio analytics: daily equity curve, returns, trade stats, insights, tax, alerts."""
import datetime as dt
import math

import numpy as np
import pandas as pd

from .config import LTCG_MIN_DAYS, NEW_REGIME_FROM_FY, TAX_RULES
from .ledger import cash_events, sort_txns, ticker_for


# ====================================================================== equity curve
def build_daily(flows, txns, positions, hist: pd.DataFrame, quotes: dict,
                bench: pd.Series = None, today: dt.date = None) -> pd.DataFrame:
    """Daily portfolio reconstruction.

    value(D) = cash(D) + Σ qty_held(D) × close(D). Handles staggered entries/exits
    and capital flows. Returns columns: cash, holdings, value, flow, twr, drawdown, bench.
    """
    today = today or dt.date.today()
    dates = []
    if not flows.empty:
        dates.append(min(flows["date"]))
    if not txns.empty:
        dates.append(min(txns["date"]))
    if not dates:
        return pd.DataFrame()
    start = pd.Timestamp(min(dates))
    idx = pd.bdate_range(start, pd.Timestamp(today))
    if len(idx) == 0:
        idx = pd.DatetimeIndex([pd.Timestamp(today)])

    def daily_cum(series_by_date: pd.Series) -> pd.Series:
        s = series_by_date.groupby(level=0).sum().sort_index().cumsum()
        s.index = pd.to_datetime(s.index)
        return s.reindex(idx.union(s.index)).ffill().fillna(0.0).reindex(idx)

    ev = cash_events(flows, txns)
    cash = daily_cum(ev.set_index("date")["amount"]) if not ev.empty else pd.Series(0.0, index=idx)

    # external flows land on the next business day (for TWR)
    flow = pd.Series(0.0, index=idx)
    if not ev.empty:
        ext = ev[ev["external"] != 0]
        for d, amt in zip(ext["date"], ext["external"]):
            pos = idx.searchsorted(pd.Timestamp(d))
            if pos < len(idx):
                flow.iloc[pos] += amt

    holdings = pd.Series(0.0, index=idx)
    if not txns.empty and not positions.empty:
        pos_map = {p.id: ticker_for(p.symbol, p.exchange) for p in positions.itertuples(index=False)}
        trade = txns[txns["kind"].isin(["BUY", "SELL"])].copy()
        trade["signed"] = np.where(trade["kind"] == "BUY", trade["qty"], -trade["qty"]).astype(float)
        for pid, g in trade.groupby("position_id"):
            tk = pos_map.get(pid)
            if tk is None:
                continue
            qty = daily_cum(g.set_index("date")["signed"])
            price = _price_series(tk, g, hist, quotes, idx)
            holdings = holdings + qty * price

    df = pd.DataFrame({"cash": cash, "holdings": holdings, "flow": flow})
    df["value"] = df["cash"] + df["holdings"]

    # time-weighted return index
    prev = df["value"].shift(1)
    r = np.where(prev > 0, (df["value"] - df["flow"]) / prev - 1, 0.0)
    r[0] = 0.0
    df["ret"] = r
    df["twr"] = (1 + df["ret"]).cumprod()
    df["drawdown"] = df["twr"] / df["twr"].cummax() - 1

    if bench is not None and not bench.empty:
        b = bench.copy()
        b.index = pd.to_datetime(b.index)
        b = b.reindex(idx.union(b.index)).ffill().reindex(idx).bfill()
        if b.notna().any() and b.iloc[0]:
            df["bench"] = b / b.iloc[0]
    return df


def _price_series(tk, trades, hist, quotes, idx) -> pd.Series:
    """Close prices for one ticker on idx; falls back to trade prices when history is missing."""
    s = None
    if hist is not None and not hist.empty and tk in hist.columns:
        s = hist[tk].dropna()
    if s is None or s.empty:
        tp = sort_txns(trades).groupby("date")["price"].last()
        tp.index = pd.to_datetime(tp.index)
        s = tp
    s = s.copy()
    q = quotes.get(tk)
    if q and q.get("price"):
        s.loc[idx[-1]] = q["price"]  # most recent price wins for "today"
    s = s[~s.index.duplicated(keep="last")].sort_index()
    return s.reindex(idx.union(s.index)).ffill().bfill().reindex(idx)


# ====================================================================== returns
def xirr(dates, amounts, guess_lo=-0.9999, guess_hi=10.0):
    """Annualised IRR for irregular cash flows (investor view: deposits < 0). None if undefined."""
    if len(amounts) < 2 or not (min(amounts) < 0 < max(amounts)):
        return None
    d0 = min(dates)
    years = np.array([(d - d0).days / 365.0 for d in dates])
    amts = np.array(amounts, dtype=float)

    def npv(r):
        return float(np.sum(amts / (1 + r) ** years))

    lo, hi = guess_lo, guess_hi
    f_lo, f_hi = npv(lo), npv(hi)
    if f_lo * f_hi > 0:
        return None
    for _ in range(200):
        mid = (lo + hi) / 2
        f_mid = npv(mid)
        if abs(f_mid) < 1e-6:
            break
        if f_lo * f_mid < 0:
            hi, f_hi = mid, f_mid
        else:
            lo, f_lo = mid, f_mid
    return mid


def portfolio_xirr(flows, current_value, today=None):
    today = today or dt.date.today()
    if flows.empty:
        return None
    dates = list(flows["date"])
    amts = [(-a if k != "WITHDRAWAL" else a) for k, a in zip(flows["kind"], flows["amount"])]
    dates.append(today)
    amts.append(current_value)
    if (today - min(dates)).days < 1:
        return None
    return xirr(dates, amts)


def monthly_returns(daily: pd.DataFrame) -> pd.DataFrame:
    """Year × month table of TWR returns (%)."""
    if daily.empty:
        return pd.DataFrame()
    me = daily["twr"].resample("ME").last()
    base = pd.concat([pd.Series([1.0], index=[me.index[0] - pd.offsets.MonthEnd(1)]), me])
    ret = (base.pct_change().dropna() * 100)
    tbl = pd.DataFrame({"year": ret.index.year, "month": ret.index.month, "ret": ret.values})
    return tbl.pivot(index="year", columns="month", values="ret").reindex(columns=range(1, 13))


def cagr(twr_end, days):
    if days < 30 or twr_end <= 0:
        return None
    return twr_end ** (365.0 / days) - 1


# ====================================================================== trade stats
def trade_stats(summary: pd.DataFrame) -> dict:
    closed = summary[summary["status"] == "Closed"] if not summary.empty else summary
    if closed.empty:
        return {"n": 0}
    pnl = closed["total_pnl"]
    wins, losses = closed[pnl > 0], closed[pnl <= 0]
    n = len(closed)
    wr = len(wins) / n
    avg_win = wins["total_pnl"].mean() if len(wins) else 0.0
    avg_loss = losses["total_pnl"].mean() if len(losses) else 0.0
    gross_win, gross_loss = wins["total_pnl"].sum(), -losses["total_pnl"].sum()
    rm = closed["r_multiple"].dropna()
    return {
        "n": n, "wins": len(wins), "losses": len(losses), "win_rate": wr,
        "avg_win": avg_win, "avg_loss": avg_loss,
        "avg_win_pct": wins["ret_pct"].mean() if len(wins) else 0.0,
        "avg_loss_pct": losses["ret_pct"].mean() if len(losses) else 0.0,
        "payoff": (avg_win / abs(avg_loss)) if avg_loss else None,
        "profit_factor": (gross_win / gross_loss) if gross_loss > 0 else None,
        "expectancy": wr * avg_win + (1 - wr) * avg_loss,
        "days_win": wins["holding_days"].mean() if len(wins) else None,
        "days_loss": losses["holding_days"].mean() if len(losses) else None,
        "avg_r": rm.mean() if len(rm) else None,
        "best": closed.loc[pnl.idxmax()], "worst": closed.loc[pnl.idxmin()],
        "total": pnl.sum(),
    }


def breakdown(summary: pd.DataFrame, by: str) -> pd.DataFrame:
    if summary.empty:
        return pd.DataFrame()
    g = summary.groupby(by, dropna=False)
    out = pd.DataFrame({
        "positions": g.size(),
        "active": g.apply(lambda x: (x["status"] == "Active").sum(), include_groups=False),
        "value": g["value"].sum(),
        "total_pnl": g["total_pnl"].sum(),
        "bought": g["total_bought"].sum(),
    })
    closed = summary[summary["status"] == "Closed"]
    if not closed.empty:
        cg = closed.groupby(by, dropna=False)
        out["closed"] = cg.size()
        out["win_rate"] = cg.apply(lambda x: (x["total_pnl"] > 0).mean() * 100, include_groups=False)
    else:
        out["closed"], out["win_rate"] = 0, np.nan
    out["ret_pct"] = out["total_pnl"] / out["bought"].replace(0, np.nan) * 100
    return out.fillna({"closed": 0}).sort_values("total_pnl", ascending=False)


def addon_effectiveness(summary: pd.DataFrame, txns: pd.DataFrame) -> pd.DataFrame:
    """Every buy after the first one in a position, judged against CMP (active) or avg exit (closed)."""
    rows = []
    if summary.empty or txns.empty:
        return pd.DataFrame()
    for s in summary.itertuples(index=False):
        buys = sort_txns(txns[(txns["position_id"] == s.id) & (txns["kind"] == "BUY")])
        if len(buys) < 2:
            continue
        ref = s.cmp if s.status == "Active" else (s.avg_sell or s.cmp)
        first_price = float(buys.iloc[0]["price"])
        for i, b in enumerate(buys.iloc[1:].itertuples(index=False), start=2):
            rows.append({"symbol": s.symbol, "buy_no": i, "date": b.date, "qty": b.qty, "price": b.price,
                         "vs_first_pct": (b.price / first_price - 1) * 100,
                         "ref_price": ref, "ret_pct": (ref / b.price - 1) * 100,
                         "pnl": (ref - b.price) * b.qty, "type": "Pyramid (higher)" if b.price > first_price else "Average down"})
    return pd.DataFrame(rows)


def insights(summary: pd.DataFrame, stats: dict, addons: pd.DataFrame, cash_pct: float,
             settings: dict) -> list:
    """Plain-English behaviour observations."""
    out = []
    if summary.empty:
        return out
    active = summary[summary["status"] == "Active"]
    if stats.get("n", 0) >= 3:
        dw, dl = stats.get("days_win"), stats.get("days_loss")
        if dw and dl:
            if dl > dw * 1.2:
                out.append(("warn", f"You hold losers **{dl / dw:.1f}× longer** than winners "
                                    f"({dl:.0f} vs {dw:.0f} days). Consider honouring stop-losses faster."))
            elif dw > dl * 1.2:
                out.append(("good", f"You let winners run **{dw / dl:.1f}× longer** than losers "
                                    f"({dw:.0f} vs {dl:.0f} days) — a healthy trait."))
        if stats.get("payoff"):
            p = stats["payoff"]
            be = 1 / (1 + p) * 100
            out.append(("info", f"Your average win is **{p:.2f}×** your average loss, so you break even at a "
                                f"**{be:.0f}%** win rate. Current win rate: **{stats['win_rate'] * 100:.0f}%**."))
        if stats.get("expectancy") is not None:
            e = stats["expectancy"]
            out.append(("good" if e > 0 else "warn",
                        f"Expectancy per closed trade is **₹{e:,.0f}** — "
                        f"{'your process is making money on average.' if e > 0 else 'your process is losing money on average.'}"))
        closed = summary[summary["status"] == "Closed"]
        bys = closed.groupby("strategy")["total_pnl"].agg(["count", lambda x: (x > 0).mean() * 100])
        bys.columns = ["n", "wr"]
        bys = bys[bys["n"] >= 2]
        if len(bys) >= 2:
            best, worst = bys["wr"].idxmax(), bys["wr"].idxmin()
            if best != worst:
                out.append(("info", f"**{best}** trades win {bys.loc[best, 'wr']:.0f}% of the time vs "
                                    f"**{worst}** at {bys.loc[worst, 'wr']:.0f}%."))
    if addons is not None and not addons.empty and len(addons) >= 2:
        for t, g in addons.groupby("type"):
            if len(g) >= 2:
                out.append(("info", f"**{t}** add-ons: {(g['ret_pct'] > 0).mean() * 100:.0f}% in profit "
                                    f"(avg {g['ret_pct'].mean():+.1f}%, {len(g)} add-ons)."))
    if not active.empty:
        no_sl = active["stop_loss"].isna().sum()
        if no_sl:
            out.append(("warn", f"**{no_sl} of {len(active)}** active holdings have no stop-loss set."))
        total = active["value"].sum()
        if total > 0:
            top = active.sort_values("value", ascending=False).head(3)
            top_pct = top["value"].sum() / total * 100
            out.append(("info", f"Top 3 holdings make up **{top_pct:.0f}%** of your equity "
                                f"({', '.join(top['symbol'])})."))
        losers = active[active["unreal_pct"] < -15]
        if not losers.empty:
            out.append(("warn", f"{len(losers)} holding(s) are down more than 15%: "
                                f"{', '.join(losers['symbol'])}. Re-check the thesis."))
    if cash_pct is not None:
        if cash_pct > 40:
            out.append(("info", f"**{cash_pct:.0f}%** of the portfolio is in cash."))
        elif cash_pct < 3:
            out.append(("info", f"Only **{cash_pct:.1f}%** cash left — little room for add-ons."))
    return out


# ====================================================================== tax
def fy_of(d: dt.date) -> int:
    """FY start year: 2025 means FY 2025-26."""
    return d.year if d.month >= 4 else d.year - 1


def fy_label(y: int) -> str:
    return f"FY {y}-{str(y + 1)[-2:]}"


def tax_lots(lots: pd.DataFrame) -> pd.DataFrame:
    if lots.empty:
        return lots
    t = lots.copy()
    t["fy"] = t["sell_date"].apply(fy_of)
    t["term"] = np.where(t["days"] > LTCG_MIN_DAYS, "LTCG", "STCG")
    return t


def tax_summary(lots: pd.DataFrame) -> pd.DataFrame:
    t = tax_lots(lots)
    if t.empty:
        return pd.DataFrame()
    rows = []
    for fy, g in t.groupby("fy"):
        rules = TAX_RULES["new" if fy >= NEW_REGIME_FROM_FY else "old"]
        st_ = g.loc[g["term"] == "STCG", "pnl"].sum()
        lt_ = g.loc[g["term"] == "LTCG", "pnl"].sum()
        # set-off: short-term loss can offset LTCG; long-term loss only LTCG
        st_net, lt_net = st_, lt_
        if st_net < 0 and lt_net > 0:
            used = min(-st_net, lt_net)
            st_net += used
            lt_net -= used
        taxable_lt = max(lt_net - rules["exemption"], 0)
        tax = max(st_net, 0) * rules["stcg"] + taxable_lt * rules["ltcg"]
        rows.append({"FY": fy_label(fy), "fy": fy, "STCG": st_, "LTCG": lt_,
                     "LTCG exemption": rules["exemption"], "Taxable LTCG": taxable_lt,
                     "STCG rate": rules["stcg"], "LTCG rate": rules["ltcg"],
                     "Est. tax": tax, "Carry-fwd loss": min(st_net, 0) + min(lt_net, 0)})
    return pd.DataFrame(rows).sort_values("fy", ascending=False)


# ====================================================================== alerts
def alerts(summary: pd.DataFrame, total_value: float, settings: dict, watch: pd.DataFrame = None,
           watch_quotes: dict = None, today: dt.date = None) -> list:
    today = today or dt.date.today()
    out = []
    conc = float(settings.get("concentration_pct", 15))
    near = float(settings.get("near_sl_pct", 5))
    act = summary[summary["status"] == "Active"] if not summary.empty else summary
    for s in act.itertuples(index=False):
        if s.stop_loss and s.cmp <= s.stop_loss:
            out.append(("critical", s.symbol, f"Stop-loss breached — CMP ₹{s.cmp:,.2f} ≤ SL ₹{s.stop_loss:,.2f}"))
        elif s.stop_loss and s.sl_dist_pct is not None and s.sl_dist_pct <= near:
            out.append(("serious", s.symbol, f"Within {s.sl_dist_pct:.1f}% of stop-loss ₹{s.stop_loss:,.2f}"))
        for lbl in ("target2", "target1"):
            tgt = getattr(s, lbl)
            if tgt and not pd.isna(tgt) and s.cmp >= tgt:
                out.append(("good", s.symbol, f"{'Target 2' if lbl == 'target2' else 'Target 1'} hit — CMP ₹{s.cmp:,.2f} ≥ ₹{tgt:,.2f}"))
                break
        if s.review_by and not pd.isna(s.review_by) and s.review_by <= today:
            out.append(("warning", s.symbol, f"Thesis review due since {s.review_by:%d %b %Y}"))
        if total_value > 0 and s.value / total_value * 100 > conc:
            out.append(("warning", s.symbol, f"Concentration {s.value / total_value * 100:.1f}% of portfolio (limit {conc:.0f}%)"))
    if watch is not None and not watch.empty and watch_quotes:
        for w in watch.itertuples(index=False):
            q = watch_quotes.get(ticker_for(w.symbol, w.exchange))
            if not q or not w.trigger_price or pd.isna(w.trigger_price):
                continue
            hit = q["price"] <= w.trigger_price if (w.trigger_dir or "below") == "below" else q["price"] >= w.trigger_price
            if hit:
                out.append(("info", w.symbol, f"Watchlist trigger hit — ₹{q['price']:,.2f} is {w.trigger_dir} ₹{w.trigger_price:,.2f}"))
    order = {"critical": 0, "serious": 1, "warning": 2, "good": 3, "info": 4}
    return sorted(out, key=lambda a: order.get(a[0], 9))


# ====================================================================== win/loss sequence
def zone_of(ret_pct: float) -> str:
    from .config import LOSS_PCT, WIN_PCT
    if ret_pct > WIN_PCT:
        return "Win"
    if ret_pct < LOSS_PCT:
        return "Loss"
    return "Flat"


def sequence(summary: pd.DataFrame) -> pd.DataFrame:
    """Positions in order of first entry, with return % (CMP-based for active) and zone."""
    if summary.empty:
        return pd.DataFrame()
    s = summary.dropna(subset=["first_buy"]).sort_values(["first_buy", "id"]).reset_index(drop=True)
    s = s[["id", "symbol", "name", "status", "first_buy", "exit_date", "ret_pct", "total_pnl",
           "holding_days", "strategy"]].copy()
    s["zone"] = s["ret_pct"].apply(zone_of)
    s["n"] = range(1, len(s) + 1)
    return s


def streaks(zones: list) -> dict:
    """Current and longest win / loss streaks. A Flat result breaks a streak."""
    best = {"Win": 0, "Loss": 0}
    run_zone, run = None, 0
    for z in zones:
        if z == run_zone:
            run += 1
        else:
            run_zone, run = z, 1
        if z in best:
            best[z] = max(best[z], run)
    return {"current_zone": run_zone, "current_len": run, "best_win": best["Win"], "best_loss": best["Loss"]}


def market_regime(bench: pd.Series, span: int = 50) -> pd.DataFrame:
    """Nifty close, its EMA and an Uptrend/Downtrend flag (close above/below EMA)."""
    if bench is None or bench.empty:
        return pd.DataFrame()
    b = bench.dropna().sort_index()
    df = pd.DataFrame({"close": b, "ema": b.ewm(span=span, adjust=False).mean()})
    df["gap_pct"] = (df["close"] / df["ema"] - 1) * 100
    df["regime"] = np.where(df["close"] >= df["ema"], "Uptrend", "Downtrend")
    return df


def tag_entries(seq: pd.DataFrame, regime: pd.DataFrame) -> pd.DataFrame:
    """Attach the market regime on each position's entry date (last trading day on/before it)."""
    out = seq.copy()
    if out.empty or regime.empty:
        out["regime"], out["nifty"], out["gap_pct"] = None, np.nan, np.nan
        return out
    pos = regime.index.searchsorted(pd.to_datetime(out["first_buy"]), side="right") - 1
    ok = pos >= 0
    for col, src in (("regime", "regime"), ("nifty", "close"), ("gap_pct", "gap_pct")):
        vals = regime[src].to_numpy()
        out[col] = [vals[p] if good else None for p, good in zip(pos, ok)]
    return out


def regime_table(tagged: pd.DataFrame) -> pd.DataFrame:
    t = tagged.dropna(subset=["regime"])
    if t.empty:
        return pd.DataFrame()
    g = t.groupby("regime")
    return pd.DataFrame({
        "Entries": g.size(),
        "Wins": g.apply(lambda x: (x["zone"] == "Win").sum(), include_groups=False),
        "Flat": g.apply(lambda x: (x["zone"] == "Flat").sum(), include_groups=False),
        "Losses": g.apply(lambda x: (x["zone"] == "Loss").sum(), include_groups=False),
        "Win %": g.apply(lambda x: (x["zone"] == "Win").mean() * 100, include_groups=False),
        "Avg return %": g["ret_pct"].mean(),
        "Total P&L": g["total_pnl"].sum(),
    }).reset_index().rename(columns={"regime": "Nifty at entry"})
