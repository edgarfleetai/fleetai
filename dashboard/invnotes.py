"""Owner's explanations per car for an investor report (additive table dashboard_investor_notes).

One text per (investor, period start, car). Written by the owner before saving
the report as PDF / Excel; nothing else reads this table.
"""
from datetime import datetime

from sqlalchemy import Column, DateTime, Integer, MetaData, String, Table, Text, UniqueConstraint, inspect, select

MAX_LEN = 2000
meta = MetaData()
notes = Table(
    "dashboard_investor_notes", meta,
    Column("id", Integer, primary_key=True, autoincrement=True),
    Column("investor", String(20), nullable=False),
    Column("period_start", String(10), nullable=False),      # YYYY-MM-DD
    Column("car_code", String(20), nullable=False),
    Column("text", Text, nullable=False, default=""),
    Column("updated_at", DateTime, nullable=False),
    UniqueConstraint("investor", "period_start", "car_code", name="uq_dashboard_investor_note"),
)


def _write_engine():
    from fleetai import db as fleet_db
    return fleet_db.engine


def _period(v):
    v = str(v or "").strip()[:10]
    datetime.strptime(v, "%Y-%m-%d")
    return v


def load(read_engine, investor, period_start):
    if not inspect(read_engine).has_table("dashboard_investor_notes"):
        return {}
    with read_engine.connect() as conn:
        rows = conn.execute(select(notes.c.car_code, notes.c.text, notes.c.updated_at).where(
            notes.c.investor == investor, notes.c.period_start == _period(period_start))).all()
    return {r[0]: {"text": r[1], "updated_at": r[2].isoformat(timespec="minutes") if r[2] else ""} for r in rows}


def save(investor, period_start, texts, allowed_cars):
    """texts: {car_code: text}. Only the investor's cars are stored. -> list of changed car codes."""
    start = _period(period_start)
    eng = _write_engine()
    meta.create_all(eng, checkfirst=True)
    changed = []
    with eng.begin() as conn:
        for code, value in (texts or {}).items():
            code = str(code).strip()[:20]
            if code not in allowed_cars:
                continue
            value = str(value or "").strip()[:MAX_LEN]
            row = conn.execute(select(notes.c.id, notes.c.text).where(
                notes.c.investor == investor, notes.c.period_start == start, notes.c.car_code == code)).first()
            if row and row[1] == value:
                continue
            if row:
                conn.execute(notes.update().where(notes.c.id == row[0]).values(text=value, updated_at=datetime.now()))
            else:
                conn.execute(notes.insert().values(investor=investor, period_start=start, car_code=code,
                                                   text=value, updated_at=datetime.now()))
            changed.append(code)
    return changed
