"""Formatting helpers and small reusable UI pieces."""
import html
import math
import re

import pandas as pd
import streamlit as st

from . import theme


def _isnum(x):
    return x is not None and not (isinstance(x, float) and math.isnan(x)) and not pd.isna(x)


def inr(x, d=0, sign=False, symbol=True) -> str:
    """Indian digit grouping: ₹12,34,567."""
    if not _isnum(x):
        return "—"
    x = float(x)
    neg = x < 0
    s = f"{abs(x):.{d}f}"
    whole, _, frac = s.partition(".")
    if len(whole) > 3:
        head, tail = whole[:-3], whole[-3:]
        head = re.sub(r"(\d)(?=(\d\d)+$)", r"\1,", head)
        whole = f"{head},{tail}"
    out = ("₹" if symbol else "") + whole + (f".{frac}" if frac else "")
    if neg:
        return "-" + out
    return ("+" + out) if (sign and x > 0) else out


def compact(x, sign=False) -> str:
    """₹1.23 Cr / ₹4.56 L / ₹7,890."""
    if not _isnum(x):
        return "—"
    a = abs(x)
    pre = "-" if x < 0 else ("+" if sign and x > 0 else "")
    if a >= 1e7:
        return f"{pre}₹{a / 1e7:.2f} Cr"
    if a >= 1e5:
        return f"{pre}₹{a / 1e5:.2f} L"
    return pre + inr(a)


def pct(x, d=2, sign=True) -> str:
    if not _isnum(x):
        return "—"
    return f"{x:+.{d}f}%" if sign else f"{x:.{d}f}%"


def num(x, d=0) -> str:
    if not _isnum(x):
        return "—"
    return f"{x:,.{d}f}" if d else inr(x, 0, symbol=False)


def pnl_color(v):
    if not _isnum(v) or v == 0:
        return ""
    t = theme.tokens()
    return f"color: {t['gain']}; font-weight: 600" if v > 0 else f"color: {t['loss']}; font-weight: 600"


def style_table(df: pd.DataFrame, money=(), money2=(), pcts=(), nums=(), pnl_cols=(), dates=(), custom=None):
    """Format + colour a table in ONE Styler.format call (pandas 3 resets on chained .format)."""
    fmt = dict(custom or {})
    for c in money:
        fmt[c] = lambda v: inr(v)
    for c in money2:
        fmt[c] = lambda v: inr(v, 2)
    for c in pcts:
        fmt[c] = lambda v: pct(v)
    for c in nums:
        fmt[c] = lambda v: num(v)
    for c in dates:
        fmt[c] = lambda v: v.strftime("%d %b %Y") if _isnum(v) and hasattr(v, "strftime") else "—"
    sty = df.style.format({k: v for k, v in fmt.items() if k in df.columns}, na_rep="—")
    cols = [c for c in pnl_cols if c in df.columns]
    if cols:
        sty = sty.map(pnl_color, subset=cols)
    return sty


ALERT_ICON = {"critical": "🔴", "serious": "🟠", "warning": "🟡", "good": "🟢", "info": "🔵"}
INSIGHT_ICON = {"warn": ":material/warning:", "good": ":material/thumb_up:", "info": ":material/lightbulb:"}


def page_header(title: str, subtitle: str = None, eyebrow: str = "Portfolio", chip: str = None):
    """Page title block. `chip` is optional HTML shown as a pill on the right."""
    right = f"<div class='pt-chip'>{chip}</div>" if chip else ""
    if subtitle:
        subtitle = re.sub(r"\*\*(.+?)\*\*", r"<b></b>", subtitle)
    sub = f"<div class='pt-sub'>{subtitle}</div>" if subtitle else ""
    st.html(f"<div class='pt-head'><div><div class='pt-eyebrow'>{html.escape(eyebrow)}</div>"
            f"<h1 class='pt-title'>{html.escape(title)}</h1>{sub}</div>{right}</div>")


def card(name: str):
    """A surface card. `name` must be unique on the page (it becomes the CSS hook st-key-card_<name>)."""
    return st.container(key=f"card_{name}")


def card_title(title: str, note: str = None):
    extra = f"<small>{html.escape(note)}</small>" if note else ""
    st.html(f"<div class='pt-card-title'>{html.escape(title)}{extra}</div>")


def empty_state(msg: str, page: str = None, label: str = None):
    with st.container(key=f"card_empty_{abs(hash(msg)) % 10**6}"):
        st.info(msg, icon=":material/info:")
        if page:
            page_link(page, label or "Go")


ALERT_STYLE = {  # level -> (label, colour)
    "critical": ("Stop-loss", "#e5484d"), "serious": ("Near SL", "#f97316"), "warning": ("Review", "#eab308"),
    "good": ("Target", "#22c55e"), "info": ("Watchlist", "#3b82f6"), "audit": ("NAV audit", "#8b5cf6"),
}


def alert_rows(alerts: list) -> str:
    """HTML for the dashboard alert list: coloured left bar + tag + symbol + text."""
    out = []
    for lvl, sym, text in alerts:
        label, col = ALERT_STYLE.get(lvl, ("Note", "#94a3b8"))
        out.append(f"<div class='pt-alert' style='border-left-color:{col}'>"
                   f"<span class='pt-tag' style='background:{col}22;color:{col}'>{label}</span>"
                   f"<b>{html.escape(str(sym))}</b><span>{html.escape(text)}</span></div>")
    return "".join(out)


def page_link(page: str, label: str, icon: str = ":material/arrow_forward:"):
    """st.page_link that degrades to nothing when the page isn't registered (single-view test harness)."""
    try:
        st.page_link(page, label=label, icon=icon)
    except Exception:
        pass
