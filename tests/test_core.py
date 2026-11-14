"""Offline tests for the accounting engine. Run: python -m pytest tests -q  (or python tests/test_core.py)"""
import datetime as dt
import os
import sys

import pandas as pd

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from core import analytics as an  # noqa: E402
from core import ledger as lg  # noqa: E402
from core.charges import zerodha_charges  # noqa: E402

D = dt.date


def _data():
    flows = pd.DataFrame([{"id": 1, "date": D(2025, 1, 1), "investor_id": 1, "kind": "DEPOSIT", "amount": 100000.0, "nav": 10.0, "units": 10000.0, "nav_manual": False, "note": ""}])
    positions = pd.DataFrame([{"id": 1, "symbol": "AAA", "exchange": "NSE", "name": "A", "sector": "X", "mcap": "Large",
                               "strategy": "Swing", "conviction": 3, "stop_loss": 90.0, "target1": 130.0, "target2": None,
                               "review_by": None, "cmp_override": None, "notes": "", "created_at": None}])
    txns = pd.DataFrame([
        {"id": 1, "position_id": 1, "kind": "BUY", "qty": 100, "price": 100.0, "date": D(2025, 1, 2), "charges": 0.0, "charges_auto": True, "reason": ""},
        {"id": 2, "position_id": 1, "kind": "BUY", "qty": 50, "price": 110.0, "date": D(2025, 2, 3), "charges": 0.0, "charges_auto": True, "reason": ""},
        {"id": 3, "position_id": 1, "kind": "SELL", "qty": 120, "price": 120.0, "date": D(2025, 3, 3), "charges": 0.0, "charges_auto": True, "reason": ""},
    ])
    return flows, positions, txns


def test_fifo_and_cash():
    flows, positions, txns = _data()
    summ, lots = lg.summarize(positions, txns, {"AAA.NS": {"price": 130.0, "prev_close": 125.0}}, today=D(2025, 4, 1))
    s = summ.iloc[0]
    assert s["qty"] == 30 and s["status"] == "Active"
    # FIFO: 100 @100 and 20 @110 sold @120 -> 2000 + 200
    assert abs(s["realized"] - 2200) < 1e-6
    assert abs(s["avg_cost"] - 110) < 1e-6
    assert abs(s["unreal"] - 600) < 1e-6
    cash = lg.cash_balance(flows, txns)
    assert abs(cash - (100000 - 10000 - 5500 + 14400)) < 1e-6
    assert lg.check_ledger(flows, txns, positions) == []


def test_validation_blocks():
    flows, positions, txns = _data()
    big = lg.with_txn(txns, {"position_id": 1, "kind": "BUY", "qty": 10000, "price": 100.0, "date": D(2025, 3, 5), "charges": 0})
    assert any(e["type"] == "cash" for e in lg.check_ledger(flows, big, positions))
    over = lg.with_txn(txns, {"position_id": 1, "kind": "SELL", "qty": 31, "price": 100.0, "date": D(2025, 3, 5), "charges": 0})
    assert any(e["type"] == "qty" for e in lg.check_ledger(flows, over, positions))
    wd = lg.with_flow(flows, {"investor_id": 1, "date": D(2025, 1, 3), "kind": "WITHDRAWAL", "amount": 95000.0, "nav": 10.0, "units": 9500.0})
    assert any(e["type"] == "cash" for e in lg.check_ledger(wd, txns, positions))


def test_charges():
    c = zerodha_charges("BUY", 100, 1000, "NSE")
    assert c["stt"] == 100 and abs(c["stamp"] - 15) < 1e-9 and c["dp"] == 0
    c2 = zerodha_charges("SELL", 100, 1000, "NSE")
    assert c2["stamp"] == 0 and c2["dp"] == 15.34


def test_daily_and_twr():
    flows, positions, txns = _data()
    daily = an.build_daily(flows, txns, positions, pd.DataFrame(), {"AAA.NS": {"price": 130.0}}, today=D(2025, 4, 1))
    last = daily.iloc[-1]
    assert abs(last["value"] - (lg.cash_balance(flows, txns) + 30 * 130)) < 1e-6
    assert abs(last["twr"] - last["value"] / 100000) < 1e-9  # no extra flows -> TWR == simple return
    x = an.portfolio_xirr(flows, last["value"], today=D(2025, 4, 1))
    assert x is not None and x > 0
    mr = an.monthly_returns(daily)
    assert not mr.empty


def test_tax():
    lots = pd.DataFrame([
        {"sell_date": D(2025, 6, 1), "buy_date": D(2024, 1, 1), "days": 517, "pnl": 200000.0},
        {"sell_date": D(2025, 6, 1), "buy_date": D(2025, 3, 1), "days": 92, "pnl": 10000.0},
    ])
    t = an.tax_summary(lots).iloc[0]
    assert t["FY"] == "FY 2025-26"
    assert abs(t["Est. tax"] - (10000 * 0.20 + 75000 * 0.125)) < 1e-6


if __name__ == "__main__":
    for name, fn in list(globals().items()):
        if name.startswith("test_"):
            fn()
            print("ok", name)
