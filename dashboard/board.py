"""Driver pipeline board (candidates before they get a car).

Stored in its own additive table dashboard_driver_board; the old FleetAI never
reads it. Drivers who already rent a car come from cars.driver, not from here.
"""
from datetime import datetime

from sqlalchemy import Column, DateTime, Integer, MetaData, String, Table, Text, inspect, select

STAGES = ("new", "check", "contract", "deposit", "returned")   # "rent" = cars.driver
FIELDS = ("name", "phone", "stage", "car_code", "note")

meta = MetaData()
board = Table(
    "dashboard_driver_board", meta,
    Column("id", Integer, primary_key=True, autoincrement=True),
    Column("name", String(200), nullable=False),
    Column("phone", String(40), nullable=False, default=""),
    Column("stage", String(20), nullable=False, default="new"),
    Column("car_code", String(20), nullable=False, default=""),
    Column("note", Text, nullable=False, default=""),
    Column("created_at", DateTime, nullable=False),
    Column("updated_at", DateTime, nullable=False),
)


def _write_engine():
    from fleetai import db as fleet_db
    return fleet_db.engine


def ensure_table():
    """CREATE TABLE IF NOT EXISTS — additive, touches no existing table."""
    meta.create_all(_write_engine(), checkfirst=True)


def list_cards(read_engine):
    if not inspect(read_engine).has_table("dashboard_driver_board"):
        return []
    with read_engine.connect() as conn:
        rows = conn.execute(select(board).order_by(board.c.updated_at.desc())).mappings().all()
    return [{"id": r["id"], "name": r["name"], "phone": r["phone"], "stage": r["stage"],
             "car_code": r["car_code"], "note": r["note"],
             "updated_at": r["updated_at"].isoformat() if r["updated_at"] else ""} for r in rows]


def _clean(data, partial):
    out = {}
    for k in FIELDS:
        if k in data:
            out[k] = str(data.get(k) or "").strip()[:200 if k != "note" else 1000]
    if "stage" in out and out["stage"] not in STAGES:
        raise ValueError("Неизвестный этап")
    if not partial and not out.get("name"):
        raise ValueError("Укажите имя водителя")
    if "name" in out and not out["name"]:
        raise ValueError("Имя не может быть пустым")
    return out


def create_card(data):
    ensure_table()
    values = _clean(data, partial=False)
    values.setdefault("stage", "new")
    now = datetime.now()
    with _write_engine().begin() as conn:
        res = conn.execute(board.insert().values(created_at=now, updated_at=now, **values))
        return int(res.inserted_primary_key[0])


def update_card(card_id, data):
    ensure_table()
    values = _clean(data, partial=True)
    if not values:
        raise ValueError("Нечего менять")
    with _write_engine().begin() as conn:
        res = conn.execute(board.update().where(board.c.id == int(card_id)).values(updated_at=datetime.now(), **values))
        return res.rowcount


def delete_card(card_id):
    ensure_table()
    with _write_engine().begin() as conn:
        return conn.execute(board.delete().where(board.c.id == int(card_id))).rowcount
