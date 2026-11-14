"""Demo fund (illustrative prices, approximate) for exploring the app.

Capital entries are saved at face value as placeholders; the caller then runs the NAV audit
(state.audit_for) and applies it, which prices every entry at the NAV of its own date."""
import datetime as dt

from . import db
from .charges import zerodha_charges
from .nav import FACE_VALUE, units_for

D = dt.date

SAMPLE = [
    # symbol, name, sector, strategy, conviction, sl, t1, t2, review, trades[(kind, qty, price, date, reason)], thesis
    ("RELIANCE", "Reliance Industries", "Energy", "Long-term", 4, 1150, 1650, 1800, None,
     [("BUY", 100, 1240, D(2025, 1, 13), "Base building near 1200 support, retail + Jio IPO optionality"),
      ("BUY", 50, 1300, D(2025, 4, 15), "Add-on after market-wide sell-off recovered")],
     "Conglomerate re-rating: Jio listing, new energy capex payback, retail margin recovery."),
    ("ICICIBANK", "ICICI Bank", "Financial Services", "Positional", 4, 1300, 1550, None, None,
     [("BUY", 120, 1250, D(2025, 1, 20), "Best-in-class private bank, ROA > 2%"),
      ("SELL", 60, 1420, D(2025, 6, 25), "Partial booking near all-time high")],
     "Consistent compounding, asset quality strongest among peers."),
    ("INFY", "Infosys", "Technology", "Momentum", 2, 1750, 2100, None, None,
     [("BUY", 80, 1880, D(2025, 2, 3), "Guidance upgrade momentum"),
      ("SELL", 80, 1560, D(2025, 4, 7), "Stop-loss hit after US tariff sell-off — thesis broken")],
     "Momentum trade on deal wins; exit if 1750 breaks."),
    ("TRENT", "Trent", "Consumer Cyclical", "Momentum", 3, 4700, 6000, None, None,
     [("BUY", 20, 5100, D(2025, 3, 10), "Reversal from 200 DMA after sharp correction"),
      ("SELL", 20, 5900, D(2025, 5, 20), "Target zone reached")],
     "Zudio store expansion; bought the correction."),
    ("TATAPOWER", "Tata Power", "Utilities", "Positional", 3, 340, 460, None, D(2026, 10, 1),
     [("BUY", 300, 360, D(2025, 2, 18), "Renewables capacity ramp + rooftop solar"),
      ("BUY", 200, 395, D(2025, 6, 10), "Pyramid on breakout above 390")],
     "Utility turning into a renewables growth story."),
    ("BHARTIARTL", "Bharti Airtel", "Communication Services", "Long-term", 5, 1500, 2200, None, None,
     [("BUY", 60, 1580, D(2025, 1, 27), "Tariff hikes + ARPU expansion")],
     "Telecom duopoly economics; ARPU heading to ₹300."),
    ("POLYCAB", "Polycab India", "Industrials", "Growth", 3, 5800, 7200, None, None,
     [("BUY", 15, 6200, D(2025, 3, 3), "Cables & wires capex cycle"),
      ("SELL", 15, 6900, D(2025, 7, 15), "Booked ahead of results")],
     "Beneficiary of power T&D and real-estate cycle."),
    ("TCS", "Tata Consultancy Services", "Technology", "Value", 2, 3200, 4000, None, None,
     [("BUY", 30, 3500, D(2025, 7, 1), "Valuation comfort at 5-yr low P/E"),
      ("SELL", 30, 3100, D(2025, 9, 15), "Exited — demand weakness persisted")],
     "Mean-reversion bet on IT valuations."),
    ("SUNPHARMA", "Sun Pharmaceutical", "Healthcare", "Swing", 3, 1550, 1850, None, None,
     [("BUY", 60, 1650, D(2025, 8, 4), "Specialty portfolio growth, pullback to support")],
     "Specialty pharma (Ilumya etc.) driving margin expansion."),
]


def load_sample(engine, owner):
    face = FACE_VALUE
    people = {}
    for name, relation, manager in (("You (manager)", "Self", True), ("Ahmed", "Family", False),
                                    ("Fatima", "Relative", False), ("Imran", "Friend", False)):
        people[name] = db.add_investor(engine, owner, name=name, relation=relation, is_manager=manager,
                                       notes="Sample investor.")
    for name, date, kind, amount, note in (
            ("You (manager)", D(2025, 1, 1), "DEPOSIT", 1000000, "Starting capital"),
            ("Ahmed", D(2025, 3, 17), "DEPOSIT", 300000, "Joined the fund"),
            ("Fatima", D(2025, 6, 2), "DEPOSIT", 200000, "Joined the fund"),
            ("Imran", D(2025, 8, 11), "DEPOSIT", 500000, "Joined the fund"),
            ("Ahmed", D(2025, 10, 6), "WITHDRAWAL", 100000, "Partial withdrawal")):
        db.add_flow(engine, owner, people[name], date, kind, amount, face, units_for(amount, face),
                    note="Sample: " + note)
    for sym, name, sector, stg, conv, sl, t1, t2, review, trades, thesis in SAMPLE:
        kind, qty, price, date, reason = trades[0]
        ch = zerodha_charges(kind, qty, price, "NSE")["total"]
        pid = db.add_position(engine, owner,
                              {"symbol": sym, "exchange": "NSE", "name": name, "sector": sector, "mcap": "Large",
                               "strategy": stg, "conviction": conv, "stop_loss": sl, "target1": t1, "target2": t2,
                               "review_by": review, "notes": "Sample data — prices are illustrative."},
                              {"kind": kind, "qty": qty, "price": price, "date": date, "charges": ch,
                               "charges_auto": True, "reason": reason}, thesis)
        for kind, qty, price, date, reason in trades[1:]:
            ch = zerodha_charges(kind, qty, price, "NSE")["total"]
            db.add_txn(engine, owner, pid, kind=kind, qty=qty, price=price, date=date, charges=ch,
                       charges_auto=True, reason=reason)
        if sym == "BHARTIARTL":
            db.add_txn(engine, owner, pid, kind="DIVIDEND", qty=60, price=16, date=D(2025, 7, 28), charges=0,
                       charges_auto=False, reason="Final dividend FY25")
    db.add_watch(engine, owner, symbol="TITAN", exchange="NSE", name="Titan Company", added_on=D(2025, 9, 1),
                 price_added=3450, trigger_price=3200, trigger_dir="below", thesis="Buy on dip below 3200",
                 tags="consumption, jewellery")
    db.add_watch(engine, owner, symbol="LT", exchange="NSE", name="Larsen & Toubro", added_on=D(2025, 9, 1),
                 price_added=3600, trigger_price=4000, trigger_dir="above", thesis="Breakout above 4000 = capex cycle confirmation",
                 tags="capex, infra")
