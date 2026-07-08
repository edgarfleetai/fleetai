from datetime import datetime
from sqlalchemy import func
from models import Income, Expense, CarInvestment, InvestorPayout, InvestorInvestment, Downtime, SettlementPeriod, Operation
from utils import normalize_code


def car_finance(session, code):
    code = normalize_code(code)

    income = 0
    for row in session.query(Income).all():
        if normalize_code(row.car_code) == code:
            income += row.amount or 0

    expenses = 0
    for row in session.query(Expense).all():
        if normalize_code(row.car_code) == code:
            expenses += row.amount or 0

    investments = 0
    for row in session.query(CarInvestment).all():
        if normalize_code(row.car_code) == code:
            investments += row.amount or 0

    payouts = 0
    for row in session.query(InvestorPayout).all():
        if normalize_code(row.car_code) == code:
            payouts += row.amount or 0

    investor_invested = 0
    for row in session.query(InvestorInvestment).all():
        if normalize_code(row.car_code) == code:
            investor_invested += row.amount or 0

    downtime_days = 0
    for row in session.query(Downtime).all():
        if normalize_code(row.car_code) == code:
            if (row.active or 0) and row.start_date:
                downtime_days += max((datetime.now().date() - row.start_date.date()).days, 1)
            else:
                downtime_days += row.days or 0

    return income, expenses, investments, payouts, investor_invested, downtime_days


def period_bounds_for_car(car, now=None):
    now = now or datetime.now()
    day = max(1, min(int(car.settlement_day or 15), 28))
    current_start = datetime(now.year, now.month, day)

    if now < current_start:
        if now.month == 1:
            start = datetime(now.year - 1, 12, day)
        else:
            start = datetime(now.year, now.month - 1, day)
        end = current_start
    else:
        start = current_start
        if now.month == 12:
            end = datetime(now.year + 1, 1, day)
        else:
            end = datetime(now.year, now.month + 1, day)

    return start, end


def downtime_days_by_period(session, car_code, start, end):
    total = 0
    for row in session.query(Downtime).all():
        if normalize_code(row.car_code) != normalize_code(car_code):
            continue

        ds = row.start_date or start
        de = row.end_date or datetime.now()
        if row.active:
            de = datetime.now()

        overlap_start = max(ds, start)
        overlap_end = min(de, end)

        if overlap_end > overlap_start:
            total += max((overlap_end.date() - overlap_start.date()).days, 1)

    return total


def calculate_period_for_car(session, car, start, end):
    income = 0
    for row in session.query(Income).all():
        if normalize_code(row.car_code) == normalize_code(car.code) and row.date and start <= row.date < end:
            income += row.amount or 0

    expenses = 0
    for row in session.query(Expense).all():
        if normalize_code(row.car_code) == normalize_code(car.code) and row.date and start <= row.date < end:
            expenses += row.amount or 0

    investments = 0
    for row in session.query(CarInvestment).all():
        if normalize_code(row.car_code) == normalize_code(car.code) and row.date and start <= row.date < end:
            investments += row.amount or 0

    profit = income - expenses
    investor_percent = car.investor_percent or 0
    investor_amount = round(profit * investor_percent / 100) if car.owner_type == "investor" else 0
    owner_amount = profit - investor_amount
    downtime_days = downtime_days_by_period(session, car.code, start, end)

    return {
        "income": income,
        "expenses": expenses,
        "investments": investments,
        "profit": profit,
        "investor_name": car.investor_name or "",
        "investor_percent": investor_percent,
        "investor_amount": investor_amount,
        "owner_amount": owner_amount,
        "downtime_days": downtime_days,
    }


def close_period(session, car):
    start, end = period_bounds_for_car(car)
    calc = calculate_period_for_car(session, car, start, end)

    exists = session.query(SettlementPeriod).filter(
        func.trim(SettlementPeriod.car_code) == normalize_code(car.code),
        SettlementPeriod.start_date == start,
        SettlementPeriod.end_date == end
    ).first()

    if exists:
        return None, "Этот расчетный период уже закрыт"

    period = SettlementPeriod(
        car_code=car.code,
        start_date=start,
        end_date=end,
        income=calc["income"],
        expenses=calc["expenses"],
        investments=calc["investments"],
        profit=calc["profit"],
        investor_name=calc["investor_name"],
        investor_percent=calc["investor_percent"],
        investor_amount=calc["investor_amount"],
        owner_amount=calc["owner_amount"],
        downtime_days=calc["downtime_days"],
        comment=f"Расчетный период {start.strftime('%d.%m.%Y')} - {end.strftime('%d.%m.%Y')}"
    )
    session.add(period)

    session.add(Operation(
        car_code=car.code,
        type="settlement_period",
        category="Расчетный период",
        description=period.comment,
        amount=calc["profit"],
        raw_message=f"{car.code} закрыт расчетный период"
    ))

    session.commit()
    return period, "Расчетный период закрыт"
