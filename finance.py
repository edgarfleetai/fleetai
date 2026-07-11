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

def previous_investor_debt(session, car_code, before_date):
    """
    Получает долг инвестора, перенесённый из последнего
    закрытого расчётного периода.

    Отрицательный investor_amount означает, что инвестор
    должен парку.
    """

    last_period = (
        session.query(SettlementPeriod)
        .filter(
            func.trim(SettlementPeriod.car_code)
            == normalize_code(car_code),
            SettlementPeriod.end_date <= before_date,
        )
        .order_by(SettlementPeriod.end_date.desc())
        .first()
    )

    if not last_period:
        return 0

    investor_amount = last_period.investor_amount or 0

    if investor_amount < 0:
        return abs(investor_amount)

    return 0

def calculate_period_for_car(session, car, start, end):
    car_code = normalize_code(car.code)

    income = 0

    for row in session.query(Income).all():
        if (
            normalize_code(row.car_code) == car_code
            and row.date
            and start <= row.date < end
        ):
            income += row.amount or 0

    shared_expenses = 0
    investor_only_expenses = 0
    park_only_expenses = 0

    for row in session.query(Expense).all():
        if (
            normalize_code(row.car_code) != car_code
            or not row.date
            or not (start <= row.date < end)
        ):
            continue

        amount = row.amount or 0
        expense_type = (row.share_type or "shared").strip().lower()

        if expense_type in {
            "investor_only",
            "investor",
            "investor-only",
            "только инвестор",
            "допрасход",
            "доп расходы",
        }:
            investor_only_expenses += amount

        elif expense_type in {
            "park_only",
            "park",
            "owner_only",
            "только парк",
        }:
            park_only_expenses += amount

        else:
            shared_expenses += amount

    investments = 0

    for row in session.query(CarInvestment).all():
        if (
            normalize_code(row.car_code) == car_code
            and row.date
            and start <= row.date < end
        ):
            investments += row.amount or 0

    investor_percent = car.investor_percent or 0

    # Обычные расходы сначала вычитаются из общего дохода.
    shared_profit = income - shared_expenses

    if car.owner_type == "investor":
        investor_share_before_expenses = round(
            shared_profit * investor_percent / 100
        )

        owner_share_before_expenses = (
            shared_profit - investor_share_before_expenses
        )
    else:
        investor_share_before_expenses = 0
        owner_share_before_expenses = shared_profit

    previous_debt = 0

    if car.owner_type == "investor":
        previous_debt = previous_investor_debt(
            session,
            car.code,
            start,
        )

    # Всё, что должен покрыть инвестор:
    # старый долг + новые расходы только инвестора.
    total_investor_debt = (
        previous_debt
        + investor_only_expenses
    )

    # Если доля инвестора отрицательная из-за общих расходов,
    # эта сумма тоже становится его долгом.
    negative_investor_share = max(
        -investor_share_before_expenses,
        0,
    )

    available_investor_share = max(
        investor_share_before_expenses,
        0,
    )

    # Сколько долга удалось закрыть из текущей доли инвестора.
    debt_repaid = min(
        available_investor_share,
        total_investor_debt,
    )

    investor_payout = max(
        available_investor_share
        - total_investor_debt,
        0,
    )

    investor_debt_to_park = (
        max(
            total_investor_debt
            - available_investor_share,
            0,
        )
        + negative_investor_share
    )

    # Если остался долг, сохраняем investor_amount отрицательным.
    # Так следующий расчётный период автоматически его увидит.
    if investor_debt_to_park > 0:
        investor_amount = -investor_debt_to_park
    else:
        investor_amount = investor_payout

    # Парк получает свою долю, минус свои расходы,
    # плюс сумму долга, которую удалось удержать из доли инвестора.
    owner_amount = (
        owner_share_before_expenses
        - park_only_expenses
        + debt_repaid
    )

    total_expenses = (
        shared_expenses
        + investor_only_expenses
        + park_only_expenses
    )

    total_profit = income - total_expenses

    downtime_days = downtime_days_by_period(
        session,
        car.code,
        start,
        end,
    )

    return {
        "income": income,
        "expenses": total_expenses,
        "shared_expenses": shared_expenses,
        "investor_only_expenses": investor_only_expenses,
        "park_only_expenses": park_only_expenses,
        "investments": investments,
        "profit": total_profit,

        "investor_name": car.investor_name or "",
        "investor_percent": investor_percent,

        "investor_share_before_expenses":
            investor_share_before_expenses,

        "owner_share_before_expenses":
            owner_share_before_expenses,

        "previous_investor_debt": previous_debt,
        "debt_repaid": debt_repaid,
        "investor_debt_to_park": investor_debt_to_park,

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
