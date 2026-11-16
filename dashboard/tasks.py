"""Tasks set by the owner or by the assistant (additive table dashboard_tasks).

Automatic oil reminders are computed in service.py and are not stored here.
"""
from datetime import datetime

from sqlalchemy import Column, DateTime, Integer, MetaData, String, Table, Text, inspect, select

meta = MetaData()
tasks = Table(
    "dashboard_tasks", meta,
    Column("id", Integer, primary_key=True, autoincrement=True),
    Column("created_at", DateTime, nullable=False),
    Column("source", String(20), nullable=False, default="owner"),   # owner | assistant
    Column("car_code", String(20), nullable=False, default=""),
    Column("title", String(300), nullable=False),
    Column("detail", Text, nullable=False, default=""),
    Column("due_date", String(10), nullable=False, default=""),      # YYYY-MM-DD or ""
    Column("status", String(10), nullable=False, default="open"),    # open | done
    Column("done_at", DateTime),
)


def _write_engine():
    from fleetai import db as fleet_db
    return fleet_db.engine


def _iso(v):
    if v is None:
        return ""
    return v.isoformat(timespec="minutes") if isinstance(v, datetime) else str(v)[:16]


def list_tasks(read_engine, status=None, car=None):
    if not inspect(read_engine).has_table("dashboard_tasks"):
        return []
    q = select(tasks)
    if status in ("open", "done"):
        q = q.where(tasks.c.status == status)
    if car:
        q = q.where(tasks.c.car_code == str(car).strip())
    with read_engine.connect() as conn:
        rows = conn.execute(q.order_by(tasks.c.status.desc(), tasks.c.created_at.desc()).limit(300)).mappings().all()
    return [{"id": r["id"], "created_at": _iso(r["created_at"]), "source": r["source"], "car": r["car_code"],
             "title": r["title"], "detail": r["detail"], "due_date": r["due_date"], "status": r["status"],
             "done_at": _iso(r["done_at"])} for r in rows]


def _clean(data):
    title = str(data.get("title") or "").strip()[:300]
    if not title:
        raise ValueError("Напишите, что нужно сделать")
    due = str(data.get("due_date") or "").strip()[:10]
    if due:
        try:
            datetime.strptime(due, "%Y-%m-%d")
        except ValueError:
            raise ValueError("Срок в формате ГГГГ-ММ-ДД") from None
    return {"title": title, "car_code": str(data.get("car_code") or "").strip()[:20],
            "detail": str(data.get("detail") or "").strip()[:2000], "due_date": due}


def create_task(data, source="owner", read_engine=None):
    """Returns (id, created). An identical open task is not created twice."""
    values = _clean(data)
    eng = _write_engine()
    meta.create_all(eng, checkfirst=True)
    with eng.begin() as conn:
        same = conn.execute(select(tasks.c.id).where(
            tasks.c.status == "open", tasks.c.title == values["title"],
            tasks.c.car_code == values["car_code"])).first()
        if same:
            return int(same[0]), False
        res = conn.execute(tasks.insert().values(created_at=datetime.now(), source=source, status="open", **values))
        return int(res.inserted_primary_key[0]), True


def set_status(task_id, status):
    if status not in ("open", "done"):
        raise ValueError("Неизвестный статус")
    eng = _write_engine()
    meta.create_all(eng, checkfirst=True)
    with eng.begin() as conn:
        row = conn.execute(select(tasks).where(tasks.c.id == int(task_id))).mappings().first()
        if not row:
            return None
        conn.execute(tasks.update().where(tasks.c.id == int(task_id)).values(
            status=status, done_at=datetime.now() if status == "done" else None))
        return dict(row)


def delete_task(task_id):
    eng = _write_engine()
    meta.create_all(eng, checkfirst=True)
    with eng.begin() as conn:
        row = conn.execute(select(tasks).where(tasks.c.id == int(task_id))).mappings().first()
        if row:
            conn.execute(tasks.delete().where(tasks.c.id == int(task_id)))
        return dict(row) if row else None
