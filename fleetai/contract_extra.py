"""Rental contracts for drivers of any citizenship.

driver_contracts keeps the Russian passport columns; what it has no columns for
(citizenship, migration card, patent, ...) lives in the additive table
dashboard_contract_extra. Used by the driver's contract page here and by the
owner's form in the dashboard, so both produce the same contract and PDF.
"""
import hashlib
import html
import io
import json
import re
from datetime import datetime

from sqlalchemy import Column, DateTime, MetaData, String, Table, Text, inspect, select

meta = MetaData()
extra = Table(
    "dashboard_contract_extra", meta,
    Column("contract_id", String(64), primary_key=True),
    Column("citizenship", String(8), nullable=False, default="RU"),
    Column("data", Text, nullable=False, default="{}"),
    Column("updated_at", DateTime, nullable=False),
)

# code -> (country, document giving the right to work, hint)
COUNTRIES = {
    "RU": ("Российская Федерация", "", ""),
    "UZ": ("Республика Узбекистан", "patent", "Нужны: миграционная карта, миграционный учёт, патент."),
    "TJ": ("Республика Таджикистан", "patent", "Нужны: миграционная карта, миграционный учёт, патент."),
    "KG": ("Кыргызская Республика", "eaeu", "Страна ЕАЭС: патент не нужен. Нужны миграционная карта и миграционный учёт."),
    "TM": ("Туркменистан", "permit", "Въезд по визе: нужны виза, миграционная карта, учёт и разрешение на работу."),
    "OTHER": ("", "", "Укажите страну и документы вручную."),
}
WORK_DOCS = {"patent": "Патент", "permit": "Разрешение на работу", "eaeu": "Не требуется (ЕАЭС)"}

BASE_FIELDS = ("driver_name", "driver_birth_date", "passport_series", "passport_number", "passport_issued_by",
               "passport_issue_date", "passport_department_code", "registration_address", "phone",
               "license_number", "license_expires", "car_make", "car_model", "car_plate", "car_vin",
               "car_year", "car_sts", "rental_start_date")
EXTRA_FIELDS = ("country_name", "name_latin", "passport_expires", "migration_card", "migration_card_date",
                "stay_address", "stay_until", "work_doc", "work_doc_number", "work_doc_date",
                "work_doc_expires", "license_country", "inn", "actual_address")
REQUIRED = ("driver_name", "driver_birth_date", "passport_number", "passport_issued_by", "passport_issue_date",
            "phone", "license_number", "license_expires", "rental_start_date")
REQUIRED_RU = ("passport_series", "passport_department_code", "registration_address")
REQUIRED_FOREIGN = ("passport_expires", "migration_card", "stay_address", "stay_until")


def countries_public():
    return {k: [v[0], v[1], v[2]] for k, v in COUNTRIES.items()}


def phone(value):
    """Russian mobile for the call check: 7XXXXXXXXXX, otherwise ''."""
    d = re.sub(r"\D", "", str(value or ""))
    if len(d) == 11 and d.startswith("8"):
        d = "7" + d[1:]
    if len(d) == 10:
        d = "7" + d
    return d if len(d) == 11 and d.startswith("7") else ""


def clean(data, citizenship):
    """-> (base values, extra values, missing field names). Raises ValueError on a bad citizenship."""
    cit = str(citizenship or "RU").upper()
    if cit not in COUNTRIES:
        raise ValueError("Неизвестное гражданство")
    vals = {k: str(data.get(k) or "").strip()[:300] for k in BASE_FIELDS if k in data}
    vals["phone"] = phone(data.get("phone"))
    ext = {}
    if cit != "RU":
        ext = {k: str(data.get(k) or "").strip()[:300] for k in EXTRA_FIELDS}
        vals["passport_department_code"] = ""
        if cit != "OTHER":
            ext["country_name"] = COUNTRIES[cit][0]
        if ext.get("work_doc") not in WORK_DOCS:
            ext["work_doc"] = COUNTRIES[cit][1]
        vals["registration_address"] = ext.get("stay_address", "")
    need = REQUIRED + (REQUIRED_RU if cit == "RU" else REQUIRED_FOREIGN)
    missing = [k for k in need if not (vals.get(k) if k in BASE_FIELDS else ext.get(k))]
    if cit == "OTHER" and not ext.get("country_name"):
        missing.append("country_name")
    if ext.get("work_doc") in ("patent", "permit") and not ext.get("work_doc_number"):
        missing.append("work_doc_number")
    return vals, ext, missing


def ensure(bind):
    meta.create_all(bind, checkfirst=True)


def load(conn, contract_id):
    """(citizenship, extra dict) for a contract; ('RU', {}) when there is none."""
    if not inspect(conn).has_table("dashboard_contract_extra"):
        return "RU", {}
    row = conn.execute(select(extra).where(extra.c.contract_id == contract_id)).mappings().first()
    if not row:
        return "RU", {}
    return row["citizenship"], json.loads(row["data"] or "{}")


def store(conn, contract_id, citizenship, ext):
    ensure(conn)
    payload = {"citizenship": citizenship, "data": json.dumps(ext, ensure_ascii=False),
               "updated_at": datetime.now().replace(microsecond=0)}
    if conn.execute(select(extra.c.contract_id).where(extra.c.contract_id == contract_id)).first():
        conn.execute(extra.update().where(extra.c.contract_id == contract_id).values(**payload))
    else:
        conn.execute(extra.insert().values(contract_id=contract_id, **payload))


def merged(conn, row):
    """Contract row + citizenship + extra fields in one dict."""
    c = dict(row)
    cit, ext = load(conn, c["id"])
    c["citizenship"] = cit
    c.update(ext)
    return c


def contract_hash(c):
    keys = ("id", "car_code", "citizenship", "daily_rent", "deposit", "owner_name", "owner_poa",
            "lessor_name", "lessor_inn", "lessor_ogrnip") + BASE_FIELDS + EXTRA_FIELDS
    payload = {k: c.get(k) for k in keys}
    return hashlib.sha256(json.dumps(payload, ensure_ascii=False, sort_keys=True, default=str,
                                     separators=(",", ":")).encode()).hexdigest()


def _font():
    from reportlab.pdfbase import pdfmetrics
    from reportlab.pdfbase.ttfonts import TTFont
    try:
        from .routes import register_pdf_font
        return register_pdf_font()
    except Exception:
        pass
    try:
        if "ContractFont" not in pdfmetrics.getRegisteredFontNames():
            pdfmetrics.registerFont(TTFont("ContractFont", "C:/Windows/Fonts/arial.ttf"))
        return "ContractFont"
    except Exception:
        return "Helvetica"


def _d(v):
    """2026-11-16 -> 16.11.2026; anything else unchanged."""
    m = re.fullmatch(r"(\d{4})-(\d{2})-(\d{2})", str(v or ""))
    return f"{m.group(3)}.{m.group(2)}.{m.group(1)}" if m else str(v or "")


def tenant_text(c):
    phone_txt = f"+{c['phone']}" if c.get("phone") else ""
    if (c.get("citizenship") or "RU") == "RU":
        return (f"Арендатор: {c['driver_name']}, дата рождения {_d(c['driver_birth_date'])}, паспорт "
                f"{c['passport_series']} {c['passport_number']}, выдан {c['passport_issued_by']} "
                f"{_d(c['passport_issue_date'])}, код подразделения {c['passport_department_code']}, адрес "
                f"регистрации: {c['registration_address']}, телефон {phone_txt}.")
    latin = f" ({c['name_latin']})" if c.get("name_latin") else ""
    number = " ".join(x for x in (c.get("passport_series"), c.get("passport_number")) if x)
    t = (f"Арендатор: {c['driver_name']}{latin}, гражданин(ка) {c.get('country_name') or ''}, дата рождения "
         f"{_d(c['driver_birth_date'])}, паспорт иностранного гражданина № {number}, выдан "
         f"{c['passport_issued_by']} {_d(c['passport_issue_date'])}, действителен до {_d(c.get('passport_expires'))}. "
         f"Миграционная карта № {c.get('migration_card')}"
         + (f" от {_d(c.get('migration_card_date'))}" if c.get("migration_card_date") else "") +
         f". Адрес места пребывания (миграционный учёт): {c.get('stay_address')}, срок пребывания до "
         f"{_d(c.get('stay_until'))}.")
    work = c.get("work_doc") or ""
    if work in ("patent", "permit"):
        t += (f" {WORK_DOCS[work]} № {c.get('work_doc_number')}"
              + (f" от {_d(c.get('work_doc_date'))}" if c.get("work_doc_date") else "")
              + (f", действителен до {_d(c.get('work_doc_expires'))}" if c.get("work_doc_expires") else "") + ".")
    elif work == "eaeu":
        t += " Гражданин государства — члена ЕАЭС."
    if c.get("inn"):
        t += f" ИНН {c['inn']}."
    if c.get("actual_address"):
        t += f" Фактический адрес проживания: {c['actual_address']}."
    return t + f" Телефон {phone_txt}."


def build_pdf(c, esign=False):
    """Contract PDF. esign=True adds the simple-electronic-signature section and stamp
    (signed by the driver's phone call); otherwise there are lines for signing on paper."""
    from reportlab.lib.enums import TA_CENTER
    from reportlab.lib.pagesizes import A4
    from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
    from reportlab.lib.units import mm
    from reportlab.platypus import Paragraph, SimpleDocTemplate, Table as PTable

    font = _font()
    buf = io.BytesIO()
    doc = SimpleDocTemplate(buf, pagesize=A4, rightMargin=14 * mm, leftMargin=14 * mm, topMargin=13 * mm,
                            bottomMargin=13 * mm, title=f"Договор {c['id']}", author="FleetAI")
    ss = getSampleStyleSheet()
    body = ParagraphStyle("CB", parent=ss["BodyText"], fontName=font, fontSize=8.5, leading=12, spaceAfter=5)
    head = ParagraphStyle("CH", parent=body, fontSize=10.5, leading=14, spaceBefore=7)
    title = ParagraphStyle("CT", parent=ss["Title"], fontName=font, fontSize=14, leading=18, alignment=TA_CENTER)

    def P(x, s=body):
        return Paragraph(html.escape(str(x)).replace("\n", "<br/>"), s)

    if c.get("owner_poa"):
        lessor = (f"{c['owner_name']}, в лице представителя {c['lessor_name']}, действующего на основании "
                  f"доверенности {c['owner_poa']}, ИНН {c['lessor_inn']}, ОГРНИП {c['lessor_ogrnip']}")
    else:
        lessor = f"{c['lessor_name']}, ИНН {c['lessor_inn']}, ОГРНИП {c['lessor_ogrnip']}"
    foreign = (c.get("citizenship") or "RU") != "RU"
    story = [P("ДОГОВОР АРЕНДЫ ТРАНСПОРТНОГО СРЕДСТВА БЕЗ ЭКИПАЖА", title),
             P(f"№ {c['id']} · г. Набережные Челны · начало аренды {_d(c['rental_start_date'])}"),
             P(f"Арендодатель: {lessor}"), P(tenant_text(c))]
    sections = [
        ("Предмет договора",
         f"Арендодатель предоставляет Арендатору за плату во временное владение и пользование без экипажа автомобиль "
         f"{c['car_make']} {c['car_model']}, госномер {c['car_plate']}, VIN {c['car_vin']}, {c['car_year']} года, "
         f"СТС {c['car_sts']}. Автомобиль может использоваться для законной деятельности легкового такси при наличии "
         f"необходимых разрешений."),
        ("Арендная плата",
         f"Арендная плата — {int(c['daily_rent'] or 0)} ₽ в сутки. Обеспечительный платёж — {int(c['deposit'] or 0)} ₽. "
         f"Начисления и платежи учитываются в FleetAI. Арендатор обязан контролировать баланс и своевременно его пополнять."),
        ("Обязанности Арендатора",
         "Арендатор обязан бережно использовать автомобиль, соблюдать ПДД и требования к перевозкам легковым такси, "
         "иметь действующее водительское удостоверение, сообщать о ДТП, неисправностях, эвакуации и повреждениях и не "
         "передавать управление третьим лицам без согласия Арендодателя."),
        ("Штрафы, ДТП и ущерб",
         "Штрафы за нарушения, совершённые в период пользования автомобилем и относящиеся к действиям Арендатора, "
         "оплачиваются Арендатором. Возмещение ущерба определяется с учётом обстоятельств, вины, страхового возмещения и "
         "законодательства РФ. Нормальный эксплуатационный износ ущербом не считается."),
    ]
    if esign:
        sections.append((
            "Простая электронная подпись",
            "Стороны используют FleetAI для заключения договора. Простой электронной подписью Арендатора является "
            "подтверждение владения указанным в договоре номером телефона посредством контрольного звонка с этого номера "
            "на номер, предоставленный сервисом подтверждения. После ознакомления с договором успешное подтверждение "
            "номера и нажатие кнопки подписания означает подписание этой версии договора. FleetAI фиксирует договор, "
            "номер телефона, дату и время подтверждения."))
    sections.append(("Передача и возврат",
                     "Передача и возврат автомобиля могут оформляться актами с фиксацией пробега, топлива, ключей, "
                     "документов, повреждений и фотографий."))
    if foreign:
        sections.append((
            "Арендатор — иностранный гражданин",
            "Арендатор подтверждает, что законно находится на территории Российской Федерации, состоит на миграционном "
            "учёте и имеет документы, необходимые для пребывания и, если это требуется, для трудовой деятельности. "
            "Арендатор обязан продлевать эти документы в срок и сообщать Арендодателю об их изменении, истечении или "
            "аннулировании; при их отсутствии Арендодатель вправе расторгнуть договор и потребовать возврата автомобиля. "
            "Арендатор подтверждает, что владеет русским языком в объёме, достаточном для понимания договора; договор "
            "составлен на русском языке."))
    sections.append(("Персональные данные и прочие условия",
                     "Персональные данные обрабатываются в объёме, необходимом для заключения и исполнения договора. "
                     "В неурегулированной части стороны руководствуются законодательством Российской Федерации."))
    for n, (h, t) in enumerate(sections, 1):
        story.extend([P(f"{n}. {h}", head), P(t)])
    lic = f"Водительское удостоверение: {c['license_number']}; действительно до {_d(c['license_expires'])}"
    if foreign and c.get("license_country"):
        lic += f"; выдано: {c['license_country']}"
    story.extend([P(lic + "."), P(f"SHA-256 данных договора: {c.get('canonical_sha256') or contract_hash(c)}")])
    signed_at = c.get("signed_at")
    if esign and signed_at:
        when = signed_at.strftime("%d.%m.%Y %H:%M:%S") if isinstance(signed_at, datetime) else str(signed_at)
        story.extend([P("ЭЛЕКТРОННО ПОДПИСАНО", head),
                      P(f"Арендатор: {c['driver_name']}. ПЭП: подтверждение номера телефона звонком с номера "
                        f"арендатора. Телефон: +{c['phone']}. Дата и время: {when} МСК.")])
    elif not esign:
        story.extend([P("ПОДПИСИ СТОРОН", head),
                      PTable([[P("Арендодатель"), P("Арендатор")],
                              [P("_______________________"), P("_______________________")],
                              [P(c.get("lessor_name") or ""), P(c.get("driver_name") or "")]],
                             colWidths=[90 * mm, 90 * mm])])
    doc.build(story)
    return buf.getvalue()
