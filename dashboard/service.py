"""Mileage and maintenance: odometer, km today / this month, oil change
reminders and how often parts are replaced. Read-only.

Odometer sources, best first:
  * Wialon tracker: odometer parameter of the last message (km or metres,
    detected against the car's mileage in FleetAI) or the Wialon counter;
  * FleetAI: cars.current_mileage and the mileage table (manual "пробег …").
"""
import re
from collections import defaultdict
from datetime import datetime, timedelta

from sqlalchemy import text

from fleetai.finance import moscow_now

from .data import RETIRED_CODES

OIL_INTERVAL_KM = 15_000
OIL_WARN_BEFORE_KM = 1_000
OIL_RE = re.compile(r"масл", re.I)
NOT_ENGINE_OIL_RE = re.compile(r"кпп|коробк|колпач|датчик|приемник|приёмник|щуп|гур|мост", re.I)


def is_oil_change(*texts):
    t = " ".join(x or "" for x in texts)
    return bool(OIL_RE.search(t)) and not NOT_ENGINE_OIL_RE.search(t)


def to_km(raw, reference_km):
    """Tracker odometer may be in km or metres; pick the scale closest to FleetAI's value."""
    if raw is None:
        return None
    if reference_km and reference_km > 0:
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


def overview(engine, units_by_car, fetch_odometers, now=None):
    """units_by_car: {car_code: wialon_unit_id}. fetch_odometers(moments) -> (data, error)."""
    now = now or moscow_now()
    day0 = now.replace(hour=0, minute=0, second=0, microsecond=0)
    month0 = day0.replace(day=1)
    with engine.connect() as conn:
        cars = {str(r[0]).strip(): int(r[1] or 0) for r in conn.execute(text("SELECT code, current_mileage FROM cars"))
                if str(r[0]).strip() not in RETIRED_CODES}
        manual = defaultdict(list)
        for code, date, km in conn.execute(text("SELECT car_code, date, mileage FROM mileage WHERE mileage > 0 ORDER BY date")):
            manual[str(code).strip()].append((_dt(date), int(km)))
        ops = conn.execute(text(
            "SELECT o.id, o.date, o.car_code, o.type, o.category, o.description, o.raw_message, o.mileage "
            "FROM operations o WHERE o.type IN ('repair','service','expense') ORDER BY o.date")).mappings().all()
        ops = [dict(o, date=_dt(o["date"])) for o in ops]
        parts = conn.execute(text(
            "SELECT car_code, part_name, install_date, install_mileage, operation_id FROM parts ORDER BY install_date")).mappings().all()
        parts = [dict(p, install_date=_dt(p["install_date"])) for p in parts]

    def code_of(c):
        c = str(c or "").strip()
        return RETIRED_CODES.get(c, c)

    # last engine-oil change per car
    oil_last = {}
    for o in ops:
        if is_oil_change(o["raw_message"], o["description"], o["category"]):
            oil_last[code_of(o["car_code"])] = o
    for p in parts:
        if is_oil_change(p["part_name"]):
            code = code_of(p["car_code"])
            prev = oil_last.get(code)
            if not prev or (p["install_date"] and prev["date"] and p["install_date"] > prev["date"]):
                oil_last[code] = {"date": p["install_date"], "mileage": p["install_mileage"], "id": p["operation_id"]}

    moments = {}
    for code, uid in units_by_car.items():
        m = {"day": _ts(day0), "month": _ts(month0)}
        o = oil_last.get(code)
        if o and o.get("date") and not o.get("mileage"):
            m["oil"] = _ts(o["date"])
        moments[uid] = m
    odo, error = fetch_odometers(moments) if units_by_car else ({}, None)

    def manual_at(code, when):
        best = None
        for d, km in manual.get(code, []):
            if d and d <= when:
                best = km
        return best

    out = []
    for code, db_km in sorted(cars.items()):
        latest_manual = manual[code][-1][1] if manual.get(code) else None
        ref = max(x for x in (db_km, latest_manual or 0, 1))
        uid = units_by_car.get(code)
        w = odo.get(uid) if uid else None
        km_now = source = today = month = None
        if w:
            raw = w.get("param_now")
            if raw is not None:
                km_now, source = to_km(raw, ref), "tracker"
                at = w.get("at") or {}
                d0, m0 = to_km(at.get("day"), ref), to_km(at.get("month"), ref)
                today = km_now - d0 if d0 is not None and km_now >= d0 else None
                month = km_now - m0 if m0 is not None and km_now >= m0 else None
            elif w.get("counter_km"):
                km_now, source = int(w["counter_km"]), "wialon_counter"
        if km_now is None:
            km_now, source = (ref if ref > 1 else None), "fleetai"
        # oil
        oil = None
        o = oil_last.get(code)
        if o:
            at_km = o.get("mileage")
            if not at_km and w and (w.get("at") or {}).get("oil") is not None:
                at_km = to_km(w["at"]["oil"], ref)
            if not at_km and o.get("date"):
                at_km = manual_at(code, o["date"])
            since = (km_now - at_km) if (km_now is not None and at_km) else None
            status = None
            if since is not None:
                status = ("overdue" if since >= OIL_INTERVAL_KM else
                          "soon" if since >= OIL_INTERVAL_KM - OIL_WARN_BEFORE_KM else "ok")
            oil = {"date": o["date"].isoformat() if o.get("date") else "", "at_km": at_km, "since_km": since,
                   "due_in_km": (OIL_INTERVAL_KM - since) if since is not None else None,
                   "interval_km": OIL_INTERVAL_KM, "status": status or "unknown"}
        out.append({"code": code, "odometer_km": km_now, "source": source,
                    "today_km": today, "month_km": month, "oil": oil})

    # how often each part is replaced
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

    tasks = []
    for r in out:
        o = r["oil"]
        if o and o["status"] == "overdue":
            tasks.append({"car": r["code"], "sev": "bad", "kind": "oil",
                          "title": f"{r['code']}: замена масла просрочена на {o['since_km'] - OIL_INTERVAL_KM:,} км".replace(",", " "),
                          "detail": f"после замены пройдено {o['since_km']:,} км".replace(",", " ")})
        elif o and o["status"] == "soon":
            tasks.append({"car": r["code"], "sev": "warn", "kind": "oil",
                          "title": f"{r['code']}: поменять масло через {o['due_in_km']:,} км".replace(",", " "),
                          "detail": f"после замены пройдено {o['since_km']:,} из {OIL_INTERVAL_KM:,} км".replace(",", " ")})
    return {"cars": out, "parts": part_rows, "tasks": tasks, "error": error,
            "oil_interval_km": OIL_INTERVAL_KM, "generated_at": now.isoformat()}
