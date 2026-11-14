"""Database layer: SQLAlchemy models + owner-scoped repository functions.

Works with SQLite (local) and Postgres/Supabase (cloud). Every public function
takes the signed-in user's email as `owner` (the fund manager), so one database
can safely hold several managers' funds. All tables are prefixed `fund_` so this
app can share a database with the personal Portfolio Tracker without clashing.

Unit accounting: every capital flow belongs to an investor and stores the NAV it
was transacted at and the units issued (deposit) or redeemed (withdrawal). Those
two numbers are ledger facts: they are frozen when the entry is saved and only
change if the manager explicitly applies the NAV audit.
"""
import datetime as dt
import json
from functools import lru_cache
from typing import Optional

import pandas as pd
from sqlalchemy import (Boolean, Date, DateTime, Float, ForeignKey, Integer, String,
                        Text, create_engine, delete, select)
from sqlalchemy.orm import DeclarativeBase, Mapped, Session, mapped_column, relationship


class Base(DeclarativeBase):
    pass


class Investor(Base):
    __tablename__ = "fund_investors"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    owner: Mapped[str] = mapped_column(String(255), index=True)
    name: Mapped[str] = mapped_column(String(120))
    relation: Mapped[Optional[str]] = mapped_column(String(40), default="")   # Self / Family / Friend / ...
    contact: Mapped[Optional[str]] = mapped_column(String(255), default="")   # phone or e-mail, free text
    is_manager: Mapped[bool] = mapped_column(Boolean, default=False)
    notes: Mapped[Optional[str]] = mapped_column(Text, default="")
    created_at: Mapped[dt.datetime] = mapped_column(DateTime, default=dt.datetime.utcnow)


class CapitalFlow(Base):
    __tablename__ = "fund_flows"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    owner: Mapped[str] = mapped_column(String(255), index=True)
    investor_id: Mapped[int] = mapped_column(ForeignKey("fund_investors.id"), index=True)
    date: Mapped[dt.date] = mapped_column(Date)
    kind: Mapped[str] = mapped_column(String(16))          # DEPOSIT / WITHDRAWAL
    amount: Mapped[float] = mapped_column(Float)           # rupees, always positive
    nav: Mapped[float] = mapped_column(Float)              # NAV per unit the flow was transacted at
    units: Mapped[float] = mapped_column(Float)            # units issued / redeemed, always positive
    nav_manual: Mapped[bool] = mapped_column(Boolean, default=False)   # True = locked; the audit never changes it
    note: Mapped[Optional[str]] = mapped_column(Text, default="")


class Position(Base):
    __tablename__ = "fund_positions"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    owner: Mapped[str] = mapped_column(String(255), index=True)
    symbol: Mapped[str] = mapped_column(String(32))
    exchange: Mapped[str] = mapped_column(String(8), default="NSE")
    name: Mapped[Optional[str]] = mapped_column(String(255), default="")
    sector: Mapped[Optional[str]] = mapped_column(String(120), default="Unclassified")
    mcap: Mapped[Optional[str]] = mapped_column(String(16), default="Unknown")
    strategy: Mapped[Optional[str]] = mapped_column(String(40), default="Positional")
    conviction: Mapped[Optional[int]] = mapped_column(Integer, default=3)
    stop_loss: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    target1: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    target2: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    review_by: Mapped[Optional[dt.date]] = mapped_column(Date, nullable=True)
    cmp_override: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    notes: Mapped[Optional[str]] = mapped_column(Text, default="")
    created_at: Mapped[dt.datetime] = mapped_column(DateTime, default=dt.datetime.utcnow)
    transactions = relationship("Transaction", cascade="all, delete-orphan", back_populates="position")
    thesis = relationship("ThesisEntry", cascade="all, delete-orphan", back_populates="position")


class Transaction(Base):
    __tablename__ = "fund_transactions"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    position_id: Mapped[int] = mapped_column(ForeignKey("fund_positions.id", ondelete="CASCADE"), index=True)
    kind: Mapped[str] = mapped_column(String(10))          # BUY / SELL / DIVIDEND
    qty: Mapped[float] = mapped_column(Float)
    price: Mapped[float] = mapped_column(Float)            # DIVIDEND: per-share dividend
    date: Mapped[dt.date] = mapped_column(Date)
    charges: Mapped[float] = mapped_column(Float, default=0.0)
    charges_auto: Mapped[bool] = mapped_column(Boolean, default=True)
    reason: Mapped[Optional[str]] = mapped_column(Text, default="")
    position = relationship("Position", back_populates="transactions")


class ThesisEntry(Base):
    __tablename__ = "fund_thesis_log"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    position_id: Mapped[int] = mapped_column(ForeignKey("fund_positions.id", ondelete="CASCADE"), index=True)
    date: Mapped[dt.date] = mapped_column(Date)
    text: Mapped[str] = mapped_column(Text)
    position = relationship("Position", back_populates="thesis")


class WatchItem(Base):
    __tablename__ = "fund_watchlist"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    owner: Mapped[str] = mapped_column(String(255), index=True)
    symbol: Mapped[str] = mapped_column(String(32))
    exchange: Mapped[str] = mapped_column(String(8), default="NSE")
    name: Mapped[Optional[str]] = mapped_column(String(255), default="")
    added_on: Mapped[dt.date] = mapped_column(Date)
    price_added: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    trigger_price: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    trigger_dir: Mapped[Optional[str]] = mapped_column(String(8), default="below")  # below / above
    thesis: Mapped[Optional[str]] = mapped_column(Text, default="")
    tags: Mapped[Optional[str]] = mapped_column(String(255), default="")


class Setting(Base):
    __tablename__ = "fund_settings"
    owner: Mapped[str] = mapped_column(String(255), primary_key=True)
    key: Mapped[str] = mapped_column(String(64), primary_key=True)
    value: Mapped[str] = mapped_column(Text)


class PriceCache(Base):
    __tablename__ = "fund_price_cache"
    ticker: Mapped[str] = mapped_column(String(40), primary_key=True)
    price: Mapped[float] = mapped_column(Float)
    prev_close: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    updated_at: Mapped[dt.datetime] = mapped_column(DateTime, default=dt.datetime.utcnow)


# ====================================================================== engine
@lru_cache(maxsize=4)
def get_engine(url: str):
    kwargs = {"pool_pre_ping": True}
    if url.startswith("sqlite"):
        kwargs["connect_args"] = {"check_same_thread": False}
    else:
        kwargs.update(pool_size=3, max_overflow=2, pool_recycle=300)
    engine = create_engine(url, **kwargs)
    Base.metadata.create_all(engine)
    return engine


def _row(obj, cols):
    return {c: getattr(obj, c) for c in cols}


INV_COLS = ["id", "name", "relation", "contact", "is_manager", "notes", "created_at"]
FLOW_COLS = ["id", "investor_id", "date", "kind", "amount", "nav", "units", "nav_manual", "note"]
POS_COLS = ["id", "symbol", "exchange", "name", "sector", "mcap", "strategy", "conviction",
            "stop_loss", "target1", "target2", "review_by", "cmp_override", "notes", "created_at"]
TXN_COLS = ["id", "position_id", "kind", "qty", "price", "date", "charges", "charges_auto", "reason"]
THESIS_COLS = ["id", "position_id", "date", "text"]
WATCH_COLS = ["id", "symbol", "exchange", "name", "added_on", "price_added", "trigger_price",
              "trigger_dir", "thesis", "tags"]


# ====================================================================== reads
def load_all(engine, owner: str) -> dict:
    """Load every table for one owner as DataFrames."""
    with Session(engine) as s:
        invs = s.scalars(select(Investor).where(Investor.owner == owner)).all()
        flows = s.scalars(select(CapitalFlow).where(CapitalFlow.owner == owner)).all()
        poss = s.scalars(select(Position).where(Position.owner == owner)).all()
        pids = [p.id for p in poss]
        txns = s.scalars(select(Transaction).where(Transaction.position_id.in_(pids))).all() if pids else []
        thes = s.scalars(select(ThesisEntry).where(ThesisEntry.position_id.in_(pids))).all() if pids else []
        watch = s.scalars(select(WatchItem).where(WatchItem.owner == owner)).all()
        sets = s.scalars(select(Setting).where(Setting.owner == owner)).all()
        out = {
            "investors": pd.DataFrame([_row(o, INV_COLS) for o in invs], columns=INV_COLS),
            "flows": pd.DataFrame([_row(o, FLOW_COLS) for o in flows], columns=FLOW_COLS),
            "positions": pd.DataFrame([_row(o, POS_COLS) for o in poss], columns=POS_COLS),
            "txns": pd.DataFrame([_row(o, TXN_COLS) for o in txns], columns=TXN_COLS),
            "thesis": pd.DataFrame([_row(o, THESIS_COLS) for o in thes], columns=THESIS_COLS),
            "watch": pd.DataFrame([_row(o, WATCH_COLS) for o in watch], columns=WATCH_COLS),
            "settings": {o.key: o.value for o in sets},
        }
    for key, col in (("investors", "is_manager"), ("flows", "nav_manual")):
        if not out[key].empty:
            out[key][col] = out[key][col].fillna(False).astype(bool)
    for key, cols in (("flows", ["date"]), ("txns", ["date"]), ("thesis", ["date"]),
                      ("watch", ["added_on"]), ("positions", ["review_by"])):
        for c in cols:
            if not out[key].empty:
                out[key][c] = pd.to_datetime(out[key][c]).dt.date
    return out


# ====================================================================== investors
INVESTOR_FIELDS = {"name", "relation", "contact", "is_manager", "notes"}


def add_investor(engine, owner, **fields) -> int:
    with Session(engine) as s:
        inv = Investor(owner=owner, **{k: v for k, v in fields.items() if k in INVESTOR_FIELDS})
        s.add(inv)
        s.commit()
        return inv.id


def update_investor(engine, owner, investor_id, **fields):
    with Session(engine) as s:
        inv = s.get(Investor, investor_id)
        if inv and inv.owner == owner:
            for k, v in fields.items():
                if k in INVESTOR_FIELDS:
                    setattr(inv, k, v)
            s.commit()


def delete_investor(engine, owner, investor_id) -> bool:
    """Delete an investor who has no capital entries. Returns False (and does nothing) otherwise."""
    with Session(engine) as s:
        inv = s.get(Investor, investor_id)
        if not inv or inv.owner != owner:
            return False
        if s.scalars(select(CapitalFlow).where(CapitalFlow.investor_id == investor_id)).first() is not None:
            return False
        s.delete(inv)
        s.commit()
        return True


# ====================================================================== capital flows
FLOW_FIELDS = {"investor_id", "date", "kind", "amount", "nav", "units", "nav_manual", "note"}


def add_flow(engine, owner, investor_id, date, kind, amount, nav, units, nav_manual=False, note="") -> int:
    with Session(engine) as s:
        inv = s.get(Investor, investor_id)
        if not inv or inv.owner != owner:
            raise ValueError("Unknown investor")
        f = CapitalFlow(owner=owner, investor_id=investor_id, date=date, kind=kind, amount=float(amount),
                        nav=float(nav), units=float(units), nav_manual=bool(nav_manual), note=note or "")
        s.add(f)
        s.commit()
        return f.id


def update_flow(engine, owner, flow_id, **fields):
    with Session(engine) as s:
        f = s.get(CapitalFlow, flow_id)
        if f and f.owner == owner:
            for k, v in fields.items():
                if k in FLOW_FIELDS:
                    setattr(f, k, v)
            s.commit()


def update_flows_bulk(engine, owner, changes: dict):
    """changes = {flow_id: {field: value}}, applied in one transaction (used by the NAV audit)."""
    with Session(engine) as s:
        for fid, fields in changes.items():
            f = s.get(CapitalFlow, int(fid))
            if f and f.owner == owner:
                for k, v in fields.items():
                    if k in FLOW_FIELDS:
                        setattr(f, k, v)
        s.commit()


def delete_flow(engine, owner, flow_id):
    with Session(engine) as s:
        s.execute(delete(CapitalFlow).where(CapitalFlow.id == flow_id, CapitalFlow.owner == owner))
        s.commit()


# ====================================================================== positions
POSITION_FIELDS = {"symbol", "exchange", "name", "sector", "mcap", "strategy", "conviction",
                   "stop_loss", "target1", "target2", "review_by", "cmp_override", "notes"}
TXN_FIELDS = {"kind", "qty", "price", "date", "charges", "charges_auto", "reason"}


def add_position(engine, owner, fields: dict, first_txn: dict, thesis: str = "") -> int:
    with Session(engine) as s:
        p = Position(owner=owner, **{k: v for k, v in fields.items() if k in POSITION_FIELDS})
        s.add(p)
        s.flush()
        s.add(Transaction(position_id=p.id, **{k: v for k, v in first_txn.items() if k in TXN_FIELDS}))
        if thesis.strip():
            s.add(ThesisEntry(position_id=p.id, date=first_txn["date"], text=thesis.strip()))
        s.commit()
        return p.id


def _owned_position(s, owner, pid) -> Optional[Position]:
    p = s.get(Position, pid)
    return p if p and p.owner == owner else None


def update_position(engine, owner, pid, **fields):
    with Session(engine) as s:
        p = _owned_position(s, owner, pid)
        if p:
            for k, v in fields.items():
                if k in POSITION_FIELDS:
                    setattr(p, k, v)
            s.commit()


def delete_position(engine, owner, pid):
    with Session(engine) as s:
        p = _owned_position(s, owner, pid)
        if p:
            s.delete(p)
            s.commit()


# ====================================================================== transactions
def add_txn(engine, owner, pid, **fields):
    with Session(engine) as s:
        if _owned_position(s, owner, pid):
            s.add(Transaction(position_id=pid, **{k: v for k, v in fields.items() if k in TXN_FIELDS}))
            s.commit()


def update_txn(engine, owner, txn_id, **fields):
    with Session(engine) as s:
        t = s.get(Transaction, txn_id)
        if t and _owned_position(s, owner, t.position_id):
            for k, v in fields.items():
                if k in TXN_FIELDS:
                    setattr(t, k, v)
            s.commit()


def delete_txn(engine, owner, txn_id):
    """Delete a transaction; deletes the position too if it has no transactions left."""
    with Session(engine) as s:
        t = s.get(Transaction, txn_id)
        if t and _owned_position(s, owner, t.position_id):
            pid = t.position_id
            s.delete(t)
            s.flush()
            left = s.scalars(select(Transaction).where(Transaction.position_id == pid)).first()
            if left is None:
                s.delete(s.get(Position, pid))
            s.commit()


# ====================================================================== thesis
def add_thesis(engine, owner, pid, date, text):
    with Session(engine) as s:
        if _owned_position(s, owner, pid) and text.strip():
            s.add(ThesisEntry(position_id=pid, date=date, text=text.strip()))
            s.commit()


def delete_thesis(engine, owner, thesis_id):
    with Session(engine) as s:
        t = s.get(ThesisEntry, thesis_id)
        if t and _owned_position(s, owner, t.position_id):
            s.delete(t)
            s.commit()


# ====================================================================== watchlist
WATCH_FIELDS = {"symbol", "exchange", "name", "added_on", "price_added", "trigger_price",
                "trigger_dir", "thesis", "tags"}


def add_watch(engine, owner, **fields):
    with Session(engine) as s:
        s.add(WatchItem(owner=owner, **{k: v for k, v in fields.items() if k in WATCH_FIELDS}))
        s.commit()


def update_watch(engine, owner, wid, **fields):
    with Session(engine) as s:
        w = s.get(WatchItem, wid)
        if w and w.owner == owner:
            for k, v in fields.items():
                if k in WATCH_FIELDS:
                    setattr(w, k, v)
            s.commit()


def delete_watch(engine, owner, wid):
    with Session(engine) as s:
        s.execute(delete(WatchItem).where(WatchItem.id == wid, WatchItem.owner == owner))
        s.commit()


# ====================================================================== settings
def set_setting(engine, owner, key, value):
    with Session(engine) as s:
        row = s.get(Setting, (owner, key))
        if row:
            row.value = str(value)
        else:
            s.add(Setting(owner=owner, key=key, value=str(value)))
        s.commit()


# ====================================================================== price cache
def get_cached_prices(engine, tickers) -> dict:
    if not tickers:
        return {}
    with Session(engine) as s:
        rows = s.scalars(select(PriceCache).where(PriceCache.ticker.in_(list(tickers)))).all()
        return {r.ticker: {"price": r.price, "prev_close": r.prev_close, "updated_at": r.updated_at}
                for r in rows}


def put_cached_prices(engine, quotes: dict):
    if not quotes:
        return
    with Session(engine) as s:
        for t, q in quotes.items():
            row = s.get(PriceCache, t)
            if row:
                row.price, row.prev_close, row.updated_at = q["price"], q.get("prev_close"), dt.datetime.utcnow()
            else:
                s.add(PriceCache(ticker=t, price=q["price"], prev_close=q.get("prev_close")))
        s.commit()


# ====================================================================== backup
def _jsonable(v):
    if isinstance(v, (dt.date, dt.datetime)):
        return v.isoformat()
    if isinstance(v, float) and pd.isna(v):
        return None
    return v


def export_json(engine, owner) -> str:
    data = load_all(engine, owner)
    out = {"version": 2, "app": "fund_tracker", "exported_at": dt.datetime.utcnow().isoformat(),
           "settings": data["settings"]}
    for k in ("investors", "flows", "positions", "txns", "thesis", "watch"):
        df = data[k].astype(object).where(data[k].notna(), None)
        out[k] = [{c: _jsonable(v) for c, v in r.items()} for r in df.to_dict("records")]
    return json.dumps(out, indent=2)


def _d(v):
    return dt.date.fromisoformat(v[:10]) if v else None


def import_json(engine, owner, payload: str):
    """Replace this owner's data with the contents of a JSON backup."""
    data = json.loads(payload)
    with Session(engine) as s:
        # wipe existing
        for p in s.scalars(select(Position).where(Position.owner == owner)).all():
            s.delete(p)
        s.execute(delete(CapitalFlow).where(CapitalFlow.owner == owner))
        s.flush()
        s.execute(delete(Investor).where(Investor.owner == owner))
        s.execute(delete(WatchItem).where(WatchItem.owner == owner))
        s.execute(delete(Setting).where(Setting.owner == owner))
        s.flush()
        inv_map = {}
        for i in data.get("investors", []):
            obj = Investor(owner=owner, name=i.get("name") or "Investor", relation=i.get("relation") or "",
                           contact=i.get("contact") or "", is_manager=bool(i.get("is_manager")),
                           notes=i.get("notes") or "")
            s.add(obj)
            s.flush()
            inv_map[i["id"]] = obj.id
        for f in data.get("flows", []):
            if f.get("investor_id") not in inv_map:
                continue
            s.add(CapitalFlow(owner=owner, investor_id=inv_map[f["investor_id"]], date=_d(f["date"]),
                              kind=f["kind"], amount=float(f["amount"]), nav=float(f["nav"]),
                              units=float(f["units"]), nav_manual=bool(f.get("nav_manual")),
                              note=f.get("note") or ""))
        id_map = {}
        for p in data.get("positions", []):
            fields = {k: p.get(k) for k in POSITION_FIELDS}
            fields["review_by"] = _d(fields.get("review_by"))
            obj = Position(owner=owner, **fields)
            s.add(obj)
            s.flush()
            id_map[p["id"]] = obj.id
        for t in data.get("txns", []):
            if t["position_id"] in id_map:
                s.add(Transaction(position_id=id_map[t["position_id"]], kind=t["kind"], qty=float(t["qty"]),
                                  price=float(t["price"]), date=_d(t["date"]), charges=float(t.get("charges") or 0),
                                  charges_auto=bool(t.get("charges_auto", True)), reason=t.get("reason") or ""))
        for th in data.get("thesis", []):
            if th["position_id"] in id_map:
                s.add(ThesisEntry(position_id=id_map[th["position_id"]], date=_d(th["date"]), text=th["text"]))
        for w in data.get("watch", []):
            fields = {k: w.get(k) for k in WATCH_FIELDS}
            fields["added_on"] = _d(fields.get("added_on")) or dt.date.today()
            s.add(WatchItem(owner=owner, **fields))
        for k, v in (data.get("settings") or {}).items():
            s.add(Setting(owner=owner, key=k, value=str(v)))
        s.commit()
