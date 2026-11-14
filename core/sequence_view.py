"""Win/loss sequence tab: tiles in entry-date order, streaks, entries vs Nifty trend, breadth site."""
import datetime as dt
import html

import pandas as pd
import streamlit as st

from . import analytics as an
from . import charts, prices
from .config import BENCHMARK, BENCHMARK_NAME, BREADTH_URL, LOSS_PCT, WIN_PCT
from .ui import card, inr, pct, style_table

GREEN = ("#a5dba5", "#0a4f1a")   # light (just above +5%) -> dark (+50% and beyond)
RED = ("#f2aaa2", "#7a1414")     # light (just below -5%) -> dark (-40% and beyond)
YELLOW = "#f4d35e"
GREEN_FULL, RED_FULL = 50.0, 40.0  # return % at which the darkest shade is reached
RANGES = {"1M": 31, "3M": 92, "6M": 183, "1Y": 366, "3Y": 1096}  # chart period -> calendar days


def _mix(c1: str, c2: str, t: float) -> str:
    t = max(0.0, min(1.0, t))
    a = [int(c1[i:i + 2], 16) for i in (1, 3, 5)]
    b = [int(c2[i:i + 2], 16) for i in (1, 3, 5)]
    return "#" + "".join(f"{round(x + (y - x) * t):02x}" for x, y in zip(a, b))


def tile_colors(ret_pct: float) -> tuple:
    """(background, text) for a return %. Green darkens with gain, red darkens with loss."""
    if ret_pct > WIN_PCT:
        t = (ret_pct - WIN_PCT) / (GREEN_FULL - WIN_PCT)
        return _mix(*GREEN, t), ("#ffffff" if t > 0.35 else "#10210f")
    if ret_pct < LOSS_PCT:
        t = (-ret_pct + LOSS_PCT) / (RED_FULL + LOSS_PCT)
        return _mix(*RED, t), ("#ffffff" if t > 0.35 else "#2a0d0b")
    return YELLOW, "#33290a"


def tiles_html(seq: pd.DataFrame) -> str:
    cells = []
    for r in seq.itertuples(index=False):
        bg, fg = tile_colors(r.ret_pct)
        mark = {"Win": "▲", "Loss": "▼", "Flat": "●"}[r.zone]
        live = "" if r.status == "Closed" else "<span style='font-size:10px;opacity:.85'> · live</span>"
        tip = (f"#{r.n} {r.symbol} ({r.status}) | entered {r.first_buy:%d %b %Y} | "
               f"return {r.ret_pct:+.1f}% | P&L {inr(r.total_pnl, sign=True)} | {r.holding_days} days")
        cells.append(
            f"<div title='{html.escape(tip)}' style='background:{bg};color:{fg};border-radius:8px;"
            f"padding:8px 10px;min-width:92px;flex:0 0 auto;line-height:1.25'>"
            f"<div style='font-size:10px;opacity:.85'>#{r.n} · {r.first_buy:%d %b %y}{live}</div>"
            f"<div style='font-weight:700;font-size:13px'>{html.escape(str(r.symbol))}</div>"
            f"<div style='font-size:13px'>{mark} {r.ret_pct:+.1f}%</div></div>")
    return "<div style='display:flex;flex-wrap:wrap;gap:6px;margin:4px 0 8px'>" + "".join(cells) + "</div>"


def legend_html() -> str:
    def sw(c, label):
        return (f"<span style='display:inline-flex;align-items:center;gap:5px;margin-right:14px'>"
                f"<span style='width:26px;height:12px;border-radius:3px;background:{c};display:inline-block'></span>"
                f"{label}</span>")
    g = f"linear-gradient(90deg,{GREEN[0]},{GREEN[1]})"
    r = f"linear-gradient(90deg,{RED[0]},{RED[1]})"
    return ("<div style='font-size:12px;opacity:.85'>"
            + sw(g, f"▲ Win: above +{WIN_PCT:.0f}% (darker = bigger gain, darkest at +{GREEN_FULL:.0f}%)")
            + sw(YELLOW, f"● Flat: {LOSS_PCT:.0f}% to +{WIN_PCT:.0f}%")
            + sw(r, f"▼ Loss: below {LOSS_PCT:.0f}% (darker = bigger loss)") + "</div>")


def render(c):
    full = an.sequence(c.summary)
    if full.empty:
        st.info("Add positions to see your win/loss sequence.", icon=":material/info:")
        return

    f1, f2 = st.columns([2, 3])
    which = f1.segmented_control("Positions", ["All", "Active", "Closed"], default="All", key="seq_which") or "All"
    f2.caption("Each tile is one position, in order of **first entry date**. Closed positions use the realised "
               "return; active ones are marked *live* and use the **current price**, so they update on every "
               "price refresh.")
    seq = full if which == "All" else full[full["status"] == which]
    if seq.empty:
        st.caption(f"No {which.lower()} positions.")
        return
    seq = seq.copy()
    seq["n"] = range(1, len(seq) + 1)

    # ------------------------------------------------------------ sequence strip
    with card("sequence_view_1"):
        st.markdown("**Win / loss sequence**")
        st.markdown(tiles_html(seq) + legend_html(), unsafe_allow_html=True)

    stz = an.streaks(list(seq["zone"]))
    n = len(seq)
    k = st.columns(6)
    k[0].metric("Wins (> +5%)", int((seq["zone"] == "Win").sum()), delta=f"{(seq['zone'] == 'Win').mean() * 100:.0f}%",
                delta_color="off")
    k[1].metric("Flat (±5%)", int((seq["zone"] == "Flat").sum()),
                delta=f"{(seq['zone'] == 'Flat').mean() * 100:.0f}%", delta_color="off")
    k[2].metric("Losses (< −5%)", int((seq["zone"] == "Loss").sum()),
                delta=f"{(seq['zone'] == 'Loss').mean() * 100:.0f}%", delta_color="off")
    k[3].metric("Current streak", f"{stz['current_len']} × {stz['current_zone']}",
                help="Counting back from your most recent entry. A flat result breaks a win or loss streak.")
    k[4].metric("Longest win streak", stz["best_win"])
    k[5].metric("Longest loss streak", stz["best_loss"])

    last5 = seq.tail(min(5, n))
    st.caption(f"Last {len(last5)} entries: avg return **{pct(last5['ret_pct'].mean())}**, "
               f"{int((last5['zone'] == 'Win').sum())} wins / {int((last5['zone'] == 'Loss').sum())} losses. "
               f"All {n}: avg **{pct(seq['ret_pct'].mean())}**.")

    # ------------------------------------------------------------ entries vs market
    today = dt.date.today()
    first_entry = min(seq["first_buy"])
    # fetch enough for the longest range (3Y) plus ~150 days so the 50-day EMA is settled
    start = (min(first_entry, today - dt.timedelta(days=RANGES["3Y"])) - dt.timedelta(days=150)).isoformat()
    hist = prices.get_history((BENCHMARK,), start)
    bench = hist[BENCHMARK] if (not hist.empty and BENCHMARK in hist.columns) else pd.Series(dtype=float)
    regime = an.market_regime(bench)
    tagged = an.tag_entries(seq, regime)

    with card("sequence_view_2"):
        st.markdown(f"**Your entries vs the market** <span style='opacity:.6'>({BENCHMARK_NAME} and its 50-day EMA; "
                    "each marker is an entry, coloured by how it turned out)</span>", unsafe_allow_html=True)
        if regime.empty:
            st.caption(f"{BENCHMARK_NAME} history is unavailable from Yahoo right now.")
        else:
            act_first = min(c.active["first_buy"]) if not c.active.empty else None
            opts = list(RANGES) + (["Active holdings"] if act_first else []) + ["Since first entry"]
            rng = st.segmented_control(
                "Chart period", opts, default="Since first entry", key="seq_rng", label_visibility="collapsed",
                help="Active holdings = from the entry date of your oldest holding that is still open") \
                or "Since first entry"
            if rng in RANGES:
                frm = today - dt.timedelta(days=RANGES[rng])
            elif rng == "Active holdings":
                frm = act_first - dt.timedelta(days=15)
            else:
                frm = first_entry - dt.timedelta(days=30)
            show = regime[regime.index >= pd.Timestamp(frm)]
            in_view = tagged[tagged["first_buy"] >= frm]
            st.plotly_chart(charts.nifty_entries(show, in_view), width="stretch", config={"displayModeBar": False})
            hidden = len(tagged) - len(in_view)
            st.caption(f"Showing {BENCHMARK_NAME} from {show.index[0]:%d %b %Y} · {len(in_view)} of {len(tagged)} "
                       "entries fall in this period"
                       + (f" ({hidden} earlier ones are off the chart; the table below still counts all of them)."
                          if hidden else "."))
            rt = an.regime_table(tagged)
            if not rt.empty:
                st.dataframe(style_table(rt, money=["Total P&L"], pcts=["Avg return %"], pnl_cols=["Avg return %", "Total P&L"],
                                         custom={"Win %": lambda v: f"{v:.0f}%"}), hide_index=True, width="stretch")
                up = rt[rt["Nifty at entry"] == "Uptrend"]
                dn = rt[rt["Nifty at entry"] == "Downtrend"]
                if not up.empty and not dn.empty:
                    u, d = up.iloc[0], dn.iloc[0]
                    better = "uptrends" if u["Avg return %"] >= d["Avg return %"] else "downtrends"
                    st.caption(f"Entries made in {better} have done better so far: uptrend avg "
                               f"**{pct(u['Avg return %'])}** over {int(u['Entries'])} entries vs downtrend avg "
                               f"**{pct(d['Avg return %'])}** over {int(d['Entries'])}. Small samples — treat as a hint.")
            st.caption(f"Uptrend / Downtrend here = {BENCHMARK_NAME} closing above / below its 50-day EMA on the entry "
                       "date. It is computed inside this app as a stand-in for market health; it is not the breadth "
                       "score from your breadth tracker.")

    # ------------------------------------------------------------ breadth site
    with card("sequence_view_3"):
        a, b, d = st.columns([3, 1.3, 1.2])
        a.markdown("**Indian market breadth tracker** <span style='opacity:.6'>(your other dashboard, live)</span>",
                   unsafe_allow_html=True)
        show_site = b.toggle("Show here", value=True, key="seq_breadth")
        d.link_button("Open in new tab", BREADTH_URL, icon=":material/open_in_new:", width="stretch")
        if show_site:
            src = BREADTH_URL.rstrip("/") + "/?embed=true"
            if hasattr(st, "iframe"):
                st.iframe(src, height=780)
            else:
                import streamlit.components.v1 as components
                components.iframe(src, height=780, scrolling=True)
            st.caption("If it shows a 'waking up' screen, give it a few seconds — free Streamlit apps sleep when idle.")
