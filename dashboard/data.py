"""Read-only data access for the FleetAI 4.0 dashboard.

Every query here is a SELECT. On PostgreSQL the connection itself is opened
with default_transaction_read_only=on, and production should additionally use
a database role that only has SELECT privileges (see docs/DASHBOARD.md).
"""
import re

from sqlalchemy import create_engine, text

INVESTORS = (("илья", "ilya"), ("равшан", "ravshan"), ("марк", "mark"))

# Findings confirmed by the owner or by comparing Wialon with the database
# (docs/current-system-audit.md). Shown as "Сверка" notes; never applied to data.
KNOWN_NOTES = {
    "119": "По словам владельца, это нынешняя 665. Записи 119 и 665 в базе нужно объединить без потери истории.",
    "665": "Бывшая 119. Прежняя 665 теперь ездит как 267 (Х267СО716) — её в базе FleetAI нет.",
    "621": "В Wialon номер «А621СУ», в базе «т621су» — одна из записей с ошибкой.",
}


def make_engine(url):
    if url.startswith("postgres://"):
        url = url.replace("postgres://", "postgresql+psycopg://", 1)
    elif url.startswith("postgresql://"):
        url = url.replace("postgresql://", "postgresql+psycopg://", 1)
    connect_args = {}
    if url.startswith("postgresql"):
        connect_args["options"] = "-c default_transaction_read_only=on"
    return create_engine(url, future=True, pool_pre_ping=True, pool_size=3, max_overflow=2,
                         connect_args=connect_args) if url.startswith("postgresql") else \
        create_engine(url, future=True)


def owner_key(owner_type, investor_name):
    name = (investor_name or "").strip().casefold()
    for needle, key in INVESTORS:
        if needle in name:
            return key
    return "park"


def car_status(status, driver):
    s = (status or "").strip().casefold()
    if "ремонт" in s:
        return "repair"
    if driver and "работ" in s:
        return "rented"
    if "работ" in s or "прост" in s or not s:
        return "free"
    return "notready"


def _rub(n):
    return f"{int(n):,}".replace(",", " ")


def map_car(row):
    code = str(row["code"]).strip()
    driver = (row["driver"] or "").strip()
    owner = owner_key(row["owner_type"], row["investor_name"])
    notes = []
    if code in KNOWN_NOTES:
        notes.append(KNOWN_NOTES[code])
    if owner != "park" and (row["owner_type"] or "") != "investor":
        notes.append(f"В базе тип «{row['owner_type'] or 'own'}», но указан инвестор «{row['investor_name']}» — исправить тип в базе.")
    weekly, daily = int(row["weekly_payment"] or 0), int(row["daily_rent"] or 0)
    if weekly > 0:
        terms, rate = "Недельная", f"{_rub(weekly)} ₽/нед"
    elif daily > 0:
        terms, rate = "Суточная", f"{_rub(daily)} ₽/сут"
    else:
        terms, rate = "—", "—"
    status = car_status(row["status"], driver)
    plate = (row["plate"] or "").strip().upper() or code
    return {
        "id": "V-" + code, "code": code, "plate": plate,
        "model": " ".join(x for x in ((row["brand"] or "").strip(), (row["model"] or "").strip()) if x) or "—",
        "year": row["year"], "owner": owner, "investor_name": row["investor_name"] or "",
        "investor_percent": int(row["investor_percent"] or 0),
        "status": status, "status_raw": row["status"] or "",
        "driver": ("D-" + code) if driver else None, "driver_name": driver,
        "terms": terms, "rate": rate,
        "deposit": int(row["driver_deposit"] or 0) * 100,   # kopecks
        "balance": None,                                     # wallet is not connected yet
        "mileage": int(row["current_mileage"] or 0),
        "plates": [plate], "flag": " ".join(notes) or None,
        "why": None if status != "notready" else (row["status"] or "Не готова"),
    }


CARS_SQL = text("""
    SELECT code, brand, model, plate, year, status, driver, owner_type, investor_name,
           investor_percent, weekly_payment, daily_rent, driver_deposit, current_mileage
    FROM cars ORDER BY code
""")


def load_fleet(engine):
    with engine.connect() as conn:
        rows = conn.execute(CARS_SQL).mappings().all()
    cars = [map_car(r) for r in rows]
    drivers = [{"id": c["driver"], "name": c["driver_name"], "phone": "", "tg": False,
                "stage": "rent", "car": c["id"]} for c in cars if c["driver"]]
    return {"cars": cars, "drivers": drivers}


def find_owner(engine, username):
    with engine.connect() as conn:
        row = conn.execute(text("SELECT username, password_hash FROM auth_owners WHERE username = :u"),
                           {"u": username}).mappings().first()
    return dict(row) if row else None


def match_units_to_cars(units, cars):
    """Attach a car code to each Wialon unit when the 3-digit code is in its name."""
    codes = {c["code"] for c in cars}
    out = []
    for u in units:
        found = [d for d in re.findall(r"\d{3}", u.get("name") or "") if d in codes and d != "716"]
        out.append(dict(u, car_code=found[0] if found else None))
    return out
