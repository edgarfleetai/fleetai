"""Rental contracts filled in by the owner in the dashboard.

Rows go into the existing driver_contracts table (the old FleetAI lists them and
serves the stored PDF). Data that table has no columns for (citizenship, migration
card, patent, ...) lives in the additive table dashboard_contract_extra.

Personal data is returned only by contract(), for the owner, never in the list,
the history log or the assistant.
"""
import hashlib
import html
import io
import json
import re
import secrets
import uuid
from datetime import datetime

from sqlalchemy import Column, DateTime, MetaData, String, Table, Text, inspect, select, text

meta = MetaData()
extra = Table(
    "dashboard_contract_extra", meta,
    Column("contract_id", String(64), primary_key=True),
    Column("citizenship", String(4), nullable=False, default="RU"),
    Column("data", Text, nullable=False, default="{}"),
    Column("updated_at", DateTime, nullable=False),
)

# country -> (name, document that gives the right to work, hint for the owner)
COUNTRIES = {
    "RU": ("Российская Федерация", "", ""),
    "UZ": ("Республика Узбекистан", "patent", "Нужны: миграционная карта, миграционный учёт, патент."),
    "TJ": ("Республика Таджикистан", "patent", "Нужны: миграционная карта, миграционный учёт, патент."),
    "KG": ("Кыргызская Республика", "eaeu", "Страна ЕАЭС: патент не нужен. Нужны миграционная карта и миграционный учёт."),
    "TM": ("Туркменистан", "permit", "Въезд по визе: нужны виза, миграционная карта, учёт и разрешение на работу."),
    "OTHER": ("", "", "Укажите страну и документы вручную."),
}
WORK_DOCS = {"patent": "Патент", "permit": "Разрешение на работу", "eaeu": "Не требуется (ЕАЭС)", "": "—"}

# columns of driver_contracts the form fills
BASE_FIELDS = ("driver_name", "driver_birth_date", "passport_series", "passport_number", "passport_issued_by",
               "passport_issue_date", "passport_department_code", "registration_address", "phone",
               "license_number", "license_expires", "car_make", "car_model", "car_plate", "car_vin",
               "car_year", "car_sts", "rental_start_date")
INT_FIELDS = ("daily_rent", "deposit")
# foreign citizens only (stored as JSON)
EXTRA_FIELDS = ("country_name", "name_latin", "passport_expires", "migration_card", "migration_card_date",
                "stay_address", "stay_until", "work_doc", "work_doc_number", "work_doc_date",
                "work_doc_expires", "license_country", "inn", "actual_address")
REQUIRED = ("driver_name", "driver_birth_date", "passport_number", "passport_issued_by", "passport_issue_date",
            "phone", "license_number", "license_expires", "rental_start_date")
REQUIRED_RU = ("passport_series", "passport_department_code", "registration_address")
REQUIRED_FOREIGN = ("passport_expires", "migration_card", "stay_address", "stay_until")


def _write_engine():
    from fleetai import db as fleet_db
    return fleet_db.engine


def _now():
    return datetime.now().replace(microsecond=0)


def _ensure(eng):
    from fleetai import db as fleet_db
    from fleetai.routes import _ensure_driver_contract_tables
    with fleet_db.Session() as s:
        _ensure_driver_contract_tables(s)
    meta.create_all(eng, checkfirst=True)


def _phone(value):
    d = re.sub(r"\D", "", str(value or ""))
    if len(d) == 11 and d.startswith("8"):
        d = "7" + d[1:]
    if len(d) == 10:
        d = "7" + d
    return d if 10 <= len(d) <= 15 else ""


def _money(value, name):
    s = str(value if value is not None else "").replace(" ", "").replace("\u00a0", "")
    if s == "":
        return 0
    if not s.isdigit():
        raise ValueError(f"{name}: целое число рублей")
    return int(s)


def prefill(read_engine, code):
    """What the form can fill in by itself for a car: vehicle, owner, rent, current driver."""
    from fleetai.routes import FLEET_CONTRACT_OWNERS, FLEET_CONTRACT_VEHICLES
    code = str(code or "").strip()
    with read_engine.connect() as conn:
        car = conn.execute(text("SELECT code, brand, model, plate, year, driver, daily_rent, driver_deposit "
                                "FROM cars WHERE TRIM(code) = :c LIMIT 1"), {"c": code}).mappings().first()
    if not car:
        return None
    v = FLEET_CONTRACT_VEHICLES.get(code, {})
    owner = FLEET_CONTRACT_OWNERS.get(code, ("", "Собственник", ""))
    return {"car_code": code, "car_make": v.get("car_make") or car["brand"] or "",
            "car_model": v.get("car_model") or car["model"] or "", "car_plate": v.get("car_plate") or car["plate"] or "",
            "car_vin": v.get("car_vin", ""), "car_year": v.get("car_year") or str(car["year"] or ""),
            "car_sts": v.get("car_sts", ""), "driver_name": car["driver"] or "",
            "daily_rent": int(car["daily_rent"] or 0), "deposit": int(car["driver_deposit"] or 0),
            "owner_name": owner[0], "owner_basis": owner[1], "owner_poa": owner[2],
            "rental_start_date": datetime.now().strftime("%Y-%m-%d")}


def _clean(data):
    cit = str(data.get("citizenship") or "RU").upper()
    if cit not in COUNTRIES:
        raise ValueError("Неизвестное гражданство")
    vals = {k: str(data.get(k) or "").strip()[:300] for k in BASE_FIELDS}
    vals["phone"] = _phone(vals["phone"])
    vals["daily_rent"] = _money(data.get("daily_rent"), "Аренда в сутки")
    vals["deposit"] = _money(data.get("deposit"), "Залог")
    ext = {k: str(data.get(k) or "").strip()[:300] for k in EXTRA_FIELDS} if cit != "RU" else {}
    if cit != "RU":
        vals["passport_department_code"] = ""
        if cit != "OTHER":
            ext["country_name"] = COUNTRIES[cit][0]
        if ext.get("work_doc") not in WORK_DOCS:
            ext["work_doc"] = COUNTRIES[cit][1]
        vals["registration_address"] = ext.get("stay_address", "")
    missing = [k for k in REQUIRED + (REQUIRED_RU if cit == "RU" else REQUIRED_FOREIGN)
               if not (vals.get(k) if k in vals else ext.get(k))]
    if cit == "OTHER" and not ext.get("country_name"):
        missing.append("country_name")
    if ext.get("work_doc") in ("patent", "permit") and not ext.get("work_doc_number"):
        missing.append("work_doc_number")
    return cit, vals, ext, missing


def save(read_engine, data, contract_id=None, allow_incomplete=False):
    """Create or update an unsigned contract. Returns (id, missing_fields)."""
    from fleetai.routes import FLEET_CONTRACT_OWNERS, LESSOR_INN, LESSOR_OGRNIP
    import os
    cit, vals, ext, missing = _clean(data)
    if missing and not allow_incomplete:
        raise ValueError("Заполните обязательные поля")
    eng = _write_engine()
    _ensure(eng)
    now = _now()
    with eng.begin() as conn:
        if contract_id:
            row = conn.execute(text("SELECT id, status, car_code FROM driver_contracts WHERE id = :i"),
                               {"i": contract_id}).mappings().first()
            if not row:
                raise LookupError("Договор не найден")
            if row["status"] == "signed":
                raise ValueError("Подписанный договор нельзя изменить")
            code = str(row["car_code"]).strip()
        else:
            code = str(data.get("car_code") or "").strip()
            car = conn.execute(text("SELECT code FROM cars WHERE TRIM(code) = :c"), {"c": code}).first()
            if not car:
                raise ValueError("Выберите машину")
            contract_id = "KP-" + now.strftime("%Y%m%d") + "-" + code + "-" + uuid.uuid4().hex[:6].upper()
            owner = FLEET_CONTRACT_OWNERS.get(code, ("", "Не указано", ""))
            conn.execute(text(
                "INSERT INTO driver_contracts (id, public_token, car_code, status, owner_name, owner_basis, owner_poa, "
                "lessor_name, lessor_inn, lessor_ogrnip, created_at, updated_at) VALUES (:id, :tok, :code, 'draft', "
                ":on, :ob, :op, :ln, :inn, :og, :now, :now)"),
                {"id": contract_id, "tok": secrets.token_urlsafe(32), "code": code, "on": owner[0], "ob": owner[1],
                 "op": owner[2], "ln": (os.getenv("LESSOR_FULL_NAME") or "ИП Лебедкин Эдгар Алексеевич").strip(),
                 "inn": LESSOR_INN, "og": LESSOR_OGRNIP, "now": now})
        sets = ", ".join(f"{k} = :{k}" for k in BASE_FIELDS + INT_FIELDS)
        conn.execute(text(f"UPDATE driver_contracts SET {sets}, status = :st, updated_at = :now WHERE id = :id"),
                     dict(vals, st="draft" if missing else "ready", now=now, id=contract_id))
        payload = {"citizenship": cit, "data": json.dumps(ext, ensure_ascii=False), "updated_at": now}
        if conn.execute(select(extra.c.contract_id).where(extra.c.contract_id == contract_id)).first():
            conn.execute(extra.update().where(extra.c.contract_id == contract_id).values(**payload))
        else:
            conn.execute(extra.insert().values(contract_id=contract_id, **payload))
        full = _load(conn, contract_id)
        conn.execute(text("UPDATE driver_contracts SET canonical_sha256 = :h WHERE id = :id"),
                     {"h": _hash(full), "id": contract_id})
    return contract_id, missing


def _load(conn, contract_id):
    row = conn.execute(text("SELECT * FROM driver_contracts WHERE id = :i"), {"i": contract_id}).mappings().first()
    if not row:
        return None
    out = {k: v for k, v in row.items() if k not in ("pdf_data", "public_token", "otp_hash")}
    out["has_pdf"] = bool(row.get("pdf_data"))
    ex = None
    if inspect(conn).has_table("dashboard_contract_extra"):
        ex = conn.execute(select(extra).where(extra.c.contract_id == contract_id)).mappings().first()
    out["citizenship"] = ex["citizenship"] if ex else "RU"
    out.update(json.loads(ex["data"]) if ex else {})
    return out


def _hash(c):
    keys = ("id", "car_code", "citizenship", "daily_rent", "deposit", "owner_name", "owner_poa",
            "lessor_name", "lessor_inn", "lessor_ogrnip") + BASE_FIELDS + EXTRA_FIELDS
    payload = {k: c.get(k) for k in keys}
    return hashlib.sha256(json.dumps(payload, ensure_ascii=False, sort_keys=True, default=str,
                                     separators=(",", ":")).encode()).hexdigest()


def contract(read_engine, contract_id):
    """Full contract with personal data — owner only."""
    if not inspect(read_engine).has_table("driver_contracts"):
        return None
    with read_engine.connect() as conn:
        c = _load(conn, contract_id)
    if not c:
        return None
    for k in ("signed_at", "created_at", "updated_at", "otp_expires_at", "otp_last_sent_at"):
        c[k] = c[k].isoformat(timespec="minutes") if isinstance(c.get(k), datetime) else (str(c[k]) if c.get(k) else "")
    for k in ("sms_id", "otp_attempts"):
        c.pop(k, None)
    return c


def citizenships(read_engine):
    """id -> citizenship code, for the list (no personal data)."""
    if not inspect(read_engine).has_table("dashboard_contract_extra"):
        return {}
    with read_engine.connect() as conn:
        return {r[0]: r[1] for r in conn.execute(select(extra.c.contract_id, extra.c.citizenship))}


def mark_signed(read_engine, contract_id):
    """Signed on paper: store the PDF that was printed and lock the contract."""
    eng = _write_engine()
    _ensure(eng)
    with eng.begin() as conn:
        c = _load(conn, contract_id)
        if not c:
            raise LookupError("Договор не найден")
        if c["status"] == "signed":
            raise ValueError("Договор уже подписан")
        if c["status"] != "ready":
            raise ValueError("Сначала заполните договор полностью")
        h = _hash(c)
        c["canonical_sha256"] = h
        pdf = build_pdf(c)
        conn.execute(text("UPDATE driver_contracts SET status = 'signed', signed_at = :now, updated_at = :now, "
                          "canonical_sha256 = :h, pdf_data = :pdf, pdf_sha256 = :ph WHERE id = :id"),
                     {"now": _now(), "h": h, "pdf": pdf, "ph": hashlib.sha256(pdf).hexdigest(), "id": contract_id})
    return c


def pdf(read_engine, contract_id):
    """The stored PDF of a signed contract, otherwise a fresh one from the current data."""
    with read_engine.connect() as conn:
        row = conn.execute(text("SELECT status, pdf_data FROM driver_contracts WHERE id = :i"),
                           {"i": contract_id}).mappings().first()
        if not row:
            return None
        if row["status"] == "signed" and row["pdf_data"]:
            return bytes(row["pdf_data"])
        c = _load(conn, contract_id)
    c["canonical_sha256"] = _hash(c)
    return build_pdf(c)


def _font():
    from reportlab.pdfbase import pdfmetrics
    from reportlab.pdfbase.ttfonts import TTFont
    try:
        from fleetai.routes import register_pdf_font
        return register_pdf_font()
    except Exception:
        pass
    for path in ("C:/Windows/Fonts/arial.ttf",):
        try:
            if "ContractFont" not in pdfmetrics.getRegisteredFontNames():
                pdfmetrics.registerFont(TTFont("ContractFont", path))
            return "ContractFont"
        except Exception:
            continue
    return "Helvetica"


def _d(v):
    """2026-11-16 -> 16.11.2026; anything else unchanged."""
    m = re.fullmatch(r"(\d{4})-(\d{2})-(\d{2})", str(v or ""))
    return f"{m.group(3)}.{m.group(2)}.{m.group(1)}" if m else str(v or "")


def build_pdf(c):
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
    cit = c.get("citizenship") or "RU"
    foreign = cit != "RU"
    phone = f"+{c['phone']}" if c.get("phone") else ""
    if foreign:
        latin = f" ({c['name_latin']})" if c.get("name_latin") else ""
        tenant = (f"Арендатор: {c['driver_name']}{latin}, гражданин(ка) {c.get('country_name') or ''}, дата рождения "
                  f"{_d(c['driver_birth_date'])}, паспорт иностранного гражданина № {c['passport_series']} "
                  f"{c['passport_number']}".replace("  ", " ") +
                  f", выдан {c['passport_issued_by']} {_d(c['passport_issue_date'])}, действителен до "
                  f"{_d(c.get('passport_expires'))}. Миграционная карта № {c.get('migration_card')}"
                  + (f" от {_d(c.get('migration_card_date'))}" if c.get("migration_card_date") else "") +
                  f". Адрес места пребывания (миграционный учёт): {c.get('stay_address')}, срок пребывания до "
                  f"{_d(c.get('stay_until'))}.")
        work = c.get("work_doc") or ""
        if work in ("patent", "permit"):
            tenant += (f" {WORK_DOCS[work]} № {c.get('work_doc_number')}"
                       + (f" от {_d(c.get('work_doc_date'))}" if c.get("work_doc_date") else "")
                       + (f", действителен до {_d(c.get('work_doc_expires'))}" if c.get("work_doc_expires") else "") + ".")
        elif work == "eaeu":
            tenant += " Гражданин государства — члена ЕАЭС."
        if c.get("inn"):
            tenant += f" ИНН {c['inn']}."
        if c.get("actual_address"):
            tenant += f" Фактический адрес проживания: {c['actual_address']}."
        tenant += f" Телефон {phone}."
    else:
        tenant = (f"Арендатор: {c['driver_name']}, дата рождения {_d(c['driver_birth_date'])}, паспорт "
                  f"{c['passport_series']} {c['passport_number']}, выдан {c['passport_issued_by']} "
                  f"{_d(c['passport_issue_date'])}, код подразделения {c['passport_department_code']}, адрес "
                  f"регистрации: {c['registration_address']}, телефон {phone}.")
    story = [P("ДОГОВОР АРЕНДЫ ТРАНСПОРТНОГО СРЕДСТВА БЕЗ ЭКИПАЖА", title),
             P(f"№ {c['id']} · г. Набережные Челны · начало аренды {_d(c['rental_start_date'])}"),
             P(f"Арендодатель: {lessor}"), P(tenant)]
    sections = [
        ("1. Предмет договора",
         f"Арендодатель предоставляет Арендатору за плату во временное владение и пользование без экипажа автомобиль "
         f"{c['car_make']} {c['car_model']}, госномер {c['car_plate']}, VIN {c['car_vin']}, {c['car_year']} года, "
         f"СТС {c['car_sts']}. Автомобиль может использоваться для законной деятельности легкового такси при наличии "
         f"необходимых разрешений."),
        ("2. Арендная плата",
         f"Арендная плата — {int(c['daily_rent'] or 0)} ₽ в сутки. Обеспечительный платёж — {int(c['deposit'] or 0)} ₽. "
         f"Начисления и платежи учитываются в FleetAI. Арендатор обязан контролировать баланс и своевременно его пополнять."),
        ("3. Обязанности Арендатора",
         "Арендатор обязан бережно использовать автомобиль, соблюдать ПДД и требования к перевозкам легковым такси, "
         "иметь действующее водительское удостоверение, сообщать о ДТП, неисправностях, эвакуации и повреждениях и не "
         "передавать управление третьим лицам без согласия Арендодателя."),
        ("4. Штрафы, ДТП и ущерб",
         "Штрафы за нарушения, совершённые в период пользования автомобилем и относящиеся к действиям Арендатора, "
         "оплачиваются Арендатором. Возмещение ущерба определяется с учётом обстоятельств, вины, страхового возмещения и "
         "законодательства РФ. Нормальный эксплуатационный износ ущербом не считается."),
        ("5. Передача и возврат",
         "Передача и возврат автомобиля могут оформляться актами с фиксацией пробега, топлива, ключей, документов, "
         "повреждений и фотографий."),
    ]
    if foreign:
        sections.append((
            "6. Арендатор — иностранный гражданин",
            "Арендатор подтверждает, что законно находится на территории Российской Федерации, состоит на миграционном "
            "учёте и имеет документы, необходимые для пребывания и, если это требуется, для трудовой деятельности. "
            "Арендатор обязан продлевать эти документы в срок и сообщать Арендодателю об их изменении, истечении или "
            "аннулировании; при их отсутствии Арендодатель вправе расторгнуть договор и потребовать возврата автомобиля. "
            "Арендатор подтверждает, что владеет русским языком в объёме, достаточном для понимания договора; договор "
            "составлен на русском языке."))
    sections.append((f"{len(sections) + 1}. Персональные данные и прочие условия",
                     "Персональные данные обрабатываются в объёме, необходимом для заключения и исполнения договора. "
                     "В неурегулированной части стороны руководствуются законодательством Российской Федерации."))
    for h, t in sections:
        story.extend([P(h, head), P(t)])
    lic = f"Водительское удостоверение: {c['license_number']}; действительно до {_d(c['license_expires'])}"
    if foreign and c.get("license_country"):
        lic += f"; выдано: {c['license_country']}"
    story.extend([P(lic + "."), P(f"SHA-256 данных договора: {c.get('canonical_sha256', '')}")])
    story.extend([P("ПОДПИСИ СТОРОН", head),
                  PTable([[P("Арендодатель"), P("Арендатор")],
                          [P("_______________________"), P("_______________________")],
                          [P(c.get("lessor_name") or ""), P(c.get("driver_name") or "")]],
                         colWidths=[90 * mm, 90 * mm])])
    doc.build(story)
    return buf.getvalue()
