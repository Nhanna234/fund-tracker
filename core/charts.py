"""Plotly chart builders. Thin marks, recessive grid, one axis, fixed categorical order."""
import calendar

import pandas as pd
import plotly.graph_objects as go

from .config import (BENCHMARK_NAME, CASH_COLOR, DIVERGING, GAIN, LOSS, NEUTRAL, OTHER_GREY,
                     SERIES)
from . import theme
from .ui import inr

FONT = dict(family="Inter, Segoe UI, system-ui, sans-serif", size=12.5)
MCAP_COLORS = {"Large": SERIES[0], "Mid": SERIES[1], "Small": SERIES[2], "Micro": SERIES[3],
               "Unknown": OTHER_GREY}


def _layout(fig, height=360, legend=True, hover="x unified"):
    t = theme.tokens()
    fig.update_layout(
        height=height, margin=dict(l=8, r=8, t=28, b=8), font=FONT, hovermode=hover,
        showlegend=legend, legend=dict(orientation="h", yanchor="bottom", y=1.02, x=0, title=None),
        paper_bgcolor="rgba(0,0,0,0)", plot_bgcolor="rgba(0,0,0,0)",
        hoverlabel=dict(bgcolor=t["card"], bordercolor=t["border"], font=dict(family=FONT["family"], size=12.5,
                                                                             color=t["text"])),
    )
    fig.update_layout(font_color=t["muted"], legend_font_color=t["text"])
    fig.update_xaxes(showgrid=False, zeroline=False)
    fig.update_yaxes(gridcolor="rgba(128,140,165,0.16)", zeroline=False)
    return fig


def color_map(labels, fixed=None):
    """Stable entity->colour mapping (alphabetical, never by rank). 'Other' grey, 'Cash' neutral."""
    fixed = fixed or {}
    out, i = {}, 0
    for lbl in sorted(set(labels), key=str):
        if lbl in fixed:
            out[lbl] = fixed[lbl]
        elif lbl == "Cash":
            out[lbl] = "#55617a" if theme.mode() == "dark" else CASH_COLOR
        elif lbl == "Other":
            out[lbl] = OTHER_GREY
        else:
            out[lbl] = SERIES[i % len(SERIES)] if i < len(SERIES) else OTHER_GREY
            i += 1
    return out


# ---------------------------------------------------------------- performance
def equity_vs_bench(daily: pd.DataFrame):
    fig = go.Figure()
    y = daily["twr"] * 100
    fig.add_trace(go.Scatter(x=daily.index, y=y, name="Portfolio (TWR)", mode="lines",
                             line=dict(color=theme.tokens()["primary"], width=2.4, shape="spline", smoothing=0.3),
                             hovertemplate="%{y:.1f}<extra>Portfolio</extra>"))
    if "bench" in daily:
        fig.add_trace(go.Scatter(x=daily.index, y=daily["bench"] * 100, name=BENCHMARK_NAME, mode="lines",
                                 line=dict(color=NEUTRAL, width=2, dash="dot"),
                                 hovertemplate="%{y:.1f}<extra>" + BENCHMARK_NAME + "</extra>"))
    fig.add_hline(y=100, line=dict(color="rgba(128,128,128,0.4)", width=1))
    fig.update_yaxes(title="Growth of 100")
    return _layout(fig, 340)


def value_and_cash(daily: pd.DataFrame):
    fig = go.Figure()
    fig.add_trace(go.Scatter(x=daily.index, y=daily["holdings"], name="Invested (market value)",
                             stackgroup="v", mode="lines", line=dict(width=0.5, color=SERIES[0]),
                             hovertemplate="₹%{y:,.0f}<extra>Invested</extra>"))
    fig.add_trace(go.Scatter(x=daily.index, y=daily["cash"].clip(lower=0), name="Cash", stackgroup="v",
                             mode="lines", line=dict(width=0.5, color=CASH_COLOR),
                             hovertemplate="₹%{y:,.0f}<extra>Cash</extra>"))
    fig.update_yaxes(title="₹", tickformat=",.0f")
    return _layout(fig, 320)


def drawdown(daily: pd.DataFrame):
    fig = go.Figure(go.Scatter(x=daily.index, y=daily["drawdown"] * 100, fill="tozeroy", mode="lines",
                               line=dict(color=LOSS, width=1.5), fillcolor="rgba(208,59,59,0.15)",
                               name="Drawdown", hovertemplate="%{y:.2f}%<extra>Drawdown</extra>"))
    fig.update_yaxes(title="% from peak", ticksuffix="%")
    return _layout(fig, 260, legend=False)


def monthly_heatmap(tbl: pd.DataFrame):
    months = [calendar.month_abbr[m] for m in tbl.columns]
    z = tbl.values
    zmax = max(abs(pd.DataFrame(z).stack()).max() if pd.DataFrame(z).stack().size else 1, 1)
    text = [[("" if pd.isna(v) else f"{v:+.1f}%") for v in row] for row in z]
    fig = go.Figure(go.Heatmap(z=z, x=months, y=[str(y) for y in tbl.index], colorscale=[[0.0, "#f04438"], [0.5, theme.tokens()["heat_mid"]], [1.0, "#2a78d6"]],
                               zmid=0, zmin=-zmax, zmax=zmax, text=text, texttemplate="%{text}",
                               xgap=2, ygap=2, hovertemplate="%{y} %{x}: %{z:+.2f}%<extra></extra>",
                               colorbar=dict(ticksuffix="%", thickness=10)))
    fig.update_yaxes(autorange="reversed", type="category", showgrid=False)
    return _layout(fig, 60 + 46 * len(tbl), legend=False, hover="closest")


# ---------------------------------------------------------------- allocation
def donut(labels, values, fixed=None, height=300):
    cmap = color_map(labels, fixed)
    fig = go.Figure(go.Pie(labels=labels, values=values, hole=0.62, sort=False,
                           marker=dict(colors=[cmap[l] for l in labels], line=dict(color=theme.tokens()["mark_ring"], width=2)),
                           textinfo="percent", textposition="inside", insidetextorientation="horizontal",
                           hovertemplate="%{label}<br>₹%{value:,.0f} · %{percent}<extra></extra>"))
    fig = _layout(fig, height, legend=True, hover="closest")
    fig.update_layout(legend=dict(orientation="v", x=1.0, y=0.5, yanchor="middle"))
    return fig


def fold(series: pd.Series, top=7) -> pd.Series:
    s = series.sort_values(ascending=False)
    if len(s) > top + 1:
        s = pd.concat([s.iloc[:top], pd.Series({"Other": s.iloc[top:].sum()})])
    return s


def hbar_signed(labels, values, fmt="₹", height=None, text=None):
    colors = [GAIN if v >= 0 else LOSS for v in values]
    h = height or max(220, 34 * len(labels) + 60)
    tmpl = "%{y}: ₹%{x:,.0f}<extra></extra>" if fmt == "₹" else "%{y}: %{x:+.2f}%<extra></extra>"
    fig = go.Figure(go.Bar(x=values, y=labels, orientation="h", marker=dict(color=colors, cornerradius=4),
                           text=text, textposition="outside", cliponaxis=False, hovertemplate=tmpl))
    fig.update_yaxes(autorange="reversed", showgrid=False)
    fig.update_xaxes(gridcolor="rgba(128,128,128,0.15)", ticksuffix="%" if fmt == "%" else "",
                     tickprefix="₹" if fmt == "₹" else "", tickformat=",.0f" if fmt == "₹" else ".0f")
    fig.update_layout(bargap=0.35)
    return _layout(fig, h, legend=False, hover="closest")


def weights_bar(labels, values, height=None):
    h = height or max(220, 30 * len(labels) + 60)
    fig = go.Figure(go.Bar(x=values, y=labels, orientation="h", marker=dict(color=SERIES[0], cornerradius=4),
                           text=[f"{v:.1f}%" for v in values], textposition="outside", cliponaxis=False,
                           hovertemplate="%{y}: %{x:.2f}%<extra></extra>"))
    fig.update_yaxes(autorange="reversed", showgrid=False)
    fig.update_xaxes(ticksuffix="%")
    fig.update_layout(bargap=0.35)
    return _layout(fig, h, legend=False, hover="closest")


# ---------------------------------------------------------------- stock chart
def candlestick(ohlc: pd.DataFrame, title="", txns: pd.DataFrame = None, avg_cost=None,
                stop_loss=None, target1=None, target2=None, trigger=None, height=480):
    fig = go.Figure(go.Candlestick(
        x=ohlc.index, open=ohlc["Open"], high=ohlc["High"], low=ohlc["Low"], close=ohlc["Close"],
        name="Monthly", increasing=dict(line=dict(color=GAIN, width=1), fillcolor=GAIN),
        decreasing=dict(line=dict(color=LOSS, width=1), fillcolor=LOSS)))
    if txns is not None and not txns.empty:
        for kind, sym, col, nm in (("BUY", "triangle-up", SERIES[0], "Buy"), ("SELL", "triangle-down", SERIES[1], "Sell")):
            t = txns[txns["kind"] == kind]
            if t.empty:
                continue
            x = pd.to_datetime(t["date"]).dt.to_period("M").dt.to_timestamp()
            fig.add_trace(go.Scatter(
                x=x, y=t["price"], mode="markers", name=nm,
                marker=dict(symbol=sym, size=13, color=col, line=dict(color=theme.tokens()["mark_ring"], width=1.5)),
                customdata=list(zip(t["qty"], pd.to_datetime(t["date"]).dt.strftime("%d %b %Y"))),
                hovertemplate=nm + " %{customdata[0]:,.0f} @ ₹%{y:,.2f}<br>%{customdata[1]}<extra></extra>"))
    lines = [(avg_cost, "Avg cost", SERIES[0], "dash"), (stop_loss, "SL", LOSS, "dot"),
             (target1, "T1", GAIN, "dot"), (target2, "T2", GAIN, "dash"), (trigger, "Trigger", SERIES[6], "dot")]
    for val, lbl, col, dash in lines:
        if val and not pd.isna(val):
            fig.add_hline(y=val, line=dict(color=col, width=1.2, dash=dash),
                          annotation_text=f"{lbl} {inr(val)}", annotation_position="top left",
                          annotation_font=dict(size=11, color=col))
    fig.update_layout(xaxis_rangeslider_visible=False, title=dict(text=title, x=0, font=dict(size=14)))
    fig.update_yaxes(tickprefix="₹", tickformat=",.0f")
    fig = _layout(fig, height, legend=True, hover="x")
    if len(ohlc) > 60:
        fig.update_xaxes(range=[ohlc.index[-60], ohlc.index[-1] + pd.Timedelta(days=45)])
    return fig


def sl_distance(df: pd.DataFrame):
    d = df.dropna(subset=["sl_dist_pct"]).sort_values("sl_dist_pct")
    colors = [LOSS if v <= 0 else (SERIES[3] if v < 5 else SERIES[0]) for v in d["sl_dist_pct"]]
    fig = go.Figure(go.Bar(x=d["sl_dist_pct"], y=d["symbol"], orientation="h",
                           marker=dict(color=colors, cornerradius=4),
                           text=[f"{v:.1f}%" for v in d["sl_dist_pct"]], textposition="outside", cliponaxis=False,
                           customdata=d["risk_to_sl"],
                           hovertemplate="%{y}: %{x:.1f}% above SL<br>Risk to SL ₹%{customdata:,.0f}<extra></extra>"))
    fig.update_yaxes(autorange="reversed", showgrid=False)
    fig.update_xaxes(ticksuffix="%")
    return _layout(fig, max(220, 32 * len(d) + 60), legend=False, hover="closest")


def nifty_entries(regime: pd.DataFrame, tagged: pd.DataFrame):
    """Nifty 50 with its 50 EMA; each entry is a marker on the line, coloured by outcome zone."""
    from .config import ZONE_COLORS
    fig = go.Figure()
    fig.add_trace(go.Scatter(x=regime.index, y=regime["close"], name=BENCHMARK_NAME, mode="lines",
                             line=dict(color=SERIES[0], width=2),
                             hovertemplate="%{y:,.0f}<extra>" + BENCHMARK_NAME + "</extra>"))
    fig.add_trace(go.Scatter(x=regime.index, y=regime["ema"], name="50-day EMA", mode="lines",
                             line=dict(color=NEUTRAL, width=1.5, dash="dot"),
                             hovertemplate="%{y:,.0f}<extra>50 EMA</extra>"))
    t = tagged.dropna(subset=["nifty"])
    symbols = {"Win": "triangle-up", "Flat": "circle", "Loss": "triangle-down"}
    for z in ("Win", "Flat", "Loss"):
        d = t[t["zone"] == z]
        if d.empty:
            continue
        fig.add_trace(go.Scatter(
            x=pd.to_datetime(d["first_buy"]), y=d["nifty"], mode="markers", name=f"{z} entry",
            marker=dict(symbol=symbols[z], size=13, color=ZONE_COLORS[z], line=dict(color=theme.tokens()["mark_ring"], width=2)),
            customdata=list(zip(d["symbol"], d["ret_pct"], d["status"], d["regime"])),
            hovertemplate="<b>%{customdata[0]}</b> %{customdata[1]:+.1f}% (%{customdata[2]})"
                          "<br>Entered in %{customdata[3]}<extra></extra>"))
    fig.update_yaxes(tickformat=",.0f")
    return _layout(fig, 380, hover="closest")


# ---------------------------------------------------------------- fund / investors
def nav_vs_bench(daily: pd.DataFrame, flows: pd.DataFrame = None, names: dict = None):
    """NAV per unit; the benchmark is rebased to the NAV at the start of the window.
    Investor deposits / withdrawals are marked on the NAV line."""
    t = theme.tokens()
    fig = go.Figure()
    fig.add_trace(go.Scatter(x=daily.index, y=daily["nav"], name="NAV per unit", mode="lines",
                             line=dict(color=t["primary"], width=2.4),
                             hovertemplate="₹%{y:.4f}<extra>NAV</extra>"))
    if "bench" in daily and daily["bench"].notna().any():
        b = daily["bench"] / daily["bench"].iloc[0] * daily["nav"].iloc[0]
        fig.add_trace(go.Scatter(x=daily.index, y=b, name=f"{BENCHMARK_NAME} (rebased)", mode="lines",
                                 line=dict(color=NEUTRAL, width=2, dash="dot"),
                                 hovertemplate="₹%{y:.4f}<extra>" + BENCHMARK_NAME + "</extra>"))
    if flows is not None and not flows.empty:
        f = flows.copy()
        f["x"] = [daily.index[min(daily.index.searchsorted(pd.Timestamp(d)), len(daily) - 1)] for d in f["date"]]
        f = f[(pd.to_datetime(f["date"]) >= daily.index[0] - pd.Timedelta(days=3))]
        for kind, sym, col, nm in (("DEPOSIT", "triangle-up", GAIN, "Money in"),
                                   ("WITHDRAWAL", "triangle-down", LOSS, "Money out")):
            g = f[f["kind"] == kind]
            if g.empty:
                continue
            who = [(names or {}).get(i, "Investor") for i in g["investor_id"]]
            fig.add_trace(go.Scatter(
                x=g["x"], y=daily["nav"].reindex(g["x"]).values, mode="markers", name=nm,
                marker=dict(symbol=sym, size=11, color=col, line=dict(color=t["mark_ring"], width=1.5)),
                customdata=list(zip(who, g["amount"], g["nav"], g["units"])),
                hovertemplate="<b>%{customdata[0]}</b> · " + nm.lower() + " ₹%{customdata[1]:,.0f}"
                              "<br>%{customdata[3]:,.2f} units at NAV ₹%{customdata[2]:.4f}<extra></extra>"))
    fig.update_yaxes(title="₹ per unit", tickprefix="₹", tickformat=".2f")
    return _layout(fig, 340)


def investor_value(h: pd.DataFrame):
    """One investor: what their units are worth vs the net money they have put in."""
    t = theme.tokens()
    fig = go.Figure()
    fig.add_trace(go.Scatter(x=h.index, y=h["value"], name="Value of units", mode="lines",
                             line=dict(color=t["primary"], width=2.2), fill="tozeroy", fillcolor=t["primary_soft"],
                             hovertemplate="₹%{y:,.0f}<extra>Value</extra>"))
    fig.add_trace(go.Scatter(x=h.index, y=h["invested"], name="Net money invested", mode="lines",
                             line=dict(color=NEUTRAL, width=1.8, dash="dot", shape="hv"),
                             hovertemplate="₹%{y:,.0f}<extra>Net invested</extra>"))
    fig.update_yaxes(tickprefix="₹", tickformat=",.0f")
    return _layout(fig, 320)
