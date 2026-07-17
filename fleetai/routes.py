import os
import io
import re
import requests

from pathlib import Path
from urllib.parse import unquote

from datetime import datetime, date, timedelta

from flask import Blueprint, request, jsonify, render_template_string, send_file
from sqlalchemy import func

from reportlab.lib import colors
from reportlab.lib.enums import TA_CENTER
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib.units import mm
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.platypus import (
    SimpleDocTemplate,
    Paragraph,
    Spacer,
    Table,
    TableStyle,
)

from .db import Session
from .models import (
    Car,
    Operation,
    Income,
    Expense,
    Part,
    CarInvestment,
    InvestorInvestment,
    InvestorPayout,
    Mileage,
    Downtime,
    SettlementPeriod,
    InvestorSettlement,
    WarehouseItem,
    WarehouseMovement,
)
from .utils import only_int, normalize_code, find_car
from .parser import parse_message
from .finance import (
    car_finance,
    investor_balance_for_car,
    current_period_investor_balance_for_car,
    moscow_now,
    period_bounds_for_car,
    period_bounds_for_investor,
    period_display_end,
    calculate_period_for_car,
    ensure_previous_period_saved,
    close_period,
)
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


def send_telegram_document(file_bytes, filename, caption=""):
    token = os.getenv("TELEGRAM_BOT_TOKEN")
    chat_id = os.getenv("TELEGRAM_CHAT_ID")

    if not token or not chat_id:
        print("Telegram не настроен: нет токена или chat id")
        return False

    url = f"https://api.telegram.org/bot{token}/sendDocument"

    try:
        response = requests.post(
            url,
            data={
                "chat_id": chat_id,
                "caption": caption,
                "parse_mode": "HTML",
            },
            files={
                "document": (
                    filename,
                    file_bytes,
                    "application/pdf",
                )
            },
            timeout=60,
        )
        response.raise_for_status()
        return True

    except requests.RequestException as error:
        print(f"Ошибка отправки PDF в Telegram: {error}")
        return False


def register_pdf_font():
    font_paths = [
        "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
        "/usr/share/fonts/dejavu/DejaVuSans.ttf",
        "/usr/local/share/fonts/DejaVuSans.ttf",
    ]

    if "FleetAIFont" in pdfmetrics.getRegisteredFontNames():
        return "FleetAIFont"

    for font_path in font_paths:
        if Path(font_path).exists():
            pdfmetrics.registerFont(
                TTFont("FleetAIFont", font_path)
            )
            return "FleetAIFont"

    raise RuntimeError(
        "Не найден системный шрифт DejaVuSans для русского PDF"
    )


def money(value):
    return f"{int(value or 0):,} ₽".replace(",", " ")


def safe_filename(value):
    cleaned = re.sub(r"[^0-9A-Za-zА-Яа-яЁё_-]+", "_", value or "")
    return cleaned.strip("_") or "investor"


def build_investor_report_pdf(
    investor_name,
    period_start,
    period_end,
    car_rows,
):
    """
    Формирует простой отчёт инвестора.

    Главная логика:
    1. Машины заработали.
    2. Вычитаются все обычные расходы всех машин, включая убыточные.
    3. От остатка считается доля инвестора.
    4. Из доли инвестора удерживаются непокрытые допрасходы и долги.
    5. Показывается одна понятная сумма к выплате.
    """
    font_name = register_pdf_font()
    buffer = io.BytesIO()

    document = SimpleDocTemplate(
        buffer,
        pagesize=A4,
        rightMargin=15 * mm,
        leftMargin=15 * mm,
        topMargin=15 * mm,
        bottomMargin=15 * mm,
        title=f"Отчёт инвестора {investor_name}",
        author="FleetAI",
    )

    styles = getSampleStyleSheet()

    title_style = ParagraphStyle(
        "InvestorReportTitle",
        parent=styles["Title"],
        fontName=font_name,
        fontSize=18,
        leading=23,
        alignment=TA_CENTER,
        spaceAfter=8,
    )

    period_style = ParagraphStyle(
        "InvestorReportPeriod",
        parent=styles["BodyText"],
        fontName=font_name,
        fontSize=10,
        leading=14,
        alignment=TA_CENTER,
        textColor=colors.HexColor("#5F5B55"),
        spaceAfter=14,
    )

    heading_style = ParagraphStyle(
        "InvestorReportHeading",
        parent=styles["Heading2"],
        fontName=font_name,
        fontSize=13,
        leading=17,
        spaceBefore=12,
        spaceAfter=7,
    )

    normal_style = ParagraphStyle(
        "InvestorReportNormal",
        parent=styles["BodyText"],
        fontName=font_name,
        fontSize=9,
        leading=13,
    )

    small_style = ParagraphStyle(
        "InvestorReportSmall",
        parent=normal_style,
        fontSize=8,
        leading=11,
        textColor=colors.HexColor("#5F5B55"),
    )

    payout_style = ParagraphStyle(
        "InvestorPayout",
        parent=styles["Heading1"],
        fontName=font_name,
        fontSize=17,
        leading=21,
        alignment=TA_CENTER,
        textColor=colors.HexColor("#234B35"),
        spaceBefore=8,
        spaceAfter=8,
    )

    total_income = sum(
        int(item.get("income", 0) or 0)
        for item in car_rows
    )

    # Все обычные расходы включаются полностью.
    # Поэтому убыток одной машины уже уменьшает общий остаток.
    total_expenses = sum(
        int(item.get("shared_expenses", 0) or 0)
        for item in car_rows
    )

    remaining_after_expenses = total_income - total_expenses

    percentages = sorted({
        int(item.get("percent", 0) or 0)
        for item in car_rows
        if int(item.get("percent", 0) or 0) > 0
    })

    if len(percentages) == 1:
        investor_percent = percentages[0]
    elif car_rows:
        # Защита на случай разных процентов:
        # используем отношение суммы начислений к положительной
        # прибыли машин, но не выше 100%.
        positive_profit = sum(
            max(int(item.get("profit_for_split", 0) or 0), 0)
            for item in car_rows
        )
        accrued_sum = sum(
            int(item.get("accrued_to_investor", 0) or 0)
            for item in car_rows
        )
        investor_percent = (
            round(accrued_sum * 100 / positive_profit)
            if positive_profit > 0
            else 0
        )
        investor_percent = max(0, min(investor_percent, 100))
    else:
        investor_percent = 0

    investor_share = max(
        round(
            max(remaining_after_expenses, 0)
            * investor_percent
            / 100
        ),
        0,
    )

    previous_debt = sum(
        int(item.get("previous_investor_debt", 0) or 0)
        for item in car_rows
    )
    extra_expenses = sum(
        int(item.get("investor_only_expenses", 0) or 0)
        for item in car_rows
    )
    investor_paid = sum(
        int(item.get("investor_paid_in_period", 0) or 0)
        for item in car_rows
    )
    already_paid = sum(
        int(item.get("payouts_in_period", 0) or 0)
        for item in car_rows
    )

    uncovered_costs = max(
        previous_debt + extra_expenses - investor_paid,
        0,
    )

    withheld = min(investor_share, uncovered_costs)

    amount_to_pay = max(
        investor_share - withheld - already_paid,
        0,
    )

    remaining_debt = max(
        uncovered_costs - withheld,
        0,
    )

    if amount_to_pay == 0 and withheld > 0:
        explanation_title = "Почему выплата отсутствует"
        explanation_text = (
            "Вся доля инвестора за этот период была направлена "
            "на погашение дополнительных вложений и задолженности."
        )
    elif withheld > 0:
        explanation_title = "Почему выплата уменьшилась"
        explanation_text = (
            "Часть доли инвестора была направлена на погашение "
            "дополнительных вложений и задолженности."
        )
    else:
        explanation_title = "Удержаний нет"
        explanation_text = (
            "Доля инвестора не уменьшалась из-за дополнительных "
            "вложений или задолженности."
        )

    story = [
        Paragraph(
            f"Отчёт инвестора {investor_name}",
            title_style,
        ),
        Paragraph(
            "За период с "
            f"{period_start.strftime('%d.%m.%Y')} по "
            f"{period_display_end(period_end).strftime('%d.%m.%Y')}",
            period_style,
        ),
    ]

    main_rows = [
        [
            Paragraph("<b>Машины заработали</b>", normal_style),
            Paragraph(
                f"<b>{money(total_income)}</b>",
                normal_style,
            ),
        ],
        [
            Paragraph(
                "<b>Все расходы по машинам "
                "(включая убыточные машины)</b>",
                normal_style,
            ),
            Paragraph(
                f"<b>{money(total_expenses)}</b>",
                normal_style,
            ),
        ],
        [
            Paragraph(
                "<b>Осталось после всех расходов</b>",
                normal_style,
            ),
            Paragraph(
                f"<b>{money(remaining_after_expenses)}</b>",
                normal_style,
            ),
        ],
        [
            Paragraph(
                f"<b>Доля инвестора ({investor_percent}%)</b>",
                normal_style,
            ),
            Paragraph(
                f"<b>{money(investor_share)}</b>",
                normal_style,
            ),
        ],
        [
            Paragraph(
                "<b>Удержано на покрытие допрасходов "
                "и долгов</b>",
                normal_style,
            ),
            Paragraph(
                f"<b>{money(withheld)}</b>",
                normal_style,
            ),
        ],
    ]

    if already_paid > 0:
        main_rows.append([
            Paragraph(
                "<b>Уже выплачено в этом периоде</b>",
                normal_style,
            ),
            Paragraph(
                f"<b>{money(already_paid)}</b>",
                normal_style,
            ),
        ])

    main_table = Table(
        main_rows,
        colWidths=[120 * mm, 50 * mm],
    )
    main_table.setStyle(
        TableStyle([
            (
                "BACKGROUND",
                (0, 0),
                (-1, -1),
                colors.HexColor("#F7F6F3"),
            ),
            (
                "GRID",
                (0, 0),
                (-1, -1),
                0.5,
                colors.HexColor("#D8D4CE"),
            ),
            ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
            ("LEFTPADDING", (0, 0), (-1, -1), 9),
            ("RIGHTPADDING", (0, 0), (-1, -1), 9),
            ("TOPPADDING", (0, 0), (-1, -1), 9),
            ("BOTTOMPADDING", (0, 0), (-1, -1), 9),
        ])
    )
    story.append(main_table)
    story.append(Spacer(1, 5 * mm))

    explanation_bg = (
        colors.HexColor("#FFF4D6")
        if withheld > 0
        else colors.HexColor("#F2F1EE")
    )
    explanation_border = (
        colors.HexColor("#D7B85E")
        if withheld > 0
        else colors.HexColor("#D8D4CE")
    )

    story.append(
        Paragraph(
            explanation_title,
            heading_style,
        )
    )
    story.append(
        Paragraph(
            explanation_text,
            normal_style,
        )
    )
    story.append(Spacer(1, 2 * mm))

    explanation_rows = [
        [
            Paragraph("<b>Удержано</b>", normal_style),
            Paragraph(
                f"<b>{money(withheld)}</b>",
                normal_style,
            ),
        ],
        [
            Paragraph(
                "<b>Остаток задолженности после удержания</b>",
                normal_style,
            ),
            Paragraph(
                f"<b>{money(remaining_debt)}</b>",
                normal_style,
            ),
        ],
    ]

    explanation_table = Table(
        explanation_rows,
        colWidths=[120 * mm, 50 * mm],
    )
    explanation_table.setStyle(
        TableStyle([
            (
                "BACKGROUND",
                (0, 0),
                (-1, -1),
                explanation_bg,
            ),
            (
                "GRID",
                (0, 0),
                (-1, -1),
                0.5,
                explanation_border,
            ),
            ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
            ("LEFTPADDING", (0, 0), (-1, -1), 9),
            ("RIGHTPADDING", (0, 0), (-1, -1), 9),
            ("TOPPADDING", (0, 0), (-1, -1), 8),
            ("BOTTOMPADDING", (0, 0), (-1, -1), 8),
        ])
    )
    story.append(explanation_table)
    story.append(Spacer(1, 5 * mm))

    payout_box = Table(
        [[
            Paragraph(
                (
                    f"К выплате инвестору: {money(amount_to_pay)}"
                    if amount_to_pay > 0
                    else "К выплате инвестору: 0 ₽"
                ),
                payout_style,
            )
        ]],
        colWidths=[170 * mm],
    )
    payout_box.setStyle(
        TableStyle([
            (
                "BACKGROUND",
                (0, 0),
                (-1, -1),
                colors.HexColor("#EAF2EC"),
            ),
            (
                "BOX",
                (0, 0),
                (-1, -1),
                1,
                colors.HexColor("#9DB6A5"),
            ),
            ("LEFTPADDING", (0, 0), (-1, -1), 10),
            ("RIGHTPADDING", (0, 0), (-1, -1), 10),
            ("TOPPADDING", (0, 0), (-1, -1), 10),
            ("BOTTOMPADDING", (0, 0), (-1, -1), 10),
        ])
    )
    story.append(payout_box)

    story.append(
        Paragraph(
            "Расчёт: из общего дохода вычтены расходы всех машин. "
            "Убыточные машины уже учтены в общей сумме расходов. "
            "После этого рассчитана доля инвестора и удержаны только "
            "непокрытые допрасходы и долги.",
            small_style,
        )
    )

    story.append(Paragraph("Кратко по машинам", heading_style))

    cars_table_data = [[
        Paragraph("<b>Машина</b>", normal_style),
        Paragraph("<b>Доход</b>", normal_style),
        Paragraph("<b>Расход</b>", normal_style),
        Paragraph("<b>Итог</b>", normal_style),
        Paragraph("<b>Простой</b>", normal_style),
    ]]

    for item in car_rows:
        car_profit = (
            int(item.get("income", 0) or 0)
            - int(item.get("shared_expenses", 0) or 0)
        )

        cars_table_data.append([
            Paragraph(
                f"{item.get('code', '')} "
                f"{item.get('car_name', '')}",
                normal_style,
            ),
            Paragraph(
                money(item.get("income", 0)),
                normal_style,
            ),
            Paragraph(
                money(item.get("shared_expenses", 0)),
                normal_style,
            ),
            Paragraph(
                money(car_profit),
                normal_style,
            ),
            Paragraph(
                f"{int(item.get('downtime_days', 0) or 0)} дн.",
                normal_style,
            ),
        ])

    cars_table = Table(
        cars_table_data,
        colWidths=[
            55 * mm,
            31 * mm,
            31 * mm,
            31 * mm,
            22 * mm,
        ],
        repeatRows=1,
    )
    cars_table.setStyle(
        TableStyle([
            (
                "BACKGROUND",
                (0, 0),
                (-1, 0),
                colors.HexColor("#E9E7E2"),
            ),
            (
                "GRID",
                (0, 0),
                (-1, -1),
                0.4,
                colors.HexColor("#D1CEC8"),
            ),
            ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
            ("LEFTPADDING", (0, 0), (-1, -1), 5),
            ("RIGHTPADDING", (0, 0), (-1, -1), 5),
            ("TOPPADDING", (0, 0), (-1, -1), 6),
            ("BOTTOMPADDING", (0, 0), (-1, -1), 6),
        ])
    )
    story.append(cars_table)

    expense_rows = []

    for item in car_rows:
        for expense in item.get("expense_rows", []):
            expense_rows.append({
                "car_code": item.get("code", ""),
                **expense,
            })

    if expense_rows:
        story.append(
            Paragraph(
                "На что ушли деньги",
                heading_style,
            )
        )

        expense_table_data = [[
            Paragraph("<b>Дата</b>", small_style),
            Paragraph("<b>Машина</b>", small_style),
            Paragraph("<b>Описание</b>", small_style),
            Paragraph("<b>Сумма</b>", small_style),
        ]]

        for expense in expense_rows:
            expense_table_data.append([
                Paragraph(expense.get("date", ""), small_style),
                Paragraph(
                    str(expense.get("car_code", "")),
                    small_style,
                ),
                Paragraph(
                    expense.get("description", ""),
                    small_style,
                ),
                Paragraph(
                    money(expense.get("amount", 0)),
                    small_style,
                ),
            ])

        expense_table = Table(
            expense_table_data,
            colWidths=[
                25 * mm,
                20 * mm,
                100 * mm,
                25 * mm,
            ],
            repeatRows=1,
        )
        expense_table.setStyle(
            TableStyle([
                (
                    "BACKGROUND",
                    (0, 0),
                    (-1, 0),
                    colors.HexColor("#F0EEEA"),
                ),
                (
                    "GRID",
                    (0, 0),
                    (-1, -1),
                    0.35,
                    colors.HexColor("#D1CEC8"),
                ),
                ("VALIGN", (0, 0), (-1, -1), "TOP"),
                ("LEFTPADDING", (0, 0), (-1, -1), 5),
                ("RIGHTPADDING", (0, 0), (-1, -1), 5),
                ("TOPPADDING", (0, 0), (-1, -1), 5),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 5),
            ])
        )
        story.append(expense_table)

    document.build(story)
    return buffer.getvalue()


@bp.route("/api/test-telegram", methods=["GET"])
def test_telegram():
    success = send_telegram_message(
        "✅ <b>Fleet AI</b>\n"
        "Telegram-уведомления успешно подключены."
    )

    if success:
        return jsonify({
            "ok": True,
            "message": "Сообщение отправлено",
        })

    return jsonify({
        "ok": False,
        "message": "Сообщение не отправлено",
    }), 500



def parse_iso_date(value):
    if not value:
        return None

    try:
        return datetime.strptime(value, "%Y-%m-%d").date()
    except (TypeError, ValueError):
        return None


def driver_payment_period(car):
    """
    Возвращает расчётный период [начало, окончание).

    День окончания — день расчёта. Период длится 7 дней.
    """
    end_date = parse_iso_date(car.next_payment_date)

    if not end_date:
        end_date = date.today()

    start_date = parse_iso_date(
        getattr(car, "last_payment_date", "")
    )

    if not start_date:
        start_date = end_date - timedelta(days=7)

    if start_date >= end_date:
        start_date = end_date - timedelta(days=7)

    return start_date, end_date


def overlap_downtime_days(session, car_code, period_start, period_end):
    """
    Считает дни простоя внутри периода.

    Правило:
    - день начала простоя считается;
    - день выхода уже рабочий;
    - расчётный период считается до даты расчёта, не включая её.
    """
    downtime_dates = set()

    rows = (
        session.query(Downtime)
        .filter(
            func.trim(Downtime.car_code)
            == normalize_code(car_code)
        )
        .all()
    )

    for row in rows:
        if not row.start_date:
            continue

        downtime_start = row.start_date.date()
        downtime_end = (
            row.end_date.date()
            if row.end_date
            else period_end
        )

        overlap_start = max(period_start, downtime_start)
        overlap_end = min(period_end, downtime_end)

        current = overlap_start

        while current < overlap_end:
            downtime_dates.add(current)
            current += timedelta(days=1)

    return len(downtime_dates)


def rental_amount_for_days(car, payable_days):
    """
    Считает аренду за фактически отработанные дни.

    Приоритет:
    1. дневная ставка;
    2. старая недельная ставка, пропорционально дням.

    Для недельной ставки 13 000 ₽:
    - 7 дней = 13 000 ₽;
    - 2 дня = round(13 000 × 2 / 7).
    """
    payable_days = max(int(payable_days or 0), 0)
    daily_rent = int(getattr(car, "daily_rent", 0) or 0)
    weekly_payment = int(getattr(car, "weekly_payment", 0) or 0)

    if daily_rent > 0:
        return daily_rent * payable_days

    if weekly_payment > 0:
        return round(weekly_payment * payable_days / 7)

    return 0


def effective_daily_rent(car):
    """
    Ставка для отображения.

    Старые машины, у которых сохранена только недельная сумма,
    больше не показывают 0 ₽/сутки.
    """
    daily_rent = int(getattr(car, "daily_rent", 0) or 0)

    if daily_rent > 0:
        return daily_rent

    weekly_payment = int(getattr(car, "weekly_payment", 0) or 0)

    if weekly_payment > 0:
        return round(weekly_payment / 7)

    return 0


def calculate_rental_interval(
    session,
    car,
    period_start,
    period_end,
):
    """
    Считает один интервал [начало, окончание).

    День начала входит в расчёт, дата окончания не входит.
    """
    total_days = max((period_end - period_start).days, 0)

    downtime_days = overlap_downtime_days(
        session,
        car.code,
        period_start,
        period_end,
    )

    payable_days = max(total_days - downtime_days, 0)
    amount = rental_amount_for_days(car, payable_days)

    return {
        "period_start": period_start.isoformat(),
        "period_end": period_end.isoformat(),
        "total_days": total_days,
        "downtime_days": downtime_days,
        "payable_days": payable_days,
        "amount": amount,
    }


def calculate_driver_payment(session, car, as_of_date=None):
    """
    Текущий расчёт водителя без объединения недель.

    Возвращает:
    - каждый завершённый неоплаченный период отдельно;
    - текущий открытый период отдельно;
    - общую сумму только как справочный итог.
    """
    today = as_of_date or moscow_now().date()

    first_start = parse_iso_date(
        getattr(car, "last_payment_date", "")
    )
    first_due = parse_iso_date(
        getattr(car, "next_payment_date", "")
    )

    if not first_due:
        first_due = today + timedelta(days=7)

    if not first_start:
        first_start = first_due - timedelta(days=7)

    if first_start >= first_due:
        first_start = first_due - timedelta(days=7)

    overdue_periods = []
    cursor_start = first_start
    cursor_due = first_due
    period_number = 1

    # Каждая полностью завершённая неделя остаётся отдельной строкой.
    while cursor_due <= today:
        period = calculate_rental_interval(
            session,
            car,
            cursor_start,
            cursor_due,
        )

        overdue_periods.append({
            **period,
            "period_number": period_number,
            "status": "overdue",
            "label": (
                f"{cursor_start.strftime('%d.%m.%Y')} — "
                f"{cursor_due.strftime('%d.%m.%Y')}"
            ),
        })

        period_number += 1
        cursor_start = cursor_due
        cursor_due = cursor_due + timedelta(days=7)

    # Начисляем только полностью завершённые сутки.
    current_end = min(
        today,
        cursor_due,
    )

    if current_end < cursor_start:
        current_end = cursor_start

    current_period = calculate_rental_interval(
        session,
        car,
        cursor_start,
        current_end,
    )

    current_period = {
        **current_period,
        "scheduled_period_end": cursor_due.isoformat(),
        "status": "current",
        "label": (
            f"{cursor_start.strftime('%d.%m.%Y')} — "
            f"{cursor_due.strftime('%d.%m.%Y')}"
        ),
    }

    overdue_total = sum(
        int(period["amount"] or 0)
        for period in overdue_periods
    )
    current_amount = int(current_period["amount"] or 0)

    return {
        "daily_rent": int(getattr(car, "daily_rent", 0) or 0),
        "effective_daily_rent": effective_daily_rent(car),
        "weekly_payment": int(getattr(car, "weekly_payment", 0) or 0),
        "rate_source": (
            "daily"
            if int(getattr(car, "daily_rent", 0) or 0) > 0
            else "weekly_prorated"
        ),

        # Старые недели — отдельный список.
        "overdue_periods": overdue_periods,
        "overdue_periods_count": len(overdue_periods),
        "overdue_total": overdue_total,

        # Текущая неделя — отдельный объект.
        "current_period": current_period,
        "current_amount": current_amount,

        # Только справочный общий итог.
        "amount_due": overdue_total + current_amount,

        "next_payment_date": cursor_due.isoformat(),
        "is_overdue": bool(overdue_periods),
        "overdue_days": (
            max((today - first_due).days, 0)
            if overdue_periods
            else 0
        ),

        # Совместимость со старым интерфейсом.
        "period_start": current_period["period_start"],
        "period_end": current_period["period_end"],
        "scheduled_period_end": current_period["scheduled_period_end"],
        "total_days": current_period["total_days"],
        "downtime_days": current_period["downtime_days"],
        "payable_days": current_period["payable_days"],
        "previous_debt": overdue_total,
        "completed_unpaid_periods": len(overdue_periods),
        "completed_period_details": overdue_periods,
    }


@bp.route("/api/payment-settings", methods=["POST"])
def save_payment_settings():
    data = request.get_json(silent=True) or request.form

    car_code = normalize_code(
        data.get("car_code") or data.get("code") or ""
    )
    driver = (data.get("driver") or "").strip()
    next_payment_date = (
        data.get("next_payment_date") or ""
    ).strip()

    try:
        daily_rent = int(data.get("daily_rent") or 0)
        driver_deposit = int(data.get("driver_deposit") or 0)
        payment_weekday = int(data.get("payment_weekday") or 0)
    except (TypeError, ValueError):
        return jsonify({
            "ok": False,
            "message": "Ставка или день недели указаны неправильно",
        }), 400

    if not car_code:
        return jsonify({
            "ok": False,
            "message": "Не указан номер машины",
        }), 400

    if daily_rent < 0:
        return jsonify({
            "ok": False,
            "message": "Ставка не может быть отрицательной",
        }), 400

    if driver_deposit < 0:
        return jsonify({
            "ok": False,
            "message": "Залог не может быть отрицательным",
        }), 400

    if payment_weekday < 0 or payment_weekday > 6:
        return jsonify({
            "ok": False,
            "message": "Неправильно указан день недели",
        }), 400

    payment_date = parse_iso_date(next_payment_date)

    if next_payment_date and not payment_date:
        return jsonify({
            "ok": False,
            "message": "Дата должна быть в формате ГГГГ-ММ-ДД",
        }), 400

    session = Session()

    try:
        car = find_car(session, car_code)

        if not car:
            return jsonify({
                "ok": False,
                "message": f"Машина {car_code} не найдена",
            }), 404

        old_next_date = parse_iso_date(car.next_payment_date)

        car.driver = driver
        car.daily_rent = daily_rent
        car.weekly_payment = daily_rent * 7
        car.payment_weekday = payment_weekday
        car.next_payment_date = next_payment_date
        car.payment_notifications = 1
        car.driver_deposit = driver_deposit

        # При первой настройке начало периода — за 7 дней до расчёта.
        if payment_date and (
            not getattr(car, "last_payment_date", "")
            or old_next_date != payment_date
        ):
            car.last_payment_date = (
                payment_date - timedelta(days=7)
            ).isoformat()

        session.commit()

        calculation = calculate_driver_payment(session, car)

        return jsonify({
            "ok": True,
            "message": "Настройки аренды сохранены",
            "car": {
                "code": car.code,
                "driver": car.driver,
                "daily_rent": car.daily_rent,
                "driver_deposit": int(
                    getattr(car, "driver_deposit", 0) or 0
                ),
                "effective_daily_rent": effective_daily_rent(car),
                "payment_weekday": car.payment_weekday,
                "last_payment_date": car.last_payment_date,
                "next_payment_date": car.next_payment_date,
                **calculation,
            },
        })

    except Exception as error:
        session.rollback()
        print(f"Ошибка сохранения оплаты: {error}")

        return jsonify({
            "ok": False,
            "message": f"Не удалось сохранить настройки: {error}",
        }), 500

    finally:
        session.close()


@bp.route("/api/check-driver-payments", methods=["GET"])
def check_driver_payments():
    secret = os.getenv("CRON_SECRET", "")
    received_secret = request.args.get("secret", "")

    if secret and received_secret != secret:
        return jsonify({
            "ok": False,
            "message": "Нет доступа",
        }), 403

    session = Session()
    today = date.today()
    messages = []

    try:
        cars = (
            session.query(Car)
            .filter(Car.payment_notifications == 1)
            .filter(
                (Car.daily_rent > 0)
                | (Car.weekly_payment > 0)
            )
            .all()
        )

        for car in cars:
            payment_date = parse_iso_date(car.next_payment_date)

            if not payment_date:
                continue

            calculation = calculate_driver_payment(session, car)
            days_left = (payment_date - today).days
            driver_name = car.driver or "Не указан"

            amount_text = (
                f"{calculation['amount_due']:,}"
                .replace(",", " ")
            )
            rate_text = (
                f"{calculation['effective_daily_rent']:,}"
                .replace(",", " ")
            )
            current_amount_text = (
                f"{calculation['current_amount']:,}"
                .replace(",", " ")
            )

            overdue_lines = []

            for index, period in enumerate(
                calculation.get("overdue_periods", []),
                start=1,
            ):
                period_amount = (
                    f"{int(period.get('amount', 0)):,}"
                    .replace(",", " ")
                )

                overdue_lines.append(
                    f"Неделя {index}: "
                    f"{period.get('label', '')} — "
                    f"{period_amount} ₽"
                )

            overdue_text = (
                "\n".join(overdue_lines)
                if overdue_lines
                else "Просроченных недель нет"
            )

            deposit_text = (
                f"{int(getattr(car, 'driver_deposit', 0) or 0):,}"
                .replace(",", " ")
            )

            details = (
                f"💵 Ставка: {rate_text} ₽/сутки\n"
                f"🔒 Залог: {deposit_text} ₽ "
                f"(не входит в доход и долг)\n"
                f"🧾 Просроченные недели:\n"
                f"{overdue_text}\n"
                f"📅 Текущий период: "
                f"{calculation['period_start']} — "
                f"{calculation['scheduled_period_end']}\n"
                f"⏸ Простой текущего периода: "
                f"{calculation['downtime_days']} дн.\n"
                f"✅ Начислено дней: "
                f"{calculation['payable_days']}\n"
                f"➕ Начислено в текущем периоде: "
                f"{current_amount_text} ₽\n"
            )

            if days_left == 1:
                messages.append(
                    "🟡 <b>Завтра расчёт</b>\n"
                    f"🚕 Машина: <b>{car.code}</b>\n"
                    f"👤 Водитель: {driver_name}\n"
                    + details
                    + f"💰 К оплате: {amount_text} ₽"
                )

            elif days_left == 0:
                messages.append(
                    "🟠 <b>Сегодня расчёт</b>\n"
                    f"🚕 Машина: <b>{car.code}</b>\n"
                    f"👤 Водитель: {driver_name}\n"
                    + details
                    + f"💰 Должен внести: {amount_text} ₽"
                )

            elif days_left < 0:
                overdue_days = abs(days_left)

                messages.append(
                    "🔴 <b>Платёж просрочен</b>\n"
                    f"🚕 Машина: <b>{car.code}</b>\n"
                    f"👤 Водитель: {driver_name}\n"
                    + details
                    + f"💰 Долг: {amount_text} ₽\n"
                    f"⏰ Просрочка: {overdue_days} дн."
                )

        if not messages:
            return jsonify({
                "ok": True,
                "message": "Платежей на сегодня нет",
                "notifications": 0,
            })

        telegram_text = (
            "🚕 <b>Расчёты водителей</b>\n\n"
            + "\n\n".join(messages)
        )

        sent = send_telegram_message(telegram_text)

        return jsonify({
            "ok": sent,
            "message": (
                "Уведомление отправлено"
                if sent
                else "Не удалось отправить уведомление"
            ),
            "notifications": len(messages),
        })

    except Exception as error:
        print(f"Ошибка проверки платежей: {error}")

        return jsonify({
            "ok": False,
            "message": f"Ошибка проверки платежей: {error}",
        }), 500

    finally:
        session.close()



@bp.route("/api/mark-driver-period-paid", methods=["POST"])
def mark_driver_period_paid():
    data = request.get_json(silent=True) or request.form

    car_code = normalize_code(
        data.get("car_code") or data.get("code") or ""
    )
    period_start_raw = (data.get("period_start") or "").strip()
    period_end_raw = (data.get("period_end") or "").strip()

    if not car_code:
        return jsonify({
            "ok": False,
            "message": "Не указан номер машины",
        }), 400

    session = Session()

    try:
        car = find_car(session, car_code)

        if not car:
            return jsonify({
                "ok": False,
                "message": f"Машина {car_code} не найдена",
            }), 404

        calculation = calculate_driver_payment(session, car)
        overdue_periods = calculation.get("overdue_periods") or []

        if not overdue_periods:
            return jsonify({
                "ok": False,
                "message": "У этой машины нет просроченного периода",
            }), 400

        earliest = overdue_periods[0]
        expected_start = parse_iso_date(earliest.get("period_start"))
        expected_end = parse_iso_date(earliest.get("period_end"))

        requested_start = parse_iso_date(period_start_raw) or expected_start
        requested_end = parse_iso_date(period_end_raw) or expected_end

        if (
            requested_start != expected_start
            or requested_end != expected_end
        ):
            return jsonify({
                "ok": False,
                "message": (
                    "Сначала нужно закрыть самую раннюю неделю: "
                    f"{expected_start.strftime('%d.%m.%Y')} — "
                    f"{expected_end.strftime('%d.%m.%Y')}"
                ),
            }), 400

        paid_period = calculate_rental_interval(
            session,
            car,
            expected_start,
            expected_end,
        )

        car.last_payment_date = expected_end.isoformat()
        car.next_payment_date = (
            expected_end + timedelta(days=7)
        ).isoformat()

        session.commit()

        return jsonify({
            "ok": True,
            "message": (
                f"Неделя {expected_start.strftime('%d.%m.%Y')} — "
                f"{expected_end.strftime('%d.%m.%Y')} оплачена. "
                f"Сумма: {int(paid_period['amount'] or 0):,} ₽"
            ).replace(",", " "),
            "car_code": car.code,
            "paid_period": paid_period,
            "next_payment_date": car.next_payment_date,
        })

    except Exception as error:
        session.rollback()
        return jsonify({
            "ok": False,
            "message": (
                "Не удалось закрыть неделю: "
                f"{type(error).__name__}: {error}"
            ),
        }), 500

    finally:
        session.close()


@bp.route("/api/mark-driver-payment-paid", methods=["POST"])
def mark_driver_payment_paid():
    data = request.get_json(silent=True) or request.form
    car_code = normalize_code(
        data.get("car_code") or data.get("code") or ""
    )

    if not car_code:
        return jsonify({
            "ok": False,
            "message": "Не указан номер машины",
        }), 400

    session = Session()

    try:
        car = find_car(session, car_code)

        if not car:
            return jsonify({
                "ok": False,
                "message": f"Машина {car_code} не найдена",
            }), 404

        calculation = calculate_driver_payment(session, car)
        today = moscow_now().date()

        # Оплата закрывает долг и начисления до сегодняшнего дня включительно.
        # Новый период начинается завтра.
        new_period_start = today + timedelta(days=1)
        car.last_payment_date = new_period_start.isoformat()

        weekday = int(getattr(car, "payment_weekday", 0) or 0)
        days_until_due = (weekday - new_period_start.weekday()) % 7

        if days_until_due == 0:
            days_until_due = 7

        next_date = new_period_start + timedelta(
            days=days_until_due
        )
        car.next_payment_date = next_date.isoformat()

        session.commit()

        return jsonify({
            "ok": True,
            "message": (
                f"Оплата отмечена: "
                f"{calculation['amount_due']:,} ₽"
                .replace(",", " ")
            ),
            "car_code": car.code,
            "paid_period": calculation,
            "next_payment_date": car.next_payment_date,
        })

    except Exception as error:
        session.rollback()
        print(f"Ошибка отметки оплаты: {error}")

        return jsonify({
            "ok": False,
            "message": f"Не удалось отметить оплату: {error}",
        }), 500

    finally:
        session.close()

    
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
            session.add(Expense(operation_id=op.id, car_code=op.car_code, category="Доп. расходы", amount=total_cost, share_type="investor_only"))
        changed = True

    if changed:
        session.commit()
    return changed



def split_message_parts(message):
    message = (message or "").strip()
    parts = [p.strip() for p in message.split("/") if p.strip()]
    return parts or [message]



def add_part_rows_from_parsed(session, op, car, data):
    """
    Сохраняет одну или несколько деталей одной операции.
    """
    parts = data.get("parts") or []

    if not parts and data.get("part"):
        parts = [{
            "part": data.get("part") or "",
            "brand": data.get("brand") or "",
            "position": data.get("position") or "",
            "price": data.get("part_price") or 0,
            "labor": data.get("labor") or 0,
        }]

    for item in parts:
        session.add(
            Part(
                car_code=car.code,
                operation_id=op.id,
                part_name=item.get("part") or "",
                brand=item.get("brand") or data.get("brand") or "",
                position=(
                    item.get("position")
                    or data.get("position")
                    or ""
                ),
                price=item.get("price") or 0,
                labor=item.get("labor") or 0,
                install_mileage=data.get("mileage"),
            )
        )



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
        session.add(Expense(operation_id=op.id, car_code=car.code, category="Доп. расходы", amount=data["total_cost"], share_type="investor_only"))

    elif data["type"] == "downtime_end":
        # Ищем любую незакрытую строку, а не только active=1.
        # Это исправляет старые записи, где active сохранился неверно.
        downtime = (
            session.query(Downtime)
            .filter(
                func.trim(Downtime.car_code) == normalize_code(car.code),
                Downtime.end_date.is_(None),
            )
            .order_by(Downtime.id.desc())
            .first()
        )

        if downtime:
            downtime.end_date = op.date or datetime.now()
            downtime.active = 0

            if downtime.start_date:
                downtime.days = max(
                    (
                        downtime.end_date.date()
                        - downtime.start_date.date()
                    ).days,
                    1,
                )

        # Выключаем все случайно оставшиеся активные простои машины.
        for old_row in (
            session.query(Downtime)
            .filter(
                func.trim(Downtime.car_code)
                == normalize_code(car.code),
                Downtime.active == 1,
            )
            .all()
        ):
            old_row.active = 0

        car.status = "Работает"

    elif data["type"] == "downtime":
        downtime_end = data.get("end_date")
        is_active = 0 if downtime_end else 1

        session.add(Downtime(
            operation_id=op.id,
            car_code=car.code,
            start_date=data.get("start_date") or datetime.now(),
            end_date=downtime_end,
            days=data.get("days", 0),
            reason=data["description"],
            active=is_active,
            comment=data["raw"],
        ))

        car.status = "Простой" if is_active else "Работает"

    add_part_rows_from_parsed(
        session,
        op,
        car,
        data,
    )

    if data.get("mileage"):
        car.current_mileage = data["mileage"]
        session.add(Mileage(car_code=car.code, mileage=data["mileage"], source=data["raw"]))



def normalize_warehouse_text(value):
    """
    Приводит разные названия одной детали к единому виду.

    Например:
    - стойка стаба
    - стойка стабилизатора
    - стойки стабилизатора

    превращаются в:
    - стойка стабилизатора
    """
    value = (value or "").strip().lower().replace("ё", "е")
    value = re.sub(r"[^0-9a-zа-я]+", " ", value)
    value = re.sub(r"\s+", " ", value).strip()

    replacements = {
        "стойки стаба": "стойка стабилизатора",
        "стойка стаба": "стойка стабилизатора",
        "стойки стабилизатора": "стойка стабилизатора",
        "линка стабилизатора": "стойка стабилизатора",
        "линк стабилизатора": "стойка стабилизатора",

        "втулки стаба": "втулка стабилизатора",
        "втулка стаба": "втулка стабилизатора",
        "втулки стабилизатора": "втулка стабилизатора",

        "передние колодки": "тормозные колодки передние",
        "колодки передние": "тормозные колодки передние",
        "задние колодки": "тормозные колодки задние",
        "колодки задние": "тормозные колодки задние",

        "подшипники ступицы передние": "подшипник ступицы передний",
        "передний подшипник ступицы": "подшипник ступицы передний",
        "подшипники ступицы задние": "подшипник ступицы задний",
        "задний подшипник ступицы": "подшипник ступицы задний",
    }

    return replacements.get(value, value)


def warehouse_name_matches(stored_name, parsed_name):
    stored = normalize_warehouse_text(stored_name)
    parsed = normalize_warehouse_text(parsed_name)

    if not stored or not parsed:
        return False

    if stored == parsed:
        return True

    # Подстраховка для похожих формулировок.
    stored_tokens = set(stored.split())
    parsed_tokens = set(parsed.split())

    if stored_tokens and parsed_tokens:
        common = stored_tokens & parsed_tokens
        shorter = min(len(stored_tokens), len(parsed_tokens))

        if shorter and len(common) / shorter >= 0.75:
            return True

    return stored in parsed or parsed in stored



def find_exact_warehouse_item(
    session,
    part_name,
    brand="",
    variant="",
):
    """
    Проверяет только точное совпадение складской позиции.

    Разные бренды и разные исполнения одной детали считаются
    отдельными позициями:
    - колодки / AMD / задние барабанные;
    - колодки / AMD / задние дисковые;
    - колодки / JUST DRIVE / задние барабанные.
    """
    part_key = normalize_warehouse_text(part_name)
    brand_key = normalize_warehouse_text(brand)
    variant_key = normalize_warehouse_text(variant)

    for item in session.query(WarehouseItem).all():
        if normalize_warehouse_text(item.part_name) != part_key:
            continue
        if normalize_warehouse_text(item.brand) != brand_key:
            continue
        if normalize_warehouse_text(
            getattr(item, "variant", "")
        ) != variant_key:
            continue

        return item

    return None


def find_warehouse_item(session, part_name, brand=""):
    """
    Ищет деталь сначала по названию и бренду,
    затем по названию без строгой привязки к бренду.
    """
    brand_key = normalize_warehouse_text(brand)

    matching_name = []

    for item in session.query(WarehouseItem).all():
        if warehouse_name_matches(item.part_name, part_name):
            matching_name.append(item)

    if not matching_name:
        return None

    if brand_key:
        for item in matching_name:
            if normalize_warehouse_text(item.brand) == brand_key:
                return item

    # Если бренд у складской позиции не заполнен,
    # разрешаем использовать её для любого бренда.
    for item in matching_name:
        if not normalize_warehouse_text(item.brand):
            return item

    # Если название совпало и на складе только одна такая позиция,
    # используем её даже при различии регистра/написания бренда.
    if len(matching_name) == 1:
        return matching_name[0]

    return None


def deduct_from_warehouse(session, op, car, data):
    """
    Списывает одну или несколько выбранных складских позиций.

    Если пользователь выбрал позиции во всплывающем списке,
    сервер списывает их строго по ID. Название в команде уже
    не влияет на складское списание.
    """
    raw_text = (
        data.get("raw") or ""
    ).lower().replace("ё", "е")

    selected_ids = data.get("warehouse_item_ids") or []

    # JSON может прислать список, одно число или строку.
    if not isinstance(selected_ids, (list, tuple, set)):
        selected_ids = [selected_ids]
    else:
        selected_ids = list(selected_ids)

    # Совместимость со старой версией интерфейса.
    old_selected_id = data.get("warehouse_item_id")
    if old_selected_id and old_selected_id not in selected_ids:
        selected_ids.append(old_selected_id)

    normalized_ids = []
    for value in selected_ids:
        try:
            item_id = int(value)
        except (TypeError, ValueError):
            continue

        if item_id not in normalized_ids:
            normalized_ids.append(item_id)

    from_warehouse = (
        bool(normalized_ids)
        or bool(data.get("from_warehouse"))
        or "со склада" in raw_text
        or "из склада" in raw_text
    )

    if not from_warehouse:
        return {
            "used": False,
            "message": "",
            "low_stock_text": "",
        }

    # Точное списание выбранных позиций.
    if normalized_ids:
        messages = []
        low_messages = []
        used_any = False

        for item_id in normalized_ids:
            item = (
                session.query(WarehouseItem)
                .filter_by(id=item_id)
                .first()
            )

            if not item:
                messages.append(
                    f"позиция ID {item_id} больше не найдена"
                )
                continue

            label = (
                f"{item.part_name}"
                f"{' ' + item.brand if item.brand else ''}"
                f"{' · ' + item.variant if getattr(item, 'variant', '') else ''}"
            )

            if (item.quantity or 0) <= 0:
                messages.append(f"«{label}» закончилась")
                continue

            item.quantity = (item.quantity or 0) - 1
            used_any = True

            session.add(
                WarehouseMovement(
                    operation_id=op.id,
                    car_code=car.code,
                    part_name=item.part_name,
                    brand=item.brand or "",
                    variant=getattr(item, "variant", "") or "",
                    quantity=1,
                    movement_type="out",
                    comment=data.get("raw") or "",
                )
            )

            remaining = item.quantity or 0
            minimum = item.min_quantity or 0

            messages.append(
                f"{label} — 1 шт., остаток {remaining}"
            )

            if remaining <= minimum:
                low_messages.append(
                    "⚠️ <b>Заканчивается деталь</b>\n"
                    f"Деталь: {label}\n"
                    f"Осталось: {remaining} шт.\n"
                    f"Минимум: {minimum} шт."
                )

        return {
            "used": used_any,
            "message": (
                ("Со склада списано: " if used_any else "Склад не списан: ")
                + "; ".join(messages)
            ),
            "low_stock_text": "\n\n".join(low_messages),
        }

    # Запасной поиск по названию для старых команд без выбора подсказки.
    parsed_parts = data.get("parts") or []

    if not parsed_parts and data.get("part"):
        parsed_parts = [{
            "part": data.get("part"),
            "brand": data.get("brand") or "",
        }]

    if not parsed_parts:
        return {
            "used": False,
            "message": (
                "Расход записан, но склад не списан: "
                "не удалось распознать детали."
            ),
            "low_stock_text": "",
        }

    messages = []
    low_messages = []
    used_any = False

    for parsed_part in parsed_parts:
        part_name = (
            parsed_part.get("part") or ""
        ).strip()
        brand = (
            parsed_part.get("brand")
            or data.get("brand")
            or ""
        ).strip()

        if not part_name:
            continue

        item = find_warehouse_item(
            session,
            part_name=part_name,
            brand=brand,
        )

        display_name = f"{part_name} {brand}".strip()

        if not item:
            messages.append(f"не найдена «{display_name}»")
            continue

        if (item.quantity or 0) <= 0:
            messages.append(f"«{display_name}» закончилась")
            continue

        item.quantity = (item.quantity or 0) - 1
        used_any = True

        session.add(
            WarehouseMovement(
                operation_id=op.id,
                car_code=car.code,
                part_name=item.part_name,
                brand=item.brand or "",
                variant=getattr(item, "variant", "") or "",
                quantity=1,
                movement_type="out",
                comment=data.get("raw") or "",
            )
        )

        remaining = item.quantity or 0
        minimum = item.min_quantity or 0

        label = (
            f"{item.part_name}"
            f"{' ' + item.brand if item.brand else ''}"
            f"{' · ' + item.variant if getattr(item, 'variant', '') else ''}"
        )

        messages.append(
            f"{label} — 1 шт., остаток {remaining}"
        )

        if remaining <= minimum:
            low_messages.append(
                "⚠️ <b>Заканчивается деталь</b>\n"
                f"Деталь: {label}\n"
                f"Осталось: {remaining} шт.\n"
                f"Минимум: {minimum} шт."
            )

    return {
        "used": used_any,
        "message": (
            ("Со склада списано: " if used_any else "Склад не списан: ")
            + "; ".join(messages)
        ),
        "low_stock_text": "\n\n".join(low_messages),
    }


def enforce_repair_total_from_raw(data):
    """
    Финальная серверная проверка стоимости ремонта.

    Не зависит от parser.py и понимает:
    - цена 1000
    - цена 1000р
    - стоимость 1 000 руб.
    - работа 700
    - ремонт 700р
    """
    if data.get("type") not in ("repair", "service", "expense"):
        return data

    raw = (data.get("raw") or "").lower().replace("ё", "е")

    if not raw:
        return data

    def to_int(raw_number):
        cleaned = re.sub(r"[^\d]", "", raw_number or "")
        return int(cleaned) if cleaned else 0

    # Сначала вариант с разделителями тысяч, затем обычное число.
    # Важно: старый порядок мог прочитать 1000 как 100.
    number_pattern = (
        r"(\d{1,3}(?:[ \u00a0]\d{3})+|\d{1,9})(?!\d)"
    )

    # Цена деталей: поддерживаем несколько упоминаний цены.
    part_price_matches = re.findall(
        rf"\b(?:цена|стоимость|деталь|запчасть)\s*[:=-]?\s*"
        rf"{number_pattern}\s*(?:₽|р\.?|руб\.?|рублей)?",
        raw,
    )

    # Работа может быть указана словами «работа» или «ремонт».
    labor_matches = re.findall(
        rf"\b(?:работа|за\s+работу|ремонт)\s*[:=-]?\s*"
        rf"{number_pattern}\s*(?:₽|р\.?|руб\.?|рублей)?",
        raw,
    )

    part_price = sum(to_int(value) for value in part_price_matches)
    labor = sum(to_int(value) for value in labor_matches)

    # Если явных меток нет, используем все денежные числа,
    # кроме кода машины и пробега.
    if part_price == 0 and labor == 0:
        car_code = normalize_code(data.get("car_code"))
        mileage = data.get("mileage")
        values = []

        for match in re.finditer(
            rf"(?<!\d){number_pattern}\s*(?:₽|р\.?|руб\.?|рублей)?",
            raw,
        ):
            value = to_int(match.group(1))

            if car_code and str(value) == str(car_code):
                continue
            if mileage and value == int(mileage):
                continue

            values.append(value)

        if values:
            # Если парсер уже определил работу, сохраняем её,
            # остальное считаем стоимостью деталей.
            existing_labor = int(data.get("labor") or 0)
            if existing_labor and existing_labor in values:
                labor = existing_labor
                removed = False
                remaining = []

                for value in values:
                    if not removed and value == existing_labor:
                        removed = True
                        continue
                    remaining.append(value)

                part_price = sum(remaining)
            else:
                part_price = sum(values)

    # Явные значения из исходной команды имеют приоритет.
    if part_price or labor:
        data["part_price"] = part_price
        data["labor"] = labor
        data["total"] = part_price + labor

        parts = data.get("parts") or []

        if parts:
            # Распределяем итоговую стоимость деталей без потери суммы.
            existing_prices = sum(
                int(item.get("price") or 0)
                for item in parts
            )
            difference = part_price - existing_prices

            if difference != 0:
                target = next(
                    (
                        item for item in parts
                        if not int(item.get("price") or 0)
                    ),
                    parts[-1],
                )
                target["price"] = max(
                    int(target.get("price") or 0) + difference,
                    0,
                )

            # Работа хранится только у первой детали.
            for index, item in enumerate(parts):
                item["labor"] = labor if index == 0 else 0

            data["parts"] = parts

    return data


def save_operation(data):
    data = enforce_repair_total_from_raw(data)
    session = Session()

    try:
        car = find_car(session, data.get("car_code"))
    
        if not car:
            existing = [c.code for c in session.query(Car).order_by(Car.code).all()]
            return {"ok": False, "message": f"Машина не найдена. Есть коды: {', '.join(existing)}"}
    
        if data["type"] == "unknown":
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
            session.add(Expense(operation_id=op.id, car_code=car.code, category="Доп. расходы", amount=data["total_cost"], share_type="investor_only"))
    
        elif data["type"] == "downtime_end":
            # Ищем любую незакрытую строку, а не только active=1.
            # Это исправляет старые записи, где active сохранился неверно.
            downtime = (
                session.query(Downtime)
                .filter(
                    func.trim(Downtime.car_code) == normalize_code(car.code),
                    Downtime.end_date.is_(None),
                )
                .order_by(Downtime.id.desc())
                .first()
            )
    
            if downtime:
                downtime.end_date = op.date or datetime.now()
                downtime.active = 0
    
                if downtime.start_date:
                    downtime.days = max(
                        (
                            downtime.end_date.date()
                            - downtime.start_date.date()
                        ).days,
                        1,
                    )
    
            # Выключаем все случайно оставшиеся активные простои машины.
            for old_row in (
                session.query(Downtime)
                .filter(
                    func.trim(Downtime.car_code)
                    == normalize_code(car.code),
                    Downtime.active == 1,
                )
                .all()
            ):
                old_row.active = 0
    
            car.status = "Работает"
    
        elif data["type"] == "downtime":
            downtime_end = data.get("end_date")
            is_active = 0 if downtime_end else 1
    
            session.add(Downtime(
                operation_id=op.id,
                car_code=car.code,
                start_date=data.get("start_date") or datetime.now(),
                end_date=downtime_end,
                days=data.get("days", 0),
                reason=data["description"],
                active=is_active,
                comment=data["raw"],
            ))
    
            car.status = "Простой" if is_active else "Работает"
    
        add_part_rows_from_parsed(
            session,
            op,
            car,
            data,
        )
    
        if data.get("mileage"):
            car.current_mileage = data["mileage"]
            session.add(Mileage(car_code=car.code, mileage=data["mileage"], source=data["raw"]))
    
        warehouse_result = deduct_from_warehouse(
            session,
            op,
            car,
            data,
        )
    
        session.commit()
        op_id = op.id
    
        low_stock_text = warehouse_result.get("low_stock_text") or ""
        if low_stock_text:
            send_telegram_message(low_stock_text)
    
        message = f"Записано. Операция #{op_id}"
        if warehouse_result.get("message"):
            message += " | " + warehouse_result["message"]
    
        return {
            "ok": True,
            "message": message,
            "data": data,
            "warehouse": warehouse_result,
        }
    except Exception as error:
        session.rollback()
        print(
            "Ошибка save_operation:",
            type(error).__name__,
            str(error),
        )
        return {
            "ok": False,
            "message": (
                "Ошибка записи операции: "
                f"{type(error).__name__}: {error}"
            ),
        }
    finally:
        session.close()


@bp.route("/")
def index():
    return render_template_string(HTML)


@bp.route("/healthz")
def healthz():
    return "ok"



@bp.route("/api/debug-repair-total", methods=["GET"])
def api_debug_repair_total():
    message = (request.args.get("message") or "").strip()

    parsed = parse_message(message)
    checked = enforce_repair_total_from_raw(parsed)

    return jsonify({
        "ok": True,
        "message": message,
        "type": checked.get("type"),
        "part_price": checked.get("part_price", 0),
        "labor": checked.get("labor", 0),
        "total": checked.get("total", 0),
        "parts": checked.get("parts", []),
    })


@bp.route("/api/debug-parse", methods=["GET"])
def api_debug_parse():
    message = (request.args.get("message") or "").strip()

    parsed = parse_message(message)
    parsed = enforce_repair_total_from_raw(parsed)

    return jsonify({
        "ok": True,
        "message": message,
        "parsed": parsed,
        "final_total": parsed.get("total", 0),
        "part_price": parsed.get("part_price", 0),
        "labor": parsed.get("labor", 0),
        "warehouse_item_id": parsed.get("warehouse_item_id"),
    })



def normalize_history_question_text(value):
    value = (value or "").lower().replace("ё", "е")
    value = re.sub(r"[^0-9a-zа-я]+", " ", value)
    value = re.sub(r"\s+", " ", value).strip()
    return value


def history_word_stem(word):
    """
    Простая нормализация русских окончаний для поиска по истории.

    Нужна, чтобы:
    - наконечник / наконечника / наконечники;
    - рулевой / рулевого;
    - колодка / колодки / колодок

    находились как одна деталь.
    """
    word = normalize_history_question_text(word)

    endings = (
        "иями", "ями", "ами", "ого", "ему", "ому",
        "ыми", "ими", "его", "ая", "яя", "ое", "ее",
        "ую", "юю", "ов", "ев", "ей", "ам", "ям",
        "ах", "ях", "ом", "ем", "ы", "и", "а", "я",
        "у", "ю", "е", "о",
    )

    for ending in endings:
        if word.endswith(ending) and len(word) - len(ending) >= 4:
            return word[:-len(ending)]

    return word


def history_tokens(value):
    stop_words = {
        "кому", "мы", "меняли", "менял", "заменили", "замена",
        "ставили", "ставил", "устанавливали", "установили",
        "последний", "последняя", "последнее", "последние",
        "раз", "когда", "где", "какой", "какая", "какую",
        "машина", "машине", "машину", "авто", "было", "был",
        "была", "кто", "покажи", "найди", "скажи",
    }

    result = []

    for word in normalize_history_question_text(value).split():
        if word in stop_words or word.isdigit() or len(word) < 3:
            continue

        stem = history_word_stem(word)

        if stem and stem not in result:
            result.append(stem)

    return result


def part_history_score(question, part, operation):
    """
    Оценивает соответствие вопроса записи ремонта.

    Важное правило: сокращения и полные названия одной детали
    получают одинаковый приоритет. Поэтому более старая запись
    «стойка стаба» больше не обгоняет новую запись
    «стойка стабилизатора» только из-за буквального совпадения.
    """
    query_tokens = history_tokens(question)

    searchable = " ".join([
        part.part_name or "",
        part.brand or "",
        part.position or "",
        operation.description if operation else "",
        operation.raw_message if operation else "",
    ])

    searchable_tokens = {
        history_word_stem(word)
        for word in normalize_history_question_text(searchable).split()
        if len(word) >= 3
    }

    score = 0

    for token in query_tokens:
        if token in searchable_tokens:
            score += 25
            continue

        if any(
            stored.startswith(token) or token.startswith(stored)
            for stored in searchable_tokens
            if len(stored) >= 4
        ):
            score += 12

    question_key = canonical_part_key(
        extract_part_phrase_from_question(question)
    )
    stored_key = canonical_part_key(part.part_name or "")

    if question_key and stored_key and question_key == stored_key:
        score += 120

    return score


def extract_part_phrase_from_question(question):
    """
    Убирает служебные слова из вопроса и оставляет название детали.
    """
    normalized = normalize_history_question_text(question)

    removable = (
        "когда последний раз менялась",
        "когда последний раз меняли",
        "кому мы меняли",
        "кому меняли",
        "на какой машине меняли",
        "последний раз меняли",
        "последняя замена",
        "когда меняли",
        "когда менялась",
        "покажи последние",
        "покажи последнюю",
        "найди последнюю",
        "какая машина",
    )

    for phrase in removable:
        normalized = normalized.replace(phrase, " ")

    normalized = re.sub(r"\s+", " ", normalized).strip()
    return normalized


def canonical_part_key(value):
    """
    Нормализует название детали для статистики.

    Примеры:
    - рулевой наконечник / рулевого наконечника;
    - стойка стаба / стойка стабилизатора;
    - колодки / тормозные колодки.
    """
    normalized = normalize_history_question_text(value)

    aliases = {
        "стойка стаба": "стойка стабилизатора",
        "стойки стаба": "стойка стабилизатора",
        "стойка стабилизатора": "стойка стабилизатора",
        "стойки стабилизатора": "стойка стабилизатора",
        "стоика стаба": "стойка стабилизатора",
        "стоика стабилизатора": "стойка стабилизатора",
        "линк стабилизатора": "стойка стабилизатора",
        "линка стабилизатора": "стойка стабилизатора",
        "втулка стаба": "втулка стабилизатора",
        "втулки стаба": "втулка стабилизатора",
        "рулевой наконечник": "рулевой наконечник",
        "рулевого наконечника": "рулевой наконечник",
        "тормозные колодки": "тормозные колодки",
        "колодки": "тормозные колодки",
        "ступичный подшипник": "подшипник ступицы",
        "подшипник ступицы": "подшипник ступицы",
    }

    if normalized in aliases:
        return aliases[normalized]

    words = [
        history_word_stem(word)
        for word in normalized.split()
        if len(word) >= 3
    ]

    return " ".join(words).strip()


def build_parts_analytics(session):
    """
    Строит статистику замен деталей по всей истории.

    Для каждой детали считает:
    - количество замен;
    - количество машин;
    - последнюю замену;
    - средний интервал в днях;
    - средний интервал по пробегу;
    - повторные замены на одной машине.
    """
    grouped = {}

    for part in session.query(Part).all():
        operation = None

        if part.operation_id:
            operation_ids_with_parts.add(part.operation_id)
            operation = (
                session.query(Operation)
                .filter_by(id=part.operation_id)
                .first()
            )

        event_date = (
            operation.date
            if operation and operation.date
            else getattr(part, "date", None)
        )

        key = canonical_part_key(part.part_name or "")

        if not key:
            continue

        row = grouped.setdefault(key, {
            "name": part.part_name or key,
            "count": 0,
            "cars": set(),
            "brands": {},
            "events": [],
            "repeat_by_car": {},
        })

        row["count"] += 1
        row["cars"].add(normalize_code(part.car_code))

        if part.brand:
            row["brands"][part.brand] = (
                row["brands"].get(part.brand, 0) + 1
            )

        event = {
            "car_code": normalize_code(part.car_code),
            "date": event_date,
            "mileage": part.install_mileage,
            "brand": part.brand or "",
            "position": part.position or "",
            "price": part.price or 0,
            "labor": part.labor or 0,
            "operation": operation,
        }

        row["events"].append(event)

        car_events = row["repeat_by_car"].setdefault(
            normalize_code(part.car_code),
            [],
        )
        car_events.append(event)

    result = []

    for key, row in grouped.items():
        intervals_days = []
        intervals_mileage = []
        repeated_cars = []

        for car_code, events in row["repeat_by_car"].items():
            events.sort(
                key=lambda item: (
                    item["date"] or datetime.min,
                    item["mileage"] or 0,
                )
            )

            if len(events) >= 2:
                repeated_cars.append({
                    "car_code": car_code,
                    "count": len(events),
                })

            for previous, current in zip(events, events[1:]):
                if previous["date"] and current["date"]:
                    day_gap = (
                        current["date"].date()
                        - previous["date"].date()
                    ).days

                    if day_gap > 0:
                        intervals_days.append(day_gap)

                if previous["mileage"] and current["mileage"]:
                    mileage_gap = (
                        current["mileage"]
                        - previous["mileage"]
                    )

                    if mileage_gap > 0:
                        intervals_mileage.append(mileage_gap)

        events_sorted = sorted(
            row["events"],
            key=lambda item: item["date"] or datetime.min,
            reverse=True,
        )

        top_brand = ""
        top_brand_count = 0

        if row["brands"]:
            top_brand, top_brand_count = max(
                row["brands"].items(),
                key=lambda item: item[1],
            )

        result.append({
            "key": key,
            "name": row["name"],
            "count": row["count"],
            "cars_count": len(row["cars"]),
            "cars": sorted(row["cars"]),
            "top_brand": top_brand,
            "top_brand_count": top_brand_count,
            "avg_days": (
                round(sum(intervals_days) / len(intervals_days))
                if intervals_days
                else None
            ),
            "avg_mileage": (
                round(
                    sum(intervals_mileage)
                    / len(intervals_mileage)
                )
                if intervals_mileage
                else None
            ),
            "repeated_cars": sorted(
                repeated_cars,
                key=lambda item: item["count"],
                reverse=True,
            ),
            "last_event": events_sorted[0] if events_sorted else None,
        })

    result.sort(
        key=lambda item: (
            item["count"],
            item["cars_count"],
        ),
        reverse=True,
    )

    return result


def answer_parts_analytics_question(session, message):
    normalized = normalize_history_question_text(message)

    analytics_signals = (
        "часто ломаются",
        "чаще ломаются",
        "самые частые поломки",
        "какие детали часто",
        "какие детали чаще",
        "реже ломаются",
        "редко ломаются",
        "реже меняются",
        "часто меняются",
        "статистика деталей",
        "анализ деталей",
        "сколько раз меняли",
        "как часто меняли",
        "как часто меняется",
        "средний срок замены",
        "через сколько меняется",
        "через сколько меняли",
    )

    if not any(signal in normalized for signal in analytics_signals):
        return None

    analytics = build_parts_analytics(session)

    if not analytics:
        return {
            "ok": True,
            "is_answer": True,
            "message": "Пока недостаточно данных по заменам деталей.",
        }

    # Вопрос про конкретную деталь.
    query_tokens = history_tokens(message)
    specific_matches = []

    for item in analytics:
        item_tokens = {
            history_word_stem(word)
            for word in normalize_history_question_text(
                item["name"]
            ).split()
        }

        score = 0

        for token in query_tokens:
            if token in item_tokens:
                score += 20
            elif any(
                stored.startswith(token)
                or token.startswith(stored)
                for stored in item_tokens
                if len(stored) >= 4
            ):
                score += 10

        if score > 0:
            specific_matches.append((score, item))

    if specific_matches and (
        "сколько раз" in normalized
        or "как часто" in normalized
        or "через сколько" in normalized
        or "средний срок" in normalized
    ):
        specific_matches.sort(
            key=lambda pair: (
                pair[0],
                pair[1]["count"],
            ),
            reverse=True,
        )

        item = specific_matches[0][1]
        lines = [
            f"Статистика по детали: {item['name']}",
            f"Всего замен: {item['count']}",
            f"Машин: {item['cars_count']}",
            f"Машины: {', '.join(item['cars'])}",
        ]

        if item["avg_days"] is not None:
            lines.append(
                f"Средний интервал: {item['avg_days']} дней"
            )
        else:
            lines.append(
                "Средний интервал по дням пока нельзя посчитать"
            )

        if item["avg_mileage"] is not None:
            lines.append(
                "Средний интервал по пробегу: "
                f"{item['avg_mileage']:,} км".replace(",", " ")
            )
        else:
            lines.append(
                "Средний интервал по пробегу пока нельзя посчитать"
            )

        if item["top_brand"]:
            lines.append(
                f"Чаще ставили бренд: {item['top_brand']} "
                f"({item['top_brand_count']} раз)"
            )

        if item["repeated_cars"]:
            repeat_text = ", ".join(
                f"{row['car_code']} — {row['count']} раза"
                for row in item["repeated_cars"][:5]
            )
            lines.append(
                f"Повторные замены на машинах: {repeat_text}"
            )

        last_event = item["last_event"]

        if last_event:
            last_date = (
                last_event["date"].strftime("%d.%m.%Y")
                if last_event["date"]
                else "дата не указана"
            )
            lines.append(
                f"Последняя замена: машина "
                f"{last_event['car_code']}, {last_date}"
            )

        return {
            "ok": True,
            "is_answer": True,
            "message": "\n".join(lines),
        }

    # Частые детали.
    if any(
        phrase in normalized
        for phrase in (
            "часто ломаются",
            "чаще ломаются",
            "самые частые",
            "часто меняются",
            "какие детали часто",
            "какие детали чаще",
        )
    ):
        frequent = [
            item
            for item in analytics
            if item["count"] >= 2
        ][:10]

        if not frequent:
            return {
                "ok": True,
                "is_answer": True,
                "message": (
                    "Пока нет деталей с повторными заменами. "
                    "Для вывода о частых поломках нужно минимум "
                    "две замены одной детали."
                ),
            }

        lines = ["Чаще всего менялись:"]

        for index, item in enumerate(frequent, start=1):
            interval_parts = []

            if item["avg_days"] is not None:
                interval_parts.append(
                    f"в среднем раз в {item['avg_days']} дней"
                )

            if item["avg_mileage"] is not None:
                interval_parts.append(
                    f"через {item['avg_mileage']:,} км".replace(",", " ")
                )

            interval_text = (
                f" · {', '.join(interval_parts)}"
                if interval_parts
                else ""
            )

            lines.append(
                f"{index}. {item['name']} — "
                f"{item['count']} замен на "
                f"{item['cars_count']} машинах"
                f"{interval_text}"
            )

        return {
            "ok": True,
            "is_answer": True,
            "message": "\n".join(lines),
        }

    # Редкие детали.
    rare = sorted(
        analytics,
        key=lambda item: (
            item["count"],
            item["cars_count"],
            item["name"],
        ),
    )[:10]

    lines = ["Реже всего менялись:"]

    for index, item in enumerate(rare, start=1):
        lines.append(
            f"{index}. {item['name']} — "
            f"{item['count']} замена"
            f"{'ы' if item['count'] in (2, 3, 4) else ''}"
        )

    return {
        "ok": True,
        "is_answer": True,
        "message": "\n".join(lines),
    }


@bp.route("/api/parts-analytics", methods=["GET"])
def api_parts_analytics():
    session = Session()

    try:
        analytics = build_parts_analytics(session)

        return jsonify({
            "ok": True,
            "items": analytics,
            "parts_count": len(analytics),
        })

    finally:
        session.close()


def answer_history_question(session, message):
    analytics_answer = answer_parts_analytics_question(
        session,
        message,
    )

    if analytics_answer is not None:
        return analytics_answer

    """
    Отвечает на вопросы по истории ремонта.

    Примеры:
    - кому мы меняли рулевой наконечник последний раз;
    - когда последний раз ставили стойку стаба;
    - на какой машине меняли компрессор кондиционера;
    - покажи последние замены колодок.
    """
    normalized = normalize_history_question_text(message)

    question_signals = (
        "кому ",
        "когда ",
        "где ",
        "на какой машине",
        "последний раз",
        "последняя замена",
        "покажи последние",
        "кто ",
    )

    if not any(signal in normalized for signal in question_signals):
        return None

    limit = 1

    if any(
        phrase in normalized
        for phrase in (
            "последние 3",
            "три последние",
            "3 последних",
        )
    ):
        limit = 3
    elif any(
        phrase in normalized
        for phrase in (
            "последние 5",
            "пять последних",
            "5 последних",
        )
    ):
        limit = 5
    elif "последние" in normalized:
        limit = 5

    candidates = []
    operation_ids_with_parts = set()

    for part in session.query(Part).all():
        operation = None

        if part.operation_id:
            operation = (
                session.query(Operation)
                .filter_by(id=part.operation_id)
                .first()
            )

        score = part_history_score(
            message,
            part,
            operation,
        )

        if score <= 0:
            continue

        event_date = (
            operation.date
            if operation and operation.date
            else getattr(part, "date", None)
        )

        candidates.append({
            "score": score,
            "part": part,
            "operation": operation,
            "date": event_date or datetime.min,
        })

    # Старые или сложные операции иногда имеют Operation,
    # но не имеют отдельной строки Part. Ищем также по тексту операции.
    query_part_key = canonical_part_key(
        extract_part_phrase_from_question(message)
    )

    for operation in (
        session.query(Operation)
        .filter(Operation.type.in_(("repair", "service")))
        .all()
    ):
        if operation.id in operation_ids_with_parts:
            continue

        operation_text = " ".join([
            operation.description or "",
            operation.raw_message or "",
        ])

        operation_key = canonical_part_key(operation_text)
        operation_tokens = {
            history_word_stem(word)
            for word in normalize_history_question_text(
                operation_text
            ).split()
            if len(word) >= 3
        }

        score = 0

        for token in history_tokens(message):
            if token in operation_tokens:
                score += 25
            elif any(
                stored.startswith(token) or token.startswith(stored)
                for stored in operation_tokens
                if len(stored) >= 4
            ):
                score += 12

        if (
            query_part_key
            and operation_key
            and (
                query_part_key in operation_key
                or operation_key in query_part_key
            )
        ):
            score += 120

        if score <= 0:
            continue

        synthetic_part = type("HistoryPart", (), {
            "part_name": operation.description or "Ремонт / замена",
            "brand": "",
            "position": "",
            "price": operation.amount or 0,
            "labor": 0,
            "install_mileage": operation.mileage,
            "car_code": operation.car_code,
            "operation_id": operation.id,
        })()

        candidates.append({
            "score": score,
            "part": synthetic_part,
            "operation": operation,
            "date": operation.date or datetime.min,
        })

    candidates.sort(
        key=lambda item: (
            item["score"],
            item["date"],
            item["operation"].id if item["operation"] else 0,
        ),
        reverse=True,
    )

    if not candidates:
        return {
            "ok": True,
            "is_answer": True,
            "message": (
                "В истории не нашёл подходящую замену. "
                "Попробуй написать точнее название детали."
            ),
        }

    best_score = candidates[0]["score"]

    # Не смешиваем явно нерелевантные результаты.
    selected = [
        item
        for item in candidates
        if item["score"] >= max(best_score - 20, 10)
    ][:limit]

    lines = []

    if limit == 1:
        lines.append("Последняя найденная замена:")
    else:
        lines.append(f"Последние найденные замены: {len(selected)}")

    for index, item in enumerate(selected, start=1):
        part = item["part"]
        operation = item["operation"]

        car = find_car(session, part.car_code)
        car_name = (
            f"{car.brand or ''} {car.model or ''}".strip()
            if car
            else ""
        )

        date_text = (
            item["date"].strftime("%d.%m.%Y")
            if item["date"] != datetime.min
            else "дата не указана"
        )

        detail_name = part.part_name or "Деталь"

        if part.brand:
            detail_name += f", фирма {part.brand}"

        if part.position:
            detail_name += f", {part.position}"

        amount_parts = []

        if part.price:
            amount_parts.append(f"деталь {int(part.price):,} ₽".replace(",", " "))

        if part.labor:
            amount_parts.append(f"работа {int(part.labor):,} ₽".replace(",", " "))

        amount_text = (
            ", ".join(amount_parts)
            if amount_parts
            else "стоимость не указана"
        )

        mileage_text = (
            f"{int(part.install_mileage):,} км".replace(",", " ")
            if part.install_mileage
            else "не указан"
        )

        raw_text = (
            operation.raw_message.strip()
            if operation and operation.raw_message
            else ""
        )

        prefix = f"{index}. " if limit > 1 else ""

        lines.append(
            f"{prefix}Машина {part.car_code}"
            f"{' — ' + car_name if car_name else ''}"
        )
        lines.append(f"Дата: {date_text}")
        lines.append(f"Деталь: {detail_name}")
        lines.append(f"Стоимость: {amount_text}")
        lines.append(f"Пробег: {mileage_text}")

        if raw_text:
            lines.append(f"Запись: {raw_text}")

        if index < len(selected):
            lines.append("")

    return {
        "ok": True,
        "is_answer": True,
        "message": "\n".join(lines),
        "matches": len(selected),
    }


@bp.route("/api/ask-history", methods=["POST"])
def api_ask_history():
    payload = request.get_json(silent=True) or {}
    message = (payload.get("message") or "").strip()

    session = Session()

    try:
        answer = answer_history_question(session, message)

        if answer is None:
            return jsonify({
                "ok": False,
                "message": "Не понял вопрос по истории ремонта",
            }), 400

        return jsonify(answer)

    finally:
        session.close()


@bp.route("/api/add", methods=["POST"])
def api_add():
    try:
        payload = request.get_json(silent=True) or {}
        message = (payload.get("message", "") or "").strip()
        warehouse_item_id = payload.get("warehouse_item_id")
        warehouse_item_ids = payload.get("warehouse_item_ids") or []

        if not message:
            return jsonify({
                "ok": False,
                "message": "Введите команду",
            }), 400

        session = Session()
        try:
            history_answer = answer_history_question(
                session,
                message,
            )
        finally:
            session.close()

        if history_answer is not None:
            return jsonify(history_answer)

        parts = [
            part.strip()
            for part in message.split("/")
            if part.strip()
        ]

        if len(parts) <= 1:
            parsed = parse_message(message)
            parsed["warehouse_item_id"] = warehouse_item_id
            parsed["warehouse_item_ids"] = warehouse_item_ids
            result = save_operation(parsed)
            return jsonify(result), (200 if result.get("ok") else 400)

        results = []
        ok = True
        first_code = None

        for index, part in enumerate(parts):
            parsed = parse_message(part)

            if index == 0:
                if warehouse_item_id:
                    parsed["warehouse_item_id"] = warehouse_item_id
                parsed["warehouse_item_ids"] = warehouse_item_ids

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
        }), (200 if ok else 400)

    except Exception as error:
        print(
            "Ошибка /api/add:",
            type(error).__name__,
            str(error),
        )
        return jsonify({
            "ok": False,
            "message": (
                "Ошибка сервера при записи: "
                f"{type(error).__name__}: {error}"
            ),
        }), 500


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





def reconcile_downtime_for_car(session, car_code, commit=False):
    """
    Исправляет рассинхронизацию между Operation и Downtime.

    Источник текущего статуса:
    - последняя операция downtime без даты окончания => машина в простое;
    - последняя операция downtime_end => машина работает;
    - простой с заранее указанной end_date не считается активным.
    """
    code = normalize_code(car_code)

    relevant_operations = (
        session.query(Operation)
        .filter(
            func.trim(Operation.car_code) == code,
            Operation.type.in_(("downtime", "downtime_end")),
        )
        .order_by(Operation.date.asc(), Operation.id.asc())
        .all()
    )

    car = find_car(session, code)
    changed = False

    if not relevant_operations:
        # Если операций нет, используем таблицу Downtime как запасной источник.
        active_row = (
            session.query(Downtime)
            .filter(
                func.trim(Downtime.car_code) == code,
                Downtime.end_date.is_(None),
            )
            .order_by(Downtime.id.desc())
            .first()
        )

        if active_row and not active_row.active:
            active_row.active = 1
            changed = True

        if car:
            expected = "Простой" if active_row else "Работает"
            if car.status != expected:
                car.status = expected
                changed = True

        if changed and commit:
            session.commit()

        return active_row

    latest_operation = relevant_operations[-1]

    if latest_operation.type == "downtime_end":
        # Закрываем все незакрытые строки, даже если active раньше сохранился как 0.
        open_rows = (
            session.query(Downtime)
            .filter(
                func.trim(Downtime.car_code) == code,
                Downtime.end_date.is_(None),
            )
            .order_by(Downtime.id.asc())
            .all()
        )

        end_time = latest_operation.date or datetime.now()

        for row in open_rows:
            row.end_date = end_time
            row.active = 0

            if row.start_date:
                row.days = max(
                    (end_time.date() - row.start_date.date()).days,
                    1,
                )

            changed = True

        # На всякий случай выключаем старые ошибочные active-флаги.
        for row in (
            session.query(Downtime)
            .filter(
                func.trim(Downtime.car_code) == code,
                Downtime.active == 1,
            )
            .all()
        ):
            row.active = 0
            changed = True

        if car and car.status != "Работает":
            car.status = "Работает"
            changed = True

        if changed and commit:
            session.commit()

        return None

    # Последняя операция открывает простой.
    row = (
        session.query(Downtime)
        .filter_by(operation_id=latest_operation.id)
        .first()
    )

    if not row:
        row = (
            session.query(Downtime)
            .filter(
                func.trim(Downtime.car_code) == code,
            )
            .order_by(Downtime.id.desc())
            .first()
        )

    if not row:
        return None

    # Если в команде был конечный диапазон, это исторический простой.
    if row.end_date is not None:
        if row.active:
            row.active = 0
            changed = True

        if car and car.status != "Работает":
            car.status = "Работает"
            changed = True

        if changed and commit:
            session.commit()

        return None

    if row.active != 1:
        row.active = 1
        changed = True

    # Только последняя незакрытая строка может быть активной.
    for other in (
        session.query(Downtime)
        .filter(
            func.trim(Downtime.car_code) == code,
            Downtime.id != row.id,
            Downtime.active == 1,
        )
        .all()
    ):
        other.active = 0
        changed = True

    if car and car.status != "Простой":
        car.status = "Простой"
        changed = True

    if changed and commit:
        session.commit()

    return row


def reconcile_all_downtimes(session, commit=False):
    for car in session.query(Car).all():
        reconcile_downtime_for_car(
            session,
            car.code,
            commit=False,
        )

    if commit:
        session.commit()


def clean_downtime_comment(row):
    """
    Не даёт закрытому простою выглядеть активным из-за старого текста
    «по настоящее время» в исходной команде.
    """
    comment = (row.comment or "").strip()

    if not comment:
        return ""

    if row.end_date and (
        "по настоящее время" in comment.lower()
        or "по наст" in comment.lower()
    ):
        return ""

    return comment


def current_downtime_for_car(session, car_code):
    """
    Возвращает фактический текущий простой после автоматической сверки.
    """
    row = reconcile_downtime_for_car(
        session,
        car_code,
        commit=False,
    )

    if not row:
        return None

    start_date = row.start_date or datetime.now()
    days = max(
        (datetime.now().date() - start_date.date()).days,
        1,
    )

    return {
        "id": row.id,
        "start_date": start_date.strftime("%d.%m.%Y"),
        "days": days,
        "reason": row.reason or "",
        "comment": clean_downtime_comment(row),
    }



def ensure_all_previous_periods_saved(session):
    """
    Автоматически сохраняет завершённый период 16-е — 15-е
    для всех машин.

    Ошибка одной машины не блокирует главную, список машин
    или раздел инвесторов.
    """
    saved = 0
    errors = []

    for car in session.query(Car).all():
        try:
            _period, created = ensure_previous_period_saved(
                session,
                car,
            )

            if created:
                saved += 1

        except Exception as error:
            session.rollback()

            message = (
                f"Машина {getattr(car, 'code', '?')}: "
                f"{type(error).__name__}: {error}"
            )
            errors.append(message)
            print(
                "Ошибка автоматического сохранения периода:",
                message,
            )

    return {
        "saved": saved,
        "errors": errors,
    }


@bp.route("/api/summary")
def api_summary():
    session = Session()

    try:
        archive_result = ensure_all_previous_periods_saved(session)

        cleanup_legacy_investor_mess(session)
        reconcile_all_downtimes(session, commit=True)

        cars = session.query(Car).order_by(Car.code).all()

        income = 0
        expenses = 0
        profit = 0
        investments = 0

        downtime_cars = []
        working_cars = []

        period_start = None
        period_end = None

        for car in cars:
            start, end = period_bounds_for_car(car)
            calc = calculate_period_for_car(
                session,
                car,
                start,
                end,
            )

            if period_start is None:
                period_start = start
                period_end = end

            income += int(calc["income"] or 0)
            expenses += int(calc["expenses"] or 0)
            profit += int(calc["profit"] or 0)
            investments += int(calc["investments"] or 0)

            active_downtime = current_downtime_for_car(
                session,
                car.code,
            )

            car_status = {
                "code": car.code,
                "brand": car.brand or "",
                "model": car.model or "",
                "plate": car.plate or "",
            }

            if active_downtime:
                car_status.update(active_downtime)
                downtime_cars.append(car_status)
            else:
                working_cars.append(car_status)

        total_downtime_days = sum(
            item["days"] for item in downtime_cars
        )

        return jsonify({
            "ok": True,
            "period_mode": "current_16_to_15",
            "period_start": (
                period_start.strftime("%d.%m.%Y")
                if period_start
                else ""
            ),
            "period_end": (
                period_display_end(period_end).strftime("%d.%m.%Y")
                if period_end
                else ""
            ),
            "archived_now": archive_result.get("saved", 0),
            "archive_errors": archive_result.get("errors", []),

            "cars": len(cars),
            "own_cars": sum(
                1 for car in cars
                if car.owner_type != "investor"
            ),
            "investor_cars": sum(
                1 for car in cars
                if car.owner_type == "investor"
            ),
            "working_cars": len(working_cars),
            "downtime_cars": len(downtime_cars),
            "working_list": working_cars,
            "downtime_list": downtime_cars,

            "income": income,
            "expenses": expenses,
            "investments": investments,
            "profit": profit,
            "downtime_days": total_downtime_days,
        })

    except Exception as error:
        session.rollback()

        return jsonify({
            "ok": False,
            "message": (
                "Ошибка главной панели: "
                f"{type(error).__name__}: {error}"
            ),
        }), 500

    finally:
        session.close()



def month_bounds(reference_date):
    """
    Возвращает начало текущего и предыдущего календарного месяца.
    """
    current_start = reference_date.replace(day=1)

    previous_end = current_start
    previous_last_day = current_start - timedelta(days=1)
    previous_start = previous_last_day.replace(day=1)

    next_month = (
        current_start.replace(year=current_start.year + 1, month=1)
        if current_start.month == 12
        else current_start.replace(month=current_start.month + 1)
    )

    return {
        "current_start": current_start,
        "current_end": next_month,
        "previous_start": previous_start,
        "previous_end": previous_end,
    }


def percent_change(current_value, previous_value):
    current_value = int(current_value or 0)
    previous_value = int(previous_value or 0)

    if previous_value == 0:
        if current_value == 0:
            return 0
        return 100

    return round(
        (current_value - previous_value)
        * 100
        / abs(previous_value)
    )


def trend_direction(current_value, previous_value):
    current_value = int(current_value or 0)
    previous_value = int(previous_value or 0)

    if current_value > previous_value:
        return "up"
    if current_value < previous_value:
        return "down"
    return "flat"


@bp.route("/api/cars-monthly-finance")
def api_cars_monthly_finance():
    """
    Сравнивает текущий расчётный период 16-е — 15-е
    с предыдущим сохранённым периодом.

    Название endpoint оставлено старым, чтобы не менять views.py.
    """
    session = Session()

    try:
        archive_result = ensure_all_previous_periods_saved(session)
        cars = session.query(Car).order_by(Car.code).all()

        current_income = 0
        current_expenses = 0
        current_profit = 0

        previous_income = 0
        previous_expenses = 0
        previous_profit = 0

        current_start = None
        current_end = None
        previous_start = None
        previous_end = None

        for car in cars:
            start, end = period_bounds_for_car(car)
            calc = calculate_period_for_car(
                session,
                car,
                start,
                end,
            )

            current_income += int(calc["income"] or 0)
            current_expenses += int(calc["expenses"] or 0)
            current_profit += int(calc["profit"] or 0)

            if current_start is None:
                current_start = start
                current_end = end

            previous = (
                session.query(SettlementPeriod)
                .filter(
                    func.trim(SettlementPeriod.car_code)
                    == normalize_code(car.code),
                    SettlementPeriod.end_date <= start,
                )
                .order_by(
                    SettlementPeriod.end_date.desc(),
                    SettlementPeriod.id.desc(),
                )
                .first()
            )

            if previous:
                previous_income += int(previous.income or 0)
                previous_expenses += int(previous.expenses or 0)
                previous_profit += int(previous.profit or 0)

                if previous_start is None:
                    previous_start = previous.start_date
                    previous_end = previous.end_date

        def metric(current_value, previous_value):
            return {
                "current": int(current_value or 0),
                "previous": int(previous_value or 0),
                "change_percent": percent_change(
                    current_value,
                    previous_value,
                ),
                "trend": trend_direction(
                    current_value,
                    previous_value,
                ),
            }

        return jsonify({
            "ok": True,
            "period_mode": "settlement_16_to_15",
            "archived_now": archive_result.get("saved", 0),

            "current_period": {
                "start": (
                    current_start.strftime("%d.%m.%Y")
                    if current_start
                    else ""
                ),
                "end": (
                    period_display_end(current_end).strftime("%d.%m.%Y")
                    if current_end
                    else ""
                ),
            },
            "previous_period": {
                "start": (
                    previous_start.strftime("%d.%m.%Y")
                    if previous_start
                    else ""
                ),
                "end": (
                    period_display_end(previous_end).strftime("%d.%m.%Y")
                    if previous_end
                    else ""
                ),
            },

            "income": metric(current_income, previous_income),
            "expenses": metric(
                current_expenses,
                previous_expenses,
            ),
            "profit": metric(current_profit, previous_profit),
        })

    except Exception as error:
        session.rollback()

        return jsonify({
            "ok": False,
            "message": (
                "Ошибка показателей расчётного периода: "
                f"{type(error).__name__}: {error}"
            ),
        }), 500

    finally:
        session.close()


@bp.route("/api/cars-monthly-mileage")
def api_cars_monthly_mileage():
    session = Session()

    try:
        cars = (
            session.query(Car)
            .order_by(Car.code.asc())
            .all()
        )

        items = [
            car_monthly_mileage(session, car)
            for car in cars
        ]

        return jsonify({
            "ok": True,
            "month": date.today().replace(day=1).strftime("%m.%Y"),
            "items": items,
        })

    except Exception as error:
        return jsonify({
            "ok": False,
            "message": f"Ошибка расчёта пробега: {error}",
        }), 500

    finally:
        session.close()


@bp.route("/api/cars")
def api_cars():
    """
    Возвращает список машин.

    Расчёты водителей, инвесторов и простоев выполняются отдельно
    для каждой машины. Ошибка одного дополнительного расчёта больше
    не может скрыть весь автопарк.
    """
    session = Session()
    ensure_all_previous_periods_saved(session)

    try:
        cars_query = session.query(Car).order_by(Car.code.asc()).all()
        result = []

        for car in cars_query:
            code = normalize_code(getattr(car, "code", ""))

            income = 0
            expenses = 0
            investments = 0
            downtime_days = 0

            try:
                period_start, period_end = period_bounds_for_car(car)
                period_calc = calculate_period_for_car(
                    session,
                    car,
                    period_start,
                    period_end,
                )

                income = int(period_calc["income"] or 0)
                expenses = int(period_calc["expenses"] or 0)
                investments = int(
                    period_calc["investments"] or 0
                )
                downtime_days = int(
                    period_calc["downtime_days"] or 0
                )

            except Exception as error:
                print(
                    f"Ошибка финансов текущего периода "
                    f"машины {code}: "
                    f"{type(error).__name__}: {error}"
                )

            try:
                active_downtime = current_downtime_for_car(
                    session,
                    code,
                )
            except Exception as error:
                print(
                    f"Ошибка простоя машины {code}: "
                    f"{type(error).__name__}: {error}"
                )
                active_downtime = None

            try:
                driver_payment = calculate_driver_payment(
                    session,
                    car,
                )
                driver_payment_error = ""
            except Exception as error:
                print(
                    f"Ошибка расчёта водителя {code}: "
                    f"{type(error).__name__}: {error}"
                )

                driver_payment = {
                    "daily_rent": int(
                        getattr(car, "daily_rent", 0) or 0
                    ),
                    "effective_daily_rent": (
                        effective_daily_rent(car)
                        if "effective_daily_rent" in globals()
                        else 0
                    ),
                    "weekly_payment": int(
                        getattr(car, "weekly_payment", 0) or 0
                    ),
                    "overdue_periods": [],
                    "overdue_periods_count": 0,
                    "overdue_total": 0,
                    "current_period": {},
                    "current_amount": 0,
                    "amount_due": 0,
                    "next_payment_date": (
                        getattr(car, "next_payment_date", "") or ""
                    ),
                    "is_overdue": False,
                }
                driver_payment_error = (
                    f"{type(error).__name__}: {error}"
                )

            mileage = int(
                getattr(car, "current_mileage", 0)
                or getattr(car, "mileage", 0)
                or 0
            )

            result.append({
                "code": code,
                "brand": getattr(car, "brand", "") or "",
                "model": getattr(car, "model", "") or "",
                "plate": getattr(car, "plate", "") or "",
                "mileage": mileage,

                "income": int(income or 0),
                "expenses": int(expenses or 0),
                "profit": int((income or 0) - (expenses or 0)),
                "period_start": (
                    period_start.strftime("%d.%m.%Y")
                    if 'period_start' in locals()
                    else ""
                ),
                "period_end": (
                    period_display_end(period_end).strftime("%d.%m.%Y")
                    if 'period_end' in locals()
                    else ""
                ),

                "purchase_price": int(
                    getattr(car, "purchase_price", 0) or 0
                ),
                "full_cost": int(
                    (getattr(car, "purchase_price", 0) or 0)
                    + (investments or 0)
                ),

                "owner_type": (
                    getattr(car, "owner_type", "own") or "own"
                ),
                "investor_name": (
                    getattr(car, "investor_name", "") or ""
                ),
                "investor_percent": int(
                    getattr(car, "investor_percent", 0) or 0
                ),

                "downtime_days": int(downtime_days or 0),
                "is_in_downtime": bool(active_downtime),
                "current_status": (
                    "Простой"
                    if active_downtime
                    else "Работает"
                ),
                "downtime_start": (
                    active_downtime.get("start_date", "")
                    if active_downtime
                    else ""
                ),
                "current_downtime_days": int(
                    active_downtime.get("days", 0)
                    if active_downtime
                    else 0
                ),
                "downtime_reason": (
                    active_downtime.get("reason", "")
                    if active_downtime
                    else ""
                ),
                "downtime_comment": (
                    active_downtime.get("comment", "")
                    if active_downtime
                    else ""
                ),

                "settlement_day": int(
                    getattr(car, "settlement_day", 15) or 15
                ),
                "driver": getattr(car, "driver", "") or "",
                "weekly_payment": int(
                    getattr(car, "weekly_payment", 0) or 0
                ),
                "daily_rent": int(
                    getattr(car, "daily_rent", 0) or 0
                ),
                "driver_deposit": int(
                    getattr(car, "driver_deposit", 0) or 0
                ),
                "effective_daily_rent": (
                    effective_daily_rent(car)
                    if "effective_daily_rent" in globals()
                    else 0
                ),
                "payment_weekday": int(
                    getattr(car, "payment_weekday", 0) or 0
                ),
                "last_payment_date": (
                    getattr(car, "last_payment_date", "") or ""
                ),
                "next_payment_date": (
                    getattr(car, "next_payment_date", "") or ""
                ),
                "payment_notifications": int(
                    getattr(car, "payment_notifications", 0) or 0
                ),

                "driver_payment": driver_payment,
                "driver_payment_error": driver_payment_error,
            })

        return jsonify(result)

    except Exception as error:
        print(
            "Критическая ошибка /api/cars:",
            type(error).__name__,
            str(error),
        )

        return jsonify({
            "ok": False,
            "message": (
                "Не удалось загрузить автопарк: "
                f"{type(error).__name__}: {error}"
            ),
        }), 500

    finally:
        session.close()


@bp.route("/api/car/<code>")
def api_car(code):
    session = Session()
    car = find_car(session, code)
    if not car:
        session.close()
        return jsonify({"ok": False, "message": "Машина не найдена"})

    reconcile_downtime_for_car(session, car.code, commit=True)

    income, expenses, investments, payouts, investor_invested, downtime_days = car_finance(session, car.code)
    active_downtime = current_downtime_for_car(session, car.code)
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
        "investor_percent": car.investor_percent or 0,
        "downtime_days": downtime_days,
        "is_in_downtime": bool(active_downtime),
        "current_status": "Простой" if active_downtime else "Работает",
        "downtime_start": active_downtime["start_date"] if active_downtime else "",
        "current_downtime_days": active_downtime["days"] if active_downtime else 0,
        "downtime_reason": active_downtime["reason"] if active_downtime else "",
        "downtime_comment": active_downtime["comment"] if active_downtime else "",
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

    try:
        car = find_car(session, code)

        if not car:
            return jsonify({
                "ok": False,
                "message": "Машина не найдена",
            }), 404

        # При первом открытии после начала нового периода
        # предыдущий период автоматически сохраняется в истории.
        archived_period, archived_now = ensure_previous_period_saved(
            session,
            car,
        )

        start, end = period_bounds_for_car(car)
        calc = calculate_period_for_car(
            session,
            car,
            start,
            end,
        )

        periods = []

        closed_rows = (
            session.query(SettlementPeriod)
            .filter(
                func.trim(SettlementPeriod.car_code)
                == normalize_code(car.code)
            )
            .order_by(
                SettlementPeriod.end_date.desc(),
                SettlementPeriod.id.desc(),
            )
            .all()
        )

        for period in closed_rows:
            periods.append({
                "id": period.id,
                "start_date": (
                    period.start_date.strftime("%d.%m.%Y")
                    if period.start_date
                    else ""
                ),
                "end_date": (
                    period_display_end(period.end_date).strftime("%d.%m.%Y")
                    if period.end_date
                    else ""
                ),
                "income": period.income or 0,
                "expenses": period.expenses or 0,
                "profit": period.profit or 0,
                "investor_amount": period.investor_amount or 0,
                "owner_amount": period.owner_amount or 0,
                "downtime_days": period.downtime_days or 0,
                "comment": period.comment or "",
                "closed_at": (
                    period.closed_at.strftime("%d.%m.%Y %H:%M")
                    if period.closed_at
                    else ""
                ),
            })

        return jsonify({
            "ok": True,
            "period_source": "current_auto",
            "archived_previous_now": archived_now,
            "archived_period": {
                "start_date": (
                    archived_period.start_date.strftime("%d.%m.%Y")
                    if archived_period
                    else ""
                ),
                "end_date": (
                    archived_period_display_end(period.end_date).strftime("%d.%m.%Y")
                    if archived_period
                    else ""
                ),
            },
            "settlement_day": car.settlement_day or 15,
            "current_period": {
                "start_date": start.strftime("%d.%m.%Y"),
                "end_date": period_display_end(
                    end
                ).strftime("%d.%m.%Y"),
                **calc,
            },
            "closed_periods": periods,
        })

    except Exception as error:
        session.rollback()
        return jsonify({
            "ok": False,
            "message": f"Ошибка расчётного периода: {error}",
        }), 500

    finally:
        session.close()


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



@bp.route("/api/reopen-period/<code>", methods=["POST"])
def api_reopen_period(code):
    """
    Удаляет последний закрытый расчётный период машины.

    После этого период снова можно пересчитать и закрыть заново.
    Доходы, расходы и остальные операции машины не удаляются.
    """
    session = Session()

    try:
        car = find_car(session, code)

        if not car:
            return jsonify({
                "ok": False,
                "message": "Машина не найдена",
            }), 404

        latest_period = (
            session.query(SettlementPeriod)
            .filter(
                func.trim(SettlementPeriod.car_code)
                == normalize_code(car.code)
            )
            .order_by(
                SettlementPeriod.end_date.desc(),
                SettlementPeriod.id.desc(),
            )
            .first()
        )

        if not latest_period:
            return jsonify({
                "ok": False,
                "message": "У машины нет закрытых периодов",
            }), 404

        period_start = latest_period.start_date
        period_end = latest_period.end_date
        period_comment = latest_period.comment or ""

        # Удаляем служебную операцию закрытия именно этого периода.
        settlement_operation = None

        if period_comment:
            settlement_operation = (
                session.query(Operation)
                .filter(
                    func.trim(Operation.car_code)
                    == normalize_code(car.code),
                    Operation.type == "settlement_period",
                    Operation.description == period_comment,
                )
                .order_by(Operation.id.desc())
                .first()
            )

        if not settlement_operation:
            settlement_operation = (
                session.query(Operation)
                .filter(
                    func.trim(Operation.car_code)
                    == normalize_code(car.code),
                    Operation.type == "settlement_period",
                )
                .order_by(Operation.id.desc())
                .first()
            )

        if settlement_operation:
            session.delete(settlement_operation)

        session.delete(latest_period)
        session.commit()

        return jsonify({
            "ok": True,
            "message": (
                "Последний период открыт заново. "
                "Теперь исправь записи и снова нажми «Закрыть период»."
            ),
            "car_code": car.code,
            "period_start": (
                period_start.strftime("%d.%m.%Y")
                if period_start
                else ""
            ),
            "period_end": (
                period_end.strftime("%d.%m.%Y")
                if period_end
                else ""
            ),
        })

    except Exception as error:
        session.rollback()
        print(f"Ошибка открытия периода: {error}")

        return jsonify({
            "ok": False,
            "message": f"Не удалось открыть период: {error}",
        }), 500

    finally:
        session.close()



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



def apply_investor_portfolio_netting(car_rows):
    """
    Объединяет взаиморасчёт по всем машинам одного инвестора.

    Правила:
    1. Долг одной машины сначала закрывается суммой к выплате
       по другим машинам этого же инвестора.
    2. Пока общей суммы к выплате хватает, долг не показывается.
    3. Удержание долга распределяется максимально равномерно
       между машинами, у которых есть сумма к выплате.
    4. Только если общий долг больше общей суммы к выплате,
       остаток долга делится поровну между всеми машинами.
    """
    if not car_rows:
        return {
            "gross_available": 0,
            "gross_debt": 0,
            "net_available": 0,
            "net_debt": 0,
            "portfolio_withheld": 0,
        }

    gross_available = sum(
        max(int(row.get("available_to_pay", 0) or 0), 0)
        for row in car_rows
    )
    gross_debt = sum(
        max(int(row.get("investor_debt_to_park", 0) or 0), 0)
        for row in car_rows
    )

    debt_to_offset = min(gross_available, gross_debt)

    # Сначала обнуляем отображаемый долг: он будет рассчитан заново
    # только если после взаимозачёта действительно останется.
    for row in car_rows:
        row["original_available_to_pay"] = max(
            int(row.get("available_to_pay", 0) or 0),
            0,
        )
        row["original_investor_debt"] = max(
            int(row.get("investor_debt_to_park", 0) or 0),
            0,
        )
        row["portfolio_debt_withheld"] = 0
        row["investor_debt_to_park"] = 0

    # Равномерно удерживаем долг с машин, по которым есть выплата.
    remaining = debt_to_offset
    active_indexes = [
        index
        for index, row in enumerate(car_rows)
        if row["original_available_to_pay"] > 0
    ]

    while remaining > 0 and active_indexes:
        equal_part = max(
            remaining // len(active_indexes),
            1,
        )
        next_indexes = []
        deducted_this_round = 0

        for index in active_indexes:
            row = car_rows[index]
            current_available = max(
                int(row.get("available_to_pay", 0) or 0),
                0,
            )

            deduction = min(
                equal_part,
                current_available,
                remaining - deducted_this_round,
            )

            row["available_to_pay"] = (
                current_available - deduction
            )
            row["portfolio_debt_withheld"] += deduction
            deducted_this_round += deduction

            if row["available_to_pay"] > 0:
                next_indexes.append(index)

            if deducted_this_round >= remaining:
                break

        if deducted_this_round <= 0:
            break

        remaining -= deducted_this_round
        active_indexes = next_indexes

    net_available = max(gross_available - gross_debt, 0)
    net_debt = max(gross_debt - gross_available, 0)

    # Если выплаты не хватило, оставшийся долг распределяем поровну
    # между всеми машинами инвестора.
    if net_debt > 0:
        count = len(car_rows)
        base = net_debt // count
        remainder = net_debt % count

        for index, row in enumerate(car_rows):
            row["available_to_pay"] = 0
            row["investor_debt_to_park"] = (
                base + (1 if index < remainder else 0)
            )

    for row in car_rows:
        # Общее удержание включает старые удержания конкретной машины
        # и новый взаимозачёт между машинами.
        row["withheld"] = (
            int(row.get("withheld", 0) or 0)
            + int(row.get("portfolio_debt_withheld", 0) or 0)
        )

    return {
        "gross_available": gross_available,
        "gross_debt": gross_debt,
        "net_available": net_available,
        "net_debt": net_debt,
        "portfolio_withheld": debt_to_offset,
    }


@bp.route("/api/investors-summary")
def api_investors_summary():
    session = Session()
    ensure_all_previous_periods_saved(session)

    try:
        cleanup_legacy_investor_mess(session)

        names = [
            row[0]
            for row in (
                session.query(Car.investor_name)
                .filter(
                    Car.owner_type == "investor",
                    Car.investor_name != "",
                )
                .distinct()
                .all()
            )
        ]

        investors = []

        totals = {
            "total_invested": 0,
            "total_payouts": 0,
            "income": 0,
            "expenses": 0,
            "profit": 0,
            "investor_share": 0,
            "owner_share": 0,
            "investor_debt_to_park": 0,
            "park_debt_to_investor": 0,
            "available_to_pay": 0,
            "portfolio_debt_offset": 0,
        }

        for name in names:
            cars = (
                session.query(Car)
                .filter_by(
                    owner_type="investor",
                    investor_name=name,
                )
                .all()
            )

            car_rows = []

            row = {
                "name": name,
                "cars_count": len(cars),
                "total_invested": 0,
                "total_payouts": 0,
                "income": 0,
                "expenses": 0,
                "profit": 0,
                "investor_share": 0,
                "owner_share": 0,
                "investor_debt_to_park": 0,
                "park_debt_to_investor": 0,
                "available_to_pay": 0,
                "portfolio_debt_offset": 0,
            }

            for car in cars:
                # При первом запросе после 16-го предыдущий период
                # автоматически сохраняется в истории.
                ensure_previous_period_saved(session, car)

                start, end = period_bounds_for_car(car)
                calc = calculate_period_for_car(
                    session,
                    car,
                    start,
                    end,
                )

                car_total_invested = investor_total_invested_for_car(
                    session,
                    car,
                )

                income = calc["income"]
                expenses = calc["expenses"]
                profit_for_split = calc["profit_for_split"]
                investor_share = calc["accrued_to_investor"]
                available = calc["available_to_pay"]
                debt = calc["investor_debt_to_park"]
                park_debt = calc["park_debt_to_investor"]
                payouts = calc["payouts_in_period"]
                owner_share = calc["owner_amount"]

                car_rows.append({
                    "available_to_pay": available,
                    "investor_debt_to_park": debt,
                    "withheld": max(
                        investor_share
                        + park_debt
                        - payouts
                        - available,
                        0,
                    ),
                })

                row["total_invested"] += car_total_invested
                row["total_payouts"] += payouts
                row["income"] += income
                row["expenses"] += expenses
                row["profit"] += profit_for_split
                row["investor_share"] += investor_share
                row["owner_share"] += owner_share
                row["park_debt_to_investor"] += park_debt

            portfolio = apply_investor_portfolio_netting(car_rows)

            row["available_to_pay"] = portfolio["net_available"]
            row["investor_debt_to_park"] = portfolio["net_debt"]
            row["portfolio_debt_offset"] = (
                portfolio["portfolio_withheld"]
            )

            investors.append(row)

            for key in totals:
                totals[key] += row.get(key, 0)

        return jsonify({
            "period_mode": "current_16_to_15",
            "server_date_moscow": moscow_now().strftime(
                "%d.%m.%Y %H:%M"
            ),
            "investors_count": len(investors),
            "investors": investors,
            **totals,
        })

    except Exception as error:
        session.rollback()
        return jsonify({
            "ok": False,
            "message": (
                "Ошибка текущего периода инвесторов: "
                f"{type(error).__name__}: {error}"
            ),
        }), 500

    finally:
        session.close()


@bp.route("/api/investors")
def api_investors():
    session = Session()
    ensure_all_previous_periods_saved(session)

    try:
        cleanup_legacy_investor_mess(session)

        names = [
            row[0]
            for row in (
                session.query(Car.investor_name)
                .filter(
                    Car.owner_type == "investor",
                    Car.investor_name != "",
                )
                .distinct()
                .all()
            )
        ]

        result = []

        for name in names:
            cars = (
                session.query(Car)
                .filter_by(
                    owner_type="investor",
                    investor_name=name,
                )
                .all()
            )

            details = []

            totals = {
                "total_invested": 0,
                "total_income": 0,
                "total_shared_expenses": 0,
                "total_investor_only_expenses": 0,
                "total_payouts": 0,
                "total_profit_for_split": 0,
                "total_accrued": 0,
                "total_withheld": 0,
                "total_park_share": 0,
                "investor_debt_to_park": 0,
                "park_debt_to_investor": 0,
                "available_to_pay": 0,
            }

            portfolio_rows = []

            for car in cars:
                ensure_previous_period_saved(session, car)

                start, end = period_bounds_for_car(car)
                calc = calculate_period_for_car(
                    session,
                    car,
                    start,
                    end,
                )

                car_total_invested = investor_total_invested_for_car(
                    session,
                    car,
                )

                income = calc["income"]
                shared_expenses = calc["shared_expenses"]
                investor_only_expenses = (
                    calc["investor_only_expenses"]
                )
                profit_for_split = calc["profit_for_split"]
                investor_share = calc["accrued_to_investor"]
                available_to_pay = calc["available_to_pay"]
                investor_debt = calc["investor_debt_to_park"]
                car_payouts = calc["payouts_in_period"]
                park_share = calc["owner_amount"]
                park_debt = calc["park_debt_to_investor"]

                withheld = max(
                    investor_share
                    + park_debt
                    - car_payouts
                    - available_to_pay,
                    0,
                )

                portfolio_rows.append({
                    "available_to_pay": available_to_pay,
                    "investor_debt_to_park": investor_debt,
                    "withheld": withheld,
                })

                totals["total_invested"] += car_total_invested
                totals["total_income"] += income
                totals["total_shared_expenses"] += shared_expenses
                totals[
                    "total_investor_only_expenses"
                ] += investor_only_expenses
                totals["total_payouts"] += car_payouts
                totals["total_profit_for_split"] += profit_for_split
                totals["total_accrued"] += investor_share
                totals["total_withheld"] += withheld
                totals["total_park_share"] += park_share
                totals["available_to_pay"] += available_to_pay
                totals["investor_debt_to_park"] += investor_debt
                totals["park_debt_to_investor"] += park_debt

                details.append({
                    "code": car.code,
                    "car": (
                        f"{car.brand or ''} {car.model or ''}"
                    ).strip(),
                    "percent": car.investor_percent or 0,
                    "period_start": start.strftime("%d.%m.%Y"),
                    "period_end": period_display_end(
                        end
                    ).strftime("%d.%m.%Y"),
                    "invested": car_total_invested,
                    "income": income,
                    "shared_expenses": shared_expenses,
                    "investor_only_expenses":
                        investor_only_expenses,
                    "profit_for_split": profit_for_split,
                    "accrued_to_investor": investor_share,
                    "withheld": withheld,
                    "paid": car_payouts,
                    "available_to_pay": available_to_pay,
                    "investor_debt_to_park": investor_debt,
                    "park_debt_to_investor": park_debt,
                    "park_share": park_share,
                })

            portfolio = apply_investor_portfolio_netting(
                portfolio_rows
            )

            totals["available_to_pay"] = portfolio["net_available"]
            totals["investor_debt_to_park"] = portfolio["net_debt"]
            totals["total_withheld"] = (
                portfolio["portfolio_withheld"]
            )

            result.append({
                "name": name,
                "cars_count": len(cars),
                "period_mode": "current_16_to_15",
                "cars": details,
                **totals,
            })

        return jsonify(result)

    except Exception as error:
        session.rollback()
        return jsonify({
            "ok": False,
            "message": (
                "Ошибка списка инвесторов: "
                f"{type(error).__name__}: {error}"
            ),
        }), 500

    finally:
        session.close()


@bp.route("/api/warehouse/check-match", methods=["POST"])
def api_warehouse_check_match():
    payload = request.get_json(silent=True) or {}

    part_name = (payload.get("part_name") or "").strip()
    brand = (payload.get("brand") or "").strip()

    session = Session()

    try:
        item = find_warehouse_item(
            session,
            part_name,
            brand,
        )

        return jsonify({
            "ok": bool(item),
            "searched_part": part_name,
            "searched_brand": brand,
            "normalized_part": normalize_warehouse_text(part_name),
            "normalized_brand": normalize_warehouse_text(brand),
            "matched_item": (
                {
                    "id": item.id,
                    "part_name": item.part_name,
                    "brand": item.brand or "",
                    "quantity": item.quantity or 0,
                }
                if item
                else None
            ),
        })

    finally:
        session.close()


@bp.route("/api/warehouse")
def api_warehouse():
    session = Session()

    try:
        items = []

        for item in (
            session.query(WarehouseItem)
            .order_by(
                WarehouseItem.part_name,
                WarehouseItem.brand,
                WarehouseItem.variant,
            )
            .all()
        ):
            items.append({
                "id": item.id,
                "part_name": item.part_name or "",
                "brand": item.brand or "",
                "variant": getattr(item, "variant", "") or "",
                "quantity": item.quantity or 0,
                "min_quantity": item.min_quantity or 0,
                "shelf": item.shelf or "",
                "comment": item.comment or "",
                "low_stock": (
                    (item.quantity or 0)
                    <= (item.min_quantity or 0)
                ),
            })

        return jsonify(items)

    finally:
        session.close()


@bp.route("/api/warehouse/add-item", methods=["POST"])
def api_warehouse_add_item():
    payload = request.get_json(silent=True) or {}

    part_name = (payload.get("part_name") or "").strip()
    brand = (payload.get("brand") or "").strip().upper()
    variant = (payload.get("variant") or "").strip()
    shelf = (payload.get("shelf") or "").strip()
    comment = (payload.get("comment") or "").strip()

    quantity = only_int(payload.get("quantity"))
    min_quantity = only_int(payload.get("min_quantity"))

    if not part_name:
        return jsonify({
            "ok": False,
            "message": "Укажи название детали",
        }), 400

    session = Session()

    try:
        existing = find_exact_warehouse_item(
            session,
            part_name,
            brand,
            variant,
        )

        if existing:
            return jsonify({
                "ok": False,
                "message": (
                    "Такая позиция с тем же брендом и исполнением "
                    "уже есть. Используй кнопку «Приход»."
                ),
            }), 400

        item = WarehouseItem(
            part_name=part_name,
            brand=brand,
            variant=variant,
            quantity=max(quantity, 0),
            min_quantity=max(min_quantity, 0),
            shelf=shelf,
            comment=comment,
        )
        session.add(item)
        session.flush()

        if quantity > 0:
            session.add(
                WarehouseMovement(
                    operation_id=None,
                    car_code="",
                    part_name=part_name,
                    brand=brand,
                    variant=variant,
                    quantity=quantity,
                    movement_type="in",
                    comment="Первоначальный остаток",
                )
            )

        session.commit()

        return jsonify({
            "ok": True,
            "message": (
                f"Добавлено на склад: {part_name}"
                f"{' ' + brand if brand else ''}"
                f"{' · ' + variant if variant else ''}. "
                f"Остаток: {max(quantity, 0)} шт."
            ),
        })

    except Exception as error:
        session.rollback()
        return jsonify({
            "ok": False,
            "message": f"Не удалось добавить деталь: {error}",
        }), 500

    finally:
        session.close()


@bp.route("/api/warehouse/restock", methods=["POST"])
def api_warehouse_restock():
    payload = request.get_json(silent=True) or {}

    item_id = only_int(payload.get("item_id"))
    quantity = only_int(payload.get("quantity"))
    comment = (payload.get("comment") or "").strip()

    if not item_id or quantity <= 0:
        return jsonify({
            "ok": False,
            "message": "Выбери деталь и укажи количество больше нуля",
        }), 400

    session = Session()

    try:
        item = (
            session.query(WarehouseItem)
            .filter_by(id=item_id)
            .first()
        )

        if not item:
            return jsonify({
                "ok": False,
                "message": "Позиция склада не найдена",
            }), 404

        item.quantity = (item.quantity or 0) + quantity

        session.add(
            WarehouseMovement(
                operation_id=None,
                car_code="",
                part_name=item.part_name,
                brand=item.brand or "",
                variant=getattr(item, "variant", "") or "",
                quantity=quantity,
                movement_type="in",
                comment=comment or "Приход на склад",
            )
        )

        session.commit()

        return jsonify({
            "ok": True,
            "message": (
                f"Приход записан. "
                f"{item.part_name}"
                f"{' ' + item.brand if item.brand else ''}: "
                f"{item.quantity} шт."
            ),
        })

    except Exception as error:
        session.rollback()
        return jsonify({
            "ok": False,
            "message": f"Не удалось записать приход: {error}",
        }), 500

    finally:
        session.close()



@bp.route("/api/warehouse/adjust", methods=["POST"])
def api_warehouse_adjust():
    payload = request.get_json(silent=True) or {}
    item_id = only_int(payload.get("item_id"))
    new_quantity = only_int(payload.get("new_quantity"))
    comment = (payload.get("comment") or "").strip()

    if not item_id:
        return jsonify({"ok": False, "message": "Выбери складскую позицию"}), 400
    if new_quantity < 0:
        return jsonify({"ok": False, "message": "Количество не может быть меньше нуля"}), 400

    session = Session()
    try:
        item = session.query(WarehouseItem).filter_by(id=item_id).first()
        if not item:
            return jsonify({"ok": False, "message": "Позиция склада не найдена"}), 404

        old_quantity = item.quantity or 0
        difference = new_quantity - old_quantity

        if difference == 0:
            return jsonify({"ok": True, "message": "Количество не изменилось"})

        item.quantity = new_quantity
        session.add(WarehouseMovement(
            operation_id=None,
            car_code="",
            part_name=item.part_name,
            brand=item.brand or "",
            variant=getattr(item, "variant", "") or "",
            quantity=abs(difference),
            movement_type="adjustment_in" if difference > 0 else "adjustment_out",
            comment=comment or f"Исправление остатка: {old_quantity} → {new_quantity}",
        ))
        session.commit()

        return jsonify({
            "ok": True,
            "message": (
                f"Остаток исправлен: {item.part_name}"
                f"{' ' + item.brand if item.brand else ''}"
                f"{' · ' + item.variant if getattr(item, 'variant', '') else ''}: "
                f"{old_quantity} → {new_quantity} шт."
            ),
        })
    except Exception as error:
        session.rollback()
        return jsonify({"ok": False, "message": f"Не удалось исправить остаток: {error}"}), 500
    finally:
        session.close()


@bp.route("/api/warehouse/write-off", methods=["POST"])
def api_warehouse_write_off():
    payload = request.get_json(silent=True) or {}
    item_id = only_int(payload.get("item_id"))
    quantity = only_int(payload.get("quantity"))
    comment = (payload.get("comment") or "").strip()

    if not item_id:
        return jsonify({"ok": False, "message": "Выбери складскую позицию"}), 400
    if quantity <= 0:
        return jsonify({"ok": False, "message": "Укажи количество для списания"}), 400

    session = Session()
    try:
        item = session.query(WarehouseItem).filter_by(id=item_id).first()
        if not item:
            return jsonify({"ok": False, "message": "Позиция склада не найдена"}), 404

        current = item.quantity or 0
        if quantity > current:
            return jsonify({
                "ok": False,
                "message": f"Нельзя списать {quantity} шт. На складе только {current} шт.",
            }), 400

        item.quantity = current - quantity
        session.add(WarehouseMovement(
            operation_id=None,
            car_code="",
            part_name=item.part_name,
            brand=item.brand or "",
            variant=getattr(item, "variant", "") or "",
            quantity=quantity,
            movement_type="manual_out",
            comment=comment or "Ручное списание",
        ))
        session.commit()

        return jsonify({
            "ok": True,
            "message": (
                f"Списано: {item.part_name}"
                f"{' ' + item.brand if item.brand else ''}"
                f"{' · ' + item.variant if getattr(item, 'variant', '') else ''} — "
                f"{quantity} шт. Остаток: {item.quantity} шт."
            ),
        })
    except Exception as error:
        session.rollback()
        return jsonify({"ok": False, "message": f"Не удалось списать: {error}"}), 500
    finally:
        session.close()


@bp.route("/api/warehouse/update-item", methods=["POST"])
def api_warehouse_update_item():
    payload = request.get_json(silent=True) or {}
    item_id = only_int(payload.get("item_id"))
    part_name = (payload.get("part_name") or "").strip()
    brand = (payload.get("brand") or "").strip().upper()
    variant = (payload.get("variant") or "").strip()
    shelf = (payload.get("shelf") or "").strip()
    comment = (payload.get("comment") or "").strip()
    min_quantity = only_int(payload.get("min_quantity"))

    if not item_id:
        return jsonify({"ok": False, "message": "Позиция склада не выбрана"}), 400
    if not part_name:
        return jsonify({"ok": False, "message": "Название детали не может быть пустым"}), 400
    if min_quantity < 0:
        return jsonify({"ok": False, "message": "Минимальный остаток не может быть меньше нуля"}), 400

    session = Session()
    try:
        item = session.query(WarehouseItem).filter_by(id=item_id).first()
        if not item:
            return jsonify({"ok": False, "message": "Позиция склада не найдена"}), 404

        duplicate = find_exact_warehouse_item(session, part_name, brand, variant)
        if duplicate and duplicate.id != item.id:
            return jsonify({
                "ok": False,
                "message": "Позиция с таким названием, брендом и исполнением уже существует",
            }), 400

        item.part_name = part_name
        item.brand = brand
        item.variant = variant
        item.min_quantity = min_quantity
        item.shelf = shelf
        item.comment = comment
        session.commit()

        return jsonify({"ok": True, "message": "Позиция склада обновлена"})
    except Exception as error:
        session.rollback()
        return jsonify({"ok": False, "message": f"Не удалось обновить позицию: {error}"}), 500
    finally:
        session.close()


@bp.route("/api/warehouse/delete-item/<int:item_id>", methods=["POST"])
def api_warehouse_delete_item(item_id):
    session = Session()
    try:
        item = session.query(WarehouseItem).filter_by(id=item_id).first()
        if not item:
            return jsonify({"ok": False, "message": "Позиция склада не найдена"}), 404
        if (item.quantity or 0) != 0:
            return jsonify({
                "ok": False,
                "message": "Сначала исправь остаток до 0. Позиции с ненулевым остатком удалять нельзя.",
            }), 400

        session.delete(item)
        session.commit()
        return jsonify({"ok": True, "message": "Позиция склада удалена"})
    except Exception as error:
        session.rollback()
        return jsonify({"ok": False, "message": f"Не удалось удалить позицию: {error}"}), 500
    finally:
        session.close()


@bp.route("/api/warehouse/movements")
def api_warehouse_movements():
    session = Session()

    try:
        rows = []

        for movement in (
            session.query(WarehouseMovement)
            .order_by(WarehouseMovement.id.desc())
            .limit(100)
            .all()
        ):
            rows.append({
                "id": movement.id,
                "date": (
                    movement.date.strftime("%d.%m.%Y %H:%M")
                    if movement.date
                    else ""
                ),
                "car_code": movement.car_code or "",
                "part_name": movement.part_name or "",
                "brand": movement.brand or "",
                "variant": getattr(movement, "variant", "") or "",
                "quantity": movement.quantity or 0,
                "movement_type": movement.movement_type or "",
                "comment": movement.comment or "",
            })

        return jsonify(rows)

    finally:
        session.close()


def delete_operation_dependencies(session, operation_id):
    """
    Удаляет операцию и связанные записи.

    Если операция списывала деталь со склада, остаток возвращается.
    """
    warehouse_movements = (
        session.query(WarehouseMovement)
        .filter_by(operation_id=operation_id)
        .all()
    )

    for movement in warehouse_movements:
        if movement.movement_type == "out":
            item = find_warehouse_item(
                session,
                movement.part_name,
                movement.brand,
            )
            if item:
                item.quantity = (
                    (item.quantity or 0)
                    + (movement.quantity or 0)
                )

        session.delete(movement)

    for model in (
        Income,
        Expense,
        Part,
        CarInvestment,
        InvestorInvestment,
        InvestorPayout,
        Downtime,
        InvestorSettlement,
    ):
        for row in (
            session.query(model)
            .filter_by(operation_id=operation_id)
            .all()
        ):
            session.delete(row)



@bp.route("/api/edit-operation/<int:operation_id>", methods=["POST"])
def api_edit_operation(operation_id):
    """
    Изменяет существующую запись ремонта или расхода.

    Складские списания не выполняются повторно:
    уже созданные WarehouseMovement сохраняются без изменений.
    После редактирования пересчитываются Expense, Part и пробег.
    """
    payload = request.get_json(silent=True) or {}
    new_message = (payload.get("message") or "").strip()
    new_date_raw = (payload.get("date") or "").strip()

    if not new_message:
        return jsonify({
            "ok": False,
            "message": "Введите исправленный текст записи",
        }), 400

    session = Session()

    try:
        operation = (
            session.query(Operation)
            .filter_by(id=operation_id)
            .first()
        )

        if not operation:
            return jsonify({
                "ok": False,
                "message": "Операция не найдена",
            }), 404

        if operation.type not in (
            "repair",
            "service",
            "expense",
        ):
            return jsonify({
                "ok": False,
                "message": (
                    "Пока можно изменять только ремонты "
                    "и обычные расходы"
                ),
            }), 400

        parsed = parse_message(new_message)
        parsed = enforce_repair_total_from_raw(parsed)

        if parsed.get("type") not in (
            "repair",
            "service",
            "expense",
        ):
            return jsonify({
                "ok": False,
                "message": (
                    "Исправленная команда должна оставаться "
                    "ремонтом или расходом"
                ),
            }), 400

        car_code = normalize_code(
            parsed.get("car_code")
            or operation.car_code
        )
        car = find_car(session, car_code)

        if not car:
            return jsonify({
                "ok": False,
                "message": f"Машина {car_code} не найдена",
            }), 404

        # При отсутствии номера в новом тексте сохраняем старую машину.
        parsed["car_code"] = car_code
        parsed["raw"] = new_message

        if new_date_raw:
            try:
                new_date = datetime.fromisoformat(new_date_raw)
            except ValueError:
                return jsonify({
                    "ok": False,
                    "message": "Дата указана неправильно",
                }), 400
        else:
            new_date = operation.date or datetime.now()

        # Удаляем только финансовые и детальные строки ремонта.
        # WarehouseMovement не трогаем, поэтому склад повторно
        # не списывается и остатки не меняются.
        for model in (Expense, Part):
            for row in (
                session.query(model)
                .filter_by(operation_id=operation_id)
                .all()
            ):
                session.delete(row)

        operation.date = new_date
        operation.car_code = car.code
        operation.type = parsed.get("type") or operation.type
        operation.category = parsed.get("category") or "Ремонт"
        operation.description = (
            parsed.get("description")
            or operation.description
            or "Ремонт / замена"
        )
        operation.amount = int(
            parsed.get("total")
            or parsed.get("amount")
            or 0
        )
        operation.mileage = parsed.get("mileage")
        operation.raw_message = new_message

        # Создаём заново Expense и Part на основании нового текста.
        create_dependencies_from_parsed(
            session,
            operation,
            car,
            parsed,
        )

        # Синхронизируем даты связанных записей с датой операции.
        for expense in (
            session.query(Expense)
            .filter_by(operation_id=operation_id)
            .all()
        ):
            expense.date = new_date

        for part in (
            session.query(Part)
            .filter_by(operation_id=operation_id)
            .all()
        ):
            part.install_date = new_date

        # Пересчитываем текущий пробег по максимальному известному.
        known_mileages = [
            int(value)
            for value, in (
                session.query(Operation.mileage)
                .filter(
                    func.trim(Operation.car_code)
                    == normalize_code(car.code),
                    Operation.mileage.isnot(None),
                    Operation.mileage > 0,
                )
                .all()
            )
            if value
        ]

        if known_mileages:
            car.current_mileage = max(
                known_mileages
                + [int(car.purchase_mileage or 0)]
            )

        session.commit()

        return jsonify({
            "ok": True,
            "message": (
                f"Операция #{operation_id} изменена. "
                "Доходы, расходы и детали пересчитаны."
            ),
            "operation": {
                "id": operation.id,
                "date": operation.date.isoformat(),
                "car_code": operation.car_code,
                "type": operation.type,
                "description": operation.description,
                "amount": operation.amount,
                "mileage": operation.mileage,
                "raw": operation.raw_message,
            },
        })

    except Exception as error:
        session.rollback()
        print(
            "Ошибка изменения операции:",
            type(error).__name__,
            str(error),
        )

        return jsonify({
            "ok": False,
            "message": (
                "Не удалось изменить запись: "
                f"{type(error).__name__}: {error}"
            ),
        }), 500

    finally:
        session.close()


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



def collect_investor_report_rows(
    session,
    investor_name,
    period_start,
    period_end,
):
    """
    Собирает подробности отчёта за любой выбранный период.
    Используется и для текущего отчёта, и для истории.
    """
    cars = (
        session.query(Car)
        .filter(
            Car.owner_type == "investor",
            func.lower(func.trim(Car.investor_name))
            == investor_name.lower(),
        )
        .order_by(Car.code)
        .all()
    )

    if not cars:
        return [], []

    report_rows = []

    for car in cars:
        period = (
            session.query(SettlementPeriod)
            .filter(
                func.trim(SettlementPeriod.car_code)
                == normalize_code(car.code),
                SettlementPeriod.start_date == period_start,
                SettlementPeriod.end_date == period_end,
            )
            .first()
        )

        calc = calculate_period_for_car(
            session,
            car,
            period_start,
            period_end,
        )

        expense_rows = []

        expenses = (
            session.query(Expense)
            .filter(
                func.trim(Expense.car_code)
                == normalize_code(car.code),
                Expense.date >= period_start,
                Expense.date < period_end,
            )
            .order_by(
                Expense.date.asc(),
                Expense.id.asc(),
            )
            .all()
        )

        for expense in expenses:
            operation = None
            parts = []

            if expense.operation_id:
                operation = (
                    session.query(Operation)
                    .filter_by(id=expense.operation_id)
                    .first()
                )
                parts = (
                    session.query(Part)
                    .filter_by(
                        operation_id=expense.operation_id
                    )
                    .order_by(Part.id.asc())
                    .all()
                )

            expense_type = (
                expense.share_type or "shared"
            ).strip().lower()

            if (
                operation
                and operation.type
                == "investor_expense_split"
            ):
                expense_type = "investor_only"

            if expense_type in {
                "investor_only",
                "investor",
                "investor-only",
                "только инвестор",
                "допрасход",
                "доп расход",
                "доп расходы",
            }:
                type_label = "Допрасход инвестора"
            elif expense_type in {
                "park_only",
                "park",
                "owner_only",
                "только парк",
            }:
                type_label = "Только парк"
            else:
                type_label = "Обычный расход"

            details = []

            for part in parts:
                part_text = part.part_name or "Деталь"

                if part.brand:
                    part_text += f", фирма {part.brand}"
                if part.position:
                    part_text += f", {part.position}"
                if part.price:
                    part_text += (
                        f", деталь {money(part.price)}"
                    )
                if part.labor:
                    part_text += (
                        f", работа {money(part.labor)}"
                    )
                if part.install_mileage:
                    part_text += (
                        f", пробег "
                        f"{int(part.install_mileage):,} км"
                    ).replace(",", " ")

                details.append(part_text)

            if operation and operation.description:
                description = operation.description.strip()

                if (
                    description
                    and description not in details
                ):
                    details.append(description)

            if operation and operation.raw_message:
                details.append(
                    "Комментарий: "
                    f"{operation.raw_message.strip()}"
                )

            if not details:
                details.append(
                    expense.category or "Расход"
                )

            expense_rows.append({
                "date": (
                    expense.date.strftime("%d.%m.%Y")
                    if expense.date
                    else ""
                ),
                "type_label": type_label,
                "description": "<br/>".join(details),
                "amount": expense.amount or 0,
            })

        downtime_rows = []
        downtime_days = 0

        for downtime in session.query(Downtime).all():
            if (
                normalize_code(downtime.car_code)
                != normalize_code(car.code)
            ):
                continue

            downtime_start = (
                downtime.start_date or period_start
            )
            downtime_end = (
                moscow_now()
                if downtime.active
                else (downtime.end_date or period_end)
            )

            overlap_start = max(
                downtime_start,
                period_start,
            )
            overlap_end = min(
                downtime_end,
                period_end,
            )

            if overlap_end <= overlap_start:
                continue

            days = max(
                (
                    overlap_end.date()
                    - overlap_start.date()
                ).days,
                1,
            )
            downtime_days += days

            reason_parts = []

            if downtime.reason:
                reason_parts.append(downtime.reason)

            clean_comment = clean_downtime_comment(
                downtime
            )

            if (
                clean_comment
                and clean_comment not in reason_parts
            ):
                reason_parts.append(
                    f"Комментарий: {clean_comment}"
                )

            downtime_rows.append({
                "start": overlap_start.strftime(
                    "%d.%m.%Y"
                ),
                "end": (
                    "по настоящее время"
                    if downtime.active
                    else overlap_end.strftime(
                        "%d.%m.%Y"
                    )
                ),
                "days": days,
                "reason": (
                    "<br/>".join(reason_parts)
                    or "Причина не указана"
                ),
            })

        report_rows.append({
            "code": car.code,
            "car_name": (
                f"{car.brand or ''} "
                f"{car.model or ''}"
            ).strip(),
            "percent": car.investor_percent or 0,
            "period_closed": period is not None,
            "income": calc.get("income", 0) or 0,
            "shared_expenses": (
                calc.get("shared_expenses", 0) or 0
            ),
            "profit_for_split": (
                calc.get("profit_for_split", 0) or 0
            ),
            "accrued_to_investor": (
                calc.get(
                    "accrued_to_investor",
                    0,
                )
                or 0
            ),
            "previous_investor_debt": (
                calc.get(
                    "previous_investor_debt",
                    0,
                )
                or 0
            ),
            "investor_only_expenses": (
                calc.get(
                    "investor_only_expenses",
                    0,
                )
                or 0
            ),
            "investor_paid_in_period": (
                calc.get(
                    "investor_paid_in_period",
                    0,
                )
                or 0
            ),
            "debt_repaid_by_profit": (
                calc.get(
                    "debt_repaid_by_profit",
                    0,
                )
                or 0
            ),
            "payouts_in_period": (
                calc.get(
                    "payouts_in_period",
                    0,
                )
                or 0
            ),
            "available_to_pay": (
                calc.get("available_to_pay", 0)
                or 0
            ),
            "investor_debt_to_park": (
                calc.get(
                    "investor_debt_to_park",
                    0,
                )
                or 0
            ),
            "park_only_expenses": (
                calc.get(
                    "park_only_expenses",
                    0,
                )
                or 0
            ),
            "owner_amount": (
                calc.get("owner_amount", 0) or 0
            ),
            "expense_rows": expense_rows,
            "downtime_rows": downtime_rows,
            "downtime_days": downtime_days,
        })

    apply_investor_portfolio_netting(report_rows)
    return cars, report_rows


def create_investor_report_bytes(
    session,
    investor_name,
    period_start,
    period_end,
):
    cars, report_rows = collect_investor_report_rows(
        session,
        investor_name,
        period_start,
        period_end,
    )

    if not cars:
        raise ValueError(
            f"Инвестор «{investor_name}» не найден"
        )

    pdf_bytes = build_investor_report_pdf(
        investor_name=investor_name,
        period_start=period_start,
        period_end=period_end,
        car_rows=report_rows,
    )

    filename = (
        f"report_{safe_filename(investor_name)}_"
        f"{period_start.strftime('%Y-%m-%d')}_"
        f"{period_display_end(period_end).strftime('%Y-%m-%d')}"
        ".pdf"
    )

    return pdf_bytes, filename, report_rows


def parse_report_period_dates(start_value, end_value):
    try:
        period_start = datetime.strptime(
            start_value,
            "%Y-%m-%d",
        )
        period_end = datetime.strptime(
            end_value,
            "%Y-%m-%d",
        )
    except (TypeError, ValueError):
        raise ValueError(
            "Неправильно указаны даты отчёта"
        )

    if period_start >= period_end:
        raise ValueError(
            "Дата начала должна быть раньше окончания"
        )

    return period_start, period_end


@bp.route(
    "/api/test-investor-report/<path:investor_name>",
    methods=["GET"],
)
def test_investor_report(investor_name):
    investor_name = unquote(investor_name).strip()
    session = Session()

    try:
        cleanup_legacy_investor_mess(session)
        reconcile_all_downtimes(
            session,
            commit=True,
        )

        cars = (
            session.query(Car)
            .filter(
                Car.owner_type == "investor",
                func.lower(
                    func.trim(Car.investor_name)
                )
                == investor_name.lower(),
            )
            .order_by(Car.code)
            .all()
        )

        if not cars:
            return jsonify({
                "ok": False,
                "message": (
                    f"Инвестор «{investor_name}» "
                    "не найден"
                ),
            }), 404

        period_start, period_end = (
            period_bounds_for_investor(cars)
        )

        pdf_bytes, filename, report_rows = (
            create_investor_report_bytes(
                session,
                investor_name,
                period_start,
                period_end,
            )
        )

        sent = send_telegram_document(
            pdf_bytes,
            filename,
            caption=(
                "📄 <b>Отчёт инвестора</b>\n"
                f"Инвестор: {investor_name}\n"
                f"Период: "
                f"{period_start.strftime('%d.%m.%Y')} — "
                f"{period_display_end(period_end).strftime('%d.%m.%Y')}\n"
                f"Машин в отчёте: {len(report_rows)}"
            ),
        )

        if not sent:
            return jsonify({
                "ok": False,
                "message": (
                    "PDF создан, но отправить "
                    "его в Telegram не удалось"
                ),
            }), 500

        return jsonify({
            "ok": True,
            "message": (
                "Отчёт сформирован "
                "и отправлен в Telegram"
            ),
            "investor": investor_name,
            "period_start": (
                period_start.isoformat()
            ),
            "period_end": period_end.isoformat(),
            "cars": len(report_rows),
        })

    except Exception as error:
        session.rollback()
        print(
            "Ошибка отчёта инвестора:",
            type(error).__name__,
            str(error),
        )

        return jsonify({
            "ok": False,
            "message": (
                "Ошибка создания отчёта: "
                f"{error}"
            ),
        }), 500

    finally:
        session.close()


@bp.route("/api/investor-report-history")
def api_investor_report_history():
    """
    Список сохранённых расчётных периодов
    по всем инвесторам.
    """
    session = Session()

    try:
        ensure_all_previous_periods_saved(session)

        investors = (
            session.query(Car.investor_name)
            .filter(
                Car.owner_type == "investor",
                Car.investor_name != "",
            )
            .distinct()
            .order_by(Car.investor_name)
            .all()
        )

        result = []

        for (investor_name,) in investors:
            cars = (
                session.query(Car)
                .filter(
                    Car.owner_type == "investor",
                    Car.investor_name
                    == investor_name,
                )
                .order_by(Car.code)
                .all()
            )

            car_codes = [
                normalize_code(car.code)
                for car in cars
            ]

            periods = (
                session.query(
                    SettlementPeriod.start_date,
                    SettlementPeriod.end_date,
                )
                .filter(
                    func.trim(
                        SettlementPeriod.car_code
                    ).in_(car_codes)
                )
                .distinct()
                .order_by(
                    SettlementPeriod.end_date.desc()
                )
                .all()
            )

            history = []

            for period_start, period_end in periods:
                snapshots = (
                    session.query(SettlementPeriod)
                    .filter(
                        func.trim(
                            SettlementPeriod.car_code
                        ).in_(car_codes),
                        SettlementPeriod.start_date
                        == period_start,
                        SettlementPeriod.end_date
                        == period_end,
                    )
                    .all()
                )

                history.append({
                    "start_iso": period_start.strftime(
                        "%Y-%m-%d"
                    ),
                    "end_iso": period_end.strftime(
                        "%Y-%m-%d"
                    ),
                    "start": period_start.strftime(
                        "%d.%m.%Y"
                    ),
                    "end": period_display_end(
                        period_end
                    ).strftime("%d.%m.%Y"),
                    "cars_saved": len(snapshots),
                    "cars_total": len(cars),
                    "complete": (
                        len(snapshots) == len(cars)
                    ),
                    "income": sum(
                        int(row.income or 0)
                        for row in snapshots
                    ),
                    "expenses": sum(
                        int(row.expenses or 0)
                        for row in snapshots
                    ),
                    "profit": sum(
                        int(row.profit or 0)
                        for row in snapshots
                    ),
                })

            result.append({
                "name": investor_name,
                "cars_total": len(cars),
                "periods": history,
            })

        return jsonify({
            "ok": True,
            "investors": result,
        })

    except Exception as error:
        session.rollback()

        return jsonify({
            "ok": False,
            "message": (
                "Ошибка истории отчётов: "
                f"{type(error).__name__}: {error}"
            ),
        }), 500

    finally:
        session.close()


@bp.route(
    "/api/investor-report-file/"
    "<path:investor_name>/<start_value>/<end_value>",
    methods=["GET"],
)
def download_investor_report(
    investor_name,
    start_value,
    end_value,
):
    investor_name = unquote(investor_name).strip()
    session = Session()

    try:
        period_start, period_end = (
            parse_report_period_dates(
                start_value,
                end_value,
            )
        )

        pdf_bytes, filename, _rows = (
            create_investor_report_bytes(
                session,
                investor_name,
                period_start,
                period_end,
            )
        )

        return send_file(
            io.BytesIO(pdf_bytes),
            mimetype="application/pdf",
            as_attachment=True,
            download_name=filename,
        )

    except ValueError as error:
        return jsonify({
            "ok": False,
            "message": str(error),
        }), 400

    except Exception as error:
        session.rollback()

        return jsonify({
            "ok": False,
            "message": (
                "Ошибка скачивания отчёта: "
                f"{error}"
            ),
        }), 500

    finally:
        session.close()


@bp.route(
    "/api/investor-report-regenerate/"
    "<path:investor_name>/<start_value>/<end_value>",
    methods=["POST"],
)
def regenerate_investor_report(
    investor_name,
    start_value,
    end_value,
):
    investor_name = unquote(investor_name).strip()
    session = Session()

    try:
        period_start, period_end = (
            parse_report_period_dates(
                start_value,
                end_value,
            )
        )

        pdf_bytes, filename, report_rows = (
            create_investor_report_bytes(
                session,
                investor_name,
                period_start,
                period_end,
            )
        )

        sent = send_telegram_document(
            pdf_bytes,
            filename,
            caption=(
                "📄 <b>Пересозданный отчёт</b>\n"
                f"Инвестор: {investor_name}\n"
                f"Период: "
                f"{period_start.strftime('%d.%m.%Y')} — "
                f"{period_display_end(period_end).strftime('%d.%m.%Y')}\n"
                f"Машин в отчёте: {len(report_rows)}"
            ),
        )

        return jsonify({
            "ok": sent,
            "message": (
                "Отчёт пересоздан и отправлен "
                "в Telegram"
                if sent
                else (
                    "Отчёт создан, но Telegram "
                    "не принял файл"
                )
            ),
        }), (200 if sent else 500)

    except ValueError as error:
        return jsonify({
            "ok": False,
            "message": str(error),
        }), 400

    except Exception as error:
        session.rollback()

        return jsonify({
            "ok": False,
            "message": (
                "Ошибка пересоздания отчёта: "
                f"{error}"
            ),
        }), 500

    finally:
        session.close()


@bp.route("/api/repair-downtime-statuses", methods=["POST", "GET"])
def api_repair_downtime_statuses():
    """
    Однократно исправляет старые рассинхронизированные простои.
    Безопасно запускать повторно.
    """
    session = Session()

    try:
        reconcile_all_downtimes(session, commit=True)

        result = []
        for car in session.query(Car).order_by(Car.code).all():
            active = current_downtime_for_car(session, car.code)
            result.append({
                "code": car.code,
                "status": "Простой" if active else "Работает",
                "start_date": active["start_date"] if active else "",
                "days": active["days"] if active else 0,
                "reason": active["reason"] if active else "",
            })

        return jsonify({
            "ok": True,
            "message": "Статусы простоев проверены и исправлены",
            "cars": result,
        })

    except Exception as error:
        session.rollback()
        return jsonify({
            "ok": False,
            "message": f"Ошибка исправления простоев: {error}",
        }), 500

    finally:
        session.close()


@bp.route("/api/operations")
def api_operations():
    session = Session()
    rows = [{
        "id": op.id,
        "date": op.date.strftime("%d.%m.%Y %H:%M"),
        "date_iso": (
            op.date.strftime("%Y-%m-%dT%H:%M")
            if op.date
            else ""
        ),
        "car_code": op.car_code, "type": op.type,
        "category": op.category, "description": op.description,
        "amount": op.amount, "mileage": op.mileage, "raw": op.raw_message,
    } for op in session.query(Operation).order_by(Operation.id.desc()).limit(80).all()]
    session.close()
    return jsonify(rows)
