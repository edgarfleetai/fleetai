"""Finance for the dashboard, computed by the SAME read-only functions the old
FleetAI uses (fleetai.finance.calculate_period_for_car), so numbers match.

Money in the database is integer rubles; the API returns kopecks (x100).
"""
import re
from datetime import datetime, timedelta

from sqlalchemy import text
from sqlalchemy.orm import Session

from fleetai.finance import (calculate_period_for_car, period_bounds_for_car,
                             previous_period_bounds_for_car, period_display_end, moscow_now)
from fleetai.models import Car

from .data import RETIRED_CODES, owner_key

GPS_PER_CAR_RUB = 500        # owner, 2026-11-14: per car per month
GARAGE_PER_MONTH_RUB = 3000  # owner, 2026-11-14: split across all cars
RECURRING_RE = re.compile(r"gps|жпс|трекер|wialon|гараж", re.I)

OP_LABELS = {
    "income": ("Доход", "in"), "expense": ("Расход", "out"), "repair": ("Ремонт", "out"),
    "part": ("Запчасть", "out"), "parts": ("Запчасти", "out"),
    "investor_payout": ("Выплата инвестору", "out"), "investor_investment": ("Внесение инвестора", "in"),
    "investor_expense_split": ("Расход с инвестором", "out"), "investment": ("Вложение", "out"),
    "downtime": ("Простой", "info"), "downtime_end": ("Конец простоя", "info"),
    "mileage": ("Пробег", "info"), "settlement_period": ("Закрытие периода", "info"),
}

KOP = 100


def _k(v):
    return int(v or 0) * KOP


def _bounds(car, period, now):
    if period == "previous":
        return previous_period_bounds_for_car(car, now=now)
    return period_bounds_for_car(car, now=now)


def fleet_finance(engine, period="current", now=None):
    now = now or moscow_now()
    with Session(engine) as s:
        cars = [c for c in s.query(Car).order_by(Car.code).all()
                if str(c.code).strip() not in RETIRED_CODES]
        n_cars = len(cars) or 1
        garage_base, garage_rest = divmod(GARAGE_PER_MONTH_RUB * KOP, n_cars)
        rows = []
        for i, car in enumerate(cars):
            start, end = _bounds(car, period, now)
            calc = calculate_period_for_car(s, car, start, end)
            owner = owner_key(car.owner_type, car.investor_name)
            pct = int(car.investor_percent or 0) if car.owner_type == "investor" else 0
            period_share = round(int(calc["profit_for_split"] or 0) * pct / 100) * KOP
            garage = garage_base + (1 if i < garage_rest else 0)
            recurring_booked = any(
                RECURRING_RE.search(cat or "") for (cat,) in s.execute(text(
                    "SELECT category FROM expenses WHERE trim(car_code) = :c AND date >= :a AND date < :b"),
                    {"c": str(car.code).strip(), "a": start, "b": end}))
            rows.append({
                "code": str(car.code).strip(), "owner": owner,
                "investor_name": car.investor_name or "", "investor_percent": int(car.investor_percent or 0),
                "owner_type": car.owner_type or "own",
                "period_start": start.date().isoformat(), "period_end": period_display_end(end).date().isoformat(),
                "income": _k(calc["income"]), "expenses": _k(calc["expenses"]),
                "shared_expenses": _k(calc["shared_expenses"]),
                "investor_only_expenses": _k(calc["investor_only_expenses"]),
                "park_only_expenses": _k(calc["park_only_expenses"]),
                "investments": _k(calc["investments"]), "profit": _k(calc["profit"]),
                "investor_amount": _k(calc["investor_amount"]), "owner_amount": _k(calc["owner_amount"]),
                "accrued_to_investor": _k(calc["accrued_to_investor"]),
                "profit_for_split": _k(calc["profit_for_split"]),
                # Investor's share of THIS period only (negative = share of a loss),
                # minus investor-only expenses and payouts made in the period.
                "period_share": period_share,
                "period_due": period_share - _k(calc["investor_only_expenses"]) - _k(calc["payouts_in_period"]),
                "previous_investor_debt": _k(calc["previous_investor_debt"]),
                "previous_park_debt_to_investor": _k(calc["previous_park_debt_to_investor"]),
                "payouts_in_period": _k(calc["payouts_in_period"]),
                "available_to_pay": _k(calc["available_to_pay"]),
                "investor_debt_to_park": _k(calc["investor_debt_to_park"]),
                "park_debt_to_investor": _k(calc["park_debt_to_investor"]),
                "downtime_days": int(calc["downtime_days"] or 0),
                # Owner's agreement: GPS 500 ₽/car and garage 3000 ₽/month split across
                # all cars are deducted from the investor's profit. Shown separately and
                # skipped when such an expense is already booked in the period.
                "gps": GPS_PER_CAR_RUB * KOP, "garage": garage, "recurring_booked": bool(recurring_booked),
            })
    return {"period": period, "cars": rows, "generated_at": now.isoformat()}


def journal(engine, days=90, now=None):
    now = now or moscow_now()
    since = now - timedelta(days=days)
    with engine.connect() as conn:
        ops = conn.execute(text(
            "SELECT id, date, car_code, type, category, description, amount, raw_message FROM operations "
            "WHERE date >= :since ORDER BY date DESC, id DESC LIMIT 1000"), {"since": since}).mappings().all()
    out = []
    for o in ops:
        code = str(o["car_code"] or "").strip()
        label, direction = OP_LABELS.get((o["type"] or "").strip(), (o["type"] or "—", "info"))
        d = o["date"]
        out.append({
            "id": o["id"], "date": d.isoformat() if isinstance(d, datetime) else str(d or ""),
            "car": ("665" if code in RETIRED_CODES else code), "car_raw": code,
            "type": o["type"] or "", "label": label, "dir": direction,
            "category": o["category"] or "", "description": (o["description"] or "")[:300],
            "amount": _k(o["amount"]),
            "raw": (o["raw_message"] or "")[:500],
            "topup": "[DRIVER_TOPUP:" in (o["raw_message"] or ""),
            "edit": ("inplace" if (o["type"] or "") in ("repair", "service", "expense") else
                     "topup" if "[DRIVER_TOPUP:" in (o["raw_message"] or "") else "replace"),
        })
    return {"days": days, "operations": out}


def repairs(engine, days=180, now=None):
    now = now or moscow_now()
    since = now - timedelta(days=days)
    with engine.connect() as conn:
        rows = conn.execute(text(
            "SELECT id, car_code, part_name, brand, position, price, labor, install_date, status FROM parts "
            "WHERE install_date >= :since ORDER BY install_date DESC, id DESC LIMIT 3000"),
            {"since": since}).mappings().all()
        exp = conn.execute(text(
            "SELECT e.id, e.car_code, e.date, e.category, e.amount, o.description FROM expenses e "
            "LEFT JOIN operations o ON o.id = e.operation_id WHERE e.date >= :since "
            "ORDER BY e.date DESC, e.id DESC LIMIT 3000"), {"since": since}).mappings().all()
    iso = lambda d: d.isoformat() if isinstance(d, datetime) else str(d or "")
    return {
        "days": days,
        "parts": [{"id": r["id"], "car": str(r["car_code"] or "").strip(), "name": r["part_name"] or "",
                   "brand": r["brand"] or "", "position": r["position"] or "",
                   "price": _k(r["price"]), "labor": _k(r["labor"]), "date": iso(r["install_date"]),
                   "status": r["status"] or ""} for r in rows],
        "expenses": [{"id": r["id"], "car": str(r["car_code"] or "").strip(), "date": iso(r["date"]),
                      "category": r["category"] or "", "amount": _k(r["amount"]),
                      "description": (r["description"] or "")[:200]} for r in exp],
    }
