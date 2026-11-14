"""Visual layer on top of .streamlit/config.toml: design tokens + CSS for cards, metrics, tabs, header.

Colours and fonts live in config.toml ([theme.light] / [theme.dark]); this module adds the
things Streamlit's theme can't express (card surfaces, shadows, pill tabs, the sidebar wallet).
"""
import streamlit as st

TOKENS = {
    "light": {
        "bg": "#f4f6fa", "card": "#ffffff", "card2": "#f8fafd", "border": "#e1e7f0", "text": "#0f172a",
        "muted": "#64748b", "primary": "#2456e6", "primary_soft": "rgba(36,86,230,.09)",
        "gain": "#0a8f4e", "loss": "#d92d3a", "warn": "#b7791f",
        "shadow": "0 1px 2px rgba(15,23,42,.04), 0 6px 20px rgba(15,23,42,.06)",
        "shadow_hover": "0 2px 4px rgba(15,23,42,.06), 0 12px 28px rgba(15,23,42,.10)",
        "glow": "radial-gradient(900px 380px at 85% -8%, rgba(36,86,230,.07), transparent 70%)",
        "heat_mid": "#eef1f6", "mark_ring": "#ffffff",
    },
    "dark": {
        "bg": "#0a0f1c", "card": "#101829", "card2": "#0d1423", "border": "#1f2a41", "text": "#e7ecf5",
        "muted": "#8a96ad", "primary": "#5b8cff", "primary_soft": "rgba(91,140,255,.14)",
        "gain": "#34d399", "loss": "#fb7185", "warn": "#fbbf24",
        "shadow": "0 1px 0 rgba(255,255,255,.03) inset, 0 8px 24px rgba(0,0,0,.35)",
        "shadow_hover": "0 1px 0 rgba(255,255,255,.05) inset, 0 14px 32px rgba(0,0,0,.5)",
        "glow": "radial-gradient(900px 380px at 85% -8%, rgba(91,140,255,.13), transparent 70%)",
        "heat_mid": "#1b2438", "mark_ring": "#101829",
    },
}


def mode() -> str:
    try:
        return "dark" if st.context.theme.type == "dark" else "light"
    except Exception:
        return "light"


def tokens() -> dict:
    return TOKENS[mode()]


def apply():
    """Inject the stylesheet. Call once per run, before any page content."""
    t = tokens()
    st.html(f"""<style>
/* ---------- canvas ---------- */
.stApp {{ background: {t['glow']}, {t['bg']}; }}
[data-testid="stMainBlockContainer"] {{ padding-top: 2.2rem; padding-bottom: 4rem; max-width: 1480px; }}
[data-testid="stHeader"] {{ background: transparent; }}
html, body, .stApp {{ -webkit-font-smoothing: antialiased; font-feature-settings: "cv11", "ss01"; }}

/* ---------- cards (st.container(key="card_*")) ---------- */
[class*="st-key-card_"] {{
  background: {t['card']}; border: 1px solid {t['border']}; border-radius: 16px;
  padding: 1.1rem 1.2rem 1.15rem; box-shadow: {t['shadow']};
}}
.pt-card-title {{ font-family: Manrope, Inter, sans-serif; font-weight: 700; font-size: 1rem;
  letter-spacing: -.01em; color: {t['text']}; margin: 0 0 .15rem; }}
.pt-card-title small {{ font-family: Inter, sans-serif; font-weight: 500; font-size: .8rem; color: {t['muted']};
  margin-left: .45rem; letter-spacing: 0; }}

/* ---------- metric tiles ---------- */
[data-testid="stMain"] [data-testid="stMetric"], [role="dialog"] [data-testid="stMetric"] {{
  background: {t['card']}; border: 1px solid {t['border']}; border-radius: 14px;
  padding: .85rem 1rem .8rem; box-shadow: {t['shadow']};
  transition: transform .15s ease, box-shadow .15s ease, border-color .15s ease;
}}
[data-testid="stMain"] [data-testid="stMetric"]:hover {{
  transform: translateY(-2px); box-shadow: {t['shadow_hover']}; border-color: {t['primary']}55;
}}
[class*="st-key-card_"] [data-testid="stMetric"] {{ background: {t['card2']}; box-shadow: none; }}
[data-testid="stMetricLabel"] p {{
  font-size: .72rem; font-weight: 600; letter-spacing: .06em; text-transform: uppercase; color: {t['muted']};
}}
[data-testid="stMetricValue"] {{
  font-family: Manrope, Inter, sans-serif; letter-spacing: -.025em; font-variant-numeric: tabular-nums;
  line-height: 1.25; padding-top: .1rem;
}}
[data-testid="stMetricDelta"] {{ font-weight: 600; font-size: .78rem; }}

/* ---------- tabs as pills ---------- */
[data-testid="stTabs"] [data-baseweb="tab-list"] {{
  gap: .3rem; background: {t['card']}; border: 1px solid {t['border']}; border-radius: 12px;
  padding: .3rem; width: fit-content; max-width: 100%; box-shadow: {t['shadow']};
}}
[data-testid="stTabs"] [data-baseweb="tab"] {{
  border-radius: 9px; padding: .42rem .95rem; height: auto; font-weight: 600; color: {t['muted']};
}}
[data-testid="stTabs"] [data-baseweb="tab"][aria-selected="true"] {{
  background: {t['primary_soft']}; color: {t['primary']};
}}
[data-testid="stTabs"] [data-baseweb="tab-highlight"], [data-testid="stTabs"] [data-baseweb="tab-border"] {{
  display: none;
}}
[data-testid="stTabs"] [data-baseweb="tab-panel"] {{ padding-top: 1.1rem; }}

/* ---------- controls ---------- */
[data-testid="stMain"] button[kind="primary"], [role="dialog"] button[kind="primary"] {{
  font-weight: 600; box-shadow: 0 6px 16px {t['primary']}40; border: 0;
}}
[data-testid="stMain"] button[kind="secondary"] {{ font-weight: 600; background: {t['card']}; }}
[data-testid="stDataFrame"] {{ border-radius: 12px; overflow: hidden; box-shadow: {t['shadow']}; }}
[data-testid="stExpander"] details {{
  background: {t['card']}; border: 1px solid {t['border']}; border-radius: 14px; box-shadow: {t['shadow']};
}}
[data-testid="stExpander"] summary {{ font-weight: 600; }}
[role="dialog"] {{ border-radius: 18px; border: 1px solid {t['border']}; }}
hr {{ border-color: {t['border']}; }}
.tnum, [data-testid="stDataFrame"] {{ font-variant-numeric: tabular-nums; }}

/* ---------- page header ---------- */
.pt-head {{ display: flex; align-items: flex-end; justify-content: space-between; gap: 1rem; flex-wrap: wrap;
  margin: 0 0 1.1rem; }}
.pt-eyebrow {{ font-size: .7rem; font-weight: 700; letter-spacing: .14em; text-transform: uppercase;
  color: {t['primary']}; margin-bottom: .2rem; }}
.pt-title {{ font-family: Manrope, Inter, sans-serif; font-weight: 800; font-size: 1.95rem; line-height: 1.1;
  letter-spacing: -.03em; color: {t['text']}; margin: 0; }}
.pt-sub {{ color: {t['muted']}; font-size: .92rem; margin-top: .35rem; max-width: 62ch; }}
.pt-chip {{ display: inline-flex; align-items: center; gap: .4rem; font-size: .78rem; font-weight: 600;
  padding: .35rem .7rem; border-radius: 999px; background: {t['card']}; border: 1px solid {t['border']};
  color: {t['muted']}; box-shadow: {t['shadow']}; white-space: nowrap; }}
.pt-dot {{ width: 7px; height: 7px; border-radius: 50%; display: inline-block; }}

/* ---------- alert rows ---------- */
.pt-alert {{ display: flex; align-items: center; gap: .7rem; padding: .5rem .7rem; border-radius: 10px;
  background: {t['card2']}; border: 1px solid {t['border']}; border-left-width: 3px; margin-bottom: .4rem;
  font-size: .9rem; }}
.pt-alert b {{ font-family: Manrope, Inter, sans-serif; min-width: 6.5rem; }}
.pt-tag {{ font-size: .66rem; font-weight: 700; letter-spacing: .07em; text-transform: uppercase;
  padding: .16rem .45rem; border-radius: 6px; white-space: nowrap; }}

/* ---------- sidebar ---------- */
[data-testid="stSidebar"] {{ border-right: 1px solid rgba(255,255,255,.06); }}
[data-testid="stSidebarHeader"] {{ padding-top: 1.1rem; padding-bottom: .6rem; }}
[data-testid="stSidebarHeader"] img {{ height: 2.6rem; }}
[data-testid="stSidebarNavLink"] {{ border-radius: 10px; font-weight: 500; padding-top: .42rem; padding-bottom: .42rem; }}
[data-testid="stSidebarNavLink"][aria-current="page"] {{
  background: linear-gradient(90deg, rgba(122,162,255,.24), rgba(122,162,255,.07)); font-weight: 600;
  box-shadow: inset 2px 0 0 #7aa2ff;
}}
[data-testid="stNavSectionHeader"] {{ font-size: .68rem; letter-spacing: .12em; text-transform: uppercase;
  font-weight: 700; opacity: .55; }}
.pt-wallet {{ border-radius: 16px; padding: 1rem 1.05rem; color: #fff; position: relative; overflow: hidden;
  background: linear-gradient(135deg, #2b5bea 0%, #4a3fd6 55%, #6d3bd1 100%);
  box-shadow: 0 10px 26px rgba(43,91,234,.35); margin-bottom: .2rem; }}
.pt-wallet:after {{ content: ""; position: absolute; right: -40px; top: -50px; width: 150px; height: 150px;
  border-radius: 50%; background: rgba(255,255,255,.09); }}
.pt-wallet .l {{ font-size: .66rem; font-weight: 700; letter-spacing: .12em; text-transform: uppercase; opacity: .78; }}
.pt-wallet .v {{ font-family: Manrope, Inter, sans-serif; font-weight: 800; font-size: 1.6rem; letter-spacing: -.03em;
  margin: .1rem 0 .55rem; font-variant-numeric: tabular-nums; }}
.pt-wallet .row {{ display: grid; grid-template-columns: repeat(3, 1fr); gap: .4rem;
  border-top: 1px solid rgba(255,255,255,.18); padding-top: .55rem; }}
.pt-wallet .row span {{ display: block; font-size: .62rem; font-weight: 700; letter-spacing: .09em;
  text-transform: uppercase; opacity: .75; }}
.pt-wallet .row b {{ display: block; font-family: Manrope, Inter, sans-serif; font-weight: 700; font-size: .92rem;
  font-variant-numeric: tabular-nums; white-space: nowrap; }}
.pt-wallet .d {{ font-size: .78rem; font-weight: 600; margin-bottom: .5rem; opacity: .95; }}
.pt-side-label {{ font-size: .68rem; letter-spacing: .12em; text-transform: uppercase; font-weight: 700;
  opacity: .55; margin: .2rem 0 .1rem; }}
.pt-status {{ font-size: .76rem; opacity: .75; display: flex; align-items: center; gap: .45rem; }}
</style>""")
