"""Offline tests for unit / NAV accounting. Run: python tests/test_nav.py  (or python -m pytest tests -q)

Scenario (prices are supplied, nothing is downloaded):
  01 Jan  Ali puts in 10,00,000 at face value 10        -> 1,00,000 units
  02 Jan  fund buys 1,000 AAA @ 500
  02 Mar  AAA closes 600 -> fund 11,00,000, NAV 11.     Bilal adds 2,20,000 -> 20,000 units
  01 Jun  AAA closes 720 -> fund 14,40,000, NAV 12.     Chand adds 1,20,000 -> 10,000 units
  01 Sep  AAA closes 540 -> fund 13,80,000, NAV 10.6154. Bilal withdraws 1,06,154 -> 10,000 units
  01 Oct  AAA quoted 660 (today)
"""
import datetime as dt
import os
import sys

import pandas as pd

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from core import analytics as an  # noqa: E402
from core import ledger as lg  # noqa: E402
from core import nav  # noqa: E402

D = dt.date
TODAY = D(2026, 10, 1)
ALI, BILAL, CHAND = 1, 2, 3
QUOTES = {"AAA.NS": {"price": 660.0}}


def _base():
    investors = pd.DataFrame([
        {"id": ALI, "name": "Ali", "relation": "Self", "contact": "", "is_manager": True, "notes": ""},
        {"id": BILAL, "name": "Bilal", "relation": "Friend", "contact": "", "is_manager": False, "notes": ""},
        {"id": CHAND, "name": "Chand", "relation": "Family", "contact": "", "is_manager": False, "notes": ""},
    ])
    positions = pd.DataFrame([{"id": 1, "symbol": "AAA", "exchange": "NSE", "name": "A", "sector": "X",
                               "mcap": "Large", "strategy": "Swing", "conviction": 3, "stop_loss": None,
                               "target1": None, "target2": None, "review_by": None, "cmp_override": None,
                               "notes": "", "created_at": None}])
    txns = pd.DataFrame([{"id": 1, "position_id": 1, "kind": "BUY", "qty": 1000, "price": 500.0,
                          "date": D(2026, 1, 2), "charges": 0.0, "charges_auto": True, "reason": ""}])
    closes = {D(2026, 1, 2): 500.0, D(2026, 2, 27): 590.0, D(2026, 3, 2): 600.0, D(2026, 3, 3): 610.0,
              D(2026, 6, 1): 720.0, D(2026, 9, 1): 540.0, D(2026, 9, 30): 650.0}
    hist = pd.DataFrame({"AAA.NS": pd.Series({pd.Timestamp(k): v for k, v in closes.items()})})
    return investors, positions, txns, hist


EMPTY = pd.DataFrame(columns=["id", "investor_id", "date", "kind", "amount", "nav", "units", "nav_manual", "note"])


def _record(flows, txns, positions, hist, iid, date, kind, amount):
    """Record a flow the way the app does: ask for the NAV on that date, then store NAV + units."""
    q = nav.nav_on(flows, txns, positions, hist, QUOTES, date, 10.0, today=TODAY)
    row = {"id": len(flows) + 1, "investor_id": iid, "date": date, "kind": kind, "amount": float(amount),
           "nav": q["nav"], "units": nav.units_for(amount, q["nav"]), "nav_manual": False, "note": ""}
    return pd.concat([flows, pd.DataFrame([row])], ignore_index=True) if not flows.empty else pd.DataFrame([row]), q


def _scenario():
    investors, positions, txns, hist = _base()
    f, q1 = _record(EMPTY, txns, positions, hist, ALI, D(2026, 1, 1), "DEPOSIT", 1000000)
    f, q2 = _record(f, txns, positions, hist, BILAL, D(2026, 3, 2), "DEPOSIT", 220000)
    f, q3 = _record(f, txns, positions, hist, CHAND, D(2026, 6, 1), "DEPOSIT", 120000)
    f, q4 = _record(f, txns, positions, hist, BILAL, D(2026, 9, 1), "WITHDRAWAL", 106154)
    return investors, positions, txns, hist, f, (q1, q2, q3, q4)


def test_units_are_issued_at_the_nav_of_the_day():
    *_, f, (q1, q2, q3, q4) = _scenario()
    assert q1["basis"] == "face" and q1["nav"] == 10.0
    assert abs(q2["nav"] - 11.0) < 1e-9 and abs(q2["value_before"] - 1100000) < 1e-6
    assert abs(q3["nav"] - 12.0) < 1e-9
    assert abs(q4["nav"] - 10.6154) < 1e-9          # 13,80,000 / 1,30,000 units
    assert list(f["units"]) == [100000.0, 20000.0, 10000.0, 10000.0]
    assert nav.units_outstanding(f) == 120000.0
    assert nav.units_outstanding(f, before=D(2026, 6, 1)) == 120000.0
    assert nav.units_outstanding(f, investor_id=BILAL) == 10000.0


def test_a_flow_does_not_move_the_nav_for_others():
    investors, positions, txns, hist, f, _ = _scenario()
    # close of 2 Mar: value 13,20,000 (incl. Bilal's 2,20,000) over 1,20,000 units is still 11
    v = nav.fund_value(f, txns, positions, hist, QUOTES, D(2026, 3, 2), TODAY)
    assert abs(v / nav.units_outstanding(f, as_of=D(2026, 3, 2)) - 11.0) < 1e-9
    # a second flow on the same day gets the same NAV as the first
    q = nav.nav_on(f, txns, positions, hist, QUOTES, D(2026, 3, 2), 10.0, today=TODAY)
    assert abs(q["nav"] - 11.0) < 1e-9


def test_investor_values_add_up_to_the_fund():
    investors, positions, txns, hist, f, _ = _scenario()
    total = lg.cash_balance(f, txns) + 1000 * 660.0
    assert abs(total - (1000000 - 500000 + 220000 + 120000 - 106154 + 660000)) < 1e-6
    nav_now = total / nav.units_outstanding(f)
    s = nav.investor_summary(investors, f, nav_now, today=TODAY).set_index("name")
    assert abs(s["value"].sum() - total) < 1e-6
    assert abs(s["share_pct"].sum() - 100) < 1e-9
    assert abs(s.loc["Ali", "value"] - 100000 * nav_now) < 1e-6
    # Bilal: bought 20,000 @ 11, sold 10,000 @ 10.6154 -> realized loss on half his cost
    b = s.loc["Bilal"]
    assert abs(b["cost"] - 110000) < 1e-6 and abs(b["realized"] - (106154 - 110000)) < 1e-6
    assert abs(b["gain"] - (b["value"] + 106154 - 220000)) < 1e-6
    assert abs(b["avg_nav"] - 11.0) < 1e-9
    # Ali never added or withdrew, so his XIRR equals the NAV's annualised growth
    yrs = (TODAY - D(2026, 1, 1)).days / 365.0
    assert abs(s.loc["Ali", "xirr"] - ((nav_now / 10.0) ** (1 / yrs) - 1)) < 1e-4
    assert s.loc["Chand", "gain"] < 0 < s.loc["Ali", "gain"]   # Chand came in at 12, NAV is now ~11.6


def test_daily_nav_history():
    investors, positions, txns, hist, f, _ = _scenario()
    daily = nav.attach_nav(an.build_daily(f, txns, positions, hist, QUOTES, today=TODAY), f, 10.0)
    assert abs(daily.loc[pd.Timestamp(2026, 3, 2), "nav"] - 11.0) < 1e-9
    assert abs(daily.loc[pd.Timestamp(2026, 3, 3), "nav"] - (500000 + 220000 + 610000) / 120000) < 1e-9
    assert abs(daily.loc[pd.Timestamp(2026, 6, 1), "nav"] - 12.0) < 1e-9
    assert abs(daily.loc[pd.Timestamp(2026, 9, 1), "nav"] - 10.6154) < 1e-4
    last = daily.iloc[-1]
    assert abs(last["nav"] - last["value"] / 120000) < 1e-9 and abs(last["twr"] - last["nav"] / 10) < 1e-12
    h = nav.investor_history(daily, f, BILAL)
    assert abs(h["value"].iloc[-1] - 10000 * last["nav"]) < 1e-6 and abs(h["invested"].iloc[-1] - 113846) < 1e-6
    assert h.loc[pd.Timestamp(2026, 3, 2), "units"] == 20000.0


def test_validation():
    investors, positions, txns, hist, f, _ = _scenario()
    assert nav.check_units(f, investors) == []
    over = lg.with_flow(f, {"investor_id": CHAND, "date": D(2026, 9, 15), "kind": "WITHDRAWAL",
                            "amount": 200000.0, "nav": 11.0, "units": 18181.8182})
    errs = nav.check_units(over, investors)
    assert len(errs) == 1 and "Chand" in errs[0]["msg"]
    early = lg.with_flow(f, {"investor_id": CHAND, "date": D(2026, 5, 1), "kind": "WITHDRAWAL",
                             "amount": 1000.0, "nav": 11.0, "units": 90.9091})
    assert nav.check_units(early, investors)          # he held nothing before June


def test_audit_reproduces_and_repairs_the_ledger():
    investors, positions, txns, hist, f, _ = _scenario()
    a = nav.audit(f, txns, positions, hist, QUOTES, 10.0, today=TODAY)
    assert not a["changed"].any() and not a["drift"].any()
    # corrupt Chand's entry (wrong NAV 10 instead of 12): the audit flags and repairs it
    bad = f.copy()
    bad.loc[bad["id"] == 3, ["nav", "units"]] = [10.0, 12000.0]
    a = nav.audit(bad, txns, positions, hist, QUOTES, 10.0, today=TODAY).set_index("id")
    assert a.loc[3, "drift"] and a.loc[3, "nav_new"] == 12.0 and a.loc[3, "units_new"] == 10000.0
    assert a.loc[4, "nav_new"] == 10.6154 and a.loc[4, "units_new"] == 10000.0
    # ...unless it is locked, in which case later flows are priced off the units it really issued
    bad.loc[bad["id"] == 3, "nav_manual"] = True
    a = nav.audit(bad, txns, positions, hist, QUOTES, 10.0, today=TODAY).set_index("id")
    assert a.loc[3, "nav_new"] == 10.0 and a.loc[3, "units_new"] == 12000.0
    assert abs(a.loc[4, "nav_new"] - round(1380000 / 132000, 4)) < 1e-9


def test_full_exit_and_restart():
    investors, positions, txns, hist, f, _ = _scenario()
    # Bilal redeems his remaining 10,000 units at the 30 Sep NAV
    q = nav.nav_on(f, txns, positions, hist, QUOTES, D(2026, 9, 30), 10.0, today=TODAY)
    held = nav.units_outstanding(f, investor_id=BILAL)
    row = {"id": 5, "investor_id": BILAL, "date": D(2026, 9, 30), "kind": "WITHDRAWAL",
           "amount": round(held * q["nav"], 2), "nav": q["nav"], "units": held, "nav_manual": False, "note": ""}
    f2 = pd.concat([f, pd.DataFrame([row])], ignore_index=True)
    s = nav.investor_summary(investors, f2, 11.0, today=TODAY).set_index("name")
    assert s.loc["Bilal", "units"] == 0 and s.loc["Bilal", "status"] == "Exited" and s.loc["Bilal", "value"] == 0
    assert nav.statement(f2, BILAL)["balance"].iloc[-1] == 0
    assert bool(nav.audit(f2, txns, positions, hist, QUOTES, 10.0, today=TODAY).set_index("id").loc[5, "units_new"] == held)
    # if everybody leaves, the next investor comes in at the last NAV, not back at face value
    solo = f[f["investor_id"] == ALI]
    out = lg.with_flow(solo, {"investor_id": ALI, "date": D(2026, 3, 2), "kind": "WITHDRAWAL",
                              "amount": 1100000.0, "nav": 11.0, "units": 100000.0})
    q = nav.nav_on(out, txns.iloc[0:0], positions, hist, QUOTES, D(2026, 4, 1), 10.0, today=TODAY)
    assert q["basis"] == "carried" and q["nav"] == 11.0


if __name__ == "__main__":
    for name, fn in list(globals().items()):
        if name.startswith("test_"):
            fn()
            print("ok", name)
