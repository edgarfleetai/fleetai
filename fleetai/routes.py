from datetime import datetime
from flask import Blueprint, request, jsonify, render_template_string
from sqlalchemy import func

from .db import Session
from .models import Car, Operation, Income, Expense, Part, CarInvestment, InvestorInvestment, InvestorPayout, Mileage, Downtime, SettlementPeriod, InvestorSettlement
from .utils import only_int, normalize_code, find_car
from .parser import parse_message
from .finance import car_finance, investor_balance_for_car, period_bounds_for_car, calculate_period_for_car, close_period
from .views import HTML

bp = Blueprint("main", __name__)


def save_operation(data):
    session = Session()
    car = find_car(session, data.get("car_code"))

    if not car:
        existing = [c.code for c in session.query(Car).order_by(Car.code).all()]
        session.close()
        return {"ok": False, "message": f"Машина не найдена. Есть коды: {', '.join(existing)}"}

    if data["type"] == "unknown":
        session.close()
        return {"ok": False, "message": "Не понял сообщение. Пример: 703 получил 13000"}

    op = Operation(
        car_code=car.code, type=data["type"], category=data["category"],
        description=data["description"], amount=data["total"],
        mileage=data["mileage"], raw_message=data["raw"],
    )
    session.add(op)
    session.flush()

    if data["type"] == "income":
        session.add(Income(operation_id=op.id, car_code=car.code, amount=data["income"], income_type=data["description"]))

    elif data["type"] in ("repair", "service", "expense"):
        session.add(Expense(operation_id=op.id, car_code=car.code, category=data["category"], amount=data["total"], share_type=data.get("share_type", "shared")))

    elif data["type"] == "car_investment":
        session.add(CarInvestment(operation_id=op.id, car_code=car.code, category=data["category"], description=data["description"], amount=data["total"], raw_message=data["raw"]))

    elif data["type"] == "investor_investment":
        # Если написано просто "636 инвестор вложил 25000",
        # не создаем инвестора с именем "Вложил". Берем текущего
        # инвестора из карточки машины.
        investor_name = data.get("investor_name") or car.investor_name or ""

        session.add(InvestorInvestment(
            operation_id=op.id,
            car_code=car.code,
            investor_name=investor_name,
            amount=data["total"],
            percent=data["investor_percent"] or car.investor_percent or 0,
            comment=data["raw"],
        ))

        car.owner_type = "investor"
        if investor_name:
            car.investor_name = investor_name
        if data["investor_percent"]:
            car.investor_percent = data["investor_percent"]

    elif data["type"] == "investor_payout":
        session.add(InvestorPayout(operation_id=op.id, car_code=car.code, investor_name=data["investor_name"], amount=data["total"], comment=data["raw"]))

    elif data["type"] == "investor_expense_split":
        session.add(InvestorSettlement(
            operation_id=op.id, investor_name=car.investor_name or data.get("investor_name", ""),
            car_code=car.code, total_cost=data["total_cost"], investor_paid=data["investor_paid"],
            park_paid=data["park_paid"], investor_debt_to_park=data["investor_debt_to_park"],
            park_debt_to_investor=data["park_debt_to_investor"], description=data["description"],
            comment=data["raw"],
        ))
        session.add(Expense(operation_id=op.id, car_code=car.code, category="Доп. расходы", amount=data["total_cost"], share_type="shared"))

    elif data["type"] == "downtime":
        session.add(Downtime(
            operation_id=op.id, car_code=car.code, start_date=data.get("start_date") or datetime.now(),
            end_date=data.get("end_date"), days=data.get("days", 0),
            reason=data["description"], active=data.get("active", 0), comment=data["raw"],
        ))

    if data.get("part"):
        session.add(Part(
            car_code=car.code, operation_id=op.id, part_name=data["part"],
            brand=data["brand"], position=data["position"], price=data["part_price"],
            labor=data["labor"], install_mileage=data["mileage"],
        ))

    if data.get("mileage"):
        car.current_mileage = data["mileage"]
        session.add(Mileage(car_code=car.code, mileage=data["mileage"], source=data["raw"]))

    session.commit()
    op_id = op.id
    session.close()
    return {"ok": True, "message": f"Записано. Операция #{op_id}", "data": data}


@bp.route("/")
def index():
    return render_template_string(HTML)


@bp.route("/healthz")
def healthz():
    return "ok"


@bp.route("/api/add", methods=["POST"])
def api_add():
    payload = request.json or {}
    message = (payload.get("message", "") or "").strip()

    # Поддержка нескольких записей в одной строке:
    # 703 получил 13000 / 703 доп расходы 41700 инвестор оплатил 25000
    parts = [p.strip() for p in message.split("/") if p.strip()]

    if len(parts) <= 1:
        return jsonify(save_operation(parse_message(message)))

    results = []
    ok = True
    first_code = None

    for part in parts:
        parsed = parse_message(part)

        if parsed.get("car_code"):
            first_code = parsed.get("car_code")
        elif first_code:
            parsed["car_code"] = first_code

        result = save_operation(parsed)
        results.append(result.get("message", ""))
        if not result.get("ok"):
            ok = False

    return jsonify({
        "ok": ok,
        "message": " | ".join(results),
        "results": results,
    })


@bp.route("/api/add-car", methods=["POST"])
def api_add_car():
    payload = request.json or {}
    session = Session()

    code = normalize_code(payload.get("code"))
    if not code:
        session.close()
        return jsonify({"ok": False, "message": "Укажи код машины"})

    if find_car(session, code):
        session.close()
        return jsonify({"ok": False, "message": "Машина с таким кодом уже есть"})

    car = Car(
        code=code, brand=str(payload.get("brand") or "").strip(),
        model=str(payload.get("model") or "").strip(), plate=str(payload.get("plate") or "").strip(),
        year=only_int(payload.get("year")) or None,
        purchase_date=str(payload.get("purchase_date") or "").strip(),
        purchase_price=only_int(payload.get("purchase_price")),
        purchase_mileage=only_int(payload.get("mileage")),
        current_mileage=only_int(payload.get("mileage")),
        owner_type=str(payload.get("owner_type") or "own").strip(),
        investor_name=str(payload.get("investor_name") or "").strip(),
        investor_percent=only_int(payload.get("investor_percent")),
        settlement_day=only_int(payload.get("settlement_day")) or 15,
        status="Работает",
    )
    session.add(car)
    session.commit()
    session.close()
    return jsonify({"ok": True, "message": f"Машина {code} добавлена"})


@bp.route("/api/summary")
def api_summary():
    session = Session()
    income = session.query(func.coalesce(func.sum(Income.amount), 0)).scalar()
    expenses = session.query(func.coalesce(func.sum(Expense.amount), 0)).scalar()
    investments = session.query(func.coalesce(func.sum(CarInvestment.amount), 0)).scalar()
    downtime_days = session.query(func.coalesce(func.sum(Downtime.days), 0)).scalar()
    result = {
        "cars": session.query(Car).count(),
        "own_cars": session.query(Car).filter(Car.owner_type != "investor").count(),
        "investor_cars": session.query(Car).filter_by(owner_type="investor").count(),
        "income": income, "expenses": expenses, "investments": investments,
        "profit": income - expenses, "downtime_days": downtime_days,
    }
    session.close()
    return jsonify(result)


@bp.route("/api/cars")
def api_cars():
    session = Session()
    rows = []
    for car in session.query(Car).order_by(Car.code).all():
        income, expenses, investments, payouts, investor_invested, downtime_days = car_finance(session, car.code)
        rows.append({
            "code": car.code, "brand": car.brand, "model": car.model, "plate": car.plate,
            "mileage": car.current_mileage, "income": income, "expenses": expenses,
            "profit": income - expenses, "purchase_price": car.purchase_price or 0,
            "full_cost": (car.purchase_price or 0) + investments,
            "owner_type": car.owner_type or "own", "investor_name": car.investor_name or "",
            "investor_percent": car.investor_percent or 0, "downtime_days": downtime_days,
            "settlement_day": car.settlement_day or 15,
        })
    session.close()
    return jsonify(rows)


@bp.route("/api/car/<code>")
def api_car(code):
    session = Session()
    car = find_car(session, code)
    if not car:
        session.close()
        return jsonify({"ok": False, "message": "Машина не найдена"})

    income, expenses, investments, payouts, investor_invested, downtime_days = car_finance(session, car.code)
    ops = [{
        "id": op.id, "date": op.date.strftime("%d.%m.%Y %H:%M"),
        "type": op.type, "category": op.category, "description": op.description,
        "amount": op.amount, "mileage": op.mileage, "raw": op.raw_message,
    } for op in session.query(Operation).filter(func.trim(Operation.car_code) == normalize_code(car.code)).order_by(Operation.id.desc()).all()]
    session.close()
    return jsonify({"ok": True, "car": {
        "code": car.code, "brand": car.brand, "model": car.model, "plate": car.plate,
        "year": car.year, "mileage": car.current_mileage,
        "purchase_price": car.purchase_price or 0, "income": income,
        "expenses": expenses, "investments": investments, "profit": income - expenses,
        "full_cost": (car.purchase_price or 0) + investments,
        "owner_type": car.owner_type or "own", "investor_name": car.investor_name or "",
        "investor_percent": car.investor_percent or 0, "downtime_days": downtime_days,
    }, "operations": ops})


@bp.route("/api/investor-balance/<code>")
def api_investor_balance(code):
    session = Session()
    car = find_car(session, code)
    if not car:
        session.close()
        return jsonify({"ok": False, "message": "Машина не найдена"})
    balance = investor_balance_for_car(session, car)
    settlements = [{
        "date": r.date.strftime("%d.%m.%Y %H:%M") if r.date else "",
        "total_cost": r.total_cost or 0, "investor_paid": r.investor_paid or 0,
        "park_paid": r.park_paid or 0,
        "investor_debt_to_park": r.investor_debt_to_park or 0,
        "park_debt_to_investor": r.park_debt_to_investor or 0,
        "description": r.description or "", "comment": r.comment or "",
    } for r in session.query(InvestorSettlement).filter(func.trim(InvestorSettlement.car_code) == normalize_code(car.code)).order_by(InvestorSettlement.id.desc()).all()]
    session.close()
    return jsonify({"ok": True, "balance": balance, "settlements": settlements})


@bp.route("/api/period/<code>")
def api_period(code):
    session = Session()
    car = find_car(session, code)
    if not car:
        session.close()
        return jsonify({"ok": False, "message": "Машина не найдена"})
    start, end = period_bounds_for_car(car)
    calc = calculate_period_for_car(session, car, start, end)
    periods = [{
        "id": p.id, "start_date": p.start_date.strftime("%d.%m.%Y") if p.start_date else "",
        "end_date": p.end_date.strftime("%d.%m.%Y") if p.end_date else "",
        "income": p.income or 0, "expenses": p.expenses or 0,
        "profit": p.profit or 0, "investor_amount": p.investor_amount or 0,
        "owner_amount": p.owner_amount or 0,
        "closed_at": p.closed_at.strftime("%d.%m.%Y %H:%M") if p.closed_at else "",
    } for p in session.query(SettlementPeriod).filter(func.trim(SettlementPeriod.car_code) == normalize_code(car.code)).order_by(SettlementPeriod.id.desc()).all()]
    session.close()
    return jsonify({"ok": True, "settlement_day": car.settlement_day or 15, "current_period": {"start_date": start.strftime("%d.%m.%Y"), "end_date": end.strftime("%d.%m.%Y"), **calc}, "closed_periods": periods})


@bp.route("/api/close-period/<code>", methods=["POST"])
def api_close_period(code):
    session = Session()
    car = find_car(session, code)
    if not car:
        session.close()
        return jsonify({"ok": False, "message": "Машина не найдена"})
    period, msg = close_period(session, car)
    session.close()
    return jsonify({"ok": period is not None, "message": msg})


@bp.route("/api/investors-summary")
def api_investors_summary():
    session = Session()
    names = [r[0] for r in session.query(Car.investor_name).filter(Car.owner_type == "investor", Car.investor_name != "").distinct().all()]
    investors = []
    totals = dict(total_invested=0, total_payouts=0, income=0, expenses=0, profit=0, investor_share=0, owner_share=0, investor_debt_to_park=0, park_debt_to_investor=0, available_to_pay=0)
    for name in names:
        cars = session.query(Car).filter_by(owner_type="investor", investor_name=name).all()
        total_invested = session.query(func.coalesce(func.sum(InvestorInvestment.amount), 0)).filter_by(investor_name=name).scalar()
        total_payouts = session.query(func.coalesce(func.sum(InvestorPayout.amount), 0)).filter_by(investor_name=name).scalar()
        row = dict(name=name, cars_count=len(cars), total_invested=total_invested, total_payouts=total_payouts, income=0, expenses=0, profit=0, investor_share=0, owner_share=0, investor_debt_to_park=0, park_debt_to_investor=0, available_to_pay=0)
        for car in cars:
            income, expenses, investments, payouts, investor_invested, downtime_days = car_finance(session, car.code)
            profit = income - expenses
            share = round(profit * (car.investor_percent or 0) / 100)
            bal = investor_balance_for_car(session, car)
            row["income"] += income
            row["expenses"] += expenses
            row["profit"] += profit
            row["investor_share"] += share
            row["owner_share"] += profit - share
            row["investor_debt_to_park"] += bal["investor_debt_to_park"]
            row["park_debt_to_investor"] += bal["park_debt_to_investor"]
            row["available_to_pay"] += bal["available_to_pay"]
        investors.append(row)
        for k in totals:
            totals[k] += row.get(k, 0)
    session.close()
    return jsonify({"investors_count": len(investors), "investors": investors, **totals})


@bp.route("/api/investors")
def api_investors():
    session = Session()
    names = [r[0] for r in session.query(Car.investor_name).filter(Car.owner_type == "investor", Car.investor_name != "").distinct().all()]
    result = []
    for name in names:
        cars = session.query(Car).filter_by(owner_type="investor", investor_name=name).all()
        details = []
        totals = dict(total_invested=session.query(func.coalesce(func.sum(InvestorInvestment.amount), 0)).filter_by(investor_name=name).scalar(), total_payouts=session.query(func.coalesce(func.sum(InvestorPayout.amount), 0)).filter_by(investor_name=name).scalar(), total_profit=0, total_to_investor=0, investor_debt_to_park=0, available_to_pay=0)
        for car in cars:
            income, expenses, investments, payouts, investor_invested, downtime_days = car_finance(session, car.code)
            profit = income - expenses
            share = round(profit * (car.investor_percent or 0) / 100)
            bal = investor_balance_for_car(session, car)
            totals["total_profit"] += profit
            totals["total_to_investor"] += share
            totals["investor_debt_to_park"] += bal["investor_debt_to_park"]
            totals["available_to_pay"] += bal["available_to_pay"]
            details.append({"code": car.code, "car": f"{car.brand or ''} {car.model or ''}", "percent": car.investor_percent or 0, "income": income, "expenses": expenses, "profit": profit, "to_investor": share, "available_to_pay": bal["available_to_pay"]})
        result.append({"name": name, "cars": details, **totals})
    session.close()
    return jsonify(result)


@bp.route("/api/operations")
def api_operations():
    session = Session()
    rows = [{
        "id": op.id, "date": op.date.strftime("%d.%m.%Y %H:%M"),
        "car_code": op.car_code, "type": op.type,
        "category": op.category, "description": op.description,
        "amount": op.amount, "mileage": op.mileage, "raw": op.raw_message,
    } for op in session.query(Operation).order_by(Operation.id.desc()).limit(80).all()]
    session.close()
    return jsonify(rows)
