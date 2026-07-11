from datetime import datetime
from sqlalchemy import func
from .models import Income, Expense, CarInvestment, InvestorPayout, InvestorInvestment, Downtime, SettlementPeriod, Operation, InvestorSettlement
from .utils import normalize_code


def car_finance(session, code):
    code = normalize_code(code)

    income = sum((r.amount or 0) for r in session.query(Income).all() if normalize_code(r.car_code) == code)
    expenses = sum((r.amount or 0) for r in session.query(Expense).all() if normalize_code(r.car_code) == code)
    car_investment_operation_ids = set()
    investments = 0
    for r in session.query(CarInvestment).all():
        if normalize_code(r.car_code) == code:
            investments += r.amount or 0
            if r.operation_id:
                car_investment_operation_ids.add(r.operation_id)

    # Старые записи могли сохраниться только в operations как car_investment,
    # без строки в car_investments. Добавляем их как fallback, но не дублируем.
    for op in session.query(Operation).all():
        if normalize_code(op.car_code) == code and op.type == "car_investment" and op.id not in car_investment_operation_ids:
            investments += op.amount or 0
    payouts = sum((r.amount or 0) for r in session.query(InvestorPayout).all() if normalize_code(r.car_code) == code)
    investor_invested = sum((r.amount or 0) for r in session.query(InvestorInvestment).all() if normalize_code(r.car_code) == code)

    downtime_days = 0
    for row in session.query(Downtime).all():
        if normalize_code(row.car_code) == code:
            if row.active and row.start_date:
                downtime_days += max((datetime.now().date() - row.start_date.date()).days, 1)
            else:
                downtime_days += row.days or 0

    return income, expenses, investments, payouts, investor_invested, downtime_days


def investor_balance_for_car(session, car):
    """
    Расчёт инвестора по машине.

    shared:
        обычный расход;
        сначала вычитается из дохода;
        остаток делится между инвестором и парком.

    investor_only:
        допрасход;
        вычитается только из доли инвестора.

    park_only:
        вычитается только из доли парка.

    Расчёт ведётся накопительно, поэтому долг инвестора
    автоматически переносится на следующие доходы.
    """

    if car.owner_type != "investor":
        return {
            "investor_debt_to_park": 0,
            "park_debt_to_investor": 0,
            "investor_share_total": 0,
            "paid_to_investor": 0,
            "debt_repaid_by_profit": 0,
            "available_to_pay": 0,
            "normal_profit_for_split": 0,
            "debt_base": 0,
            "investor_extra_paid": 0,
            "extra_expenses": 0,
            "shared_expenses": 0,
            "park_only_expenses": 0,
            "park_share_total": 0,
        }

    car_code = normalize_code(car.code)
    percent = car.investor_percent or 0

    income = 0
    payouts = 0
    investor_invested = 0

    shared_expenses = 0
    investor_only_expenses = 0
    park_only_expenses = 0

    # Доход машины.
    for row in session.query(Income).all():
        if normalize_code(row.car_code) == car_code:
            income += row.amount or 0

    # Выплаты инвестору.
    for row in session.query(InvestorPayout).all():
        if normalize_code(row.car_code) == car_code:
            payouts += row.amount or 0

    # Деньги, которые инвестор дополнительно внес на расходы.
    for row in session.query(InvestorInvestment).all():
        if normalize_code(row.car_code) == car_code:
            investor_invested += row.amount or 0

    # Разделяем расходы по типам.
        shared_expenses = 0
    investor_only_expenses = 0
    park_only_expenses = 0

    for row in session.query(Expense).all():
        if normalize_code(row.car_code) != car_code:
            continue

        amount = row.amount or 0

        operation = None

        if row.operation_id:
            operation = (
                session.query(Operation)
                .filter_by(id=row.operation_id)
                .first()
            )

        # Все операции "Доп. расходы / взаиморасчёт"
        # всегда считаем только расходом инвестора,
        # даже если в старой записи share_type сохранился неправильно.
        if operation and operation.type == "investor_expense_split":
            investor_only_expenses += amount
            continue

        expense_type = (
            row.share_type or "shared"
        ).strip().lower()

        if expense_type in {
            "investor_only",
            "investor",
            "investor-only",
            "только инвестор",
            "допрасход",
            "доп расход",
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
            
    # Явные взаиморасчёты:
    # "636 доп расходы 41700 инвестор оплатил 25000"
    settlement_expenses = 0
    settlement_investor_paid = 0
    park_debt_to_investor = 0

    for row in session.query(InvestorSettlement).all():
        if normalize_code(row.car_code) != car_code:
            continue

        settlement_expenses += row.total_cost or 0
        settlement_investor_paid += row.investor_paid or 0
        park_debt_to_investor += row.park_debt_to_investor or 0

    # Если есть явный взаиморасчёт, используем его как допрасход.
    # Это защищает от двойного учёта одной и той же операции.
        if settlement_expenses > 0:
        # InvestorSettlement уже содержит сумму допрасхода.
        # Не прибавляем investor_only_expenses второй раз.
        extra_expenses = settlement_expenses

        # Учитываем и оплату внутри одной команды,
        # и отдельные вложения инвестора.
        investor_extra_paid = max(
            settlement_investor_paid,
            investor_invested,
        )
    else:
        extra_expenses = investor_only_expenses
        investor_extra_paid = investor_invested

    # Обычные расходы вычитаются ДО разделения прибыли.
    normal_profit_for_split = (
        income
        - shared_expenses
    )

    # Доля инвестора может быть отрицательной,
    # если обычные расходы оказались больше дохода.
    investor_share_raw = round(
        normal_profit_for_split
        * percent
        / 100
    )

    park_share_raw = (
        normal_profit_for_split
        - investor_share_raw
    )

    # Если по обычным расходам инвестор получил минус,
    # его часть убытка тоже становится долгом.
    investor_shared_loss = max(
        -investor_share_raw,
        0,
    )

    investor_positive_share = max(
        investor_share_raw,
        0,
    )

    # Допрасход инвестора минус деньги,
    # которые он уже сам внёс.
    extra_debt = max(
        extra_expenses
        - investor_extra_paid,
        0,
    )

    # Общая задолженность инвестора.
    debt_base = (
        extra_debt
        + investor_shared_loss
    )

    # Сколько долга погашено из накопленной доли инвестора.
    debt_repaid = min(
        investor_positive_share,
        debt_base,
    )

    remaining_debt = max(
        debt_base
        - investor_positive_share,
        0,
    )

    # Остаток доли после закрытия долга и прежних выплат.
    available_to_pay = max(
        investor_positive_share
        - debt_base
        + park_debt_to_investor
        - payouts,
        0,
    )

    # Доля парка после обычного разделения,
    # затем отдельно вычитаются расходы только парка.
    park_share_total = (
        park_share_raw
        - park_only_expenses
        + debt_repaid
    )

    return {
        "investor_debt_to_park": remaining_debt,
        "park_debt_to_investor": park_debt_to_investor,

        "investor_share_total": investor_positive_share,
        "paid_to_investor": payouts,
        "debt_repaid_by_profit": debt_repaid,
        "available_to_pay": available_to_pay,

        "normal_profit_for_split": normal_profit_for_split,

        "debt_base": debt_base,
        "investor_extra_paid": investor_extra_paid,

        "extra_expenses": extra_expenses,
        "shared_expenses": shared_expenses,
        "park_only_expenses": park_only_expenses,

        "park_share_total": park_share_total,
    }

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
    income = sum((r.amount or 0) for r in session.query(Income).all() if normalize_code(r.car_code) == normalize_code(car.code) and r.date and start <= r.date < end)
    expenses = sum((r.amount or 0) for r in session.query(Expense).all() if normalize_code(r.car_code) == normalize_code(car.code) and r.date and start <= r.date < end)
    investments = sum((r.amount or 0) for r in session.query(CarInvestment).all() if normalize_code(r.car_code) == normalize_code(car.code) and r.date and start <= r.date < end)

    profit = income - expenses
    investor_percent = car.investor_percent or 0
    investor_amount = round(profit * investor_percent / 100) if car.owner_type == "investor" else 0
    owner_amount = profit - investor_amount
    downtime_days = downtime_days_by_period(session, car.code, start, end)

    return {
        "income": income, "expenses": expenses, "investments": investments,
        "profit": profit, "investor_name": car.investor_name or "",
        "investor_percent": investor_percent, "investor_amount": investor_amount,
        "owner_amount": owner_amount, "downtime_days": downtime_days,
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
        car_code=car.code, start_date=start, end_date=end,
        income=calc["income"], expenses=calc["expenses"], investments=calc["investments"],
        profit=calc["profit"], investor_name=calc["investor_name"],
        investor_percent=calc["investor_percent"], investor_amount=calc["investor_amount"],
        owner_amount=calc["owner_amount"], downtime_days=calc["downtime_days"],
        comment=f"Расчетный период {start.strftime('%d.%m.%Y')} - {end.strftime('%d.%m.%Y')}"
    )
    session.add(period)
    session.add(Operation(
        car_code=car.code, type="settlement_period", category="Расчетный период",
        description=period.comment, amount=calc["profit"],
        raw_message=f"{car.code} закрыт расчетный период"
    ))
    session.commit()
    return period, "Расчетный период закрыт"
