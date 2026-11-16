"""Driver payments that reached the park's income but not the driver's wallet.

Before 15.11.2026 a payment typed as "621 получил 13000" (command box, old site or
bot) was saved as plain income: the park's finances saw the money, the driver's
wallet did not, so the driver looked like a debtor. This finds such payments made
since the current driver took the car and, on the owner's confirmation, credits the
wallet. No operation or income is created: the money is already in the books.
A credited payment is marked external_id "op:<id>", so it is never credited twice.
"""
from datetime import datetime, timedelta

from sqlalchemy import func, or_
from sqlalchemy.orm import Session

from fleetai.models import Car, DriverWalletTransaction, Operation

from .data import RETIRED_CODES

KOP = 100
SKIP_WORDS = ("залог", "депозит")


def _start(s, code):
    """When the current driver's wallet started: the last driver change, else the first wallet entry."""
    w = DriverWalletTransaction
    last_change = s.query(func.max(w.date)).filter(
        func.trim(w.car_code) == code, w.transaction_type == "driver_change_balance").scalar()
    if last_change:
        return last_change
    return s.query(func.min(w.date)).filter(func.trim(w.car_code) == code).scalar()


def unposted(engine):
    out = []
    with Session(engine) as s:
        credited = {str(x[0]) for x in s.query(DriverWalletTransaction.external_id).filter(
            DriverWalletTransaction.external_id.like("op:%")).all()}
        for car in s.query(Car).order_by(Car.code).all():
            code = str(car.code).strip()
            if code in RETIRED_CODES or not (car.driver or "").strip():
                continue
            start = _start(s, code)
            if not start:
                continue
            ops = s.query(Operation).filter(
                func.trim(Operation.car_code) == code, Operation.type == "income", Operation.amount > 0,
                Operation.date >= start, or_(Operation.category.is_(None), Operation.category != "Аренда"),
            ).order_by(Operation.date).all()
            rows = []                         # every plain payment, credited or not (for the duplicate check)
            for op in ops:
                raw = (op.raw_message or "").lower()
                if "[driver_topup:" in raw or "[bank" in raw or any(w in raw for w in SKIP_WORDS):
                    continue
                rows.append(op)
            for i, op in enumerate(rows):
                if f"op:{op.id}" in credited:
                    continue
                # a twin within 15 minutes (credited or not) makes this one a possible duplicate
                dup = any(o.amount == op.amount and abs((o.date - op.date).total_seconds()) <= 15 * 60
                          for j, o in enumerate(rows) if j != i and (j < i or f"op:{o.id}" in credited))
                out.append({"id": op.id, "car": code, "driver": (car.driver or "").strip(),
                            "date": op.date.isoformat(timespec="minutes"), "amount": int(op.amount) * KOP,
                            "raw": (op.raw_message or "")[:120], "maybe_duplicate": dup,
                            "since": start.isoformat(timespec="minutes")})
    return out


def credit(engine_unused, op_ids):
    """Credit the chosen payments to the current drivers' wallets. Returns [(op_id, car, amount)]."""
    from fleetai import db as fleet_db
    allowed = {x["id"]: x for x in unposted(fleet_db.engine)}
    done = []
    with fleet_db.Session() as s:
        for op_id in op_ids:
            item = allowed.get(int(op_id))
            if not item:
                continue                      # already credited, not a driver payment, or unknown
            car = s.query(Car).filter(func.trim(Car.code) == item["car"]).first()
            amount = item["amount"] // KOP
            s.add(DriverWalletTransaction(
                driver_name=(car.driver or "") if car else item["driver"], car_code=car.code if car else item["car"],
                amount=amount, transaction_type="dispatcher_topup", source="dashboard_fix",
                external_id=f"op:{item['id']}",
                comment=f"Зачтена оплата из операции #{item['id']} ({item['raw'][:80]})",
                date=datetime.now()))
            done.append((item["id"], item["car"], amount))
        s.commit()
    return done


def reverse_for_operation(op_id):
    """An operation that was credited to a wallet is deleted or replaced: take the credit back."""
    from fleetai import db as fleet_db
    with fleet_db.Session() as s:
        w = DriverWalletTransaction
        got = s.query(w).filter(w.external_id == f"op:{int(op_id)}").all()
        total = sum(int(x.amount or 0) for x in got)
        if not got or total == 0:
            return 0
        first = got[0]
        s.add(w(driver_name=first.driver_name, car_code=first.car_code, amount=-total,
                transaction_type="correction", source="dashboard",
                external_id=f"op:{int(op_id)}",
                comment=f"Отмена зачёта: операция #{int(op_id)} удалена или исправлена",
                date=datetime.now() + timedelta(seconds=1)))
        s.commit()
        return total
