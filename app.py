import os
import re
from datetime import datetime
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

    if any(w in text for w in ["получил", "расчет", "недельный", "перевел"]):
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
        "ALTER TABLE expenses ADD COLUMN share_type VARCHAR DEFAULT 'shared'",
    ]
    with engine.begin() as conn:
        for sql in migrations:
            try:
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

    return income, expenses, investments, payouts, inv_in


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
    s.close()
    return jsonify(dict(cars=cars, own_cars=own_cars, investor_cars=investor_cars,
                        income=income, expenses=expenses, investments=investments, profit=income - expenses))


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
        income, expenses, investments, payouts, inv_in = car_finance(s, c.code)
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
                         investor_payouts=payouts))
    s.close()
    return jsonify(rows)


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

        for c in cars:
            income, expenses, investments, payouts, inv_in = car_finance(s, c.code)
            profit = income - expenses
            to_investor = round(profit * (c.investor_percent or 0) / 100)

            total_income += income
            total_expenses += expenses
            total_profit += profit
            total_to_investor += to_investor

            details.append(dict(
                code=c.code,
                car=f"{c.brand or ''} {c.model or ''}",
                percent=c.investor_percent or 0,
                income=income,
                expenses=expenses,
                profit=profit,
                to_investor=to_investor,
                invested=inv_in,
                payouts=payouts
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
.card{background:white;border-radius:16px;padding:18px;margin:14px 0;box-shadow:0 2px 12px #0001}.grid{display:grid;grid-template-columns:repeat(6,1fr);gap:12px}
.stat{background:#111827;color:white;border-radius:14px;padding:16px}.stat b{font-size:24px;display:block;margin-top:8px}
input,select{padding:12px;font-size:16px;border:1px solid #ddd;border-radius:10px;margin:4px}input.msg{width:78%;font-size:18px}button{padding:12px 16px;font-size:16px;border:0;border-radius:10px;background:#2563eb;color:white;cursor:pointer}
table{width:100%;border-collapse:collapse}td,th{padding:9px;border-bottom:1px solid #eee;text-align:left}.tabs button{background:#e5e7eb;color:#111}.tabs button.active{background:#2563eb;color:white}
.badge{padding:4px 8px;border-radius:999px;background:#e0f2fe;color:#0369a1;font-size:12px}.warn{background:#fff7ed;border-left:5px solid #f97316}
.ok{color:#16a34a}.bad{color:#dc2626}
@media(max-width:800px){.grid{grid-template-columns:1fr 1fr}input.msg{width:100%;margin-bottom:8px}table{font-size:12px}}
</style></head><body><div class="wrap"><h1>🚗 FleetAI Cloud</h1>
<div id="summary"></div>
<div class="card"><input class="msg" id="msg" placeholder="703 получил 13000"><button onclick="add()">Записать</button><p id="res"></p></div>

<div class="card warn"><h2>Инвесторы</h2><div id="investors"></div></div>

<div class="card">
<h2>Добавить машину</h2>
<select id="owner_type"><option value="own">Моя машина</option><option value="investor">Машина инвестора</option></select>
<input id="code" placeholder="Код 777"><input id="brand" placeholder="Марка"><input id="model" placeholder="Модель"><input id="plate" placeholder="Госномер">
<input id="year" placeholder="Год"><input id="purchase_date" placeholder="Дата покупки"><input id="purchase_price" placeholder="Цена покупки"><input id="mileage" placeholder="Пробег">
<input id="investor_name" placeholder="Имя инвестора"><input id="investor_percent" placeholder="% инвестора"><button onclick="addCar()">Добавить авто</button><p id="carRes"></p>
</div>

<div class="card">
<h2>Машины</h2><div class="tabs"><button id="tab_all" class="active" onclick="loadCars('all')">Все</button><button id="tab_own" onclick="loadCars('own')">Мои</button><button id="tab_investor" onclick="loadCars('investor')">Инвесторов</button></div>
<table id="cars"></table></div>
<div class="card"><h2>Последние операции</h2><table id="ops"></table></div>
</div><script>
let currentFilter='all';
async function api(u,o){let r=await fetch(u,o);return await r.json()}
function rub(n){return (n||0).toLocaleString('ru-RU')+' ₽'}
async function loadSummary(){let s=await api('/api/summary'); summary.innerHTML=`<div class="grid"><div class="stat">Всего <b>${s.cars}</b></div><div class="stat">Мои <b>${s.own_cars}</b></div><div class="stat">Инвесторов <b>${s.investor_cars}</b></div><div class="stat">Доход <b>${rub(s.income)}</b></div><div class="stat">Доп. вложения <b>${rub(s.investments)}</b></div><div class="stat">Прибыль <b>${rub(s.profit)}</b></div></div>`}
async function loadInvestors(){let d=await api('/api/investors'); if(!d.length){investors.innerHTML='Пока нет машин инвесторов';return} investors.innerHTML=d.map(i=>`<div class="card"><h3>${i.name}</h3><b>Вложил:</b> ${rub(i.total_invested)} | <b>Выплачено:</b> ${rub(i.total_payouts)} | <b>Остаток:</b> ${rub(i.balance)}<table><tr><th>Машина</th><th>%</th><th>Доход</th><th>Расход</th><th>Прибыль</th><th>Расчетно инвестору</th></tr>${i.cars.map(c=>`<tr><td>${c.code} ${c.car}</td><td>${c.percent}%</td><td>${rub(c.income)}</td><td>${rub(c.expenses)}</td><td>${rub(c.profit)}</td><td>${rub(c.to_investor)}</td></tr>`).join('')}</table></div>`).join('')}
async function loadCars(filter='all'){currentFilter=filter; ['all','own','investor'].forEach(x=>document.getElementById('tab_'+x).classList.remove('active')); document.getElementById('tab_'+filter).classList.add('active'); let url='/api/cars'; if(filter!=='all')url+='?owner_type='+filter; let c=await api(url); cars.innerHTML='<tr><th>Тип</th><th>Код</th><th>Авто</th><th>Госномер</th><th>Инвестор</th><th>%</th><th>Пробег</th><th>Стоимость</th><th>Доп.</th><th>Доход</th><th>Расход</th><th>Прибыль</th></tr>'+c.map(x=>`<tr><td><span class="badge">${x.owner_type==='investor'?'Инвестор':'Моя'}</span></td><td>${x.code}</td><td>${x.brand||''} ${x.model||''}</td><td>${x.plate||''}</td><td>${x.investor_name||''}</td><td>${x.investor_percent||0}</td><td>${x.mileage||0}</td><td>${rub(x.full_cost)}</td><td>${rub(x.car_investments)}</td><td>${rub(x.income)}</td><td>${rub(x.expenses)}</td><td class="${x.profit>=0?'ok':'bad'}">${rub(x.profit)}</td></tr>`).join('')}
async function loadOps(){let o=await api('/api/operations'); ops.innerHTML='<tr><th>Дата</th><th>Машина</th><th>Тип</th><th>Описание</th><th>Сумма</th><th>Сообщение</th></tr>'+o.map(x=>`<tr><td>${x.date}</td><td>${x.car_code}</td><td>${x.type}</td><td>${x.description||''}</td><td>${rub(x.amount)}</td><td>${x.raw||''}</td></tr>`).join('')}
async function load(){await loadSummary(); await loadInvestors(); await loadCars(currentFilter); await loadOps()}
async function add(){let m=msg.value; let r=await api('/api/add',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({message:m})}); res.innerText=r.message; msg.value=''; load()}
async function addCar(){let payload={owner_type:owner_type.value,code:code.value,brand:brand.value,model:model.value,plate:plate.value,year:year.value,purchase_date:purchase_date.value,purchase_price:purchase_price.value,mileage:mileage.value,investor_name:investor_name.value,investor_percent:investor_percent.value}; let r=await api('/api/add-car',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(payload)}); carRes.innerText=r.message; load()}
msg.addEventListener('keydown',e=>{if(e.key==='Enter')add()}); load();
</script></body></html>
"""

ensure_schema()
init_seed()

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.getenv("PORT", 8000)))
