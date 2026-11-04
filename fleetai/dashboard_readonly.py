"""Isolated, read-only dashboard. Disabled until its own password hash is configured."""
import os
from datetime import datetime, timedelta
from pathlib import Path
from flask import Blueprint, request, jsonify, Response, send_file
from sqlalchemy import func
from werkzeug.security import check_password_hash
from .db import Session
from .models import Car, Operation, Income, Expense, Part, InvestorPayout, DriverWalletTransaction, DriverDebt
from .finance import moscow_now
from .routes import effective_daily_rent

dashboard_bp = Blueprint("dashboard_preview", __name__)

@dashboard_bp.before_request
def _dashboard_auth():
    password_hash = os.getenv("FLEETAI_DASHBOARD_PASSWORD_HASH", "").strip()
    if not password_hash:
        return jsonify({"ok": False, "message": "Dashboard is not configured"}), 503
    auth = request.authorization
    if not auth or auth.username != "admin" or not check_password_hash(password_hash, auth.password or ""):
        return Response("Authentication required", 401, {"WWW-Authenticate": 'Basic realm="FleetAI dashboard", charset="UTF-8"', "Cache-Control": "no-store"})

@dashboard_bp.after_request
def _no_cache(response):
    response.headers["Cache-Control"] = "no-store"
    response.headers["X-Content-Type-Options"] = "nosniff"
    return response

@dashboard_bp.route("/dashboard-preview", methods=["GET"])
def dashboard_preview():
    return send_file(Path(__file__).with_name("dashboard_preview.html"), mimetype="text/html")

@dashboard_bp.route("/dashboard-api/repair-history-readonly", methods=["GET"])
def api_repair_history_readonly():
    """Read-only repair/service operation history; no financial reconciliation."""
    session = Session()
    try:
        rows = session.query(Operation).filter(
            Operation.type.in_(["repair", "service"])
        ).order_by(Operation.id.desc()).limit(100).all()
        return jsonify({
            "ok": True,
            "read_only": True,
            "items": [{
                "id": op.id,
                "date": op.date.strftime("%d.%m.%Y %H:%M") if op.date else "",
                "car_code": op.car_code or "",
                "type": op.type,
                "description": op.description or "",
                "category": op.category or "",
                "amount": op.amount,
            } for op in rows],
        })
    except Exception:
        session.rollback()
        return jsonify({"ok": False, "message": "Не удалось загрузить историю ремонтов"}), 500
    finally:
        session.close()


@dashboard_bp.route("/dashboard-api/repair-details-readonly/<int:operation_id>", methods=["GET"])
def api_repair_details_readonly(operation_id):
    """Read-only breakdown for one repair; no financial reconciliation."""
    session = Session()
    try:
        op = session.query(Operation).filter(
            Operation.id == operation_id,
            Operation.type.in_(["repair", "service"]),
        ).first()
        if not op:
            return jsonify({"ok": False, "message": "Ремонт не найден"}), 404
        parts = session.query(Part).filter(Part.operation_id == op.id).order_by(Part.id.asc()).all()
        expenses = session.query(Expense).filter(Expense.operation_id == op.id).order_by(Expense.id.asc()).all()
        return jsonify({
            "ok": True, "read_only": True,
            "operation": {
                "id": op.id, "car_code": op.car_code or "",
                "date": op.date.strftime("%d.%m.%Y %H:%M") if op.date else "",
                "category": op.category or "", "description": op.description or "",
                "amount": op.amount, "mileage": op.mileage,
            },
            "parts": [{
                "name": p.part_name or "", "brand": p.brand or "",
                "price": p.price, "labor": p.labor,
            } for p in parts],
            "expenses": [{
                "category": e.category or "", "amount": e.amount,
            } for e in expenses],
            "note": "Связанные позиции показаны отдельно и могут уже входить в сумму операции; повторно не суммируются.",
        })
    except Exception:
        session.rollback()
        return jsonify({"ok": False, "message": "Не удалось загрузить детали ремонта"}), 500
    finally:
        session.close()


@dashboard_bp.route("/dashboard-api/car-profile-readonly/<code>", methods=["GET"])
def api_car_profile_readonly(code):
    """Raw car ledger snapshot without settlement/reconciliation side effects."""
    session = Session()
    try:
        car = session.query(Car).filter(Car.code == code).first()
        if not car:
            return jsonify({"ok": False, "message": "Автомобиль не найден"}), 404
        income_rows = session.query(Income).filter(Income.car_code == code).all()
        expense_rows = session.query(Expense).filter(Expense.car_code == code).all()
        wallet_balance = int(session.query(
            func.coalesce(func.sum(DriverWalletTransaction.amount), 0)
        ).filter(
            func.trim(DriverWalletTransaction.car_code) == code
        ).scalar() or 0)
        wallet_aggregates = session.query(
            DriverWalletTransaction.transaction_type,
            func.coalesce(func.sum(DriverWalletTransaction.amount), 0),
            func.count(DriverWalletTransaction.id),
        ).filter(
            func.trim(DriverWalletTransaction.car_code) == code
        ).group_by(DriverWalletTransaction.transaction_type).all()
        rental_charged = sum(-int(total or 0) for kind, total, count in wallet_aggregates if kind == "daily_rent" and int(total or 0) < 0)
        wallet_credits = sum(int(total or 0) for kind, total, count in wallet_aggregates if int(total or 0) > 0)
        wallet_debits_other = sum(-int(total or 0) for kind, total, count in wallet_aggregates if kind != "daily_rent" and int(total or 0) < 0)
        wallet_rows = session.query(DriverWalletTransaction).filter(
            DriverWalletTransaction.car_code == code
        ).order_by(DriverWalletTransaction.id.desc()).limit(100).all()
        debt_rows = session.query(DriverDebt).filter(
            DriverDebt.car_code == code
        ).order_by(DriverDebt.id.desc()).all()
        ledger_rows = (
            [{"date": x.date.strftime("%d.%m.%Y") if x.date else "",
              "kind": "Поступление", "category": x.income_type or "",
              "amount": int(x.amount or 0), "source": "income", "date_iso": x.date.strftime("%Y-%m-%d") if x.date else ""} for x in income_rows]
            + [{"date": x.date.strftime("%d.%m.%Y") if x.date else "",
                "kind": "Расход", "category": x.category or "",
                "amount": int(x.amount or 0), "source": "expenses", "date_iso": x.date.strftime("%Y-%m-%d") if x.date else ""} for x in expense_rows]
        )
        ledger_rows.sort(key=lambda x: x["date_iso"], reverse=True)
        repairs = session.query(Operation).filter(
            Operation.car_code == code,
            Operation.type.in_(["repair", "service"]),
        ).order_by(Operation.id.desc()).limit(100).all()
        return jsonify({
            "ok": True, "read_only": True,
            "car": {
                "code": car.code, "brand": car.brand or "", "model": car.model or "",
                "plate": car.plate or "", "year": car.year,
                "driver": car.driver or "", "status": car.status or "",
                "owner_type": car.owner_type or "own",
                "investor_name": car.investor_name or "",
                "weekly_payment": car.weekly_payment,
                "daily_rent": car.daily_rent,
            },
            "ledger": {
                "income": sum(int(x.amount or 0) for x in income_rows),
                "expenses": sum(int(x.amount or 0) for x in expense_rows),
                "income_count": len(income_rows),
                "expense_count": len(expense_rows),
                "scope": "За всё время по записям income и expenses; без расчёта кредитов, выплат инвесторам и задолженностей.",
            },
            "ledger_entries": ledger_rows,
            "ledger_entries_limited": False,
            "rental_summary": {
                "daily_rate": int(effective_daily_rent(car) or 0),
                "weekly_rate": int(car.weekly_payment or 0),
                "charged_from_wallet": rental_charged,
                "wallet_credits": wallet_credits,
                "other_wallet_debits": wallet_debits_other,
                "wallet_balance": wallet_balance,
                "next_payment_date": car.next_payment_date or "",
                "last_payment_date": car.last_payment_date or "",
                "note": "Начислено — сумма записанных списаний daily_rent. Пополнения и баланс взяты из кошелька. Не включает ещё не записанные начисления; отрицательный баланс не всегда равен долгу по аренде."
            },
            "wallet": {
                "balance": wallet_balance,
                "balance_note": "Текущий баланс по сумме всех операций кошелька автомобиля, включая пополнения и списания.",
                "entries": [{
                    "date": x.date.strftime("%d.%m.%Y") if x.date else "",
                    "type": x.transaction_type or "",
                    "amount": int(x.amount or 0),
                    "comment": x.comment or "",
                } for x in wallet_rows],
                "limited": len(wallet_rows) == 100,
                "note": "Операции кошелька показываются отдельно; могут отражать те же поступления, поэтому не суммируются с доходами."
            },
            "debts": [{
                "driver": x.driver_name or "", "reason": x.reason or "",
                "original": int(x.original_amount or 0),
                "paid": int(x.paid_amount or 0),
                "balance": int(x.balance or 0),
                "status": x.status or "",
            } for x in debt_rows],
            "debt_note": "Задолженности по отдельному реестру долгов. Не равны автоматически долгу по аренде.",
            "repairs": [{
                "id": x.id, "date": x.date.strftime("%d.%m.%Y") if x.date else "",
                "category": x.category or "", "description": x.description or "",
                "amount": x.amount,
            } for x in repairs],
            "repairs_limited": len(repairs) == 100,
        })
    except Exception:
        session.rollback()
        return jsonify({"ok": False, "message": "Не удалось получить карточку автомобиля"}), 500
    finally:
        session.close()


@dashboard_bp.route("/dashboard-api/investor-ledger-readonly", methods=["GET"])
def api_investor_ledger_readonly():
    """Raw investor-linked records, no automatic settlements or mutations."""
    session = Session()
    try:
        cars = session.query(Car).filter(Car.owner_type == "investor").order_by(Car.code).all()
        codes = [str(car.code).strip() for car in cars]
        income = session.query(Income).filter(Income.car_code.in_(codes)).all() if codes else []
        expenses = session.query(Expense).filter(Expense.car_code.in_(codes)).all() if codes else []
        # Reuse the existing settlement formula, including carried balances,
        # expense allocation, investor contributions and recorded payouts.
        from .finance import calculate_period_for_car
        today = moscow_now()
        current_start = datetime(today.year, today.month, 16)
        if today.day < 16:
            last_month = current_start - timedelta(days=1)
            current_start = datetime(last_month.year, last_month.month, 16)
        previous_month = current_start.replace(day=1) - timedelta(days=1)
        previous_start = datetime(previous_month.year, previous_month.month, 16)
        # Optional inclusive date range for dashboard comparisons; no ledger mutations.
        custom_start_text = request.args.get("start", "").strip()
        custom_end_text = request.args.get("end", "").strip()
        custom_start = custom_end = None
        if custom_start_text or custom_end_text:
            try:
                if not custom_start_text or not custom_end_text:
                    raise ValueError("Both dates required")
                custom_start = datetime.strptime(custom_start_text, "%Y-%m-%d")
                custom_end = datetime.strptime(custom_end_text, "%Y-%m-%d") + timedelta(days=1)
                if custom_start >= custom_end or (custom_end - custom_start).days > 366:
                    raise ValueError("Invalid range")
            except ValueError:
                return jsonify({"ok": False, "message": "Некорректный диапазон дат"}), 400
        calculated = {}
        for car in cars:
            next_month = current_start + timedelta(days=32)
            current_end = datetime(next_month.year, next_month.month, 16)
            previous_end = current_start
            calculated[str(car.code).strip()] = {
                "cycle": calculate_period_for_car(session, car, current_start, current_end, include_previous_carry=False),
                **({"custom": calculate_period_for_car(session, car, custom_start, custom_end, include_previous_carry=False)} if custom_start else {}),
                "previous": calculate_period_for_car(session, car, previous_start, previous_end, include_previous_carry=False),
                "all": calculate_period_for_car(session, car, datetime(2000, 1, 1), current_end, include_previous_carry=False),
            }
        payouts = session.query(InvestorPayout).all()
        def entry(row, kind, category):
            return {"date_iso": row.date.strftime("%Y-%m-%d") if row.date else "",
                    "date": row.date.strftime("%d.%m.%Y") if row.date else "",
                    "car_code": str(row.car_code or "").strip(),
                    "kind": kind, "category": category,
                    "amount": int(row.amount or 0)}
        entries = (
            [entry(row, "income", row.income_type or "") for row in income]
            + [entry(row, "expense", row.category or "") for row in expenses]
            + [dict(entry(row, "payout", "Выплата инвестору"),
                    investor_name=row.investor_name or "") for row in payouts]
        )
        entries.sort(key=lambda row: row["date_iso"], reverse=True)
        dated_entries = [row["date_iso"] for row in entries if row["date_iso"]]
        previous_entries = [row for row in entries if previous_start.strftime("%Y-%m-%d") <= row["date_iso"] < current_start.strftime("%Y-%m-%d")]
        diagnostics = {"previous_entries": len(previous_entries), "total_entries": len(entries), "earliest_entry": min(dated_entries) if dated_entries else None, "latest_entry": max(dated_entries) if dated_entries else None}
        return jsonify({"ok": True, "read_only": True,
                        "diagnostics": diagnostics, "periods": {"cycle": {"start": current_start.strftime("%Y-%m-%d"), "end_exclusive": current_end.strftime("%Y-%m-%d")}, "previous": {"start": previous_start.strftime("%Y-%m-%d"), "end_exclusive": previous_end.strftime("%Y-%m-%d")}},
                        "cars": [{"code": str(car.code).strip(),
                                  "name": " ".join(filter(None, [car.brand, car.model])),
                                  "investor": car.investor_name or "Не указан",
                                  "percent": int(car.investor_percent or 0)} for car in cars],
                        "entries": entries,
                        "calculations": {code: {period: {"available_to_pay": int(calc.get("available_to_pay") or 0), "investor_debt_to_park": int(calc.get("investor_debt_to_park") or 0), "accrued": int(calc.get("accrued_to_investor") or 0), "paid": int(calc.get("payouts_in_period") or 0), "payout_excess": max(int(calc.get("payouts_in_period") or 0) - int(calc.get("available_before_payouts") or 0), 0), "income": int(calc.get("income") or 0), "shared_expenses": int(calc.get("shared_expenses") or 0), "investor_only_expenses": int(calc.get("investor_only_expenses") or 0), "park_only_expenses": int(calc.get("park_only_expenses") or 0), "investor_paid": int(calc.get("investor_paid_in_period") or 0), "withheld": int(calc.get("debt_repaid_by_profit") or 0), "park_debt": int(calc.get("park_debt_to_investor") or 0)} for period, calc in periods.items()} for code, periods in calculated.items()},
                        "note": "Поступления и расходы — по машинам с текущим статусом инвестора; выплаты — из журнала выплат. Это не расчёт суммы к выплате."})
    except Exception:
        session.rollback()
        return jsonify({"ok": False, "message": "Не удалось загрузить данные инвесторов"}), 500
    finally:
        session.close()


@dashboard_bp.route("/dashboard-api/finance-ledger-readonly", methods=["GET"])
def api_finance_ledger_readonly():
    """Read-only raw income and expense records across all cars."""
    session = Session()
    try:
        income_rows = session.query(Income).all()
        expense_rows = session.query(Expense).all()
        entries = (
            [{"date_iso": row.date.strftime("%Y-%m-%d") if row.date else "",
              "date": row.date.strftime("%d.%m.%Y") if row.date else "",
              "car_code": str(row.car_code or "").strip(),
              "kind": "income", "category": row.income_type or "",
              "amount": int(row.amount or 0)} for row in income_rows]
            + [{"date_iso": row.date.strftime("%Y-%m-%d") if row.date else "",
                "date": row.date.strftime("%d.%m.%Y") if row.date else "",
                "car_code": str(row.car_code or "").strip(),
                "kind": "expense", "category": row.category or "",
                "amount": int(row.amount or 0)} for row in expense_rows]
        )
        entries.sort(key=lambda row: row["date_iso"], reverse=True)
        return jsonify({"ok": True, "read_only": True, "entries": entries,
                        "scope": "Только записи Income и Expense. Без кошельков, долгов, кредитов и выплат инвесторам."})
    except Exception:
        session.rollback()
        return jsonify({"ok": False, "message": "Не удалось загрузить финансовый журнал"}), 500
    finally:
        session.close()


@dashboard_bp.route("/dashboard-api/overview-readonly", methods=["GET"])
def api_overview_readonly():
    """Read-only inventory snapshot; never archive periods or reconcile downtime."""
    session = Session()
    try:
        cars = session.query(Car).order_by(Car.code.asc()).all()
        items = [{
            "code": car.code,
            "brand": car.brand or "",
            "model": car.model or "",
            "driver": car.driver or "",
            "status": car.status or "",
            "owner_type": car.owner_type or "own",
        } for car in cars]
        wallet_balances = dict(
            (str(car_code).strip(), int(balance or 0))
            for car_code, balance in session.query(
                DriverWalletTransaction.car_code,
                func.coalesce(func.sum(DriverWalletTransaction.amount), 0)
            ).group_by(DriverWalletTransaction.car_code).all()
        )
        for item in items:
            item["wallet_balance"] = wallet_balances.get(str(item["code"]).strip(), 0)
        negative_items = [item for item in items if item["wallet_balance"] < 0]
        return jsonify({
            "negative_wallet_count": len(negative_items),
            "negative_wallet_total": sum(-item["wallet_balance"] for item in negative_items),
            "negative_wallets": negative_items,
            "ok": True,
            "cars": len(items),
            "own_cars": sum(1 for item in items if item["owner_type"] != "investor"),
            "investor_cars": sum(1 for item in items if item["owner_type"] == "investor"),
            "items": items,
            "read_only": True,
            "financial_totals_included": False,
        })
    except Exception:
        session.rollback()
        return jsonify({"ok": False, "message": "Не удалось получить список автомобилей"}), 500
    finally:
        session.close()
