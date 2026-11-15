"""Mileage and maintenance: km today / this month, oil change reminders and how
often parts are replaced.

Distances are always a difference of readings from ONE source, never mixed:
  * "param"   — the tracker's own odometer parameter (km or metres), with
                history from Wialon messages;
  * "counter" — Wialon's mileage counter; it is not the real odometer, so its
                history comes from hourly readings the dashboard records in
                dashboard_odometer_log (additive table);
  * "fleetai" — mileage written in FleetAI commands ("пробег 152000").
The odometer shown is the FleetAI value unless the tracker reports a real one.
"""
import re
from collections import defaultdict
from datetime import datetime, timedelta

from sqlalchemy import Column, DateTime, Float, Integer, MetaData, String, Table, inspect, select, text

from fleetai.finance import moscow_now

from .data import RETIRED_CODES

OIL_INTERVAL_KM = 15_000
OIL_WARN_BEFORE_KM = 1_000
MAX_KM_PER_DAY = 1_500          # anything above is a bad reading, not a trip
OIL_RE = re.compile(r"масл", re.I)
NOT_ENGINE_OIL_RE = re.compile(r"кпп|коробк|колпач|датчик|приемник|приёмник|щуп|гур|мост", re.I)

meta = MetaData()
odo_log = Table(
    "dashboard_odometer_log", meta,
    Column("id", Integer, primary_key=True, autoincrement=True),
    Column("car_code", String(20), nullable=False),
    Column("ts", DateTime, nullable=False),
    Column("kind", String(10), nullable=False),      # param | counter
    Column("km", Float, nullable=False),
)


def is_oil_change(*texts):
    t = " ".join(x or "" for x in texts)
    return bool(OIL_RE.search(t)) and not NOT_ENGINE_OIL_RE.search(t)


def to_km(raw, reference_km):
    """Tracker odometer may be in km or metres; pick the scale closest to FleetAI's value."""
    if raw is None:
        return None
    if reference_km and reference_km > 1:
        km, m = abs(raw - reference_km), abs(raw / 1000 - reference_km)
        return round(raw if km <= m else raw / 1000)
    return round(raw / 1000) if raw > 3_000_000 else round(raw)


def _dt(v):
    """Raw SQL returns datetimes on PostgreSQL and ISO strings on SQLite."""
    if v is None or isinstance(v, datetime):
        return v
    try:
        return datetime.fromisoformat(str(v).replace("Z", ""))
    except ValueError:
        return None


def _ts(dt):
    return int(dt.timestamp()) - 3 * 3600   # Moscow wall time -> unix (UTC+3)


def _distance(now_km, then_km, days):
    """A plausible distance or None (odometer reset, wrong unit, missing data)."""
    if now_km is None or then_km is None:
        return None
    d = now_km - then_km
    return d if 0 <= d <= MAX_KM_PER_DAY * max(days, 1) else None


def record_readings(write_engine, readings, now):
    """Store at most one reading per car and hour (for counter-only trackers)."""
    meta.create_all(write_engine, checkfirst=True)
    hour = now.replace(minute=0, second=0, microsecond=0)
    with write_engine.begin() as conn:
        for code, (kind, km) in readings.items():
            exists = conn.execute(select(odo_log.c.id).where(
                odo_log.c.car_code == code, odo_log.c.kind == kind, odo_log.c.ts >= hour).limit(1)).first()
            if not exists:
                conn.execute(odo_log.insert().values(car_code=code, ts=now, kind=kind, km=float(km)))


def first_reading_since(read_engine, code, kind, since):
    if not inspect(read_engine).has_table("dashboard_odometer_log"):
        return None
    with read_engine.connect() as conn:
        row = conn.execute(select(odo_log.c.ts, odo_log.c.km).where(
            odo_log.c.car_code == code, odo_log.c.kind == kind, odo_log.c.ts >= since)
            .order_by(odo_log.c.ts).limit(1)).first()
    return (_dt(row[0]), row[1]) if row else None


def overview(engine, units_by_car, fetch_odometers, now=None, write_engine=None):
    """units_by_car: {car_code: wialon_unit_id}. fetch_odometers(moments) -> (data, error)."""
    now = now or moscow_now()
    day0 = now.replace(hour=0, minute=0, second=0, microsecond=0)
    month0 = day0.replace(day=1)
    with engine.connect() as conn:
        cars = {str(r[0]).strip(): int(r[1] or 0) for r in conn.execute(text("SELECT code, current_mileage FROM cars"))
                if str(r[0]).strip() not in RETIRED_CODES}
        manual = defaultdict(list)
        for code, date, km in conn.execute(text("SELECT car_code, date, mileage FROM mileage WHERE mileage > 0 ORDER BY date")):
            manual[RETIRED_CODES.get(str(code).strip(), str(code).strip())].append((_dt(date), int(km)))
        ops = [dict(o, date=_dt(o["date"])) for o in conn.execute(text(
            "SELECT o.id, o.date, o.car_code, o.type, o.category, o.description, o.raw_message, o.mileage "
            "FROM operations o WHERE o.type IN ('repair','service','expense') ORDER BY o.date")).mappings().all()]
        parts = [dict(p, install_date=_dt(p["install_date"])) for p in conn.execute(text(
            "SELECT car_code, part_name, install_date, install_mileage, operation_id FROM parts ORDER BY install_date")).mappings().all()]

    def code_of(c):
        c = str(c or "").strip()
        return RETIRED_CODES.get(c, c)

    oil_last = {}
    for o in ops:
        if is_oil_change(o["raw_message"], o["description"], o["category"]):
            oil_last[code_of(o["car_code"])] = o
    for p in parts:
        if is_oil_change(p["part_name"]):
            code, prev = code_of(p["car_code"]), oil_last.get(code_of(p["car_code"]))
            if not prev or (p["install_date"] and prev["date"] and p["install_date"] > prev["date"]):
                oil_last[code] = {"date": p["install_date"], "mileage": p["install_mileage"], "id": p["operation_id"]}

    moments = {}
    for code, uid in units_by_car.items():
        m = {"day": _ts(day0), "month": _ts(month0)}
        if oil_last.get(code) and oil_last[code].get("date"):
            m["oil"] = _ts(oil_last[code]["date"])
        moments[uid] = m
    odo, error = fetch_odometers(moments) if units_by_car else ({}, None)

    def manual_at(code, when):
        best = None
        for d, km in manual.get(code, []):
            if d and when and d <= when:
                best = km
        return best

    readings, out = {}, []
    for code, db_km in sorted(cars.items()):
        fleet_km = max([db_km] + [km for _, km in manual.get(code, [])] + [0]) or None
        w = odo.get(units_by_car.get(code)) if units_by_car.get(code) else None
        kind = track_now = None
        if w and w.get("param_now") is not None:
            kind, track_now = "param", to_km(w["param_now"], fleet_km)
        elif w and w.get("counter_km"):
            kind, track_now = "counter", float(w["counter_km"])
        if kind:
            readings[code] = (kind, track_now)

        def tracker_at(label, since_dt):
            if kind == "param":
                return to_km((w.get("at") or {}).get(label), fleet_km), True
            hit = first_reading_since(engine, code, kind, since_dt) if kind == "counter" else None
            return (hit[1] if hit else None), bool(hit and hit[0] and hit[0] <= since_dt + timedelta(hours=2))

        today = month = None
        partial = False
        if kind:
            d0, exact_d = tracker_at("day", day0)
            m0, exact_m = tracker_at("month", month0)
            today = _distance(track_now, d0, 1)
            month = _distance(track_now, m0, (now - month0).days + 1)
            partial = month is not None and not exact_m
        odometer = track_now if kind == "param" else fleet_km
        source = "tracker" if kind == "param" else "fleetai"

        oil = None
        o = oil_last.get(code)
        if o:
            since = None
            how = None
            if kind and o.get("date"):
                at, exact = tracker_at("oil", o["date"])
                since = _distance(track_now, at, (now - o["date"]).days + 1) if exact or kind == "param" else None
                how = "трекер" if since is not None else None
            if since is None:
                at_km = o.get("mileage") or manual_at(code, o.get("date"))
                latest = fleet_km
                if at_km and latest and latest >= at_km:
                    since, how = latest - at_km, "записи пробега FleetAI"
            status = None if since is None else ("overdue" if since >= OIL_INTERVAL_KM else
                                                 "soon" if since >= OIL_INTERVAL_KM - OIL_WARN_BEFORE_KM else "ok")
            oil = {"date": o["date"].isoformat() if o.get("date") else "", "since_km": since, "how": how,
                   "due_in_km": (OIL_INTERVAL_KM - since) if since is not None else None,
                   "interval_km": OIL_INTERVAL_KM, "status": status or "unknown"}
        out.append({"code": code, "odometer_km": odometer, "source": source, "tracker": kind,
                    "today_km": today, "month_km": month, "month_partial": partial, "oil": oil})

    if write_engine is not None and readings:
        try:
            record_readings(write_engine, readings, now)
        except Exception:   # history is a nice-to-have; never break the page
            pass

    history = defaultdict(lambda: defaultdict(list))
    for p in parts:
        if not p["part_name"]:
            continue
        code = code_of(p["car_code"])
        km = p["install_mileage"] or (manual_at(code, p["install_date"]) if p["install_date"] else None)
        history[code][p["part_name"]].append((p["install_date"], km))
    part_rows = []
    for code, by_part in history.items():
        for name, events in by_part.items():
            days = [(b[0] - a[0]).days for a, b in zip(events, events[1:]) if a[0] and b[0]]
            kms = [b[1] - a[1] for a, b in zip(events, events[1:]) if a[1] and b[1] and b[1] > a[1]]
            part_rows.append({"car": code, "part": name, "count": len(events),
                              "last_date": events[-1][0].isoformat() if events[-1][0] else "",
                              "last_km": events[-1][1],
                              "avg_days": round(sum(days) / len(days)) if days else None,
                              "avg_km": round(sum(kms) / len(kms)) if kms else None})
    part_rows.sort(key=lambda r: (r["car"], -r["count"], r["part"]))

    fmt = lambda n: f"{int(n):,}".replace(",", " ")
    tasks = []
    for r in out:
        o = r["oil"]
        if o and o["status"] == "overdue":
            tasks.append({"car": r["code"], "sev": "bad", "kind": "oil",
                          "title": f"{r['code']}: замена масла просрочена на {fmt(o['since_km'] - OIL_INTERVAL_KM)} км",
                          "detail": f"после замены пройдено {fmt(o['since_km'])} км ({o['how']})"})
        elif o and o["status"] == "soon":
            tasks.append({"car": r["code"], "sev": "warn", "kind": "oil",
                          "title": f"{r['code']}: поменять масло через {fmt(o['due_in_km'])} км",
                          "detail": f"после замены пройдено {fmt(o['since_km'])} из {fmt(OIL_INTERVAL_KM)} км ({o['how']})"})
    return {"cars": out, "parts": part_rows, "tasks": tasks, "error": error,
            "oil_interval_km": OIL_INTERVAL_KM, "generated_at": now.isoformat()}
