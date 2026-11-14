"""Static configuration: charge rates, tax rules, palettes, option lists."""
from datetime import date

# ---------------------------------------------------------------- Zerodha
# Equity delivery (CNC). Source: zerodha.com/charges — review periodically.
ZERODHA = {
    "brokerage": 0.0,                 # ₹0 on delivery
    "stt_rate": 0.001,                # 0.1% on buy and sell
    "txn_rate": {"NSE": 0.0000297,    # exchange transaction charge
                 "BSE": 0.0000375},
    "sebi_rate": 10 / 1e7,            # ₹10 per crore
    "stamp_rate": 0.00015,            # 0.015% on buy side
    "gst_rate": 0.18,                 # on brokerage + txn + SEBI
    "dp_per_scrip": 15.34,            # per scrip per sell day (incl. GST)
}

# ---------------------------------------------------------------- Tax
NEW_REGIME_FROM_FY = 2024  # FY 2024-25 onwards (Budget July 2024)
TAX_RULES = {
    "new": {"stcg": 0.20, "ltcg": 0.125, "exemption": 125000},
    "old": {"stcg": 0.15, "ltcg": 0.10, "exemption": 100000},
}
LTCG_MIN_DAYS = 365  # held for more than 12 months -> long term

# ---------------------------------------------------------------- Defaults
DEFAULT_SETTINGS = {
    "concentration_pct": 15.0,   # alert when a stock is above this % of portfolio
    "near_sl_pct": 5.0,          # alert when CMP within this % above SL
    "risk_free_pct": 7.0,        # for reference only
}

STRATEGIES = ["Positional", "Swing", "Long-term", "Momentum", "Value", "Growth",
              "Turnaround", "Dividend", "Special situation", "Other"]
MCAP_BUCKETS = ["Large", "Mid", "Small", "Micro", "Unknown"]
EXCHANGES = ["NSE", "BSE"]
BENCHMARK = "^NSEI"
BENCHMARK_NAME = "Nifty 50"

# Market-cap bucket cut-offs in ₹ (approximate, AMFI-like)
MCAP_CUTOFFS = [(1.0e12, "Large"), (3.3e11, "Mid"), (5.0e10, "Small"), (0, "Micro")]

# ---------------------------------------------------------------- Palette
# Categorical (fixed order, never cycled) — validated dataviz reference palette.
SERIES = ["#2a78d6", "#eb6834", "#1baf7a", "#eda100",
          "#e87ba4", "#008300", "#6250d6", "#e34948"]
OTHER_GREY = "#9a9893"
GAIN = "#12b76a"
LOSS = "#f04438"
NEUTRAL = "#8a8984"
DIVERGING = [[0.0, "#d03b3b"], [0.5, "#f0efec"], [1.0, "#2a78d6"]]  # loss -> 0 -> gain
CASH_COLOR = "#b8b6ae"


def today() -> date:
    return date.today()

# ---------------------------------------------------------------- Win/loss sequence
BREADTH_URL = "https://abdullahdashboard.streamlit.app/"
WIN_PCT = 5.0      # return above this = win (green)
LOSS_PCT = -5.0    # return below this = loss (red); in between = flat (yellow)
ZONE_COLORS = {"Win": "#12b76a", "Flat": "#eda100", "Loss": "#f04438"}

# ---------------------------------------------------------------- Fund / investors
DEFAULT_FUND_NAME = "Family Fund"
RELATIONS = ["Self", "Family", "Relative", "Friend", "Other"]
