"""Rent and contracts for the dashboard. Read-only.

Rent due, overdue periods and separate debts are computed by the old FleetAI's
own read-only functions (calculate_driver_payment, driver_debt_summary). The
old site also runs _sync_daily_rent (it writes daily accruals) before showing a
wallet; the dashboard never does, so the wallet is "as of the last accrual
made by FleetAI".
"""
from datetime import date, datetime

from sqlalchemy import func, inspect, text
from sqlalchemy.orm import Session

from fleetai.models import Car, DriverWalletTransaction
from fleetai.routes import calculate_driver_payment, driver_debt_summary, effective_daily_rent

from .data import RETIRED_CODES

KOP = 100


def _iso(v):
    if isinstance(v, (datetime, date)):
        return v.isoformat()
    return str(v or "")


def rent_overview(engine):
    out = []
    with Session(engine) as s:
        cars = [c for c in s.query(Car).order_by(Car.code).all()
                if str(c.code).strip() not in RETIRED_CODES and (c.driver or "").strip()]
        for car in cars:
            code = str(car.code).strip()
            wallet = s.query(func.coalesce(func.sum(DriverWalletTransaction.amount), 0)).filter(
                func.trim(DriverWalletTransaction.car_code) == code).scalar() or 0
            calc = calculate_driver_payment(s, car)
            debts = [d for d in driver_debt_summary(s, car.driver or "")
                     if str(d.get("car_code") or "").strip() == code and int(d.get("balance") or 0) > 0]
            last = s.query(DriverWalletTransaction).filter(
                func.trim(DriverWalletTransaction.car_code) == code).order_by(
                DriverWalletTransaction.date.desc(), DriverWalletTransaction.id.desc()).limit(8).all()
            debt_total = sum(int(d.get("balance") or 0) for d in debts)
            out.append({
                "code": code, "driver": (car.driver or "").strip(),
                "daily_rent": int(effective_daily_rent(car) or 0) * KOP,
                "weekly_payment": int(car.weekly_payment or 0) * KOP,
                "deposit": int(car.driver_deposit or 0) * KOP,
                "wallet": int(wallet) * KOP,
                "amount_due": int(calc.get("amount_due") or 0) * KOP,
                "overdue_total": int(calc.get("overdue_total") or 0) * KOP,
                "overdue_days": int(calc.get("overdue_days") or 0),
                "is_overdue": bool(calc.get("is_overdue")),
                "next_payment_date": calc.get("next_payment_date") or "",
                "period_start": _iso(calc.get("period_start")), "period_end": _iso(calc.get("period_end")),
                "debt_total": debt_total * KOP,
                "debts": [{"amount": int(d.get("balance") or 0) * KOP, "reason": d.get("reason") or "",
                           "created_at": d.get("created_at") or ""} for d in debts],
                "transactions": [{"date": _iso(t.date), "amount": int(t.amount or 0) * KOP,
                                  "type": t.transaction_type or "", "comment": (t.comment or "")[:160]} for t in last],
            })
    return {"rentals": out}


CONTRACT_COLUMNS = ("id", "car_code", "status", "driver_name", "daily_rent", "deposit",
                    "rental_start_date", "signed_at", "created_at", "updated_at")


def contracts(engine):
    """Contract list without passport data, phone or PDF."""
    if not inspect(engine).has_table("driver_contracts"):
        return {"contracts": []}
    with engine.connect() as conn:
        rows = conn.execute(text(
            "SELECT " + ", ".join(CONTRACT_COLUMNS) + " FROM driver_contracts "
            "ORDER BY created_at DESC LIMIT 300")).mappings().all()
    return {"contracts": [{
        "id": str(r["id"]), "car": str(r["car_code"] or "").strip(), "status": r["status"] or "",
        "driver": r["driver_name"] or "", "daily_rent": int(r["daily_rent"] or 0) * KOP,
        "deposit": int(r["deposit"] or 0) * KOP, "start": r["rental_start_date"] or "",
        "signed_at": _iso(r["signed_at"]), "created_at": _iso(r["created_at"]),
    } for r in rows]}
