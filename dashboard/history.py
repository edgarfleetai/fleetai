"""Change history: what changed, when and by whom.

Two sources, both in additive tables the old FleetAI never reads:
  * every write made through the dashboard (operations, owner actions, edits,
    deletions, board cards, tasks, the assistant) is logged at once;
  * once an hour a snapshot of the cars and of recent operations is compared
    with the previous one, so changes made elsewhere (Telegram bot, old site)
    are recorded too, as "вне дашборда".
"""
import json
from datetime import datetime, timedelta

from sqlalchemy import Column, DateTime, Integer, MetaData, String, Table, Text, inspect, select, text

from fleetai.finance import moscow_now

from .data import RETIRED_CODES

meta = MetaData()
audit = Table(
    "dashboard_audit_log", meta,
    Column("id", Integer, primary_key=True, autoincrement=True),
    Column("ts", DateTime, nullable=False),
    Column("source", String(20), nullable=False),     # dashboard | outside | assistant
    Column("actor", String(80), nullable=False, default=""),
    Column("kind", String(40), nullable=False),
    Column("car_code", String(20), nullable=False, default=""),
    Column("summary", Text, nullable=False),
    Column("detail", Text, nullable=False, default=""),
)
snapshots = Table(
    "dashboard_snapshot", meta,
    Column("id", Integer, primary_key=True, autoincrement=True),
    Column("ts", DateTime, nullable=False),
    Column("data", Text, nullable=False),
)

CAR_FIELDS = ("plate", "brand", "model", "status", "driver", "owner_type", "investor_name",
              "investor_percent", "daily_rent", "weekly_payment", "driver_deposit")
FIELD_NAMES = {"plate": "номер", "brand": "марка", "model": "модель", "status": "статус", "driver": "водитель",
               "owner_type": "тип владения", "investor_name": "инвестор", "investor_percent": "процент инвестора",
               "daily_rent": "аренда в сутки", "weekly_payment": "аренда в неделю", "driver_deposit": "залог"}
OPS_DAYS = 120
SNAPSHOT_EVERY = timedelta(hours=1)
KEEP_SNAPSHOTS = 48


def _write_engine():
    from fleetai import db as fleet_db
    return fleet_db.engine


def _dt(v):
    if v is None or isinstance(v, datetime):
        return v
    try:
        return datetime.fromisoformat(str(v).replace("Z", ""))
    except ValueError:
        return None


def log(kind, summary, car_code="", actor="", source="dashboard", detail=None, write_engine=None, now=None):
    """Never raises: a failed log line must not undo or block the change itself."""
    try:
        eng = write_engine or _write_engine()
        meta.create_all(eng, checkfirst=True)
        with eng.begin() as conn:
            conn.execute(audit.insert().values(
                ts=now or moscow_now().replace(tzinfo=None), source=source, actor=str(actor or "")[:80],
                kind=str(kind)[:40], car_code=str(car_code or "")[:20], summary=str(summary)[:1000],
                detail=json.dumps(detail, ensure_ascii=False, default=str)[:4000] if detail is not None else ""))
        return True
    except Exception:
        return False


def events(read_engine, car=None, days=30, limit=200, now=None):
    if not inspect(read_engine).has_table("dashboard_audit_log"):
        return []
    since = (now or moscow_now()).replace(tzinfo=None) - timedelta(days=days)
    q = select(audit).where(audit.c.ts >= since)
    if car:
        q = q.where(audit.c.car_code == str(car).strip())
    with read_engine.connect() as conn:
        rows = conn.execute(q.order_by(audit.c.ts.desc(), audit.c.id.desc()).limit(limit)).mappings().all()
    out = []
    for r in rows:
        ts = _dt(r["ts"])
        out.append({"id": r["id"], "ts": ts.isoformat(timespec="minutes") if ts else "", "source": r["source"],
                    "actor": r["actor"], "kind": r["kind"], "car": r["car_code"], "summary": r["summary"]})
    return out


# ---- snapshots: catch changes made outside the dashboard -------------------

def take(read_engine, now):
    since = now - timedelta(days=OPS_DAYS)
    with read_engine.connect() as conn:
        cars = {}
        for r in conn.execute(text("SELECT code, " + ", ".join(CAR_FIELDS) + " FROM cars")).mappings():
            code = str(r["code"] or "").strip()
            if code and code not in RETIRED_CODES:
                cars[code] = {k: ("" if r[k] is None else str(r[k]).strip()) for k in CAR_FIELDS}
        ops = {}
        for r in conn.execute(text("SELECT id, date, car_code, type, amount, description FROM operations "
                                   "WHERE date >= :s"), {"s": since}).mappings():
            d = _dt(r["date"])
            ops[str(r["id"])] = [d.isoformat(timespec="minutes") if d else "", str(r["car_code"] or "").strip(),
                                 r["type"] or "", int(r["amount"] or 0), (r["description"] or "")[:120]]
    return {"cars": cars, "ops": ops, "ops_since": since.isoformat()}


def diff(old, new):
    """Return [(kind, car, summary)] for what changed between two snapshots."""
    out = []
    oc, nc = old.get("cars", {}), new.get("cars", {})
    for code in sorted(set(oc) | set(nc)):
        if code not in oc:
            out.append(("car_added", code, f"Машина {code} появилась в базе"))
            continue
        if code not in nc:
            out.append(("car_removed", code, f"Машина {code} исчезла из базы"))
            continue
        for f in CAR_FIELDS:
            a, b = oc[code].get(f, ""), nc[code].get(f, "")
            if a != b:
                out.append(("car_changed", code, f"{code}: {FIELD_NAMES[f]} «{a or '—'}» → «{b or '—'}»"))
    oo, no = old.get("ops", {}), new.get("ops", {})
    edge = new.get("ops_since", "")
    for op_id in sorted(set(oo) | set(no), key=lambda x: int(x)):
        a, b = oo.get(op_id), no.get(op_id)
        if a and not b:
            if a[0] >= edge:   # not just aged out of the window
                out.append(("op_deleted", a[1], f"Удалена операция #{op_id}: {a[1]} {a[2]} {a[3]} ₽ «{a[4]}» от {a[0][:10]}"))
        elif b and not a:
            out.append(("op_added", b[1], f"Новая операция #{op_id}: {b[1]} {b[2]} {b[3]} ₽ «{b[4]}»"))
        elif a != b:
            out.append(("op_changed", b[1], f"Изменена операция #{op_id}: {a[1]} {a[3]} ₽ «{a[4]}» → {b[1]} {b[3]} ₽ «{b[4]}»"))
    return out


def snapshot_and_compare(read_engine, write_engine, now=None, skip_ids=()):
    """At most once an hour. Changes already logged by the dashboard itself are
    skipped by operation id (skip_ids) so they do not appear twice."""
    now = (now or moscow_now()).replace(tzinfo=None)
    meta.create_all(write_engine, checkfirst=True)
    with write_engine.connect() as conn:
        last = conn.execute(select(snapshots).order_by(snapshots.c.ts.desc()).limit(1)).mappings().first()
    if last and now - _dt(last["ts"]) < SNAPSHOT_EVERY:
        return None
    new = take(read_engine, now)
    found = []
    if last:
        old = json.loads(last["data"])
        own = dashboard_op_ids(read_engine, _dt(last["ts"]) - timedelta(minutes=5))
        for kind, car, summary in diff(old, new):
            if kind.startswith("op_") and summary.split("#")[1].split(":")[0] in own | set(map(str, skip_ids)):
                continue
            found.append((kind, car, summary))
    with write_engine.begin() as conn:
        for kind, car, summary in found:
            conn.execute(audit.insert().values(ts=now, source="outside", actor="бот / старый сайт",
                                               kind=kind, car_code=car, summary=summary, detail=""))
        conn.execute(snapshots.insert().values(ts=now, data=json.dumps(new, ensure_ascii=False)))
        ids = [r[0] for r in conn.execute(select(snapshots.c.id).order_by(snapshots.c.ts.desc()))]
        if len(ids) > KEEP_SNAPSHOTS:
            conn.execute(snapshots.delete().where(snapshots.c.id.in_(ids[KEEP_SNAPSHOTS:])))
    return found


def dashboard_op_ids(read_engine, since):
    """Operation ids the dashboard itself touched (their detail holds op_ids)."""
    ids = set()
    if not inspect(read_engine).has_table("dashboard_audit_log"):
        return ids
    with read_engine.connect() as conn:
        for (d,) in conn.execute(select(audit.c.detail).where(audit.c.ts >= since, audit.c.source != "outside")):
            try:
                ids.update(str(x) for x in (json.loads(d or "{}") or {}).get("op_ids", []))
            except (ValueError, AttributeError):
                pass
    return ids


def op_ids_since(read_engine, since_id):
    with read_engine.connect() as conn:
        return [r[0] for r in conn.execute(text("SELECT id FROM operations WHERE id > :i"), {"i": since_id})]


def max_op_id(read_engine):
    with read_engine.connect() as conn:
        return int(conn.execute(text("SELECT coalesce(max(id), 0) FROM operations")).scalar() or 0)
