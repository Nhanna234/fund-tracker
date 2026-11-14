import pandas as pd
import streamlit as st

from core import analytics as an
from core import charts, sequence_view, state
from core.config import BENCHMARK_NAME
from core.ui import card, INSIGHT_ICON, compact, empty_state, inr, page_header, pct, style_table

c = state.ctx()
page_header("Analytics", "How the fund is doing, how good your trades are, and where the risk sits.",
            eyebrow="Insights")

if c.summary.empty:
    empty_state("Add positions to see analytics.", "views/new_position.py", "New position")
    st.stop()

daily = state.daily_for(c)   # twr / drawdown here are driven by NAV per unit
stats = an.trade_stats(c.summary)
addons = an.addon_effectiveness(c.summary, c.txns)
act = c.active

# ------------------------------------------------------------------ insights
ins = an.insights(c.summary, stats, addons, c.cash_pct, c.settings)
if ins:
    with card("analytics_1"):
        st.markdown("**What your data says**")
        for kind, text in ins:
            st.markdown(f"{INSIGHT_ICON.get(kind, '')} {text}")

t_seq, t_perf, t_trades, t_break, t_risk, t_add = st.tabs(
    ["🟩 Win/loss sequence", "📈 Performance", "🎯 Trade quality", "🧩 Breakdown", "🛡️ Risk", "➕ Add-ons"])

# ------------------------------------------------------------------ win/loss sequence + market
with t_seq:
    sequence_view.render(c)

# ------------------------------------------------------------------ performance
with t_perf:
    if daily.empty:
        st.caption("Not enough history.")
    else:
        days = (daily.index[-1] - daily.index[0]).days
        cg = an.cagr(daily["twr"].iloc[-1], days)
        mdd = daily["drawdown"].min()
        vol = daily["ret"].std() * (252 ** 0.5) * 100 if len(daily) > 20 else None
        k = st.columns(5)
        k[0].metric("NAV return", pct((daily["twr"].iloc[-1] - 1) * 100), help="Growth of one unit since day one")
        k[1].metric("CAGR (NAV)", pct(cg * 100) if cg is not None else "—", help="Shown after 30 days")
        k[2].metric(f"{BENCHMARK_NAME}", pct((daily["bench"].iloc[-1] - 1) * 100) if "bench" in daily else "—")
        k[3].metric("Max drawdown", pct(mdd * 100))
        k[4].metric("Volatility (ann.)", pct(vol, 1, sign=False) if vol else "—")

        a, b = st.columns(2, gap="medium")
        with a:
            with card("analytics_2"):
                st.markdown("**Fund value: invested vs cash**")
                st.plotly_chart(charts.value_and_cash(daily), width="stretch", config={"displayModeBar": False})
        with b:
            with card("analytics_3"):
                st.markdown("**Drawdown from peak**")
                st.plotly_chart(charts.drawdown(daily), width="stretch", config={"displayModeBar": False})
        mr = an.monthly_returns(daily)
        if not mr.empty:
            with card("analytics_4"):
                st.markdown("**Monthly returns (time-weighted)**")
                st.plotly_chart(charts.monthly_heatmap(mr), width="stretch", config={"displayModeBar": False})

# ------------------------------------------------------------------ trade quality
with t_trades:
    if stats["n"] == 0:
        st.info("Trade-quality stats appear once you have closed positions.", icon=":material/info:")
    else:
        k = st.columns(4)
        k[0].metric("Closed trades", stats["n"], delta=f"{stats['wins']} W / {stats['losses']} L", delta_color="off")
        k[1].metric("Win rate", pct(stats["win_rate"] * 100, 0, sign=False))
        k[2].metric("Profit factor", f"{stats['profit_factor']:.2f}" if stats["profit_factor"] else "∞",
                    help="Gross profit ÷ gross loss. Above 1.5 is good.")
        k[3].metric("Expectancy / trade", inr(stats["expectancy"], sign=True))
        k = st.columns(4)
        k[0].metric("Avg win", inr(stats["avg_win"], sign=True), delta=pct(stats["avg_win_pct"]))
        k[1].metric("Avg loss", inr(stats["avg_loss"], sign=True), delta=pct(stats["avg_loss_pct"]))
        k[2].metric("Payoff ratio", f"{stats['payoff']:.2f}" if stats["payoff"] else "—", help="Avg win ÷ |avg loss|")
        k[3].metric("Avg R-multiple", f"{stats['avg_r']:.2f}R" if stats["avg_r"] is not None else "—",
                    help="P&L ÷ initial risk (entry − stop-loss). Needs a stop-loss set.")
        k = st.columns(4)
        k[0].metric("Avg days — winners", f"{stats['days_win']:.0f}" if stats["days_win"] else "—")
        k[1].metric("Avg days — losers", f"{stats['days_loss']:.0f}" if stats["days_loss"] else "—")
        k[2].metric("Best trade", stats["best"]["symbol"], delta=inr(stats["best"]["total_pnl"], sign=True))
        k[3].metric("Worst trade", stats["worst"]["symbol"], delta=inr(stats["worst"]["total_pnl"], sign=True))

        closed = c.summary[c.summary["status"] == "Closed"].sort_values("ret_pct", ascending=False)
        with card("analytics_5"):
            st.markdown("**Return per closed trade**")
            st.plotly_chart(charts.hbar_signed(list(closed["symbol"]), list(closed["ret_pct"]), fmt="%",
                                               text=[inr(v, sign=True) for v in closed["total_pnl"]]),
                            width="stretch", config={"displayModeBar": False})

# ------------------------------------------------------------------ breakdown
with t_break:
    dim = st.segmented_control("Group by", ["strategy", "sector", "conviction", "mcap"], default="strategy",
                               format_func=lambda x: {"mcap": "Market cap"}.get(x, x.title()), key="an_dim") or "strategy"
    bd = an.breakdown(c.summary, dim)
    a, b = st.columns([3, 2], gap="medium")
    with a:
        tbl = bd.reset_index().rename(columns={dim: dim.title(), "positions": "Positions", "active": "Active",
                                               "closed": "Closed", "value": "Value", "total_pnl": "Total P&L",
                                               "ret_pct": "Return %", "win_rate": "Win rate %", "bought": "Bought"})
        tbl = tbl.drop(columns=["Bought"])
        st.dataframe(style_table(tbl, money=["Value", "Total P&L"], pcts=["Return %"], pnl_cols=["Total P&L", "Return %"],
                                 nums=["Positions", "Active", "Closed"],
                                 custom={"Win rate %": lambda v: "—" if pd.isna(v) else f"{v:.0f}%"}),
                     hide_index=True, width="stretch")
    with b:
        st.plotly_chart(charts.hbar_signed([str(i) for i in bd.index], list(bd["total_pnl"])),
                        width="stretch", config={"displayModeBar": False})

# ------------------------------------------------------------------ risk
with t_risk:
    if act.empty:
        st.caption("No active holdings.")
    else:
        with_sl = act.dropna(subset=["stop_loss"])
        risk = with_sl["risk_to_sl"].sum()
        unreal_at_sl = ((with_sl["stop_loss"] - with_sl["avg_cost"]) * with_sl["qty"]).sum()
        k = st.columns(4)
        k[0].metric("Capital at risk (all SLs hit)", inr(risk), delta=f"{risk / c.total * 100:.1f}% of portfolio",
                    delta_color="off", help="Drop from current value if every stop-loss is hit")
        k[1].metric("P&L if all SLs hit", inr(unreal_at_sl, sign=True), help="vs. your cost, for holdings with SL")
        k[2].metric("Holdings without SL", f"{act['stop_loss'].isna().sum()} / {len(act)}")
        top_w = act["weight"].max()
        k[3].metric("Largest position", act.loc[act["weight"].idxmax(), "symbol"], delta=f"{top_w:.1f}% weight",
                    delta_color="off")
        a, b = st.columns(2, gap="medium")
        with a:
            with card("analytics_6"):
                st.markdown("**Distance to stop-loss**")
                if with_sl.empty:
                    st.caption("Set stop-losses to see this.")
                else:
                    st.plotly_chart(charts.sl_distance(with_sl), width="stretch", config={"displayModeBar": False})
        with b:
            with card("analytics_7"):
                st.markdown(f"**Position weights** (limit {c.settings['concentration_pct']:.0f}%)")
                w = act.sort_values("weight", ascending=False)
                fig = charts.weights_bar(list(w["symbol"]), list(w["weight"]))
                fig.add_vline(x=c.settings["concentration_pct"], line=dict(color="#d03b3b", dash="dot", width=1))
                st.plotly_chart(fig, width="stretch", config={"displayModeBar": False})

# ------------------------------------------------------------------ add-ons
with t_add:
    if addons.empty:
        st.info("No add-ons yet. Every 2nd/3rd buy in a position will be evaluated here.", icon=":material/info:")
    else:
        k = st.columns(3)
        k[0].metric("Add-ons", len(addons))
        k[1].metric("In profit", pct((addons["ret_pct"] > 0).mean() * 100, 0, sign=False))
        k[2].metric("Add-on P&L (vs CMP/exit)", inr(addons["pnl"].sum(), sign=True))
        t = addons.rename(columns={"symbol": "Stock", "buy_no": "Buy #", "date": "Date", "qty": "Qty", "price": "Price",
                                   "vs_first_pct": "vs 1st buy %", "ref_price": "CMP / exit", "ret_pct": "Return %",
                                   "pnl": "P&L ₹", "type": "Type"})
        st.dataframe(style_table(t, money=["P&L ₹"], money2=["Price", "CMP / exit"], pcts=["vs 1st buy %", "Return %"],
                                 nums=["Qty"], dates=["Date"], pnl_cols=["Return %", "P&L ₹"]),
                     hide_index=True, width="stretch")
        st.caption("Pyramid = added above the first buy price. Average down = added below it.")
