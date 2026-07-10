import os
import requests

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

def send_telegram_message(text):
    token = os.getenv("TELEGRAM_BOT_TOKEN")
    chat_id = os.getenv("TELEGRAM_CHAT_ID")

    if not token or not chat_id:
        print("Telegram не настроен: нет токена или chat id")
        return False

    url = f"https://api.telegram.org/bot{token}/sendMessage"

    try:
        response = requests.post(
            url,
            json={
                "chat_id": chat_id,
                "text": text,
                "parse_mode": "HTML",
            },
            timeout=15,
        )

        response.raise_for_status()
        return True

    except requests.RequestException as error:
        print(f"Ошибка Telegram: {error}")
        return False

@bp.route("/api/test-telegram")
def test_telegram():
    success = send_telegram_message(
        "✅ <b>Fleet AI</b>\n"
        "Telegram-уведомления успешно подключены."
    )

    if success:
        return jsonify({
            "ok": True,
            "message": "Сообщение отправлено"
        })

    return jsonify({
        "ok": False,
        "message": "Сообщение не отправлено"
    }), 500
    
BAD_INVESTOR_NAMES = {"вложил", "вложила", "оплатил", "оплатила", "внес", "внесла", "дал", "дала", "инвестор", ""}


def cleanup_legacy_investor_mess(session):
    """Исправляет старые ошибочные записи, которые уже попали в базу.

    1) Если инвестор случайно получил имя "Вложил"/"Оплатил" — перекидываем
       машину и операции на нормального инвестора (обычно "илья").
    2) Если есть операция вида "доп расходы 41700 инвестор оплатил 25000",
       но нет записи InvestorSettlement, создаем взаиморасчет.
    """
    changed = False

    real_names = []
    for name, in session.query(Car.investor_name).filter(Car.investor_name != "").all():
        if (name or "").strip().lower() not in BAD_INVESTOR_NAMES:
            real_names.append((name or "").strip())

    default_name = real_names[0] if real_names else "илья"

    # Исправляем машины с ошибочным именем инвестора.
    for car in session.query(Car).filter(Car.owner_type == "investor").all():
        if (car.investor_name or "").strip().lower() in BAD_INVESTOR_NAMES:
            car.investor_name = default_name
            if not car.investor_percent:
                car.investor_percent = 75
            changed = True

    # Исправляем записи вложений/выплат/взаиморасчетов с ошибочным именем.
    for table in (InvestorInvestment, InvestorPayout, InvestorSettlement):
        for row in session.query(table).all():
            name = (getattr(row, "investor_name", "") or "").strip().lower()
            if name in BAD_INVESTOR_NAMES:
                car = find_car(session, getattr(row, "car_code", ""))
                setattr(row, "investor_name", (car.investor_name if car and car.investor_name else default_name))
                changed = True

    # Создаем недостающий взаиморасчет из старых операций.
    import re
    for op in session.query(Operation).all():
        raw = (op.raw_message or "").lower()
        if "доп" not in raw or "расход" not in raw or "инвестор" not in raw:
            continue
        exists = session.query(InvestorSettlement).filter_by(operation_id=op.id).first()
        if exists:
            continue
        nums = [int(x) for x in re.findall(r"\b\d{2,9}\b", raw) if str(x) != str(op.car_code)]
        if not nums:
            continue
        total_cost = nums[0]
        investor_paid = 0
        m = re.search(r"инвестор\s*(?:оплатил|оплатила|дал|дала|внес|внесла)?\s*(\d{2,9})", raw)
        if m:
            investor_paid = int(m.group(1))
        elif len(nums) > 1:
            investor_paid = nums[1]
        park_paid = max(total_cost - investor_paid, 0)
        car = find_car(session, op.car_code)
        session.add(InvestorSettlement(
            operation_id=op.id,
            investor_name=(car.investor_name if car and car.investor_name else default_name),
            car_code=op.car_code,
            total_cost=total_cost,
            investor_paid=investor_paid,
            park_paid=park_paid,
            investor_debt_to_park=park_paid,
            park_debt_to_investor=0,
            description="Доп. расходы / взаиморасчет",
            comment=op.raw_message,
        ))
        # Если расход уже есть по этой операции — не дублируем.
        exp = session.query(Expense).filter_by(operation_id=op.id).first()
        if not exp:
            session.add(Expense(operation_id=op.id, car_code=op.car_code, category="Доп. расходы", amount=total_cost, share_type="shared"))
        changed = True

    if changed:
        session.commit()
    return changed



def split_message_parts(message):
    message = (message or "").strip()
    parts = [p.strip() for p in message.split("/") if p.strip()]
    return parts or [message]


def create_dependencies_from_parsed(session, op, car, data):
    """Создает связанные записи для уже существующей операции.

    Нужно для полного пересчета: удалили старые Income/Expense/Investor...
    и заново собрали их из raw_message операций.
    """
    if data["type"] == "income":
        session.add(Income(operation_id=op.id, car_code=car.code, amount=data["income"], income_type=data["description"]))

    elif data["type"] in ("repair", "service", "expense"):
        session.add(Expense(operation_id=op.id, car_code=car.code, category=data["category"], amount=data["total"], share_type=data.get("share_type", "shared")))

    elif data["type"] == "car_investment":
        session.add(CarInvestment(operation_id=op.id, car_code=car.code, category=data["category"], description=data["description"], amount=data["total"], raw_message=data["raw"]))

    elif data["type"] == "investor_investment":
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
        if data.get("investor_percent"):
            car.investor_percent = data["investor_percent"]

    elif data["type"] == "investor_payout":
        session.add(InvestorPayout(operation_id=op.id, car_code=car.code, investor_name=data.get("investor_name") or car.investor_name or "", amount=data["total"], comment=data["raw"]))

    elif data["type"] == "investor_expense_split":
        session.add(InvestorSettlement(
            operation_id=op.id,
            investor_name=car.investor_name or data.get("investor_name", ""),
            car_code=car.code,
            total_cost=data["total_cost"],
            investor_paid=data["investor_paid"],
            park_paid=data["park_paid"],
            investor_debt_to_park=data["investor_debt_to_park"],
            park_debt_to_investor=data["park_debt_to_investor"],
            description=data["description"],
            comment=data["raw"],
        ))
        session.add(Expense(operation_id=op.id, car_code=car.code, category="Доп. расходы", amount=data["total_cost"], share_type="shared"))

    elif data["type"] == "downtime_end":
        downtime = (
            session.query(Downtime)
            .filter(
                func.trim(Downtime.car_code) == normalize_code(car.code),
                Downtime.active == 1,
            )
            .order_by(Downtime.id.desc())
            .first()
        )
        if downtime:
            downtime.end_date = op.date or datetime.now()
            downtime.active = 0
            if downtime.start_date:
                downtime.days = max(
                    (downtime.end_date.date() - downtime.start_date.date()).days,
                    1,
                )
            car.status = "Работает"

    elif data["type"] == "downtime":
        session.add(Downtime(
            operation_id=op.id,
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
            operation_id=op.id,
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

    elif data["type"] == "downtime_end":
        downtime = (
            session.query(Downtime)
            .filter(
                func.trim(Downtime.car_code) == normalize_code(car.code),
                Downtime.active == 1,
            )
            .order_by(Downtime.id.desc())
            .first()
        )
        if downtime:
            downtime.end_date = op.date or datetime.now()
            downtime.active = 0
            if downtime.start_date:
                downtime.days = max(
                    (downtime.end_date.date() - downtime.start_date.date()).days,
                    1,
                )
            car.status = "Работает"

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
    cleanup_legacy_investor_mess(session)
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
    cleanup_legacy_investor_mess(session)
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
    cleanup_legacy_investor_mess(session)
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




def investor_total_invested_for_car(session, car):
    """Возвращает все вложения инвестора по машине.

    Сюда входят:
    - InvestorInvestment: команды вида "636 инвестор вложил 25000";
    - CarInvestment: команды вида "550 доп вложения 66900" для машин инвестора.

    Так доп. вложения по инвесторской машине не теряются в карточке инвестора.
    """
    code = normalize_code(car.code)

    investor_in = sum(
        (row.amount or 0)
        for row in session.query(InvestorInvestment).all()
        if normalize_code(row.car_code) == code
    )

    car_extra_in = 0
    car_investment_operation_ids = set()

    for row in session.query(CarInvestment).all():
        if normalize_code(row.car_code) == code:
            car_extra_in += row.amount or 0
            if row.operation_id:
                car_investment_operation_ids.add(row.operation_id)

    # Важно: старые операции типа car_investment могли остаться только в Operation,
    # без строки в таблице CarInvestment. Поэтому считаем их тоже.
    for op in session.query(Operation).all():
        if normalize_code(op.car_code) == code and op.type == "car_investment" and op.id not in car_investment_operation_ids:
            car_extra_in += op.amount or 0

    return investor_in + car_extra_in

@bp.route("/api/fix-investor-data", methods=["POST", "GET"])
def api_fix_investor_data():
    session = Session()
    changed = cleanup_legacy_investor_mess(session)
    session.close()
    return jsonify({"ok": True, "message": "Ошибочные инвесторы и взаиморасчеты исправлены" if changed else "Исправлять нечего"})


@bp.route("/api/investors-summary")
def api_investors_summary():
    session = Session()
    cleanup_legacy_investor_mess(session)
    names = [r[0] for r in session.query(Car.investor_name).filter(Car.owner_type == "investor", Car.investor_name != "").distinct().all()]
    investors = []
    totals = dict(total_invested=0, total_payouts=0, income=0, expenses=0, profit=0, investor_share=0, owner_share=0, investor_debt_to_park=0, park_debt_to_investor=0, available_to_pay=0)
    for name in names:
        cars = session.query(Car).filter_by(owner_type="investor", investor_name=name).all()
        total_payouts = session.query(func.coalesce(func.sum(InvestorPayout.amount), 0)).filter_by(investor_name=name).scalar()
        row = dict(name=name, cars_count=len(cars), total_invested=0, total_payouts=total_payouts, income=0, expenses=0, profit=0, investor_share=0, owner_share=0, investor_debt_to_park=0, park_debt_to_investor=0, available_to_pay=0)
        for car in cars:
            row["total_invested"] += investor_total_invested_for_car(session, car)
            income, expenses, investments, payouts, investor_invested, downtime_days = car_finance(session, car.code)
            profit = income - expenses
            bal = investor_balance_for_car(session, car)
            # Для инвесторского расчета показываем прибыль, которая реально делится,
            # то есть доход минус обычные расходы. Доп. расходы запуска уходят в долг.
            split_profit = bal.get("normal_profit_for_split", profit)
            share = bal["investor_share_total"]
            row["income"] += income
            row["expenses"] += expenses
            row["profit"] += split_profit
            row["investor_share"] += share
            row["owner_share"] += bal.get("park_share_total", max(split_profit - share, 0))
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
    cleanup_legacy_investor_mess(session)
    names = [r[0] for r in session.query(Car.investor_name).filter(Car.owner_type == "investor", Car.investor_name != "").distinct().all()]
    result = []
    for name in names:
        cars = session.query(Car).filter_by(owner_type="investor", investor_name=name).all()
        details = []
        totals = dict(total_invested=0, total_payouts=session.query(func.coalesce(func.sum(InvestorPayout.amount), 0)).filter_by(investor_name=name).scalar(), total_profit=0, total_to_investor=0, investor_debt_to_park=0, available_to_pay=0)
        for car in cars:
            car_total_invested = investor_total_invested_for_car(session, car)
            totals["total_invested"] += car_total_invested
            income, expenses, investments, payouts, investor_invested, downtime_days = car_finance(session, car.code)
            profit = income - expenses
            bal = investor_balance_for_car(session, car)
            split_profit = bal.get("normal_profit_for_split", profit)
            share = bal["investor_share_total"]
            totals["total_profit"] += split_profit
            totals["total_to_investor"] += share
            totals["investor_debt_to_park"] += bal["investor_debt_to_park"]
            totals["available_to_pay"] += bal["available_to_pay"]
            details.append({"code": car.code, "car": f"{car.brand or ''} {car.model or ''}", "percent": car.investor_percent or 0, "income": income, "expenses": expenses, "profit": split_profit, "to_investor": share, "available_to_pay": bal["available_to_pay"], "investor_debt_to_park": bal["investor_debt_to_park"], "invested": car_total_invested})
        result.append({"name": name, "cars": details, **totals})
    session.close()
    return jsonify(result)



def delete_operation_dependencies(session, operation_id):
    """Удаляет операцию и все связанные с ней записи, чтобы пересчеты стали чистыми."""
    for model in (Income, Expense, Part, CarInvestment, InvestorInvestment, InvestorPayout, Downtime, InvestorSettlement):
        for row in session.query(model).filter_by(operation_id=operation_id).all():
            session.delete(row)


@bp.route("/api/delete-operation/<int:operation_id>", methods=["POST"])
def api_delete_operation(operation_id):
    session = Session()
    op = session.query(Operation).filter_by(id=operation_id).first()
    if not op:
        session.close()
        return jsonify({"ok": False, "message": "Операция не найдена"})

    delete_operation_dependencies(session, operation_id)
    session.delete(op)
    session.commit()
    session.close()
    return jsonify({"ok": True, "message": f"Операция #{operation_id} удалена. Расчеты обновлены."})


@bp.route("/api/delete-car/<code>", methods=["POST"])
def api_delete_car(code):
    session = Session()
    car = find_car(session, code)
    if not car:
        session.close()
        return jsonify({"ok": False, "message": "Машина не найдена"})

    normalized = normalize_code(code)

    # Сначала удаляем операции и связанные таблицы по operation_id.
    operations = session.query(Operation).filter(func.trim(Operation.car_code) == normalized).all()
    for op in operations:
        delete_operation_dependencies(session, op.id)
        session.delete(op)

    # Потом чистим записи, которые могли быть без operation_id.
    for model in (Income, Expense, Part, CarInvestment, InvestorInvestment, InvestorPayout, Mileage, Downtime, SettlementPeriod, InvestorSettlement):
        for row in session.query(model).all():
            if normalize_code(getattr(row, "car_code", "")) == normalized:
                session.delete(row)

    session.delete(car)
    session.commit()
    session.close()
    return jsonify({"ok": True, "message": f"Машина {code} и ее записи удалены"})


@bp.route("/api/reset-car-investor/<code>", methods=["POST"])
def api_reset_car_investor(code):
    session = Session()
    car = find_car(session, code)
    if not car:
        session.close()
        return jsonify({"ok": False, "message": "Машина не найдена"})

    car.owner_type = "own"
    car.investor_name = ""
    car.investor_percent = 0

    for row in session.query(InvestorInvestment).all():
        if normalize_code(row.car_code) == normalize_code(code):
            session.delete(row)
    for row in session.query(InvestorPayout).all():
        if normalize_code(row.car_code) == normalize_code(code):
            session.delete(row)
    for row in session.query(InvestorSettlement).all():
        if normalize_code(row.car_code) == normalize_code(code):
            session.delete(row)

    session.commit()
    session.close()
    return jsonify({"ok": True, "message": f"Инвестор у машины {code} убран"})




@bp.route("/api/reassign-car-investor", methods=["POST"])
def api_reassign_car_investor():
    payload = request.json or {}
    code = normalize_code(payload.get("code"))
    new_name = (payload.get("investor_name") or "").strip()
    percent = only_int(payload.get("percent")) or 75

    session = Session()
    car = find_car(session, code)
    if not car:
        session.close()
        return jsonify({"ok": False, "message": "Машина не найдена"})

    if not new_name:
        session.close()
        return jsonify({"ok": False, "message": "Укажи имя инвестора"})

    old_name = car.investor_name or ""
    car.owner_type = "investor"
    car.investor_name = new_name
    car.investor_percent = percent

    # Перекидываем все инвесторские записи этой машины на правильного инвестора.
    for model in (InvestorInvestment, InvestorPayout, InvestorSettlement):
        for row in session.query(model).all():
            if normalize_code(getattr(row, "car_code", "")) == normalize_code(code):
                row.investor_name = new_name

    session.commit()
    session.close()
    return jsonify({"ok": True, "message": f"Машина {code}: инвестор изменен с '{old_name}' на '{new_name}', процент {percent}%"})


@bp.route("/api/rebuild-calculations", methods=["POST", "GET"])
def api_rebuild_calculations():
    """Полностью пересобирает расчетные таблицы из истории операций.

    Это нужно после ручного удаления ошибочных строк: удаляем старые производные
    данные и заново строим Income/Expense/Investor... по Operation.raw_message.
    """
    session = Session()

    # 1. Удаляем все производные расчеты. Сами Operation и Car не трогаем.
    for model in (Income, Expense, Part, CarInvestment, InvestorInvestment, InvestorPayout, Mileage, Downtime, InvestorSettlement):
        for row in session.query(model).all():
            session.delete(row)
    session.flush()

    rebuilt = 0
    skipped = 0

    # 2. Заново собираем производные таблицы из операций.
    for op in session.query(Operation).order_by(Operation.id).all():
        first_code = normalize_code(op.car_code)
        for part in split_message_parts(op.raw_message or ""):
            parsed = parse_message(part)
            if parsed.get("car_code"):
                first_code = parsed.get("car_code")
            elif first_code:
                parsed["car_code"] = first_code

            car = find_car(session, parsed.get("car_code"))
            if not car:
                skipped += 1
                continue

            # Если старый парсер не понял raw_message, но сама операция уже имеет тип,
            # восстанавливаем зависимости по сохраненному op.type/op.amount.
            if parsed.get("type") == "unknown" and op.type in ("income", "expense", "repair", "service", "car_investment", "investor_investment", "investor_payout", "downtime", "downtime_end"):
                parsed["type"] = op.type
                parsed["category"] = op.category or parsed.get("category") or ""
                parsed["description"] = op.description or parsed.get("description") or ""
                parsed["total"] = op.amount or parsed.get("total") or 0
                if op.type == "income":
                    parsed["income"] = op.amount or 0

            if parsed.get("type") == "unknown":
                skipped += 1
                continue

            create_dependencies_from_parsed(session, op, car, parsed)
            rebuilt += 1

    session.commit()
    session.close()
    return jsonify({"ok": True, "message": f"Пересчет выполнен. Восстановлено записей: {rebuilt}. Пропущено: {skipped}."})

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
