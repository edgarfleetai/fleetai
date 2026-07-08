from datetime import datetime
from flask import Flask, request, jsonify, render_template_string
from sqlalchemy import func

from db import Session
from migrations import ensure_schema, init_seed
from models import (
    Car, Operation, Income, Expense, Part, CarInvestment,
    InvestorInvestment, InvestorPayout, Mileage, Downtime, SettlementPeriod
)
from utils import only_int, normalize_code, find_car
from parser import parse_message
from finance import car_finance, period_bounds_for_car, calculate_period_for_car, close_period
from templates import HTML


app = Flask(__name__)


def save_operation(data):
    session = Session()
    car_code = normalize_code(data.get("car_code"))
    car = find_car(session, car_code)

    if not car_code or not car:
        existing = [c.code for c in session.query(Car).order_by(Car.code).all()]
        session.close()
        return {"ok": False, "message": f"Машина {car_code or 'без кода'} не найдена. Есть коды: {', '.join(existing)}"}

    if data["type"] == "unknown":
        session.close()
        return {"ok": False, "message": "Не понял сообщение. Пример: 703 получил 13000"}

    operation = Operation(
        car_code=car.code,
        type=data["type"],
        category=data["category"],
        description=data["description"],
        amount=data["total"],
        mileage=data["mileage"],
        raw_message=data["raw"],
    )
    session.add(operation)
    session.flush()

    if data["type"] == "income":
        session.add(Income(operation_id=operation.id, car_code=car.code, amount=data["income"], income_type=data["description"]))

    elif data["type"] in ("repair", "service", "expense"):
        session.add(Expense(operation_id=operation.id, car_code=car.code, category=data["category"], amount=data["total"], share_type=data.get("share_type", "shared")))

    elif data["type"] == "car_investment":
        session.add(CarInvestment(operation_id=operation.id, car_code=car.code, category=data["category"], description=data["description"], amount=data["total"], raw_message=data["raw"]))

    elif data["type"] == "investor_investment":
        session.add(InvestorInvestment(operation_id=operation.id, car_code=car.code, investor_name=data["investor_name"], amount=data["total"], percent=data["investor_percent"], comment=data["raw"]))

        if data["investor_name"]:
            car.owner_type = "investor"
            car.investor_name = data["investor_name"]
        if data["investor_percent"]:
            car.investor_percent = data["investor_percent"]

    elif data["type"] == "investor_payout":
        session.add(InvestorPayout(operation_id=operation.id, car_code=car.code, investor_name=data["investor_name"], amount=data["total"], comment=data["raw"]))

    elif data["type"] == "downtime":
        session.add(Downtime(
            operation_id=operation.id,
            car_code=car.code,
            start_date=data.get("start_date") or datetime.now(),
            end_date=data.get("end_date"),
            days=data.get("days", 0),
            reason=data["description"],
            active=data.get("active", 0),
            comment=data["raw"],
        ))

    if data.get("part"):
        session.add(Part(
            car_code=car.code,
            operation_id=operation.id,
            part_name=data["part"],
            brand=data["brand"],
            position=data["position"],
            price=data["part_price"],
            labor=data["labor"],
            install_mileage=data["mileage"],
        ))

    if data.get("mileage"):
        car.current_mileage = data["mileage"]
        session.add(Mileage(car_code=car.code, mileage=data["mileage"], source=data["raw"]))

    session.commit()
    operation_id = operation.id
    session.close()

    return {"ok": True, "message": f"Записано. Операция #{operation_id}", "data": data}


@app.route("/")
def index():
    return render_template_string(HTML)


@app.route("/healthz")
def healthz():
    return "ok"


@app.route("/api/add", methods=["POST"])
def api_add():
    payload = request.json or {}
    return jsonify(save_operation(parse_message(payload.get("message", ""))))


@app.route("/api/add-car", methods=["POST"])
def api_add_car():
    payload = request.json or {}
    session = Session()

    code_value = normalize_code(payload.get("code"))
    if not code_value:
        session.close()
        return jsonify({"ok": False, "message": "Укажи код машины"})

    if find_car(session, code_value):
        session.close()
        return jsonify({"ok": False, "message": "Машина с таким кодом уже есть"})

    car = Car(
        code=code_value,
        brand=str(payload.get("brand") or "").strip(),
        model=str(payload.get("model") or "").strip(),
        plate=str(payload.get("plate") or "").strip(),
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

    return jsonify({"ok": True, "message": f"Машина {code_value} добавлена"})


@app.route("/api/summary")
def api_summary():
    session = Session()

    cars = session.query(Car).count()
    own_cars = session.query(Car).filter(Car.owner_type != "investor").count()
    investor_cars = session.query(Car).filter_by(owner_type="investor").count()
    income = session.query(func.coalesce(func.sum(Income.amount), 0)).scalar()
    expenses = session.query(func.coalesce(func.sum(Expense.amount), 0)).scalar()
    investments = session.query(func.coalesce(func.sum(CarInvestment.amount), 0)).scalar()
    downtime_days = session.query(func.coalesce(func.sum(Downtime.days), 0)).scalar()

    session.close()

    return jsonify({
        "cars": cars, "own_cars": own_cars, "investor_cars": investor_cars,
        "income": income, "expenses": expenses, "investments": investments,
        "profit": income - expenses, "downtime_days": downtime_days,
    })


@app.route("/api/cars")
def api_cars():
    owner_type = request.args.get("owner_type")
    session = Session()

    query = session.query(Car).order_by(Car.code)
    if owner_type == "own":
        query = query.filter(Car.owner_type != "investor")
    elif owner_type == "investor":
        query = query.filter_by(owner_type="investor")

    rows = []
    for car in query.all():
        income, expenses, investments, payouts, investor_invested, downtime_days = car_finance(session, car.code)
        rows.append({
            "code": car.code, "brand": car.brand, "model": car.model, "plate": car.plate,
            "mileage": car.current_mileage, "status": car.status, "income": income,
            "expenses": expenses, "car_investments": investments, "profit": income - expenses,
            "purchase_price": car.purchase_price or 0, "full_cost": (car.purchase_price or 0) + investments,
            "owner_type": car.owner_type or "own", "investor_name": car.investor_name or "",
            "investor_percent": car.investor_percent or 0, "investor_invested": investor_invested,
            "investor_payouts": payouts, "downtime_days": downtime_days,
            "settlement_day": car.settlement_day or 15,
        })

    session.close()
    return jsonify(rows)


@app.route("/api/car/<code>")
def api_car_card(code):
    session = Session()
    car = find_car(session, code)

    if not car:
        session.close()
        return jsonify({"ok": False, "message": "Машина не найдена"})

    income, expenses, investments, payouts, investor_invested, downtime_days = car_finance(session, car.code)

    operations = [
        {
            "id": op.id, "date": op.date.strftime("%d.%m.%Y %H:%M"),
            "type": op.type, "category": op.category, "description": op.description,
            "amount": op.amount, "mileage": op.mileage, "raw": op.raw_message,
        }
        for op in session.query(Operation).filter(func.trim(Operation.car_code) == normalize_code(car.code)).order_by(Operation.id.desc()).all()
    ]

    session.close()

    return jsonify({
        "ok": True,
        "car": {
            "code": car.code, "brand": car.brand, "model": car.model, "plate": car.plate,
            "year": car.year, "mileage": car.current_mileage,
            "purchase_price": car.purchase_price or 0,
            "income": income, "expenses": expenses, "investments": investments,
            "profit": income - expenses, "full_cost": (car.purchase_price or 0) + investments,
            "owner_type": car.owner_type or "own", "investor_name": car.investor_name or "",
            "investor_percent": car.investor_percent or 0,
            "investor_invested": investor_invested, "investor_payouts": payouts,
            "downtime_days": downtime_days, "settlement_day": car.settlement_day or 15,
        },
        "operations": operations,
    })


@app.route("/api/period/<code>")
def api_period_preview(code):
    session = Session()
    car = find_car(session, code)

    if not car:
        session.close()
        return jsonify({"ok": False, "message": "Машина не найдена"})

    start, end = period_bounds_for_car(car)
    calc = calculate_period_for_car(session, car, start, end)

    periods = [
        {
            "id": p.id,
            "start_date": p.start_date.strftime("%d.%m.%Y") if p.start_date else "",
            "end_date": p.end_date.strftime("%d.%m.%Y") if p.end_date else "",
            "income": p.income or 0, "expenses": p.expenses or 0,
            "investments": p.investments or 0, "profit": p.profit or 0,
            "investor_amount": p.investor_amount or 0, "owner_amount": p.owner_amount or 0,
            "downtime_days": p.downtime_days or 0,
            "closed_at": p.closed_at.strftime("%d.%m.%Y %H:%M") if p.closed_at else "",
        }
        for p in session.query(SettlementPeriod).filter(func.trim(SettlementPeriod.car_code) == normalize_code(car.code)).order_by(SettlementPeriod.id.desc()).all()
    ]

    session.close()

    return jsonify({
        "ok": True,
        "car_code": car.code,
        "settlement_day": car.settlement_day or 15,
        "current_period": {
            "start_date": start.strftime("%d.%m.%Y"),
            "end_date": end.strftime("%d.%m.%Y"),
            **calc
        },
        "closed_periods": periods
    })


@app.route("/api/close-period/<code>", methods=["POST"])
def api_close_period(code):
    session = Session()
    car = find_car(session, code)

    if not car:
        session.close()
        return jsonify({"ok": False, "message": "Машина не найдена"})

    period, message = close_period(session, car)
    session.close()

    return jsonify({"ok": period is not None, "message": message})


@app.route("/api/investors")
def api_investors():
    session = Session()
    names = [row[0] for row in session.query(Car.investor_name).filter(Car.owner_type == "investor", Car.investor_name != "").distinct().all()]
    result = []

    for name in names:
        cars = session.query(Car).filter_by(owner_type="investor", investor_name=name).all()
        total_invested = session.query(func.coalesce(func.sum(InvestorInvestment.amount), 0)).filter_by(investor_name=name).scalar()
        total_payouts = session.query(func.coalesce(func.sum(InvestorPayout.amount), 0)).filter_by(investor_name=name).scalar()

        details = []
        total_income = total_expenses = total_profit = total_to_investor = total_downtime_days = 0

        for car in cars:
            income, expenses, investments, payouts, investor_invested, downtime_days = car_finance(session, car.code)
            profit = income - expenses
            to_investor = round(profit * (car.investor_percent or 0) / 100)

            total_income += income
            total_expenses += expenses
            total_profit += profit
            total_to_investor += to_investor
            total_downtime_days += downtime_days

            details.append({
                "code": car.code, "car": f"{car.brand or ''} {car.model or ''}",
                "percent": car.investor_percent or 0, "income": income,
                "expenses": expenses, "profit": profit, "to_investor": to_investor,
                "invested": investor_invested, "payouts": payouts,
                "downtime_days": downtime_days,
            })

        result.append({
            "name": name, "total_invested": total_invested, "total_payouts": total_payouts,
            "balance": total_invested - total_payouts, "total_income": total_income,
            "total_expenses": total_expenses, "total_profit": total_profit,
            "total_to_investor": total_to_investor,
            "total_downtime_days": total_downtime_days, "cars": details,
        })

    session.close()
    return jsonify(result)


@app.route("/api/operations")
def api_operations():
    session = Session()

    rows = [
        {
            "id": op.id, "date": op.date.strftime("%d.%m.%Y %H:%M"),
            "car_code": op.car_code, "type": op.type, "category": op.category,
            "description": op.description, "amount": op.amount,
            "mileage": op.mileage, "raw": op.raw_message,
        }
        for op in session.query(Operation).order_by(Operation.id.desc()).limit(80).all()
    ]

    session.close()
    return jsonify(rows)


ensure_schema()
init_seed()

if __name__ == "__main__":
    app.run(host="0.0.0.0")
