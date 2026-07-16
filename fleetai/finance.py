from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

from sqlalchemy import func

from .models import (
    Income,
    Expense,
    CarInvestment,
    InvestorPayout,
    InvestorInvestment,
    Downtime,
    SettlementPeriod,
    Operation,
    InvestorSettlement,
)
from .utils import normalize_code


INVESTOR_ONLY_TYPES = {
    "investor_only",
    "investor",
    "investor-only",
    "только инвестор",
    "допрасход",
    "доп расход",
    "доп расходы",
}

PARK_ONLY_TYPES = {
    "park_only",
    "park",
    "owner_only",
    "только парк",
}


def _same_car(row, car_code):
    return normalize_code(getattr(row, "car_code", "")) == normalize_code(car_code)


def _expense_type(session, row):
    """
    Возвращает тип расхода.

    Старые операции investor_expense_split принудительно считаются
    допрасходом инвестора, даже если share_type раньше сохранился неверно.
    """
    if getattr(row, "operation_id", None):
        operation = (
            session.query(Operation)
            .filter_by(id=row.operation_id)
            .first()
        )
        if operation and operation.type == "investor_expense_split":
            return "investor_only"

    value = (getattr(row, "share_type", None) or "shared").strip().lower()

    if value in INVESTOR_ONLY_TYPES:
        return "investor_only"

    if value in PARK_ONLY_TYPES:
        return "park_only"

    return "shared"


def _split_expenses(session, car_code, start=None, end=None):
    shared = 0
    investor_only = 0
    park_only = 0

    for row in session.query(Expense).all():
        if not _same_car(row, car_code):
            continue

        if start is not None and end is not None:
            if not row.date or not (start <= row.date < end):
                continue

        amount = row.amount or 0
        expense_type = _expense_type(session, row)

        if expense_type == "investor_only":
            investor_only += amount
        elif expense_type == "park_only":
            park_only += amount
        else:
            shared += amount

    return shared, investor_only, park_only


def car_finance(session, code):
    code = normalize_code(code)

    income = sum(
        (row.amount or 0)
        for row in session.query(Income).all()
        if _same_car(row, code)
    )

    expenses = sum(
        (row.amount or 0)
        for row in session.query(Expense).all()
        if _same_car(row, code)
    )

    car_investment_operation_ids = set()
    investments = 0

    for row in session.query(CarInvestment).all():
        if _same_car(row, code):
            investments += row.amount or 0
            if row.operation_id:
                car_investment_operation_ids.add(row.operation_id)

    # Старые записи могли остаться только в operations.
    for operation in session.query(Operation).all():
        if (
            _same_car(operation, code)
            and operation.type == "car_investment"
            and operation.id not in car_investment_operation_ids
        ):
            investments += operation.amount or 0

    payouts = sum(
        (row.amount or 0)
        for row in session.query(InvestorPayout).all()
        if _same_car(row, code)
    )

    investor_invested = sum(
        (row.amount or 0)
        for row in session.query(InvestorInvestment).all()
        if _same_car(row, code)
    )

    downtime_days = 0

    for row in session.query(Downtime).all():
        if not _same_car(row, code):
            continue

        if row.active and row.start_date:
            downtime_days += max(
                (moscow_now().date() - row.start_date.date()).days,
                1,
            )
        else:
            downtime_days += row.days or 0

    return (
        income,
        expenses,
        investments,
        payouts,
        investor_invested,
        downtime_days,
    )


def investor_balance_for_car(session, car):
    """
    Накопительный расчёт инвестора.

    shared:
        вычитается из дохода до разделения прибыли.

    investor_only:
        вычитается только из доли инвестора.

    park_only:
        вычитается только из доли парка.

    Непогашенный долг инвестора автоматически переносится,
    потому что расчёт выполняется по всей истории машины.
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
            "investor_only_expenses": 0,
            "park_only_expenses": 0,
            "park_share_total": 0,
        }

    car_code = normalize_code(car.code)
    percent = car.investor_percent or 0

    income = sum(
        (row.amount or 0)
        for row in session.query(Income).all()
        if _same_car(row, car_code)
    )

    payouts = sum(
        (row.amount or 0)
        for row in session.query(InvestorPayout).all()
        if _same_car(row, car_code)
    )

    shared_expenses, investor_only_expenses, park_only_expenses = (
        _split_expenses(session, car_code)
    )

    # Явные взаиморасчёты содержат сумму допрасхода и оплату инвестора.
    settlement_expenses = 0
    settlement_investor_paid = 0
    park_debt_to_investor = 0
    settlement_operation_ids = set()

    for row in session.query(InvestorSettlement).all():
        if not _same_car(row, car_code):
            continue

        settlement_expenses += row.total_cost or 0
        settlement_investor_paid += row.investor_paid or 0
        park_debt_to_investor += row.park_debt_to_investor or 0

        if row.operation_id:
            settlement_operation_ids.add(row.operation_id)

    # Отдельные вложения инвестора прибавляем, но не дублируем
    # оплату, уже сохранённую внутри той же операции взаиморасчёта.
    separate_investor_invested = 0

    for row in session.query(InvestorInvestment).all():
        if not _same_car(row, car_code):
            continue

        if row.operation_id and row.operation_id in settlement_operation_ids:
            continue

        separate_investor_invested += row.amount or 0

    if settlement_expenses > 0:
        extra_expenses = settlement_expenses
    else:
        extra_expenses = investor_only_expenses

    investor_extra_paid = (
        settlement_investor_paid
        + separate_investor_invested
    )

    # Обычные расходы делятся между сторонами.
    normal_profit_for_split = income - shared_expenses

    investor_share_raw = round(
        normal_profit_for_split * percent / 100
    )
    park_share_raw = normal_profit_for_split - investor_share_raw

    investor_positive_share = max(investor_share_raw, 0)
    investor_shared_loss = max(-investor_share_raw, 0)

    extra_debt = max(
        extra_expenses - investor_extra_paid,
        0,
    )

    debt_base = extra_debt + investor_shared_loss

    debt_repaid = min(
        investor_positive_share,
        debt_base,
    )

    remaining_debt = max(
        debt_base - investor_positive_share,
        0,
    )

    available_to_pay = max(
        investor_positive_share
        - debt_base
        + park_debt_to_investor
        - payouts,
        0,
    )

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
        "investor_only_expenses": investor_only_expenses,
        "park_only_expenses": park_only_expenses,
        "park_share_total": park_share_total,
    }



MOSCOW_TZ = ZoneInfo("Europe/Moscow")


def moscow_now():
    """
    Текущее московское время.

    Render обычно работает в UTC. Без этой функции в Москве уже
    может наступить 16-е число, а сервер ещё будет считать 15-е.
    """
    return datetime.now(MOSCOW_TZ).replace(tzinfo=None)


def period_bounds_for_car(car, now=None):
    """
    Расчётный период идёт с 16-го числа по 15-е включительно.

    Внутри программы период хранится как:
        [16-е 00:00, 16-е следующего месяца 00:00)

    Поэтому все операции 15-го числа входят в старый период,
    а новый период начинается 16-го числа.
    """
    now = now or moscow_now()

    closing_day = max(
        1,
        min(int(car.settlement_day or 15), 27),
    )
    start_day = closing_day + 1

    current_start = datetime(
        now.year,
        now.month,
        start_day,
    )

    if now < current_start:
        if now.month == 1:
            start = datetime(
                now.year - 1,
                12,
                start_day,
            )
        else:
            start = datetime(
                now.year,
                now.month - 1,
                start_day,
            )

        end = current_start
    else:
        start = current_start

        if now.month == 12:
            end = datetime(
                now.year + 1,
                1,
                start_day,
            )
        else:
            end = datetime(
                now.year,
                now.month + 1,
                start_day,
            )

    return start, end


def period_display_end(end):
    """
    Техническое окончание 16-го числа отображает
    как последний включённый день — 15-е число.
    """
    return end - timedelta(days=1)


def period_bounds_for_investor(cars, now=None):
    """
    Возвращает единый текущий расчётный период инвестора.

    Период всегда определяется текущей датой, а не последним
    закрытым SettlementPeriod. Благодаря этому после наступления
    расчётного дня сайт и PDF автоматически переходят на новый
    период, а старые закрытые периоды остаются только в истории.

    Если у машин инвестора случайно указаны разные расчётные дни,
    используется день первой машины. В нормальной работе у всех
    машин одного инвестора расчётный день должен совпадать.
    """
    cars = list(cars or [])

    if not cars:
        raise ValueError(
            "Нельзя определить период: у инвестора нет машин"
        )

    return period_bounds_for_car(cars[0], now=now)



def previous_period_bounds_for_car(car, now=None):
    """
    Возвращает полностью завершённый период перед текущим.

    Например, если текущий период 16.07–15.08,
    предыдущий будет 16.06–15.07.
    """
    current_start, _current_end = period_bounds_for_car(
        car,
        now=now,
    )

    day = current_start.day

    if current_start.month == 1:
        previous_start = datetime(
            current_start.year - 1,
            12,
            day,
        )
    else:
        previous_start = datetime(
            current_start.year,
            current_start.month - 1,
            day,
        )

    return previous_start, current_start


def save_period_snapshot(session, car, start, end, auto=False):
    """
    Сохраняет снимок выбранного расчётного периода.

    Повторно один и тот же период не создаётся.
    """
    exists = (
        session.query(SettlementPeriod)
        .filter(
            func.trim(SettlementPeriod.car_code)
            == normalize_code(car.code),
            SettlementPeriod.start_date == start,
            SettlementPeriod.end_date == end,
        )
        .first()
    )

    if exists:
        return exists, False

    calc = calculate_period_for_car(
        session,
        car,
        start,
        end,
    )

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
        comment=(
            f"{'Автоматически сохранённый' if auto else 'Расчётный'} "
            f"период {start.strftime('%d.%m.%Y')} - "
            f"{period_display_end(end).strftime('%d.%m.%Y')}"
        ),
    )

    session.add(period)

    session.add(
        Operation(
            car_code=car.code,
            type="settlement_period",
            category="Расчётный период",
            description=period.comment,
            amount=calc["profit"],
            raw_message=(
                f"{car.code} "
                f"{'автоматически сохранён' if auto else 'закрыт'} "
                f"расчётный период"
            ),
        )
    )

    session.commit()
    return period, True


def ensure_previous_period_saved(session, car, now=None):
    """
    При наступлении нового периода автоматически сохраняет предыдущий.

    Новый текущий период остаётся открытым и начинает считать только
    новые доходы и расходы. Старый период появляется в истории.
    """
    start, end = previous_period_bounds_for_car(
        car,
        now=now,
    )

    return save_period_snapshot(
        session,
        car,
        start,
        end,
        auto=True,
    )


def downtime_days_by_period(session, car_code, start, end):
    total = 0

    for row in session.query(Downtime).all():
        if not _same_car(row, car_code):
            continue

        downtime_start = row.start_date or start
        downtime_end = row.end_date or moscow_now()

        if row.active:
            downtime_end = moscow_now()

        overlap_start = max(downtime_start, start)
        overlap_end = min(downtime_end, end)

        if overlap_end > overlap_start:
            total += max(
                (overlap_end.date() - overlap_start.date()).days,
                1,
            )

    return total


def _previous_period_debt(session, car_code, before_date):
    previous = (
        session.query(SettlementPeriod)
        .filter(
            func.trim(SettlementPeriod.car_code)
            == normalize_code(car_code),
            SettlementPeriod.end_date <= before_date,
        )
        .order_by(SettlementPeriod.end_date.desc())
        .first()
    )

    if not previous:
        return 0

    investor_amount = previous.investor_amount or 0
    return abs(investor_amount) if investor_amount < 0 else 0


def calculate_period_for_car(session, car, start, end):
    """
    Прозрачный расчёт строго за выбранный период.

    Логика:
    1. Обычные расходы уменьшают прибыль до разделения.
    2. Из прибыли до разделения рассчитывается процент инвестора.
    3. Допрасходы инвестора и старый долг уменьшаются на деньги,
       которые инвестор внёс в этом периоде.
    4. Оставшийся долг погашается начисленной долей инвестора.
    5. Реальные выплаты инвестору за период вычитаются отдельно.

    Благодаря этому в отчёте видно каждую причину разницы между
    «начислено инвестору» и «осталось выплатить».
    """
    car_code = normalize_code(car.code)

    income = sum(
        (row.amount or 0)
        for row in session.query(Income).all()
        if (
            _same_car(row, car_code)
            and row.date
            and start <= row.date < end
        )
    )

    shared_expenses, investor_only_expenses, park_only_expenses = (
        _split_expenses(session, car_code, start, end)
    )

    investments = sum(
        (row.amount or 0)
        for row in session.query(CarInvestment).all()
        if (
            _same_car(row, car_code)
            and row.date
            and start <= row.date < end
        )
    )

    investor_percent = car.investor_percent or 0
    profit_for_split = income - shared_expenses

    if car.owner_type == "investor":
        investor_share_raw = round(
            profit_for_split * investor_percent / 100
        )
        owner_share_raw = profit_for_split - investor_share_raw
    else:
        investor_share_raw = 0
        owner_share_raw = profit_for_split

    accrued_to_investor = max(investor_share_raw, 0)
    investor_shared_loss = max(-investor_share_raw, 0)

    previous_debt = (
        _previous_period_debt(session, car.code, start)
        if car.owner_type == "investor"
        else 0
    )

    # Явные взаиморасчёты за период.
    settlement_operation_ids = set()
    settlement_investor_paid = 0
    park_debt_to_investor = 0

    for row in session.query(InvestorSettlement).all():
        if not _same_car(row, car_code):
            continue
        if not row.date or not (start <= row.date < end):
            continue

        settlement_investor_paid += row.investor_paid or 0
        park_debt_to_investor += row.park_debt_to_investor or 0

        if row.operation_id:
            settlement_operation_ids.add(row.operation_id)

    # Отдельные внесения инвестора за период, без двойного учёта
    # суммы, уже записанной внутри InvestorSettlement.
    separate_investor_paid = 0

    for row in session.query(InvestorInvestment).all():
        if not _same_car(row, car_code):
            continue
        if not row.date or not (start <= row.date < end):
            continue
        if row.operation_id and row.operation_id in settlement_operation_ids:
            continue

        separate_investor_paid += row.amount or 0

    investor_paid_in_period = (
        settlement_investor_paid
        + separate_investor_paid
    )

    payouts_in_period = sum(
        (row.amount or 0)
        for row in session.query(InvestorPayout).all()
        if (
            _same_car(row, car_code)
            and row.date
            and start <= row.date < end
        )
    )

    # Общая обязанность инвестора до учёта его внесений.
    debt_before_payments = (
        previous_debt
        + investor_only_expenses
        + investor_shared_loss
    )

    # Внесённые инвестором деньги сначала уменьшают его долг.
    debt_after_investor_payments = max(
        debt_before_payments - investor_paid_in_period,
        0,
    )

    investor_overpayment = max(
        investor_paid_in_period - debt_before_payments,
        0,
    )

    # Затем оставшийся долг погашается начисленной долей инвестора.
    debt_repaid_by_profit = min(
        accrued_to_investor,
        debt_after_investor_payments,
    )

    remaining_debt = max(
        debt_after_investor_payments - accrued_to_investor,
        0,
    )

    available_before_payouts = (
        max(
            accrued_to_investor - debt_after_investor_payments,
            0,
        )
        + investor_overpayment
        + park_debt_to_investor
    )

    available_to_pay = max(
        available_before_payouts - payouts_in_period,
        0,
    )

    investor_amount = (
        -remaining_debt
        if remaining_debt > 0
        else available_to_pay
    )

    owner_amount = (
        owner_share_raw
        - park_only_expenses
        + debt_repaid_by_profit
    )

    total_expenses = (
        shared_expenses
        + investor_only_expenses
        + park_only_expenses
    )

    profit = income - total_expenses
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
        "profit": profit,
        "profit_for_split": profit_for_split,
        "normal_profit_for_split": profit_for_split,

        "investor_name": car.investor_name or "",
        "investor_percent": investor_percent,
        "accrued_to_investor": accrued_to_investor,
        "investor_share_total": accrued_to_investor,

        "previous_investor_debt": previous_debt,
        "investor_shared_loss": investor_shared_loss,
        "debt_before_payments": debt_before_payments,
        "investor_paid_in_period": investor_paid_in_period,
        "investor_overpayment": investor_overpayment,
        "debt_after_investor_payments": debt_after_investor_payments,
        "debt_repaid_by_profit": debt_repaid_by_profit,
        "investor_debt_to_park": remaining_debt,

        "park_debt_to_investor": park_debt_to_investor,
        "payouts_in_period": payouts_in_period,
        "available_before_payouts": available_before_payouts,
        "available_to_pay": available_to_pay,

        "investor_amount": investor_amount,
        "owner_amount": owner_amount,
        "downtime_days": downtime_days,
    }



def current_period_investor_balance_for_car(session, car, now=None):
    """
    Баланс инвестора только за текущий период 16-е — 15-е.

    Нужен для сайта: после наступления нового периода старые доходы
    и расходы больше не остаются в текущих карточках, а сохраняются
    в истории SettlementPeriod.
    """
    start, end = period_bounds_for_car(car, now=now)
    calc = calculate_period_for_car(
        session,
        car,
        start,
        end,
    )

    return {
        "period_start": start,
        "period_end": end,
        "investor_debt_to_park": calc["investor_debt_to_park"],
        "park_debt_to_investor": calc["park_debt_to_investor"],
        "investor_share_total": calc["accrued_to_investor"],
        "paid_to_investor": calc["payouts_in_period"],
        "debt_repaid_by_profit": calc["debt_repaid_by_profit"],
        "available_to_pay": calc["available_to_pay"],
        "normal_profit_for_split": calc["profit_for_split"],
        "debt_base": calc["debt_before_payments"],
        "investor_extra_paid": calc["investor_paid_in_period"],
        "extra_expenses": calc["investor_only_expenses"],
        "shared_expenses": calc["shared_expenses"],
        "investor_only_expenses": calc["investor_only_expenses"],
        "park_only_expenses": calc["park_only_expenses"],
        "park_share_total": calc["owner_amount"],
        "income": calc["income"],
        "expenses": calc["expenses"],
    }


def close_period(session, car):
    start, end = period_bounds_for_car(car)

    period, created = save_period_snapshot(
        session,
        car,
        start,
        end,
        auto=False,
    )

    if not created:
        return None, "Этот расчётный период уже сохранён"

    return period, "Расчётный период сохранён"
