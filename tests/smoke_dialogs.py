"""Exercise write dialogs end-to-end on a throwaway SQLite DB. Run: python tests/smoke_dialogs.py"""
import os
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
tmp = os.path.join(tempfile.mkdtemp(), "t.db")
os.environ["DATABASE_URL"] = "sqlite:///" + tmp
sys.path.insert(0, ROOT)

import pandas as pd  # noqa: E402
from streamlit.testing.v1 import AppTest  # noqa: E402

from core import db, ledger, nav, sample  # noqa: E402

OWNER = "local@dev"
eng = db.get_engine(os.environ["DATABASE_URL"])
sample.load_sample(eng, OWNER)


def data():
    return db.load_all(eng, OWNER)


# price the sample's capital entries (offline: trade prices stand in for closing prices)
d0 = data()
aud = nav.audit(d0["flows"], d0["txns"], d0["positions"], pd.DataFrame(), {}, 10.0)
db.update_flows_bulk(eng, OWNER, {int(r.id): {"nav": float(r.nav_new), "units": float(r.units_new)}
                                  for r in aud.itertuples()})
assert nav.check_units(data()["flows"], data()["investors"]) == []


def dialog(*spec):
    at = AppTest.from_file(os.path.join(HERE, "harness.py"), default_timeout=120)
    at.session_state["_dialog"] = spec
    at.run()
    ok(at)
    return at


def ok(at):
    assert not at.exception, [e.message for e in at.exception]


def txt(at):
    return " ".join(str(getattr(e, "value", "")) for e in list(at.error) + list(at.warning))


def units(iid):
    return nav.units_outstanding(data()["flows"], investor_id=iid)


pid = int(data()["positions"].query("symbol == 'RELIANCE'")["id"].iloc[0])

# 1. Add-on buy -----------------------------------------------------------
at = dialog("trade_dialog", pid, "BUY")
at.number_input(key="td_qty").set_value(5).run()
at.number_input(key="td_price").set_value(1300.0).run()
n_before = len(data()["txns"])
at.button(key="td_go").click().run()
assert len(data()["txns"]) == n_before + 1, "add-on not saved"
t = data()["txns"].sort_values("id").iloc[-1]
print(f"ok   add-on buy saved: {t['qty']:g} @ {t['price']} charges Rs {t['charges']}")

# 2. Oversized buy is blocked (cash must come from an investor) -----------
at = dialog("trade_dialog", pid, "BUY")
at.number_input(key="td_qty").set_value(50000).run()
assert "Insufficient cash" in txt(at), txt(at)
assert at.button(key="td_go").disabled
print("ok   oversize buy blocked")

# 3. Partial exit ---------------------------------------------------------
at = dialog("trade_dialog", pid, "SELL")
at.toggle(key="td_full").set_value(False).run()
at.number_input(key="td_qty").set_value(20).run()
at.button(key="td_go").click().run()
held = ledger.held_qty(data()["txns"], pid)
assert held == 135, held
print("ok   partial exit saved, remaining qty", held)

# 4. Full exit closes the position ---------------------------------------
at = dialog("trade_dialog", pid, "SELL")
at.button(key="td_go").click().run()
assert ledger.held_qty(data()["txns"], pid) == 0
print("ok   full exit -> position closed")

# 5. New investor ----------------------------------------------------------
at = dialog("investor_dialog")
at.text_input(key="iv_name").set_value("Zara").run()
at.button(key="iv_go").click().run()
inv = data()["investors"]
assert "Zara" in set(inv["name"])
zara = int(inv.loc[inv["name"] == "Zara", "id"].iloc[0])
at = dialog("investor_dialog")
at.text_input(key="iv_name").set_value("zara ").run()
assert "already an investor" in txt(at) and at.button(key="iv_go").disabled
print("ok   investor added; duplicate name blocked")

# 6. Deposit issues units at today's NAV ----------------------------------
total_before = nav.units_outstanding(data()["flows"])
at = dialog("funds_dialog", zara, "DEPOSIT")
at.number_input(key="fd_amt").set_value(50000.0).run()
at.button(key="fd_go").click().run()
f = data()["flows"].sort_values("id").iloc[-1]
assert f["investor_id"] == zara and f["kind"] == "DEPOSIT" and f["nav"] > 0
assert abs(f["units"] - round(50000 / f["nav"], 4)) < 1e-9
assert abs(nav.units_outstanding(data()["flows"]) - total_before - f["units"]) < 1e-6
print(f"ok   deposit of Rs 50,000 issued {f['units']:,.4f} units at NAV Rs {f['nav']:.4f}")

# 7. Withdrawals: more than held is blocked; a valid one redeems units -----
at = dialog("funds_dialog", zara, "WITHDRAWAL")
at.number_input(key="fd_amt").set_value(1e9).run()
assert "redeem more units" in txt(at), txt(at)
assert at.button(key="fd_go").disabled
at.number_input(key="fd_amt").set_value(5000.0).run()
u0 = units(zara)
at.button(key="fd_go").click().run()
f = data()["flows"].sort_values("id").iloc[-1]
assert f["kind"] == "WITHDRAWAL" and abs(u0 - units(zara) - f["units"]) < 1e-6
print(f"ok   over-withdrawal blocked; Rs 5,000 withdrawal redeemed {f['units']:,.4f} units")

# 8. Manual (locked) NAV ---------------------------------------------------
at = dialog("funds_dialog", zara, "DEPOSIT")
at.toggle(key="fd_manual").set_value(True).run()
at.number_input(key="fd_nav").set_value(12.5).run()
at.number_input(key="fd_amt").set_value(25000.0).run()
at.button(key="fd_go").click().run()
f = data()["flows"].sort_values("id").iloc[-1]
assert bool(f["nav_manual"]) and f["nav"] == 12.5 and f["units"] == 2000.0
print("ok   manual NAV entry saved and locked")

# 9. Withdraw everything -> zero units ------------------------------------
at = dialog("funds_dialog", zara, "WITHDRAWAL")
at.toggle(key="fd_full").set_value(True).run()
at.button(key="fd_go").click().run()
assert units(zara) == 0, units(zara)
s = nav.investor_summary(data()["investors"], data()["flows"], 10.0).set_index("name")
assert s.loc["Zara", "status"] == "Exited"
print("ok   full withdrawal leaves exactly zero units")

# 10. Deleting a deposit that later withdrawals depend on is blocked ------
first = int(data()["flows"].query("investor_id == @zara").sort_values("id")["id"].iloc[0])
at = dialog("delete_flow_dialog", first)
assert "redeem more units" in txt(at) and at.button(key="fdel_go").disabled
last = int(data()["flows"].query("investor_id == @zara").sort_values("id")["id"].iloc[-1])
at = dialog("delete_flow_dialog", last)
at.button(key="fdel_go").click().run()
assert last not in set(data()["flows"]["id"]) and units(zara) > 0
print("ok   dependent deposit protected; last withdrawal deleted")

# 11. An investor with entries cannot be removed ---------------------------
at = dialog("delete_investor_dialog", zara)
assert not [b for b in at.button if b.key == "ivd_go"]
print("ok   investor with capital entries cannot be removed")

# 12. Delete position ------------------------------------------------------
pid2 = int(data()["positions"].query("symbol == 'SUNPHARMA'")["id"].iloc[0])
at = dialog("delete_position_dialog", pid2)
at.text_input[0].set_value("SUNPHARMA").run()
at.button[0].click().run()
assert pid2 not in set(data()["positions"]["id"])
print("ok   position deleted")

# 13. Backup round-trip keeps investors and units --------------------------
before = data()
db.import_json(eng, OWNER, db.export_json(eng, OWNER))
after = data()
assert len(after["investors"]) == len(before["investors"]) and len(after["flows"]) == len(before["flows"])
assert abs(nav.units_outstanding(after["flows"]) - nav.units_outstanding(before["flows"])) < 1e-9
assert sorted(after["flows"]["units"].round(4)) == sorted(before["flows"]["units"].round(4))
print("ok   JSON backup round-trip preserves investors and units")

# 14. Final ledger is consistent -------------------------------------------
d = data()
assert ledger.check_ledger(d["flows"], d["txns"], d["positions"]) == []
assert nav.check_units(d["flows"], d["investors"]) == []
print("all dialog tests passed")
