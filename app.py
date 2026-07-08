import os
import re
from datetime import datetime, timedelta
from flask import Flask, request, jsonify, render_template_string
from sqlalchemy import create_engine, Column, Integer, String, DateTime, Text, func, text as sql_text
from sqlalchemy.orm import declarative_base, sessionmaker

DATABASE_URL = os.getenv("DATABASE_URL", "sqlite:///fleet.db")

if DATABASE_URL.startswith("postgres://"):
    DATABASE_URL = DATABASE_URL.replace("postgres://", "postgresql+psycopg://", 1)
elif DATABASE_URL.startswith("postgresql://") and not DATABASE_URL.startswith("postgresql+psycopg://"):
    DATABASE_URL = DATABASE_URL.replace("postgresql://", "postgresql+psycopg://", 1)

engine = create_engine(DATABASE_URL, future=True, pool_pre_ping=True)
Session = sessionmaker(bind=engine)
Base = declarative_base()
app = Flask(__name__)


class Car(Base):
    __tablename__ = "cars"
    id = Column(Integer, primary_key=True)
    code = Column(String, unique=True, nullable=False)
    brand = Column(String)
    model = Column(String)
    plate = Column(String)
    year = Column(Integer)
    purchase_date = Column(String)
    purchase_price = Column(Integer, default=0)
    purchase_mileage = Column(Integer, default=0)
    current_mileage = Column(Integer, default=0)
    status = Column(String, default="Работает")
    driver = Column(String, default="")
    owner_type = Column(String, default="own")
    investor_name = Column(String, default="")
    investor_percent = Column(Integer, default=0)
    settlement_day = Column(Integer, default=15)


class Operation(Base):
    __tablename__ = "operations"
    id = Column(Integer, primary_key=True)
    date = Column(DateTime, default=datetime.now)
    car_code = Column(String)
    type = Column(String)
    category = Column(String)
    description = Column(String)
    amount = Column(Integer, default=0)
    mileage = Column(Integer)
    raw_message = Column(Text)


class Part(Base):
    __tablename__ = "parts"
    id = Column(Integer, primary_key=True)
    car_code = Column(String)
    operation_id = Column(Integer)
    part_name = Column(String)
    brand = Column(String)
    position = Column(String)
    price = Column(Integer, default=0)
    labor = Column(Integer, default=0)
    install_date = Column(DateTime, default=datetime.now)
    install_mileage = Column(Integer)
    remove_date = Column(DateTime)
    remove_mileage = Column(Integer)
    status = Column(String, default="Установлена")


class Income(Base):
    __tablename__ = "income"
    id = Column(Integer, primary_key=True)
    operation_id = Column(Integer)
    car_code = Column(String)
    date = Column(DateTime, default=datetime.now)
    amount = Column(Integer, default=0)
    income_type = Column(String)


class Expense(Base):
    __tablename__ = "expenses"
    id = Column(Integer, primary_key=True)
    operation_id = Column(Integer)
    car_code = Column(String)
    date = Column(DateTime, default=datetime.now)
    category = Column(String)
    amount = Column(Integer, default=0)
    share_type = Column(String, default="shared")


class CarInvestment(Base):
    __tablename__ = "car_investments"
    id = Column(Integer, primary_key=True)
    operation_id = Column(Integer)
    date = Column(DateTime, default=datetime.now)
    car_code = Column(String)
    category = Column(String, default="Доп. вложение")
    description = Column(String)
    amount = Column(Integer, default=0)
    investor_name = Column(String, default="")
    raw_message = Column(Text)


class InvestorInvestment(Base):
    __tablename__ = "investor_investments"
    id = Column(Integer, primary_key=True)
    operation_id = Column(Integer)
    date = Column(DateTime, default=datetime.now)
    investor_name = Column(String)
    car_code = Column(String)
    amount = Column(Integer, default=0)
    percent = Column(Integer, default=0)
    comment = Column(Text)


class InvestorPayout(Base):
    __tablename__ = "investor_payouts"
    id = Column(Integer, primary_key=True)
    operation_id = Column(Integer)
    date = Column(DateTime, default=datetime.now)
    investor_name = Column(String)
    car_code = Column(String)
    amount = Column(Integer, default=0)
    comment = Column(Text)


class Mileage(Base):
    __tablename__ = "mileage"
    id = Column(Integer, primary_key=True)
    car_code = Column(String)
    date = Column(DateTime, default=datetime.now)
    mileage = Column(Integer)
    source = Column(Text)


class Downtime(Base):
    __tablename__ = "downtime"
    id = Column(Integer, primary_key=True)
    operation_id = Column(Integer)
    car_code = Column(String)
    start_date = Column(DateTime, default=datetime.now)
    end_date = Column(DateTime)
    days = Column(Integer, default=0)
    reason = Column(String)
    comment = Column(Text)
    active = Column(Integer, default=0)


PARTS = {
    "стойка стаба": ("Стойка стабилизатора", "Подвеска"),
    "стойки стаба": ("Стойка стабилизатора", "Подвеска"),
    "стаба": ("Стойка стабилизатора", "Подвеска"),
    "амортизатор": ("Амортизатор", "Подвеска"),
    "амортизаторы": ("Амортизатор", "Подвеска"),
    "колодки": ("Тормозные колодки", "Тормоза"),
    "накладки": ("Тормозные колодки", "Тормоза"),
    "шаровая": ("Шаровая опора", "Подвеска"),
    "рулевая рейка": ("Рулевая рейка", "Рулевое"),
    "рейка": ("Рулевая рейка", "Рулевое"),
    "замена колес": ("Замена колес", "Шиномонтаж"),
    "колеса": ("Колеса", "Колеса"),
    "шины": ("Шины", "Колеса"),
    "фара": ("Фара", "Кузов"),
    "компрессор": ("Компрессор кондиционера", "Кондиционер"),
    "компресор": ("Компрессор кондиционера", "Кондиционер"),
    "помпа": ("Помпа", "Охлаждение"),
    "антифриз": ("Антифриз", "Охлаждение"),
    "фреон": ("Фреон", "Кондиционер"),
    "фрион": ("Фреон", "Кондиционер"),
    "лобач": ("Лобовое стекло", "Кузов"),
    "лобовое": ("Лобовое стекло", "Кузов"),
    "тонер": ("Тонировка", "Кузов"),
    "тонировка": ("Тонировка", "Кузов"),
    "химчистка": ("Химчистка", "Салон"),
    "сцепление": ("Сцепление", "Трансмиссия"),
    "масло": ("Масло двигателя", "ТО"),
    "масло двигателя": ("Масло двигателя", "ТО"),
    "масло в коробку": ("Масло КПП", "ТО"),
    "салонный": ("Салонный фильтр", "ТО"),
    "воздушный": ("Воздушный фильтр", "ТО"),
    "масляный": ("Масляный фильтр", "ТО"),
    "масленый": ("Масляный фильтр", "ТО"),
    "электрика": ("Электрика", "Электрика"),
    "дворники": ("Дворники", "Кузов"),
    "радиатор": ("Радиатор", "Охлаждение"),
    "выхлоп": ("Выхлоп", "Выхлоп"),
    "краска": ("Покраска", "Кузов"),
}
BRANDS = ["amd", "ctr", "mann", "mando", "lynx", "hi-q", "hiq", "sachs", "kyb", "gates", "bosch", "ngk", "denso", "shell", "лукойл"]


def only_int(v):
    try:
        return int(v or 0)
    except Exception:
        return 0


def normalize_code(v):
    return str(v or "").strip()


def find_car(session, code):
    code = normalize_code(code)
    if not code:
        return None
    return session.query(Car).filter(func.trim(Car.code) == code).first()


def parse_amounts(text, car_code=None):
    nums = [int(x) for x in re.findall(r"\b\d{2,9}\b", text)]
    if car_code:
        nums = [n for n in nums if str(n) != str(car_code)]
    return nums


def clean_desc(text, car_code, words, amount):
    desc = text
    if car_code:
        desc = re.sub(r"^" + re.escape(str(car_code)) + r"\b", "", desc).strip()
    for w in sorted(words, key=len, reverse=True):
        desc = re.sub(r"\b" + re.escape(w) + r"\b", "", desc).strip()
    if amount:
        desc = re.sub(r"\b" + str(amount) + r"\b", "", desc).strip()
    return desc.replace("руб", "").replace("р", "").strip()



MONTHS_RU = {
    "января": 1, "январь": 1,
    "февраля": 2, "февраль": 2,
    "марта": 3, "март": 3,
    "апреля": 4, "апрель": 4,
    "мая": 5, "май": 5,
    "июня": 6, "июнь": 6,
    "июля": 7, "июль": 7,
    "августа": 8, "август": 8,
    "сентября": 9, "сентябрь": 9,
    "октября": 10, "октябрь": 10,
    "ноября": 11, "ноябрь": 11,
    "декабря": 12, "декабрь": 12,
}

def parse_russian_date_piece(piece, default_month=None):
    piece = (piece or "").strip().lower()
    now = datetime.now()
    year = now.year

    m = re.search(r"(\d{1,2})[./-](\d{1,2})(?:[./-](\d{2,4}))?", piece)
    if m:
        day = int(m.group(1))
        month = int(m.group(2))
        if m.group(3):
            year = int(m.group(3))
            if year < 100:
                year += 2000
        return datetime(year, month, day)

    m = re.search(r"(\d{1,2})\s+([а-яё]+)", piece)
    if m:
        day = int(m.group(1))
        month = MONTHS_RU.get(m.group(2))
        if month:
            return datetime(year, month, day)

    m = re.search(r"\b(\d{1,2})\b", piece)
    if m and default_month:
        return datetime(year, default_month, int(m.group(1)))

    return None

def parse_downtime_period(text):
    today = datetime.now()

    # Закрытый простой: 373 простой с 20 мая по 24 мая
    m = re.search(
        r"\bс\s+(.+?)\s+по\s+(.+?)(?=\s+(?:ремонт|коробка|двигатель|дтп|ожид|замена|из-за|из за)|$)",
        text
    )

    if m:
        start_piece = m.group(1).strip()
        end_piece = m.group(2).strip()

        if any(x in end_piece for x in ["настоящее", "сегодня", "сейчас"]):
            start_dt = parse_russian_date_piece(start_piece)
            if start_dt:
                days = max((today.date() - start_dt.date()).days, 1)
                reason = text
                reason = re.sub(r"^\s*\d{3}\b", "", reason).strip()
                reason = re.sub(r"\b(простой|стояла|стоял|стоит|не работала|не работал|в простое)\b", "", reason).strip()
                reason = re.sub(r"\bс\s+.+?\s+по\s+(настоящее время|сегодня|сейчас)\b", "", reason).strip()
                reason = reason.strip(" -—.,")
                return start_dt, None, days, reason, 1

        end_month_match = re.search(r"([а-яё]+)", end_piece)
        default_month = MONTHS_RU.get(end_month_match.group(1)) if end_month_match else None

        start_dt = parse_russian_date_piece(start_piece, default_month=default_month)
        end_dt = parse_russian_date_piece(end_piece)

        if start_dt and not end_dt:
            end_dt = parse_russian_date_piece(end_piece, default_month=start_dt.month)

        if not start_dt and end_dt:
            start_dt = parse_russian_date_piece(start_piece, default_month=end_dt.month)

        if start_dt and end_dt:
            if end_dt < start_dt:
                end_dt = end_dt.replace(year=end_dt.year + 1)

            days = max((end_dt.date() - start_dt.date()).days, 1)

            reason = text
            reason = re.sub(r"^\s*\d{3}\b", "", reason).strip()
            reason = re.sub(r"\b(простой|стояла|стоял|стоит|не работала|не работал|в простое)\b", "", reason).strip()
            reason = re.sub(r"\bс\s+.+?\s+по\s+.+?(?=\s+(?:ремонт|коробка|двигатель|дтп|ожид|замена|из-за|из за)|$)", "", reason).strip()
            reason = reason.strip(" -—.,")
            return start_dt, end_dt, days, reason, 0

    # Открытый простой: 373 стоит с 20 мая
    m_open = re.search(r"\bс\s+(\d{1,2}[./-]\d{1,2}(?:[./-]\d{2,4})?|\d{1,2}\s+[а-яё]+)", text)
    if m_open:
        start_piece = m_open.group(1).strip()
        start_dt = parse_russian_date_piece(start_piece)
        if start_dt:
            days = max((today.date() - start_dt.date()).days, 1)
            reason = text
            reason = re.sub(r"^\s*\d{3}\b", "", reason).strip()
            reason = re.sub(r"\b(простой|стояла|стоял|стоит|не работала|не работал|в простое)\b", "", reason).strip()
            reason = re.sub(r"\bс\s+(\d{1,2}[./-]\d{1,2}(?:[./-]\d{2,4})?|\d{1,2}\s+[а-яё]+)\b", "", reason).strip()
            reason = reason.strip(" -—.,")
            return start_dt, None, days, reason, 1

    return None, None, 0, "", 0


def parse_message(message):
    raw = (message or "").strip()
    text = raw.lower().replace(",", " ").replace(".", " ")
    data = dict(raw=raw, car_code=None, type="unknown", category="", description="", part="",
                brand="", position="", part_price=0, labor=0, total=0, income=0, mileage=None,
                share_type="shared", investor_name="", investor_percent=0)

    car = re.match(r"^\s*(\d{3})\b", text)
    if car:
        data["car_code"] = car.group(1).strip()

    m = re.search(r"пробег\s*(\d{4,7})", text)
    if m:
        data["mileage"] = int(m.group(1))

    if "справа" in text or "правая" in text:
        data["position"] = "Правая"
    elif "слева" in text or "левая" in text:
        data["position"] = "Левая"

    for b in BRANDS:
        if re.search(r"\b" + re.escape(b) + r"\b", text):
            data["brand"] = b.upper()
            break
    # Общий ремонт / замена / работа
    if any(word in text for word in ["замена", "поменял", "поменяли", "ремонт"]):
        data["type"] = "repair"
        data["category"] = "Ремонт"
        data["description"] = "Ремонт / замена"

        nums = parse_amounts(text, data["car_code"])
        if data["mileage"]:
            nums = [n for n in nums if n != data["mileage"]]

        data["total"] = sum(nums) if nums else 0
        return data
    # Простой машины
    if "простой" in text or "стояла" in text or "стоял" in text or "стоит" in text or "в простое" in text or "не работала" in text or "не работал" in text:
        data["type"] = "downtime"
        data["category"] = "Простой"
        data["total"] = 0

        start_dt, end_dt, period_days, period_reason, active = parse_downtime_period(text)

        if period_days:
            data["days"] = period_days
            data["start_date"] = start_dt
            data["end_date"] = end_dt
            data["active"] = active
            data["description"] = period_reason or "Простой"
            return data

        days_match = re.search(r"(\d+)\s*(день|дня|дней)", text)
        if days_match:
            data["days"] = int(days_match.group(1))
        else:
            nums = parse_amounts(text, data["car_code"])
            data["days"] = nums[0] if nums else 0

        reason = text
        if data["car_code"]:
            reason = re.sub(r"^\s*" + re.escape(data["car_code"]) + r"\b", "", reason).strip()
        for word in ["простой", "стояла", "стоял", "не работала", "не работал"]:
            reason = reason.replace(word, "").strip()
        reason = re.sub(r"\d+\s*(день|дня|дней)", "", reason).strip()

        data["description"] = reason or "Простой"
        return data

    car_investment_words = ["доп вложение", "дополнительное вложение", "дополнительные вложения", "допы", "доп", "вложение", "вложения", "кап вложение", "капиталка"]
    if any(re.search(r"\b" + re.escape(w) + r"\b", text) for w in car_investment_words):
        data["type"] = "car_investment"
        data["category"] = "Доп. вложение"
        nums = parse_amounts(text, data["car_code"])
        data["total"] = nums[-1] if nums else 0
        data["description"] = clean_desc(text, data["car_code"], car_investment_words, data["total"]) or "Дополнительное вложение"
        return data

    if "инвестор" in text and any(w in text for w in ["вложил", "внес", "дал"]):
        data["type"] = "investor_investment"
        data["category"] = "Вложение инвестора"
        nums = parse_amounts(text, data["car_code"])
        data["total"] = nums[0] if nums else 0
        pct = re.search(r"(\d{1,3})\s*%", text)
        data["investor_percent"] = int(pct.group(1)) if pct else 0
        name = re.search(r"инвестор\s+([а-яa-zё]+)", text)
        data["investor_name"] = name.group(1).capitalize() if name else ""
        data["description"] = "Вложение инвестора"
        return data

    if "выплата" in text:
        data["type"] = "investor_payout"
        data["category"] = "Выплата инвестору"
        nums = parse_amounts(text, data["car_code"])
        data["total"] = nums[-1] if nums else 0
        name = re.search(r"выплата\s+([а-яa-zё]+)", text)
        data["investor_name"] = name.group(1).capitalize() if name else ""
        data["description"] = "Выплата инвестору"
        return data

    if any(w in text for w in ["получил", "расчет", "расчёт", "недельный", "перевел", "перевёл", "прибыль", "доход", "заработал", "пришло"]):
        data["type"] = "income"
        nums = parse_amounts(text, data["car_code"])
        data["income"] = nums[-1] if nums else 0
        data["total"] = data["income"]
        data["description"] = "Недельный расчет"
        return data

    expense_words = {"штраф": "Штраф", "страховка": "Страховка", "осаго": "Страховка", "мойка": "Мойка", "бензин": "Топливо", "газ": "Топливо", "эвакуатор": "Эвакуатор", "шиномонтаж": "Шиномонтаж"}
    for word, cat in expense_words.items():
        if word in text:
            data["type"] = "expense"
            data["category"] = cat
            data["description"] = cat
            nums = parse_amounts(text, data["car_code"])
            data["total"] = nums[-1] if nums else 0
            return data

    for key, val in sorted(PARTS.items(), key=lambda x: len(x[0]), reverse=True):
        if key in text:
            data["part"], data["category"] = val
            data["description"] = "Замена " + data["part"].lower()
            data["type"] = "service" if data["category"] == "ТО" else "repair"
            break

    price = re.search(r"(стоимость|цена)\s*(\d+)", text)
    labor = re.search(r"(работа|ремонт)\s*(\d+)", text)
    if price:
        data["part_price"] = int(price.group(2))
    if labor:
        data["labor"] = int(labor.group(2))

    if data["part"] and data["part_price"] == 0:
        nums = parse_amounts(text, data["car_code"])
        if data["mileage"]:
            nums = [n for n in nums if n != data["mileage"]]
        if nums:
            data["part_price"] = nums[0]
        if len(nums) > 1 and data["labor"] == 0:
            data["labor"] = nums[1]

    data["total"] = data["part_price"] + data["labor"]
    return data


def ensure_schema():
    Base.metadata.create_all(engine)
    migrations = [
        "ALTER TABLE cars ADD COLUMN owner_type VARCHAR DEFAULT 'own'",
        "ALTER TABLE cars ADD COLUMN investor_name VARCHAR DEFAULT ''",
        "ALTER TABLE cars ADD COLUMN investor_percent INTEGER DEFAULT 0",
        "ALTER TABLE cars ADD COLUMN driver VARCHAR DEFAULT ''",
        "ALTER TABLE expenses ADD COLUMN share_type VARCHAR DEFAULT 'shared'",
        "ALTER TABLE car_investments ADD COLUMN investor_name VARCHAR DEFAULT ''",
        "ALTER TABLE downtime ADD COLUMN operation_id INTEGER",
        "ALTER TABLE downtime ADD COLUMN active INTEGER DEFAULT 0",
    ]
    # Важно: каждая миграция в отдельной транзакции.
    # Если одна колонка уже существует, PostgreSQL отменяет только эту транзакцию,
    # а следующие ALTER TABLE все равно выполняются.
    for sql in migrations:
        try:
            with engine.begin() as conn:
                conn.execute(sql_text(sql))
        except Exception:
            pass


def init_seed():
    s = Session()
    seed = [
        ("897", "Kia", "Rio", "К897УР716", 2018, "11.2025", 900000, 180000),
        ("119", "Kia", "Rio", "В119ЕН716", 2018, "21.03.2025", 790000, 253000),
        ("665", "Kia", "Rio", "С665ХК716", 2020, "04.2024", 1575000, 240000),
        ("404", "Hyundai", "Solaris", "Н404ЕК716", 2017, "09.04.2026", 575000, 410000),
        ("218", "Hyundai", "Solaris", "Е218РТ716", None, "22.04.2026", 420000, 280000),
    ]
    for code, brand, model, plate, year, pd, pp, mil in seed:
        if not find_car(s, code):
            s.add(Car(code=code, brand=brand, model=model, plate=plate, year=year,
                      purchase_date=pd, purchase_price=pp, purchase_mileage=mil,
                      current_mileage=mil, owner_type="own"))
    s.commit()
    s.close()


def save(data):
    s = Session()
    car_code = normalize_code(data.get("car_code"))
    car = find_car(s, car_code)

    if not car_code or not car:
        existing = [c.code for c in s.query(Car).order_by(Car.code).all()]
        s.close()
        return {"ok": False, "message": f"Машина {car_code or 'без кода'} не найдена. Есть коды: {', '.join(existing)}"}

    op = Operation(car_code=car.code, type=data["type"], category=data["category"],
                   description=data["description"], amount=data["total"],
                   mileage=data["mileage"], raw_message=data["raw"])
    s.add(op)
    s.flush()

    if data["type"] == "income":
        s.add(Income(operation_id=op.id, car_code=car.code, amount=data["income"], income_type=data["description"]))
    elif data["type"] in ("repair", "service", "expense"):
        s.add(Expense(operation_id=op.id, car_code=car.code, category=data["category"], amount=data["total"], share_type=data.get("share_type", "shared")))
    elif data["type"] == "car_investment":
        s.add(CarInvestment(operation_id=op.id, car_code=car.code, category=data["category"], description=data["description"], amount=data["total"], raw_message=data["raw"]))
    elif data["type"] == "investor_investment":
        s.add(InvestorInvestment(operation_id=op.id, car_code=car.code, investor_name=data["investor_name"], amount=data["total"], percent=data["investor_percent"], comment=data["raw"]))
        if data["investor_name"]:
            car.owner_type = "investor"
            car.investor_name = data["investor_name"]
        if data["investor_percent"]:
            car.investor_percent = data["investor_percent"]
    elif data["type"] == "investor_payout":
        s.add(InvestorPayout(operation_id=op.id, car_code=car.code, investor_name=data["investor_name"], amount=data["total"], comment=data["raw"]))
    elif data["type"] == "downtime":
        s.add(Downtime(
            operation_id=op.id,
            car_code=car.code,
            start_date=data.get("start_date") or datetime.now(),
            end_date=data.get("end_date"),
            days=data.get("days", 0),
            reason=data["description"],
            active=data.get("active", 0),
            comment=data["raw"]
        ))

    if data.get("part"):
        s.add(Part(car_code=car.code, operation_id=op.id, part_name=data["part"], brand=data["brand"],
                   position=data["position"], price=data["part_price"], labor=data["labor"], install_mileage=data["mileage"]))

    if data.get("mileage"):
        car.current_mileage = data["mileage"]
        s.add(Mileage(car_code=car.code, mileage=data["mileage"], source=data["raw"]))

    s.commit()
    op_id = op.id
    s.close()
    return {"ok": True, "message": f"Записано. Операция #{op_id}", "data": data}


def car_finance(s, code):
    code = normalize_code(code)

    income = 0
    for row in s.query(Income).all():
        if normalize_code(row.car_code) == code:
            income += row.amount or 0

    expenses = 0
    for row in s.query(Expense).all():
        if normalize_code(row.car_code) == code:
            expenses += row.amount or 0

    investments = 0
    for row in s.query(CarInvestment).all():
        if normalize_code(row.car_code) == code:
            investments += row.amount or 0

    payouts = 0
    for row in s.query(InvestorPayout).all():
        if normalize_code(row.car_code) == code:
            payouts += row.amount or 0

    inv_in = 0
    for row in s.query(InvestorInvestment).all():
        if normalize_code(row.car_code) == code:
            inv_in += row.amount or 0

    downtime_days = 0
    for row in s.query(Downtime).all():
        if normalize_code(row.car_code) == code:
            downtime_days += row.days or 0

    return income, expenses, investments, payouts, inv_in, downtime_days


@app.route("/")
def index():
    return render_template_string(HTML)


@app.route("/healthz")
def healthz():
    return "ok"


@app.route("/api/add", methods=["POST"])
def api_add():
    return jsonify(save(parse_message(request.json.get("message", ""))))


@app.route("/api/add-car", methods=["POST"])
def api_add_car():
    p = request.json or {}
    s = Session()
    code_value = normalize_code(p.get("code"))

    if not code_value:
        s.close()
        return jsonify({"ok": False, "message": "Укажи код машины"})

    if find_car(s, code_value):
        s.close()
        return jsonify({"ok": False, "message": "Машина с таким кодом уже есть"})

    car = Car(
        code=code_value,
        brand=str(p.get("brand") or "").strip(),
        model=str(p.get("model") or "").strip(),
        plate=str(p.get("plate") or "").strip(),
        year=only_int(p.get("year")) or None,
        purchase_date=str(p.get("purchase_date") or "").strip(),
        purchase_price=only_int(p.get("purchase_price")),
        purchase_mileage=only_int(p.get("mileage")),
        current_mileage=only_int(p.get("mileage")),
        owner_type=str(p.get("owner_type") or "own").strip(),
        investor_name=str(p.get("investor_name") or "").strip(),
        investor_percent=only_int(p.get("investor_percent")),
        settlement_day=only_int(p.get("settlement_day")) or 15,
        status="Работает"
    )
    s.add(car)
    s.commit()
    s.close()
    return jsonify({"ok": True, "message": f"Машина {code_value} добавлена"})


@app.route("/api/summary")
def api_summary():
    s = Session()
    cars = s.query(Car).count()
    own_cars = s.query(Car).filter(Car.owner_type != "investor").count()
    investor_cars = s.query(Car).filter_by(owner_type="investor").count()
    income = s.query(func.coalesce(func.sum(Income.amount), 0)).scalar()
    expenses = s.query(func.coalesce(func.sum(Expense.amount), 0)).scalar()
    investments = s.query(func.coalesce(func.sum(CarInvestment.amount), 0)).scalar()
    downtime_days = s.query(func.coalesce(func.sum(Downtime.days), 0)).scalar()
    s.close()
    return jsonify(dict(cars=cars, own_cars=own_cars, investor_cars=investor_cars,
                        income=income, expenses=expenses, investments=investments,
                        profit=income - expenses, downtime_days=downtime_days))


@app.route("/api/cars")
def api_cars():
    owner_type = request.args.get("owner_type")
    s = Session()
    q = s.query(Car).order_by(Car.code)
    if owner_type == "own":
        q = q.filter(Car.owner_type != "investor")
    elif owner_type == "investor":
        q = q.filter_by(owner_type="investor")

    rows = []
    for c in q.all():
        income, expenses, investments, payouts, inv_in, downtime_days = car_finance(s, c.code)
        rows.append(dict(code=c.code, brand=c.brand, model=c.model, plate=c.plate,
                         mileage=c.current_mileage, status=c.status, income=income,
                         expenses=expenses, car_investments=investments,
                         profit=income - expenses,
                         full_cost=(c.purchase_price or 0) + investments,
                         purchase_price=c.purchase_price or 0,
                         owner_type=c.owner_type or "own",
                         investor_name=c.investor_name or "",
                         investor_percent=c.investor_percent or 0,
                         investor_invested=inv_in,
                         investor_payouts=payouts,
                         downtime_days=downtime_days,
                         settlement_day=c.settlement_day or 15))
    s.close()
    return jsonify(rows)



@app.route("/api/car/<code>")
def api_car_card(code):
    s = Session()
    car = find_car(s, code)

    if not car:
        s.close()
        return jsonify({"ok": False, "message": "Машина не найдена"})

    income, expenses, investments, payouts, investor_invested, downtime_days = car_finance(s, car.code)

    operations = [
        {
            "id": op.id,
            "date": op.date.strftime("%d.%m.%Y %H:%M"),
            "type": op.type,
            "category": op.category,
            "description": op.description,
            "amount": op.amount,
            "mileage": op.mileage,
            "raw": op.raw_message,
        }
        for op in s.query(Operation)
        .filter(func.trim(Operation.car_code) == normalize_code(car.code))
        .order_by(Operation.id.desc())
        .all()
    ]

    downtime = [
        {
            "date": row.start_date.strftime("%d.%m.%Y %H:%M") if row.start_date else "",
            "end_date": row.end_date.strftime("%d.%m.%Y %H:%M") if row.end_date else "",
            "days": max((datetime.now().date() - row.start_date.date()).days, 1) if getattr(row, "active", 0) and row.start_date else (row.days or 0),
            "active": row.active or 0,
            "reason": row.reason or "",
            "comment": row.comment or "",
        }
        for row in s.query(Downtime)
        .filter(func.trim(Downtime.car_code) == normalize_code(car.code))
        .order_by(Downtime.id.desc())
        .all()
    ]

    s.close()

    return jsonify({
        "ok": True,
        "car": {
            "code": car.code,
            "brand": car.brand,
            "model": car.model,
            "plate": car.plate,
            "year": car.year,
            "mileage": car.current_mileage,
            "purchase_price": car.purchase_price or 0,
            "income": income,
            "expenses": expenses,
            "investments": investments,
            "profit": income - expenses,
            "full_cost": (car.purchase_price or 0) + investments,
            "owner_type": car.owner_type or "own",
            "investor_name": car.investor_name or "",
            "investor_percent": car.investor_percent or 0,
            "investor_invested": investor_invested,
            "investor_payouts": payouts,
            "downtime_days": downtime_days,
        },
        "operations": operations,
        "downtime": downtime,
    })



@app.route("/api/close-downtime/<code>", methods=["POST"])
def api_close_downtime(code):
    s = Session()
    car = find_car(s, code)

    if not car:
        s.close()
        return jsonify({"ok": False, "message": "Машина не найдена"})

    rows = s.query(Downtime).filter(
        func.trim(Downtime.car_code) == normalize_code(car.code),
        Downtime.active == 1
    ).all()

    if not rows:
        s.close()
        return jsonify({"ok": False, "message": "Активного простоя нет"})

    now = datetime.now()
    for row in rows:
        row.end_date = now
        row.days = max((now.date() - row.start_date.date()).days, 1) if row.start_date else (row.days or 0)
        row.active = 0

    op = Operation(
        car_code=car.code,
        type="downtime_closed",
        category="Простой",
        description="Простой закрыт",
        amount=0,
        raw_message=f"{car.code} вышла из простоя"
    )
    s.add(op)
    s.commit()
    s.close()

    return jsonify({"ok": True, "message": "Простой закрыт"})


@app.route("/api/period/<code>")
def api_period_preview(code):
    s = Session()
    car = find_car(s, code)

    if not car:
        s.close()
        return jsonify({"ok": False, "message": "Машина не найдена"})

    start, end = period_bounds_for_car(car)
    calc = calculate_period_for_car(s, car, start, end)

    periods = [
        {
            "id": p.id,
            "start_date": p.start_date.strftime("%d.%m.%Y") if p.start_date else "",
            "end_date": p.end_date.strftime("%d.%m.%Y") if p.end_date else "",
            "income": p.income or 0,
            "expenses": p.expenses or 0,
            "investments": p.investments or 0,
            "profit": p.profit or 0,
            "investor_amount": p.investor_amount or 0,
            "owner_amount": p.owner_amount or 0,
            "downtime_days": p.downtime_days or 0,
            "closed_at": p.closed_at.strftime("%d.%m.%Y %H:%M") if p.closed_at else "",
        }
        for p in s.query(SettlementPeriod)
        .filter(func.trim(SettlementPeriod.car_code) == normalize_code(car.code))
        .order_by(SettlementPeriod.id.desc())
        .all()
    ]

    s.close()

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
    s = Session()
    car = find_car(s, code)

    if not car:
        s.close()
        return jsonify({"ok": False, "message": "Машина не найдена"})

    start, end = period_bounds_for_car(car)
    calc = calculate_period_for_car(s, car, start, end)

    exists = s.query(SettlementPeriod).filter(
        func.trim(SettlementPeriod.car_code) == normalize_code(car.code),
        SettlementPeriod.start_date == start,
        SettlementPeriod.end_date == end
    ).first()

    if exists:
        s.close()
        return jsonify({"ok": False, "message": "Этот расчетный период уже закрыт"})

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
    s.add(period)

    op = Operation(
        car_code=car.code,
        type="settlement_period",
        category="Расчетный период",
        description=period.comment,
        amount=calc["profit"],
        raw_message=f"{car.code} закрыт расчетный период"
    )
    s.add(op)

    s.commit()
    s.close()

    return jsonify({"ok": True, "message": "Расчетный период закрыт", "period": calc})


@app.route("/api/set-settlement-day/<code>", methods=["POST"])
def api_set_settlement_day(code):
    payload = request.json or {}
    day = only_int(payload.get("day"))

    if day < 1 or day > 28:
        return jsonify({"ok": False, "message": "День должен быть от 1 до 28"})

    s = Session()
    car = find_car(s, code)

    if not car:
        s.close()
        return jsonify({"ok": False, "message": "Машина не найдена"})

    car.settlement_day = day
    s.commit()
    s.close()

    return jsonify({"ok": True, "message": f"Расчетный день установлен: {day}"})

@app.route("/api/investors")
def api_investors():
    s = Session()
    names = [r[0] for r in s.query(Car.investor_name).filter(Car.owner_type == "investor", Car.investor_name != "").distinct().all()]
    out = []

    for name in names:
        cars = s.query(Car).filter_by(owner_type="investor", investor_name=name).all()
        total_invested = s.query(func.coalesce(func.sum(InvestorInvestment.amount), 0)).filter_by(investor_name=name).scalar()
        total_payouts = s.query(func.coalesce(func.sum(InvestorPayout.amount), 0)).filter_by(investor_name=name).scalar()

        details = []
        total_income = 0
        total_expenses = 0
        total_profit = 0
        total_to_investor = 0
        total_downtime_days = 0

        for c in cars:
            income, expenses, investments, payouts, inv_in, downtime_days = car_finance(s, c.code)
            profit = income - expenses
            to_investor = round(profit * (c.investor_percent or 0) / 100)

            total_income += income
            total_expenses += expenses
            total_profit += profit
            total_to_investor += to_investor
            total_downtime_days += downtime_days

            details.append(dict(
                code=c.code,
                car=f"{c.brand or ''} {c.model or ''}",
                percent=c.investor_percent or 0,
                income=income,
                expenses=expenses,
                profit=profit,
                to_investor=to_investor,
                invested=inv_in,
                payouts=payouts,
                downtime_days=downtime_days
            ))

        out.append(dict(
            name=name,
            total_invested=total_invested,
            total_payouts=total_payouts,
            balance=total_invested - total_payouts,
            total_income=total_income,
            total_expenses=total_expenses,
            total_profit=total_profit,
            total_to_investor=total_to_investor,
            total_downtime_days=total_downtime_days,
            cars=details
        ))

    s.close()
    return jsonify(out)


@app.route("/api/operations")
def api_operations():
    s = Session()
    rows = [dict(id=o.id, date=o.date.strftime("%d.%m.%Y %H:%M"), car_code=o.car_code, type=o.type,
                 category=o.category, description=o.description, amount=o.amount,
                 mileage=o.mileage, raw=o.raw_message)
            for o in s.query(Operation).order_by(Operation.id.desc()).limit(80).all()]
    s.close()
    return jsonify(rows)


HTML = """
<!doctype html><html lang="ru"><head><meta charset="utf-8"><title>FleetAI Cloud</title>
<style>
body{font-family:Arial;background:#f3f5f7;margin:0;color:#111827}.wrap{max-width:1280px;margin:auto;padding:24px}
.card{background:white;border-radius:16px;padding:18px;margin:14px 0;box-shadow:0 2px 12px #0001}.grid{display:grid;grid-template-columns:repeat(7,1fr);gap:12px}
.stat{background:#111827;color:white;border-radius:14px;padding:16px}.stat b{font-size:22px;display:block;margin-top:8px}
input,select{padding:12px;font-size:16px;border:1px solid #ddd;border-radius:10px;margin:4px}input.msg{width:78%;font-size:18px}button{padding:10px 14px;font-size:15px;border:0;border-radius:10px;background:#2563eb;color:white;cursor:pointer}
table{width:100%;border-collapse:collapse}td,th{padding:9px;border-bottom:1px solid #eee;text-align:left}.tabs button{background:#e5e7eb;color:#111}.tabs button.active{background:#2563eb;color:white}
.badge{padding:4px 8px;border-radius:999px;background:#e0f2fe;color:#0369a1;font-size:12px}.warn{background:#fff7ed;border-left:5px solid #f97316}
.ok{color:#16a34a}.bad{color:#dc2626}
.calendar{display:grid;grid-template-columns:repeat(auto-fill,minmax(260px,1fr));gap:12px}
.daycard{border:1px solid #e5e7eb;border-radius:14px;padding:12px;background:#f9fafb}
.daycard h4{margin:0 0 10px 0}
.event{background:white;border-left:4px solid #2563eb;border-radius:10px;padding:9px;margin:8px 0;box-shadow:0 1px 6px #0001}
.event.income{border-left-color:#16a34a}
.event.repair,.event.service,.event.expense{border-left-color:#dc2626}
.event.downtime{border-left-color:#f97316}
.event .sum{font-weight:bold}
.event .raw{font-size:13px;color:#6b7280;margin-top:4px}
@media(max-width:800px){.grid{grid-template-columns:1fr 1fr}input.msg{width:100%;margin-bottom:8px}table{font-size:12px}}
</style></head><body><div class="wrap"><h1>🚗 FleetAI Cloud</h1>
<div id="summary"></div>
<div class="card"><input class="msg" id="msg" placeholder="703 получил 13000 / 703 простой 3 дня коробка / 703 замена масла 2500 работа 700"><button onclick="add()">Записать</button><p id="res"></p></div>

<div class="card warn"><h2>Инвесторы</h2><div id="investors"></div></div>

<div class="card">
<h2>Добавить машину</h2>
<select id="owner_type"><option value="own">Моя машина</option><option value="investor">Машина инвестора</option></select>
<input id="code" placeholder="Код 777"><input id="brand" placeholder="Марка"><input id="model" placeholder="Модель"><input id="plate" placeholder="Госномер">
<input id="year" placeholder="Год"><input id="purchase_date" placeholder="Дата покупки"><input id="purchase_price" placeholder="Цена покупки"><input id="mileage" placeholder="Пробег">
<input id="investor_name" placeholder="Имя инвестора"><input id="investor_percent" placeholder="% инвестора"><input id="settlement_day" placeholder="Расчетный день 15"><button onclick="addCar()">Добавить авто</button><p id="carRes"></p>
</div>

<div class="card">
<h2>Машины</h2><div class="tabs"><button id="tab_all" class="active" onclick="loadCars('all')">Все</button><button id="tab_own" onclick="loadCars('own')">Мои</button><button id="tab_investor" onclick="loadCars('investor')">Инвесторов</button></div>
<table id="cars"></table></div>

<div id="carCard"></div>

<div class="card"><h2>Последние операции</h2><table id="ops"></table></div>
</div><script>
let currentFilter='all';
async function api(u,o){let r=await fetch(u,o);return await r.json()}
function rub(n){return (n||0).toLocaleString('ru-RU')+' ₽'}
async function loadSummary(){let s=await api('/api/summary'); summary.innerHTML=`<div class="grid"><div class="stat">Всего <b>${s.cars}</b></div><div class="stat">Мои <b>${s.own_cars}</b></div><div class="stat">Инвесторов <b>${s.investor_cars}</b></div><div class="stat">Доход <b>${rub(s.income)}</b></div><div class="stat">Расход <b>${rub(s.expenses)}</b></div><div class="stat">Прибыль <b>${rub(s.profit)}</b></div><div class="stat">Простой <b>${s.downtime_days||0} дн.</b></div></div>`}
async function loadInvestors(){let d=await api('/api/investors'); if(!d.length){investors.innerHTML='Пока нет машин инвесторов';return} investors.innerHTML=d.map(i=>`<div class="card"><h3>${i.name}</h3><b>Вложил:</b> ${rub(i.total_invested)} | <b>Выплачено:</b> ${rub(i.total_payouts)} | <b>Остаток:</b> ${rub(i.balance)} | <b>Общая прибыль:</b> ${rub(i.total_profit)} | <b>Доля инвестора:</b> ${rub(i.total_to_investor)} | <b>Простой:</b> ${i.total_downtime_days||0} дн.<table><tr><th>Машина</th><th>%</th><th>Доход</th><th>Расход</th><th>Прибыль</th><th>Инвестору</th><th>Простой</th><th>Расчет</th><th>Карточка</th></tr>${i.cars.map(c=>`<tr><td>${c.code} ${c.car}</td><td>${c.percent}%</td><td>${rub(c.income)}</td><td>${rub(c.expenses)}</td><td>${rub(c.profit)}</td><td>${rub(c.to_investor)}</td><td>${c.downtime_days||0} дн.</td><td><button onclick="openCar('${c.code}')">Открыть</button></td></tr>`).join('')}</table></div>`).join('')}
async function loadCars(filter='all'){currentFilter=filter; ['all','own','investor'].forEach(x=>document.getElementById('tab_'+x).classList.remove('active')); document.getElementById('tab_'+filter).classList.add('active'); let url='/api/cars'; if(filter!=='all')url+='?owner_type='+filter; let c=await api(url); cars.innerHTML='<tr><th>Тип</th><th>Код</th><th>Авто</th><th>Госномер</th><th>Инвестор</th><th>%</th><th>Пробег</th><th>Стоимость</th><th>Доход</th><th>Расход</th><th>Прибыль</th><th>Простой</th><th>Расчет</th><th>Карточка</th></tr>'+c.map(x=>`<tr><td><span class="badge">${x.owner_type==='investor'?'Инвестор':'Моя'}</span></td><td>${x.code}</td><td>${x.brand||''} ${x.model||''}</td><td>${x.plate||''}</td><td>${x.investor_name||''}</td><td>${x.investor_percent||0}</td><td>${x.mileage||0}</td><td>${rub(x.full_cost)}</td><td>${rub(x.income)}</td><td>${rub(x.expenses)}</td><td class="${x.profit>=0?'ok':'bad'}">${rub(x.profit)}</td><td>${x.downtime_days||0} дн.</td><td>${x.settlement_day||15} число<br><button onclick="openPeriod('${x.code}')">Расчет</button></td><td><button onclick="openCar('${x.code}')">Открыть</button></td></tr>`).join('')}

function groupByDate(operations){
  let groups = {};
  operations.forEach(o=>{
    let day = (o.date || '').split(' ')[0] || 'Без даты';
    if(!groups[day]) groups[day] = [];
    groups[day].push(o);
  });
  return groups;
}

function eventTitle(o){
  if(o.type === 'income') return '💰 Доход';
  if(o.type === 'repair') return '🔧 Ремонт';
  if(o.type === 'service') return '🛠 ТО';
  if(o.type === 'expense') return '💸 Расход';
  if(o.type === 'car_investment') return '📈 Доп. вложение';
  if(o.type === 'downtime') return '🚫 Простой';
  if(o.type === 'downtime_closed') return '✅ Простой закрыт';
  return '📝 Запись';
}

function renderCalendar(operations){
  let groups = groupByDate(operations);

  return `<div class="calendar">
    ${Object.keys(groups).map(day=>`
      <div class="daycard">
        <h4>${day}</h4>
        ${groups[day].map(o=>`
          <div class="event ${o.type}">
            <div><b>${eventTitle(o)}</b></div>
            <div>${o.description || ''}</div>
            <div class="sum">${rub(o.amount)}</div>
            ${o.mileage ? `<div>Пробег: ${o.mileage}</div>` : ''}
            <div class="raw">${o.raw || ''}</div>
          </div>
        `).join('')}
      </div>
    `).join('')}
  </div>`;
}



async function openPeriod(code){
  let d = await api('/api/period/' + code);
  if(!d.ok){alert(d.message);return}

  let p = d.current_period;
  let html = `
  <div class="card warn">
    <h2>Расчетный период машины ${code}</h2>
    <p><b>Период:</b> ${p.start_date} — ${p.end_date}</p>
    <p><b>Расчетный день:</b> ${d.settlement_day} число</p>
    <p><b>Доход:</b> ${rub(p.income)}</p>
    <p><b>Расход:</b> ${rub(p.expenses)}</p>
    <p><b>Доп. вложения:</b> ${rub(p.investments)}</p>
    <p><b>Прибыль:</b> ${rub(p.profit)}</p>
    <p><b>Инвестору:</b> ${rub(p.investor_amount)} ${p.investor_percent ? '('+p.investor_percent+'%)' : ''}</p>
    <p><b>Собственнику:</b> ${rub(p.owner_amount)}</p>
    <p><b>Простой:</b> ${p.downtime_days || 0} дн.</p>
    <button onclick="closePeriod('${code}')">Закрыть расчетный период</button>
  </div>

  <div class="card">
    <h3>История закрытых периодов</h3>
    <table>
      <tr><th>Период</th><th>Доход</th><th>Расход</th><th>Прибыль</th><th>Инвестору</th><th>Собственнику</th><th>Простой</th><th>Закрыт</th></tr>
      ${d.closed_periods.map(x=>`
        <tr>
          <td>${x.start_date} — ${x.end_date}</td>
          <td>${rub(x.income)}</td>
          <td>${rub(x.expenses)}</td>
          <td>${rub(x.profit)}</td>
          <td>${rub(x.investor_amount)}</td>
          <td>${rub(x.owner_amount)}</td>
          <td>${x.downtime_days||0} дн.</td>
          <td>${x.closed_at}</td>
        </tr>
      `).join('')}
    </table>
  </div>`;

  document.getElementById('carCard').innerHTML = html;
  window.scrollTo(0, document.getElementById('carCard').offsetTop);
}

async function closePeriod(code){
  if(!confirm('Закрыть расчетный период по машине '+code+'?')) return;
  let r = await api('/api/close-period/' + code, {
    method:'POST',
    headers:{'Content-Type':'application/json'},
    body:JSON.stringify({})
  });
  alert(r.message);
  await load();
  await openPeriod(code);
}


async function openCar(code){let d=await api('/api/car/'+code); if(!d.ok){alert(d.message);return} let c=d.car; let html=`<div class="card"><h2>${c.code} ${c.brand||''} ${c.model||''}</h2><p><b>Госномер:</b> ${c.plate||''}</p><p><b>Год:</b> ${c.year||''}</p><p><b>Пробег:</b> ${c.mileage||0}</p><p><b>Стоимость покупки:</b> ${rub(c.purchase_price)}</p><p><b>Доп. вложения:</b> ${rub(c.investments)}</p><p><b>Полная стоимость:</b> ${rub(c.full_cost)}</p><p><b>Доход:</b> ${rub(c.income)}</p><p><b>Расход:</b> ${rub(c.expenses)}</p><p><b>Прибыль:</b> ${rub(c.profit)}</p><p><b>Дни простоя:</b> ${c.downtime_days||0} дн.</p><p><button onclick="closeDowntime('${c.code}')">Закрыть активный простой</button></p><p><b>Инвестор:</b> ${c.investor_name||'-'} ${c.investor_percent?'('+c.investor_percent+'%)':''}</p><p><button onclick="openPeriod('${c.code}')">Открыть расчетный период</button></p></div><div class="card"><h3>Простои</h3><table><tr><th>Дата начала</th><th>Дата конца</th><th>Дней</th><th>Статус</th><th>Причина</th><th>Комментарий</th></tr>${d.downtime.map(o=>`<tr><td>${o.date}</td><td>${o.end_date||''}</td><td>${o.days}</td><td>${o.active?'Активный':'Закрыт'}</td><td>${o.reason||''}</td><td>${o.comment||''}</td></tr>`).join('')}</table></div><div class="card"><h3>Календарь изменений</h3>${renderCalendar(d.operations)}</div><div class="card"><h3>История машины таблицей</h3><table><tr><th>Дата</th><th>Тип</th><th>Описание</th><th>Сумма</th><th>Пробег</th><th>Сообщение</th></tr>${d.operations.map(o=>`<tr><td>${o.date}</td><td>${o.type}</td><td>${o.description||''}</td><td>${rub(o.amount)}</td><td>${o.mileage||''}</td><td>${o.raw||''}</td></tr>`).join('')}</table></div>`; document.getElementById('carCard').innerHTML=html; window.scrollTo(0,document.getElementById('carCard').offsetTop)}
async function closeDowntime(code){
  let r=await api('/api/close-downtime/'+code,{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({})});
  alert(r.message);
  await load();
  await openCar(code);
}
async function loadOps(){let o=await api('/api/operations'); ops.innerHTML='<tr><th>Дата</th><th>Машина</th><th>Тип</th><th>Описание</th><th>Сумма</th><th>Сообщение</th></tr>'+o.map(x=>`<tr><td>${x.date}</td><td>${x.car_code}</td><td>${x.type}</td><td>${x.description||''}</td><td>${rub(x.amount)}</td><td>${x.raw||''}</td></tr>`).join('')}
async function load(){await loadSummary(); await loadInvestors(); await loadCars(currentFilter); await loadOps()}
async function add(){
  let m=msg.value;
  try{
    let r=await api('/api/add',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({message:m})});
    res.innerText=r.message || JSON.stringify(r);
    if(r.ok){msg.value='';}
    await load();
  }catch(e){
    res.innerText='Ошибка записи. Открой Render Logs или проверь /api/add. ' + e;
  }
}
async function addCar(){let payload={owner_type:owner_type.value,code:code.value,brand:brand.value,model:model.value,plate:plate.value,year:year.value,purchase_date:purchase_date.value,purchase_price:purchase_price.value,mileage:mileage.value,investor_name:investor_name.value,investor_percent:investor_percent.value,settlement_day:settlement_day.value}; let r=await api('/api/add-car',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(payload)}); carRes.innerText=r.message; load()}
msg.addEventListener('keydown',e=>{if(e.key==='Enter')add()}); load();
</script></body></html>
"""

ensure_schema()
init_seed()

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.getenv("PORT", 8000)))
