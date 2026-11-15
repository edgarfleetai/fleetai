"""Entering operations from the dashboard.

Uses the old FleetAI's own parser and save function (fleetai.parser.parse_message,
fleetai.routes.save_operation), exactly like the "/api/add" command box, so a
record made here is identical to one made in the old site. Two steps: preview
(no database access except reading car codes) and commit (only after the owner
confirms the preview; protected by CSRF, origin and an idempotency key).
"""
import hashlib
import threading
import time

from sqlalchemy import text

from fleetai import db as fleet_db
from fleetai.parser import parse_message

from .data import RETIRED_CODES

TYPE_LABELS = {
    "income": "Доход", "expense": "Расход", "repair": "Ремонт", "service": "Обслуживание",
    "car_investment": "Вложение в машину", "investor_investment": "Внесение инвестора",
    "investor_payout": "Выплата инвестору", "investor_expense_split": "Расход с инвестором",
    "downtime": "Простой", "downtime_end": "Конец простоя", "mileage": "Пробег",
}
SHARE_LABELS = {"shared": "общий", "investor_only": "только инвестор", "park_only": "только парк"}
MAX_PARTS, MAX_LEN = 10, 1000

_done = {}
_lock = threading.Lock()


def configure_writes(url):
    """Point the old FleetAI session factory at the dashboard's database."""
    fleet_db.configure_database(url)


def _split(message):
    parts = [p.strip() for p in (message or "").split("/") if p.strip()]
    return parts[:MAX_PARTS]


def _known_codes(engine):
    """{code: current driver name or ''}"""
    with engine.connect() as conn:
        return {str(r[0]).strip(): (r[1] or "").strip() for r in conn.execute(text("SELECT code, driver FROM cars"))}


def parse_all(message, engine):
    """Parse like /api/add: '/'-separated parts inherit the first car code."""
    codes = _known_codes(engine)
    items, first_code = [], None
    for part in _split(message):
        p = parse_message(part)
        if p.get("car_code"):
            first_code = p["car_code"]
        elif first_code:
            p["car_code"] = first_code
        code = (p.get("car_code") or "").strip()
        problem = None
        if p.get("type") == "unknown":
            problem = "Не понял команду. Пример: 703 получил 13000"
        elif not code:
            problem = "Не указан код машины (три цифры в начале)"
        elif code in RETIRED_CODES:
            problem = f"Машины {code} больше нет: она ездит как {RETIRED_CODES[code]}"
        elif code not in codes:
            problem = f"Машины {code} нет в базе"
        amount = int(p.get("income") or p.get("total") or p.get("total_cost") or 0)
        items.append({
            "raw": part, "car": code, "type": p.get("type"),
            "label": TYPE_LABELS.get(p.get("type"), p.get("type") or "—"),
            "category": p.get("category") or "", "description": p.get("description") or "",
            "amount": amount * 100, "share": SHARE_LABELS.get(p.get("share_type"), p.get("share_type") or ""),
            "mileage": p.get("mileage"), "investor": p.get("investor_name") or "",
            "parts": [{"name": x.get("part") or x.get("name") or "", "price": int(x.get("price") or x.get("part_price") or 0) * 100}
                      for x in (p.get("parts") or []) if isinstance(x, dict)],
            "problem": problem, "_parsed": p,
            # Income on a car with a driver is usually the driver's payment: the
            # dashboard offers to post it as a wallet top-up (cabinet + income).
            "driver": codes.get(code, "") if p.get("type") == "income" and not problem else "",
        })
    return items


def fingerprint(message):
    return hashlib.sha256((message or "").strip().encode("utf-8")).hexdigest()[:24]


def public(items):
    return [{k: v for k, v in i.items() if k != "_parsed"} for i in items]


def commit(message, key, engine, save=None):
    """Save every part with the old FleetAI save_operation. Returns (ok, results)."""
    if save is None:
        from fleetai.routes import save_operation as save
    now = time.time()
    with _lock:
        for k in [k for k, (t, _) in _done.items() if now - t > 3600]:
            _done.pop(k, None)
        if key in _done:
            return True, _done[key][1] + [{"ok": True, "message": "Уже сохранено (повторное нажатие не записано)"}]
        _done[key] = (now, [])
    items = parse_all(message, engine)
    if not items or any(i["problem"] for i in items):
        with _lock:
            _done.pop(key, None)
        return False, [{"ok": False, "message": i["problem"] or "", "raw": i["raw"]} for i in items if i["problem"]] or \
            [{"ok": False, "message": "Пустая команда"}]
    results = []
    for i in items:
        r = save(i["_parsed"])
        results.append({"ok": bool(r.get("ok")), "message": r.get("message", ""), "raw": i["raw"]})
        if not r.get("ok"):
            break
    with _lock:
        _done[key] = (now, results)
    return all(r["ok"] for r in results), results
