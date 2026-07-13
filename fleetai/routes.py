import os
import io
import re
import requests

from pathlib import Path
from urllib.parse import unquote

from datetime import datetime, date, timedelta

from flask import Blueprint, request, jsonify, render_template_string
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
    period_bounds_for_car,
    calculate_period_for_car,
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
        "ReportTitle",
        parent=styles["Title"],
        fontName=font_name,
        fontSize=18,
        leading=22,
        alignment=TA_CENTER,
        spaceAfter=12,
    )

    heading_style = ParagraphStyle(
        "ReportHeading",
        parent=styles["Heading2"],
        fontName=font_name,
        fontSize=13,
        leading=17,
        spaceBefore=10,
        spaceAfter=7,
    )

    subheading_style = ParagraphStyle(
        "ReportSubheading",
        parent=styles["Heading3"],
        fontName=font_name,
        fontSize=11,
        leading=15,
        spaceBefore=8,
        spaceAfter=5,
    )

    normal_style = ParagraphStyle(
        "ReportNormal",
        parent=styles["BodyText"],
        fontName=font_name,
        fontSize=9,
        leading=13,
    )

    small_style = ParagraphStyle(
        "ReportSmall",
        parent=normal_style,
        fontSize=8,
        leading=11,
    )

    story = [
        Paragraph("Отчёт по расчётному периоду", title_style),
        Paragraph(f"<b>Инвестор:</b> {investor_name}", normal_style),
        Paragraph(
            "<b>Период:</b> "
            f"{period_start.strftime('%d.%m.%Y')} — "
            f"{period_end.strftime('%d.%m.%Y')}",
            normal_style,
        ),
        Paragraph(
            "<b>Сформирован:</b> "
            f"{datetime.now().strftime('%d.%m.%Y %H:%M')}",
            normal_style,
        ),
        Spacer(1, 8 * mm),
    ]

    total_income = 0
    total_shared = 0
    total_extra = 0
    total_park_only = 0
    total_investor_paid = 0
    total_available = 0
    total_owner = 0
    total_debt = 0
    total_downtime_days = 0

    for item in car_rows:
        total_income += item["income"]
        total_shared += item["shared_expenses"]
        total_extra += item["investor_only_expenses"]
        total_park_only += item["park_only_expenses"]
        total_investor_paid += item["investor_extra_paid"]
        total_available += item["available_to_pay"]
        total_owner += item["owner_amount"]
        total_debt += item["investor_debt_to_park"]
        total_downtime_days += item["downtime_days"]

        story.append(
            Paragraph(
                f"Машина {item['code']} — {item['car_name']}",
                heading_style,
            )
        )

        summary_data = [
            [
                Paragraph("<b>Показатель</b>", normal_style),
                Paragraph("<b>Сумма</b>", normal_style),
            ],
            [Paragraph("Доход", normal_style), Paragraph(money(item["income"]), normal_style)],
            [Paragraph("Обычные расходы", normal_style), Paragraph(money(item["shared_expenses"]), normal_style)],
            [Paragraph("Допрасходы инвестора", normal_style), Paragraph(money(item["investor_only_expenses"]), normal_style)],
            [Paragraph("Расходы только парка", normal_style), Paragraph(money(item["park_only_expenses"]), normal_style)],
            [Paragraph("Инвестор внёс", normal_style), Paragraph(money(item["investor_extra_paid"]), normal_style)],
            [Paragraph(f"Доля инвестора ({item['percent']}%)", normal_style), Paragraph(money(item["investor_share_total"]), normal_style)],
            [Paragraph("К выплате инвестору", normal_style), Paragraph(money(item["available_to_pay"]), normal_style)],
            [Paragraph("Доля парка", normal_style), Paragraph(money(item["owner_amount"]), normal_style)],
            [Paragraph("Долг инвестора", normal_style), Paragraph(money(item["investor_debt_to_park"]), normal_style)],
            [Paragraph("Дней простоя", normal_style), Paragraph(str(item["downtime_days"]), normal_style)],
        ]

        summary_table = Table(
            summary_data,
            colWidths=[115 * mm, 55 * mm],
            repeatRows=1,
        )
        summary_table.setStyle(
            TableStyle([
                ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#E5E7EB")),
                ("GRID", (0, 0), (-1, -1), 0.5, colors.HexColor("#D1D5DB")),
                ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
                ("LEFTPADDING", (0, 0), (-1, -1), 7),
                ("RIGHTPADDING", (0, 0), (-1, -1), 7),
                ("TOPPADDING", (0, 0), (-1, -1), 6),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 6),
            ])
        )
        story.append(summary_table)

        story.append(Paragraph("Куда ушли деньги", subheading_style))

        if item["expense_rows"]:
            expense_table_data = [[
                Paragraph("<b>Дата</b>", small_style),
                Paragraph("<b>Тип</b>", small_style),
                Paragraph("<b>Описание</b>", small_style),
                Paragraph("<b>Сумма</b>", small_style),
            ]]

            for expense in item["expense_rows"]:
                expense_table_data.append([
                    Paragraph(expense["date"], small_style),
                    Paragraph(expense["type_label"], small_style),
                    Paragraph(expense["description"], small_style),
                    Paragraph(money(expense["amount"]), small_style),
                ])

            expense_table = Table(
                expense_table_data,
                colWidths=[25 * mm, 35 * mm, 85 * mm, 25 * mm],
                repeatRows=1,
            )
            expense_table.setStyle(
                TableStyle([
                    ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#F3F4F6")),
                    ("GRID", (0, 0), (-1, -1), 0.4, colors.HexColor("#D1D5DB")),
                    ("VALIGN", (0, 0), (-1, -1), "TOP"),
                    ("LEFTPADDING", (0, 0), (-1, -1), 5),
                    ("RIGHTPADDING", (0, 0), (-1, -1), 5),
                    ("TOPPADDING", (0, 0), (-1, -1), 5),
                    ("BOTTOMPADDING", (0, 0), (-1, -1), 5),
                ])
            )
            story.append(expense_table)
        else:
            story.append(
                Paragraph(
                    "За этот период расходов не зарегистрировано.",
                    normal_style,
                )
            )

        story.append(Paragraph("Простой", subheading_style))

        if item["downtime_rows"]:
            downtime_table_data = [[
                Paragraph("<b>Начало</b>", small_style),
                Paragraph("<b>Окончание</b>", small_style),
                Paragraph("<b>Дней</b>", small_style),
                Paragraph("<b>Причина</b>", small_style),
            ]]

            for downtime in item["downtime_rows"]:
                downtime_table_data.append([
                    Paragraph(downtime["start"], small_style),
                    Paragraph(downtime["end"], small_style),
                    Paragraph(str(downtime["days"]), small_style),
                    Paragraph(downtime["reason"], small_style),
                ])

            downtime_table = Table(
                downtime_table_data,
                colWidths=[30 * mm, 38 * mm, 18 * mm, 84 * mm],
                repeatRows=1,
            )
            downtime_table.setStyle(
                TableStyle([
                    ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#FFF7ED")),
                    ("GRID", (0, 0), (-1, -1), 0.4, colors.HexColor("#D1D5DB")),
                    ("VALIGN", (0, 0), (-1, -1), "TOP"),
                    ("LEFTPADDING", (0, 0), (-1, -1), 5),
                    ("RIGHTPADDING", (0, 0), (-1, -1), 5),
                    ("TOPPADDING", (0, 0), (-1, -1), 5),
                    ("BOTTOMPADDING", (0, 0), (-1, -1), 5),
                ])
            )
            story.append(downtime_table)
        else:
            story.append(
                Paragraph(
                    "За этот период простой не зарегистрирован.",
                    normal_style,
                )
            )

        story.append(Spacer(1, 8 * mm))

    story.append(Paragraph("Общий итог по инвестору", heading_style))

    totals_data = [
        [Paragraph("<b>Всего доход</b>", normal_style), Paragraph(money(total_income), normal_style)],
        [Paragraph("<b>Обычные расходы</b>", normal_style), Paragraph(money(total_shared), normal_style)],
        [Paragraph("<b>Допрасходы инвестора</b>", normal_style), Paragraph(money(total_extra), normal_style)],
        [Paragraph("<b>Расходы только парка</b>", normal_style), Paragraph(money(total_park_only), normal_style)],
        [Paragraph("<b>Инвестор внёс</b>", normal_style), Paragraph(money(total_investor_paid), normal_style)],
        [Paragraph("<b>К выплате инвестору</b>", normal_style), Paragraph(money(total_available), normal_style)],
        [Paragraph("<b>Доля парка</b>", normal_style), Paragraph(money(total_owner), normal_style)],
        [Paragraph("<b>Долг инвестора</b>", normal_style), Paragraph(money(total_debt), normal_style)],
        [Paragraph("<b>Всего дней простоя</b>", normal_style), Paragraph(str(total_downtime_days), normal_style)],
    ]

    totals_table = Table(
        totals_data,
        colWidths=[115 * mm, 55 * mm],
    )
    totals_table.setStyle(
        TableStyle([
            ("BACKGROUND", (0, 0), (-1, -1), colors.HexColor("#F3F4F6")),
            ("GRID", (0, 0), (-1, -1), 0.6, colors.HexColor("#9CA3AF")),
            ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
            ("LEFTPADDING", (0, 0), (-1, -1), 7),
            ("RIGHTPADDING", (0, 0), (-1, -1), 7),
            ("TOPPADDING", (0, 0), (-1, -1), 7),
            ("BOTTOMPADDING", (0, 0), (-1, -1), 7),
        ])
    )

    story.append(totals_table)
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
        weekly_payment = int(data.get("weekly_payment") or 0)
        payment_weekday = int(data.get("payment_weekday") or 0)
    except (TypeError, ValueError):
        return jsonify({
            "ok": False,
            "message": "Сумма или день недели указаны неправильно",
        }), 400

    if not car_code:
        return jsonify({
            "ok": False,
            "message": "Не указан номер машины",
        }), 400

    if weekly_payment < 0:
        return jsonify({
            "ok": False,
            "message": "Сумма не может быть отрицательной",
        }), 400

    if payment_weekday < 0 or payment_weekday > 6:
        return jsonify({
            "ok": False,
            "message": "Неправильно указан день недели",
        }), 400

    if next_payment_date:
        try:
            datetime.strptime(next_payment_date, "%Y-%m-%d")
        except ValueError:
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

        car.driver = driver
        car.weekly_payment = weekly_payment
        car.payment_weekday = payment_weekday
        car.next_payment_date = next_payment_date
        car.payment_notifications = 1

        session.commit()

        return jsonify({
            "ok": True,
            "message": "Настройки оплаты сохранены",
            "car": {
                "code": car.code,
                "driver": car.driver,
                "weekly_payment": car.weekly_payment,
                "payment_weekday": car.payment_weekday,
                "next_payment_date": car.next_payment_date,
            },
        })

    except Exception as error:
        session.rollback()
        print(f"Ошибка сохранения оплаты: {error}")

        return jsonify({
            "ok": False,
            "message": "Не удалось сохранить настройки",
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
            .filter(Car.weekly_payment > 0)
            .all()
        )

        for car in cars:
            if not car.next_payment_date:
                continue

            try:
                payment_date = datetime.strptime(
                    car.next_payment_date,
                    "%Y-%m-%d",
                ).date()
            except (ValueError, TypeError):
                continue

            days_left = (payment_date - today).days
            driver_name = car.driver or "Не указан"
            payment_text = f"{car.weekly_payment:,}".replace(",", " ")

            if days_left == 1:
                messages.append(
                    "🟡 <b>Завтра расчёт</b>\n"
                    f"🚕 Машина: <b>{car.code}</b>\n"
                    f"👤 Водитель: {driver_name}\n"
                    f"💰 Сумма: {payment_text} ₽"
                )

            elif days_left == 0:
                messages.append(
                    "🟠 <b>Сегодня расчёт</b>\n"
                    f"🚕 Машина: <b>{car.code}</b>\n"
                    f"👤 Водитель: {driver_name}\n"
                    f"💰 Должен внести: {payment_text} ₽"
                )

            elif days_left < 0:
                overdue_days = abs(days_left)

                messages.append(
                    "🔴 <b>Платёж просрочен</b>\n"
                    f"🚕 Машина: <b>{car.code}</b>\n"
                    f"👤 Водитель: {driver_name}\n"
                    f"💰 Долг: {payment_text} ₽\n"
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
            "message": "Ошибка проверки платежей",
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

        today = date.today()

        if car.next_payment_date:
            try:
                next_date = datetime.strptime(
                    car.next_payment_date,
                    "%Y-%m-%d",
                ).date()
            except (ValueError, TypeError):
                next_date = today
        else:
            next_date = today

        next_date += timedelta(days=7)

        while next_date <= today:
            next_date += timedelta(days=7)

        car.next_payment_date = next_date.isoformat()
        session.commit()

        return jsonify({
            "ok": True,
            "message": "Оплата отмечена",
            "car_code": car.code,
            "next_payment_date": car.next_payment_date,
        })

    except Exception as error:
        session.rollback()
        print(f"Ошибка отметки оплаты: {error}")

        return jsonify({
            "ok": False,
            "message": "Не удалось отметить оплату",
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
    Списывает одну деталь со склада, когда в сообщении есть
    «со склада» или «из склада».

    Цена расхода берётся из команды и уже записывается в Expense.
    Склад хранит только количество.
    """
    raw_text = (data.get("raw") or "").lower().replace("ё", "е")

    from_warehouse = (
        bool(data.get("from_warehouse"))
        or "со склада" in raw_text
        or "из склада" in raw_text
    )

    if not from_warehouse:
        return {
            "used": False,
            "message": "",
            "low_stock_text": "",
        }

    part_name = (data.get("part") or "").strip()
    brand = (data.get("brand") or "").strip()

    if not part_name:
        return {
            "used": False,
            "message": (
                "Расход записан, но склад не списан: "
                "не удалось распознать деталь."
            ),
            "low_stock_text": "",
        }

    item = find_warehouse_item(
        session,
        part_name=part_name,
        brand=brand,
    )

    display_name = (
        f"{part_name} {brand}".strip()
    )

    if not item:
        return {
            "used": False,
            "message": (
                f"Расход записан, но на складе не найдена "
                f"деталь «{display_name}»."
            ),
            "low_stock_text": "",
        }

    if (item.quantity or 0) <= 0:
        return {
            "used": False,
            "message": (
                f"Расход записан, но «{display_name}» "
                f"закончилась на складе."
            ),
            "low_stock_text": "",
        }

    item.quantity = (item.quantity or 0) - 1

    session.add(
        WarehouseMovement(
            operation_id=op.id,
            car_code=car.code,
            part_name=item.part_name,
            brand=item.brand or "",
            quantity=1,
            movement_type="out",
            comment=data.get("raw") or "",
        )
    )

    remaining = item.quantity or 0
    minimum = item.min_quantity or 0

    low_stock_text = ""

    if remaining <= minimum:
        low_stock_text = (
            "⚠️ <b>Заканчивается деталь</b>\n"
            f"Деталь: {item.part_name}"
            f"{' ' + item.brand if item.brand else ''}\n"
            f"Осталось: {remaining} шт.\n"
            f"Минимум: {minimum} шт."
        )

    return {
        "used": True,
        "message": (
            f"Со склада списано: {item.part_name}"
            f"{' ' + item.brand if item.brand else ''} — 1 шт. "
            f"Остаток: {remaining} шт."
        ),
        "low_stock_text": low_stock_text,
    }


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
        session.add(Expense(operation_id=op.id, car_code=car.code, category="Доп. расходы", amount=data["total_cost"], share_type="investor_only"))

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

    session.close()
    return {
        "ok": True,
        "message": message,
        "data": data,
        "warehouse": warehouse_result,
    }


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
            "settlement_day": car.settlement_day or 15,"driver": car.driver or "",
            "weekly_payment": car.weekly_payment or 0,
            "payment_weekday": car.payment_weekday or 0,
            "next_payment_date": car.next_payment_date or "",
            "payment_notifications": car.payment_notifications or 0,
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
                "total_payouts": (
                    session.query(
                        func.coalesce(
                            func.sum(InvestorPayout.amount),
                            0,
                        )
                    )
                    .filter_by(investor_name=name)
                    .scalar()
                    or 0
                ),
                "total_profit_for_split": 0,
                "total_accrued": 0,
                "total_withheld": 0,
                "total_park_share": 0,
                "investor_debt_to_park": 0,
                "park_debt_to_investor": 0,
                "available_to_pay": 0,
            }

            for car in cars:
                car_code = normalize_code(car.code)

                car_total_invested = investor_total_invested_for_car(
                    session,
                    car,
                )

                income = 0
                shared_expenses = 0
                investor_only_expenses = 0
                park_only_expenses = 0

                for row in session.query(Income).all():
                    if normalize_code(row.car_code) == car_code:
                        income += row.amount or 0

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

                    if (
                        operation
                        and operation.type
                        == "investor_expense_split"
                    ):
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
                        "owner_only",
                        "park",
                        "только парк",
                    }:
                        park_only_expenses += amount

                    else:
                        shared_expenses += amount

                balance = investor_balance_for_car(session, car)

                available_to_pay = (
                    balance.get("available_to_pay", 0) or 0
                )

                investor_debt = (
                    balance.get("investor_debt_to_park", 0) or 0
                )

                investor_share = (
                    balance.get("investor_share_total", 0) or 0
                )

                car_payouts = sum(
                    (row.amount or 0)
                    for row in session.query(InvestorPayout).all()
                    if normalize_code(row.car_code) == car_code
                )

                profit_for_split = (
                    balance.get(
                        "normal_profit_for_split",
                        income - shared_expenses,
                    )
                    or 0
                )

                park_share = (
                    balance.get("park_share_total", 0) or 0
                )

                park_debt = (
                    balance.get("park_debt_to_investor", 0) or 0
                )

                withheld = max(
                    investor_share
                    + park_debt
                    - car_payouts
                    - available_to_pay,
                    0,
                )

                totals["total_invested"] += car_total_invested
                totals["total_income"] += income
                totals["total_shared_expenses"] += shared_expenses
                totals[
                    "total_investor_only_expenses"
                ] += investor_only_expenses
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

                    "invested": car_total_invested,
                    "income": income,

                    "investor_only_expenses":
                        investor_only_expenses,

                    "shared_expenses": shared_expenses,
                    "park_only_expenses": park_only_expenses,

                    "profit_for_split": profit_for_split,
                    "accrued_to_investor": investor_share,
                    "withheld": withheld,
                    "paid_to_investor": car_payouts,
                    "park_share": park_share,
                    "park_debt_to_investor": park_debt,
                    "available_to_pay": available_to_pay,
                    "investor_debt_to_park": investor_debt,
                })

            result.append({
                "name": name,
                "cars": details,
                **totals,
            })

        return jsonify(result)

    except Exception as error:
        session.rollback()
        print(f"Ошибка /api/investors: {error}")

        return jsonify({
            "ok": False,
            "message": "Ошибка расчёта инвесторов",
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
            .order_by(WarehouseItem.part_name, WarehouseItem.brand)
            .all()
        ):
            items.append({
                "id": item.id,
                "part_name": item.part_name or "",
                "brand": item.brand or "",
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
        existing = find_warehouse_item(
            session,
            part_name,
            brand,
        )

        if existing:
            return jsonify({
                "ok": False,
                "message": (
                    "Такая позиция уже есть. "
                    "Используй кнопку «Приход»."
                ),
            }), 400

        item = WarehouseItem(
            part_name=part_name,
            brand=brand,
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
                f"{' ' + brand if brand else ''}. "
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


@bp.route(
    "/api/test-investor-report/<path:investor_name>",
    methods=["GET"],
)
def test_investor_report(investor_name):
    investor_name = unquote(investor_name).strip()
    session = Session()

    try:
        cleanup_legacy_investor_mess(session)

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
            return jsonify({
                "ok": False,
                "message": f"Инвестор «{investor_name}» не найден",
            }), 404

        car_codes = [normalize_code(car.code) for car in cars]

        latest_period = (
            session.query(SettlementPeriod)
            .filter(
                func.trim(SettlementPeriod.car_code).in_(car_codes)
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
                "message": (
                    "У этого инвестора пока нет "
                    "закрытых расчётных периодов"
                ),
            }), 404

        period_start = latest_period.start_date
        period_end = latest_period.end_date
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

            if not period:
                continue

            calc = calculate_period_for_car(
                session,
                car,
                period_start,
                period_end,
            )
            balance = investor_balance_for_car(session, car)

            expense_rows = []

            for expense in (
                session.query(Expense)
                .filter(
                    func.trim(Expense.car_code)
                    == normalize_code(car.code),
                    Expense.date >= period_start,
                    Expense.date < period_end,
                )
                .order_by(Expense.date.asc(), Expense.id.asc())
                .all()
            ):
                operation = None

                if expense.operation_id:
                    operation = (
                        session.query(Operation)
                        .filter_by(id=expense.operation_id)
                        .first()
                    )

                expense_type = (
                    expense.share_type or "shared"
                ).strip().lower()

                if operation and operation.type == "investor_expense_split":
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

                description = (
                    (operation.description if operation else "")
                    or expense.category
                    or (operation.raw_message if operation else "")
                    or "Расход"
                )

                expense_rows.append({
                    "date": (
                        expense.date.strftime("%d.%m.%Y")
                        if expense.date
                        else ""
                    ),
                    "type_label": type_label,
                    "description": description,
                    "amount": expense.amount or 0,
                })

            downtime_rows = []
            downtime_days = 0

            for downtime in session.query(Downtime).all():
                if normalize_code(downtime.car_code) != normalize_code(car.code):
                    continue

                downtime_start = downtime.start_date or period_start
                downtime_end = (
                    datetime.now()
                    if downtime.active
                    else (downtime.end_date or period_end)
                )

                overlap_start = max(downtime_start, period_start)
                overlap_end = min(downtime_end, period_end)

                if overlap_end <= overlap_start:
                    continue

                days = max(
                    (overlap_end.date() - overlap_start.date()).days,
                    1,
                )
                downtime_days += days

                reason = (
                    downtime.reason
                    or downtime.comment
                    or "Причина не указана"
                )

                downtime_rows.append({
                    "start": overlap_start.strftime("%d.%m.%Y"),
                    "end": (
                        "по настоящее время"
                        if downtime.active and downtime_end >= datetime.now()
                        else overlap_end.strftime("%d.%m.%Y")
                    ),
                    "days": days,
                    "reason": reason,
                })

            report_rows.append({
                "code": car.code,
                "car_name": (
                    f"{car.brand or ''} {car.model or ''}"
                ).strip(),
                "percent": car.investor_percent or 0,
                "income": period.income or calc.get("income", 0) or 0,
                "shared_expenses": calc.get("shared_expenses", 0) or 0,
                "investor_only_expenses": (
                    calc.get("investor_only_expenses", 0) or 0
                ),
                "park_only_expenses": (
                    calc.get("park_only_expenses", 0) or 0
                ),
                "investor_extra_paid": (
                    balance.get("investor_extra_paid", 0) or 0
                ),
                "investor_share_total": (
                    balance.get("investor_share_total", 0) or 0
                ),
                "available_to_pay": max(period.investor_amount or 0, 0),
                "owner_amount": period.owner_amount or 0,
                "investor_debt_to_park": max(
                    -(period.investor_amount or 0),
                    0,
                ),
                "expense_rows": expense_rows,
                "downtime_rows": downtime_rows,
                "downtime_days": downtime_days,
            })

        if not report_rows:
            return jsonify({
                "ok": False,
                "message": (
                    "За последний закрытый период "
                    "не найдено машин"
                ),
            }), 404

        pdf_bytes = build_investor_report_pdf(
            investor_name=investor_name,
            period_start=period_start,
            period_end=period_end,
            car_rows=report_rows,
        )

        filename = (
            f"report_{safe_filename(investor_name)}_"
            f"{period_start.strftime('%Y-%m-%d')}_"
            f"{period_end.strftime('%Y-%m-%d')}.pdf"
        )

        sent = send_telegram_document(
            pdf_bytes,
            filename,
            caption=(
                "📄 <b>Тестовый отчёт инвестора</b>\n"
                f"Инвестор: {investor_name}\n"
                f"Период: "
                f"{period_start.strftime('%d.%m.%Y')} — "
                f"{period_end.strftime('%d.%m.%Y')}"
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
                "Подробный отчёт сформирован "
                "и отправлен в твой Telegram"
            ),
            "investor": investor_name,
            "period_start": period_start.isoformat(),
            "period_end": period_end.isoformat(),
            "cars": len(report_rows),
        })

    except Exception as error:
        session.rollback()
        print(f"Ошибка отчёта инвестора: {error}")

        return jsonify({
            "ok": False,
            "message": f"Ошибка создания отчёта: {error}",
        }), 500

    finally:
        session.close()

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
