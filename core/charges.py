"""Zerodha equity-delivery charge calculator."""
from .config import ZERODHA


def zerodha_charges(kind: str, qty: float, price: float, exchange: str = "NSE") -> dict:
    """Return a breakdown of charges for one delivery trade.

    kind: "BUY" or "SELL". DP charge applies once per scrip per sell day.
    """
    kind = kind.upper()
    turnover = float(qty) * float(price)
    if turnover <= 0 or kind not in ("BUY", "SELL"):
        return {"turnover": 0.0, "brokerage": 0.0, "stt": 0.0, "txn": 0.0, "sebi": 0.0,
                "stamp": 0.0, "gst": 0.0, "dp": 0.0, "total": 0.0}
    z = ZERODHA
    brokerage = z["brokerage"]
    stt = round(turnover * z["stt_rate"])  # STT is rounded to nearest rupee
    txn = turnover * z["txn_rate"].get(exchange, z["txn_rate"]["NSE"])
    sebi = turnover * z["sebi_rate"]
    stamp = turnover * z["stamp_rate"] if kind == "BUY" else 0.0
    gst = (brokerage + txn + sebi) * z["gst_rate"]
    dp = z["dp_per_scrip"] if kind == "SELL" else 0.0
    total = brokerage + stt + txn + sebi + stamp + gst + dp
    return {"turnover": turnover, "brokerage": brokerage, "stt": stt, "txn": txn,
            "sebi": sebi, "stamp": stamp, "gst": gst, "dp": dp, "total": round(total, 2)}
