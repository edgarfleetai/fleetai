import os
import re
from datetime import datetime, date
from flask import Flask, request, jsonify, render_template_string
from sqlalchemy import create_engine, Column, Integer, String, DateTime, Text, func, text as sql_text
from sqlalchemy.orm import declarative_base, sessionmaker

DATABASE_URL = os.getenv("DATABASE_URL", "sqlite:///fleet.db")
if DATABASE_URL.startswith("postgres://"):
    DATABASE_URL = DATABASE_URL.replace("postgres://", "postgresql://", 1)

engine = create_engine(DATABASE_URL, future=True)
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
    driver = Column(String)

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
    date = Column(DateTime, default=datetime.now)
    car_code = Column(String)
    category = Column(String)
    description = Column(String)
    amount = Column(Integer, default=0)
    investor_name = Column(String, default="")
    raw_message = Column(Text)

class InvestorInvestment(Base):
    __tablename__ = "investor_investments"
    id = Column(Integer, primary_key=True)
    date = Column(DateTime, default=datetime.now)
    investor_name = Column(String)
    car_code = Column(String)
    amount = Column(Integer, default=0)
    percent = Column(Integer, default=0)
    comment = Column(Text)

class InvestorPayout(Base):
    __tablename__ = "investor_payouts"
    id = Column(Integer, primary_key=True)
    date = Column(DateTime, default=datetime.now)
    investor_name = Column(String)
    car_code = Column(String)
    amount = Column(Integer, default=0)
    period_start = Column(DateTime)
    period_end = Column(DateTime)
    comment = Column(Text)

class InvestorPeriod(Base):
    __tablename__ = "investor_periods"
    id = Column(Integer, primary_key=True)
    investor_name = Column(String)
    start_date = Column(DateTime)
    end_date = Column(DateTime)
    income = Column(Integer, default=0)
    expenses = Column(Integer, default=0)
    profit = Column(Integer, default=0)
    investor_amount = Column(Integer, default=0)
    owner_amount = Column(Integer, default=0)
    status = Column(String, default="open")  # open / closed / paid
    paid_date = Column(DateTime)
    created_at = Column(DateTime, default=datetime.now)

PARTS = {
    "стойка стаба": ("Стойка стабилизатора", "Подвеска"),
    "стаба": ("Стойка стабилизатора", "Подвеска"),
    "замена колес": ("Замена колес", "Шиномонтаж"),
    "амортизатор": ("Амортизатор", "Подвеска"),
    "колодки": ("Тормозные колодки", "Тормоза"),
    "накладки": ("Тормозные колодки", "Тормоза"),
    "шаровая": ("Шаровая опора", "Подвеска"),
    "рулевая рейка": ("Рулевая рейка", "Рулевое"),
    "рейка": ("Рулевая рейка", "Рулевое"),
    "масло": ("Масло двигателя", "ТО"),
    "салонный": ("Салонный фильтр", "ТО"),
    "воздушный": ("Воздушный фильтр", "ТО"),
    "масляный": ("Масляный фильтр", "ТО"),
    "масленый": ("Масляный фильтр", "ТО"),
    "сцепление": ("Сцепление", "Трансмиссия"),
    "выжимной": ("Выжимной подшипник", "Трансмиссия"),
    "маховик": ("Маховик", "Трансмиссия"),
    "помпа": ("Помпа", "Охлаждение"),
    "антифриз": ("Антифриз", "Охлаждение"),
    "фрион": ("Фреон", "Кондиционер"),
    "лобач": ("Лобовое стекло", "Кузов"),
    "лобовое": ("Лобовое стекло", "Кузов"),
    "тонер": ("Тонировка", "Кузов"),
    "тонировка": ("Тонировка", "Кузов"),
    "химчистка": ("Химчистка", "Салон"),
    "фара": ("Фара", "Кузов"),
}
BRANDS = ["amd", "ctr", "mann", "mando", "lynx", "hi-q", "hiq", "sachs", "kyb", "gates", "bosch", "ngk", "denso", "shell", "лукойл"]

def ensure_migrations():
    with engine.begin() as conn:
        for sql in [
            "ALTER TABLE cars ADD COLUMN owner_type VARCHAR DEFAULT 'own'",
            "ALTER TABLE cars ADD COLUMN investor_name VARCHAR DEFAULT ''",
            "ALTER TABLE cars ADD COLUMN investor_percent INTEGER DEFAULT 0",
            "ALTER TABLE expenses ADD COLUMN share_type VARCHAR DEFAULT 'shared'",
        ]:
            try:
                conn.execute(sql_text(sql))
            except Exception:
                pass

def period_15(today=None):
    today = today or date.today()
    if today.day >= 15:
        start = date(today.year, today.month, 15)
        if today.month == 12:
            end = date(today.year + 1, 1, 15)
        else:
            end = date(today.year, today.month + 1, 15)
    else:
        end = date(today.year, today.month, 15)
        if today.month == 1:
            start = date(today.year - 1, 12, 15)
        else:
            start = date(today.year, today.month - 1, 15)
    return datetime.combine(start, datetime.min.time()), datetime.combine(end, datetime.min.time())

def parse_message(message):
    raw = message.strip()
    text = raw.lower().replace(",", " ").replace(".", " ")
    data = dict(raw=raw, car_code=None, type="unknown", category="", description="", part="",
                brand="", position="", part_price=0, labor=0, total=0, income=0, mileage=None, share_type="shared")

    car = re.match(r"^(\d{3})\b", text)
    if car:
        data["car_code"] = car.group(1)

    m = re.search(r"пробег\s*(\d{4,7})", text)
    if m:
        data["mileage"] = int(m.group(1))

    if "моя ответственность" in text or "не делить" in text:
        data["share_type"] = "owner_only"
    elif "инвестора" in text and "расход" in text:
        data["share_type"] = "investor_only"

    if "справа" in text or "правая" in text:
        data["position"] = "Правая"
    elif "слева" in text or "левая" in text:
        data["position"] = "Левая"
    elif "перед" in text:
        data["position"] = "Передняя ось"
    elif "зад" in text:
        data["position"] = "Задняя ось"

    for b in BRANDS:
        if re.search(r"\b" + re.escape(b) + r"\b", text):
            data["brand"] = b.upper()
            break


    # Дополнительные вложения в машину: 665 вложение ГБО 58000
    if any(w in text for w in ["вложение", "доп вложение", "допвложение", "кап вложение"]):
        data["type"] = "car_investment"
        data["category"] = "Капитальное вложение"
        nums = [int(x) for x in re.findall(r"\b\d{2,9}\b", text)]
        nums = [n for n in nums if str(n) != data["car_code"]]
        if nums:
            data["total"] = nums[-1]
        desc = text
        for w in ["вложение", "доп вложение", "допвложение", "кап вложение"]:
            desc = desc.replace(w, "")
        desc = re.sub(r"\b\d{2,9}\b", "", desc).strip()
        data["description"] = desc or "Дополнительное вложение"
        return data

    # Деньги инвестора в машину: 665 инвестор Иван вложил 300000 50%
    if "инвестор" in text and any(w in text for w in ["вложил", "внес", "дал"]):
        data["type"] = "investor_investment"
        data["category"] = "Вложение инвестора"
        nums = [int(x) for x in re.findall(r"\b\d{2,9}\b", text)]
        nums = [n for n in nums if str(n) != data["car_code"]]
        if nums:
            data["total"] = nums[0]
        pct = re.search(r"(\d{1,3})\s*%", text)
        data["investor_percent"] = int(pct.group(1)) if pct else 0
        name = re.search(r"инвестор\s+([а-яa-zё]+)", text)
        data["investor_name"] = name.group(1).capitalize() if name else ""
        data["description"] = "Вложение инвестора"
        return data

    # Выплата инвестору: 665 выплата Ивану 25000
    if "выплата" in text:
        data["type"] = "investor_payout"
        data["category"] = "Выплата инвестору"
        nums = [int(x) for x in re.findall(r"\b\d{2,9}\b", text)]
        nums = [n for n in nums if str(n) != data["car_code"]]
        if nums:
            data["total"] = nums[-1]
        name = re.search(r"выплата\s+([а-яa-zё]+)", text)
        data["investor_name"] = name.group(1).capitalize() if name else ""
        data["description"] = "Выплата инвестору"
        return data

    if any(w in text for w in ["получил", "расчет", "недельный", "перевел"]):
        data["type"] = "income"
        nums = [int(x) for x in re.findall(r"\b\d{3,7}\b", text)]
        nums = [n for n in nums if str(n) != data["car_code"]]
        if nums:
            data["income"] = nums[-1]
            data["total"] = nums[-1]
        data["description"] = "Недельный расчет"
        return data

    expense_words = {"штраф":"Штраф","страховка":"Страховка","мойка":"Мойка","бензин":"Топливо","газ":"Топливо","эвакуатор":"Эвакуатор"}
    for word, cat in expense_words.items():
        if word in text:
            data["type"] = "expense"
            data["category"] = cat
            data["description"] = cat
            nums = [int(x) for x in re.findall(r"\b\d{2,7}\b", text)]
            nums = [n for n in nums if str(n) != data["car_code"]]
            if nums:
                data["total"] = nums[-1]
            return data

    for key, val in sorted(PARTS.items(), key=lambda x: len(x[0]), reverse=True):
        if key in text:
            data["part"], data["category"] = val
            data["description"] = "Замена " + data["part"].lower()
            data["type"] = "service" if data["category"] == "ТО" else "repair"
            break

    price = re.search(r"(стоимость|цена)\s*(\d+)", text)
    if price:
        data["part_price"] = int(price.group(2))
    labor = re.search(r"(работа|ремонт)\s*(\d+)", text)
    if labor:
        data["labor"] = int(labor.group(2))

    if data["part"] and data["part_price"] == 0:
        nums = [int(x) for x in re.findall(r"\b\d{2,7}\b", text)]
        filtered = [n for n in nums if str(n) != data["car_code"] and n != data["mileage"]]
        if filtered:
            data["part_price"] = filtered[0]
        if len(filtered) > 1 and data["labor"] == 0:
            data["labor"] = filtered[1]

    data["total"] = data["part_price"] + data["labor"]
    return data

def init_data():
    Base.metadata.create_all(engine)
    ensure_migrations()
    s = Session()
    seed = [
        ("897","Kia","Rio","К897УР716",2018,"11.2025",900000,180000,"own","",0),
        ("119","Kia","Rio","В119ЕН716",2018,"21.03.2025",790000,253000,"own","",0),
        ("665","Kia","Rio","С665ХК716",2020,"04.2024",1575000,240000,"own","",0),
        ("404","Hyundai","Solaris","Н404ЕК716",2017,"09.04.2026",575000,410000,"own","",0),
        ("218","Hyundai","Solaris","Е218РТ716",None,"22.04.2026",420000,280000,"own","",0),
    ]
    for code, brand, model, plate, year, pd, pp, mil, owner_type, investor_name, investor_percent in seed:
        if not s.query(Car).filter_by(code=code).first():
            s.add(Car(code=code, brand=brand, model=model, plate=plate, year=year,
                      purchase_date=pd, purchase_price=pp, purchase_mileage=mil, current_mileage=mil,
                      owner_type=owner_type, investor_name=investor_name, investor_percent=investor_percent))
    s.commit()
    s.close()

def save(data):
    s = Session()
    car = s.query(Car).filter_by(code=data.get("car_code")).first()
    if not data.get("car_code") or not car:
        s.close()
        return {"ok": False, "message": "Машина не найдена или не указан код"}

    op = Operation(car_code=data["car_code"], type=data["type"], category=data["category"],
                   description=data["description"], amount=data["total"], mileage=data["mileage"], raw_message=data["raw"])
    s.add(op)
    s.flush()


    if data["type"] == "car_investment":
        s.add(CarInvestment(car_code=data["car_code"], category=data.get("category"),
                            description=data.get("description"), amount=data.get("total", 0),
                            investor_name=data.get("investor_name", ""), raw_message=data.get("raw")))

    if data["type"] == "investor_investment":
        s.add(InvestorInvestment(investor_name=data.get("investor_name", ""), car_code=data["car_code"],
                                 amount=data.get("total", 0), percent=data.get("investor_percent", 0),
                                 comment=data.get("raw")))
        car.owner_type = "investor"
        if data.get("investor_name"):
            car.investor_name = data.get("investor_name")
        if data.get("investor_percent"):
            car.investor_percent = data.get("investor_percent")

    if data["type"] == "investor_payout":
        start, end = period_15()
        s.add(InvestorPayout(investor_name=data.get("investor_name", ""), car_code=data["car_code"],
                             amount=data.get("total", 0), period_start=start, period_end=end,
                             comment=data.get("raw")))

    if data["type"] == "income":
        s.add(Income(operation_id=op.id, car_code=data["car_code"], amount=data["income"], income_type=data["description"]))

    if data["type"] in ("repair", "service", "expense"):
        s.add(Expense(operation_id=op.id, car_code=data["car_code"], category=data["category"], amount=data["total"], share_type=data.get("share_type","shared")))

    if data.get("part"):
        old = s.query(Part).filter_by(car_code=data["car_code"], part_name=data["part"], position=data["position"], status="Установлена").all()
        for p in old:
            p.status = "Снята"
            p.remove_date = datetime.now()
            p.remove_mileage = data["mileage"]

        s.add(Part(car_code=data["car_code"], operation_id=op.id, part_name=data["part"], brand=data["brand"],
                   position=data["position"], price=data["part_price"], labor=data["labor"], install_mileage=data["mileage"]))

    if data.get("mileage"):
        car.current_mileage = data["mileage"]

    s.commit()
    op_id = op.id
    s.close()
    return {"ok": True, "message": f"Записано. Операция #{op_id}", "data": data}

def investor_period_calc(investor_name, start, end):
    s = Session()
    cars = s.query(Car).filter(Car.owner_type=="investor", Car.investor_name==investor_name).all()
    car_codes = [c.code for c in cars]
    if not car_codes:
        s.close()
        return {"investor_name": investor_name, "cars": [], "income":0, "expenses":0, "profit":0, "investor_amount":0, "owner_amount":0, "start":start.isoformat(), "end":end.isoformat()}

    income = s.query(func.coalesce(func.sum(Income.amount),0)).filter(Income.car_code.in_(car_codes), Income.date >= start, Income.date < end).scalar()
    # Расходы делим только shared. owner_only не уменьшает расчет инвестора.
    expenses = s.query(func.coalesce(func.sum(Expense.amount),0)).filter(Expense.car_code.in_(car_codes), Expense.date >= start, Expense.date < end, Expense.share_type!="owner_only").scalar()
    profit = income - expenses

    # Если у инвестора несколько авто с разными %, считаем по каждой машине отдельно.
    investor_amount = 0
    details = []
    for c in cars:
        ci = s.query(func.coalesce(func.sum(Income.amount),0)).filter_by(car_code=c.code).filter(Income.date >= start, Income.date < end).scalar()
        ce = s.query(func.coalesce(func.sum(Expense.amount),0)).filter_by(car_code=c.code).filter(Expense.date >= start, Expense.date < end, Expense.share_type!="owner_only").scalar()
        cp = ci - ce
        ca = round(cp * (c.investor_percent or 0) / 100)
        investor_amount += ca
        details.append({"code": c.code, "car": f"{c.brand or ''} {c.model or ''}", "percent": c.investor_percent or 0, "income": ci, "expenses": ce, "profit": cp, "investor_amount": ca})
    s.close()

    return {
        "investor_name": investor_name,
        "cars": details,
        "income": income,
        "expenses": expenses,
        "profit": profit,
        "investor_amount": investor_amount,
        "owner_amount": profit - investor_amount,
        "start": start.strftime("%d.%m.%Y"),
        "end": end.strftime("%d.%m.%Y")
    }

@app.route("/")
def index():
    return render_template_string(HTML)

@app.route("/api/add", methods=["POST"])
def api_add():
    return jsonify(save(parse_message(request.json.get("message",""))))

@app.route("/api/add-car", methods=["POST"])
def api_add_car():
    p = request.json
    s = Session()
    if s.query(Car).filter_by(code=p.get("code")).first():
        s.close()
        return jsonify({"ok": False, "message": "Машина с таким кодом уже есть"})
    car = Car(
        code=p.get("code"),
        brand=p.get("brand"),
        model=p.get("model"),
        plate=p.get("plate"),
        year=int(p.get("year") or 0) or None,
        purchase_date=p.get("purchase_date"),
        purchase_price=int(p.get("purchase_price") or 0),
        purchase_mileage=int(p.get("mileage") or 0),
        current_mileage=int(p.get("mileage") or 0),
        owner_type=p.get("owner_type") or "own",
        investor_name=p.get("investor_name") or "",
        investor_percent=int(p.get("investor_percent") or 0),
        status="Работает"
    )
    s.add(car)
    s.commit()
    s.close()
    return jsonify({"ok": True, "message": "Машина добавлена"})

@app.route("/api/summary")
def api_summary():
    s = Session()
    cars = s.query(Car).count()
    own_cars = s.query(Car).filter_by(owner_type="own").count()
    investor_cars = s.query(Car).filter_by(owner_type="investor").count()
    income = s.query(func.coalesce(func.sum(Income.amount),0)).scalar()
    expenses = s.query(func.coalesce(func.sum(Expense.amount),0)).scalar()
    car_investments = s.query(func.coalesce(func.sum(CarInvestment.amount),0)).scalar()
    investor_investments = s.query(func.coalesce(func.sum(InvestorInvestment.amount),0)).scalar()
    investor_payouts = s.query(func.coalesce(func.sum(InvestorPayout.amount),0)).scalar()
    s.close()
    return jsonify(dict(cars=cars, own_cars=own_cars, investor_cars=investor_cars,
                        income=income, expenses=expenses, profit=income-expenses,
                        car_investments=car_investments,
                        investor_investments=investor_investments,
                        investor_payouts=investor_payouts))

@app.route("/api/cars")
def api_cars():
    owner_type = request.args.get("owner_type")
    s = Session()
    q = s.query(Car).order_by(Car.code)
    if owner_type in ("own", "investor"):
        q = q.filter_by(owner_type=owner_type)
    rows = []
    for c in q.all():
        income = s.query(func.coalesce(func.sum(Income.amount),0)).filter_by(car_code=c.code).scalar()
        expenses = s.query(func.coalesce(func.sum(Expense.amount),0)).filter_by(car_code=c.code).scalar()
        car_investments = s.query(func.coalesce(func.sum(CarInvestment.amount),0)).filter_by(car_code=c.code).scalar()
        investor_investments = s.query(func.coalesce(func.sum(InvestorInvestment.amount),0)).filter_by(car_code=c.code).scalar()
        investor_payouts = s.query(func.coalesce(func.sum(InvestorPayout.amount),0)).filter_by(car_code=c.code).scalar()
        rows.append(dict(code=c.code, brand=c.brand, model=c.model, plate=c.plate, mileage=c.current_mileage,
                         status=c.status, income=income, expenses=expenses, profit=income-expenses,
                         car_investments=car_investments, real_cost=(c.purchase_price or 0)+car_investments,
                         investor_investments=investor_investments, investor_payouts=investor_payouts,
                         owner_type=c.owner_type or "own", investor_name=c.investor_name or "",
                         investor_percent=c.investor_percent or 0))
    s.close()
    return jsonify(rows)

@app.route("/api/investors")
def api_investors():
    s = Session()
    names = [r[0] for r in s.query(Car.investor_name).filter(Car.owner_type=="investor", Car.investor_name!="").distinct().all()]
    s.close()
    start, end = period_15()
    data = [investor_period_calc(name, start, end) for name in names]
    return jsonify({"period_start": start.strftime("%d.%m.%Y"), "period_end": end.strftime("%d.%m.%Y"), "investors": data})

@app.route("/api/close-period", methods=["POST"])
def api_close_period():
    name = request.json.get("investor_name")
    start, end = period_15()
    calc = investor_period_calc(name, start, end)
    s = Session()
    existing = s.query(InvestorPeriod).filter_by(investor_name=name, start_date=start, end_date=end).first()
    if existing:
        existing.income = calc["income"]
        existing.expenses = calc["expenses"]
        existing.profit = calc["profit"]
        existing.investor_amount = calc["investor_amount"]
        existing.owner_amount = calc["owner_amount"]
        existing.status = "closed"
    else:
        s.add(InvestorPeriod(investor_name=name, start_date=start, end_date=end,
                             income=calc["income"], expenses=calc["expenses"], profit=calc["profit"],
                             investor_amount=calc["investor_amount"], owner_amount=calc["owner_amount"], status="closed"))
    s.commit()
    s.close()
    return jsonify({"ok": True, "message": "Период закрыт", "period": calc})

@app.route("/api/operations")
def api_operations():
    s = Session()
    rows = [dict(id=o.id, date=o.date.strftime("%d.%m.%Y %H:%M"), car_code=o.car_code, type=o.type,
                 category=o.category, description=o.description, amount=o.amount, mileage=o.mileage, raw=o.raw_message)
            for o in s.query(Operation).order_by(Operation.id.desc()).limit(50).all()]
    s.close()
    return jsonify(rows)

HTML = r"""
<!doctype html><html lang="ru"><head><meta charset="utf-8"><title>FleetAI Cloud</title>
<style>
body{font-family:Arial;background:#f3f5f7;margin:0;color:#111827}.wrap{max-width:1250px;margin:auto;padding:24px}
.card{background:white;border-radius:16px;padding:18px;margin:14px 0;box-shadow:0 2px 12px #0001}.grid{display:grid;grid-template-columns:repeat(6,1fr);gap:12px}
.stat{background:#111827;color:white;border-radius:14px;padding:16px}.stat b{font-size:26px;display:block;margin-top:8px}
input,select{padding:12px;font-size:16px;border:1px solid #ddd;border-radius:10px;margin:4px}input.msg{width:78%;font-size:18px}button{padding:12px 16px;font-size:16px;border:0;border-radius:10px;background:#2563eb;color:white;cursor:pointer}
table{width:100%;border-collapse:collapse}td,th{padding:9px;border-bottom:1px solid #eee;text-align:left}.tabs button{background:#e5e7eb;color:#111}.tabs button.active{background:#2563eb;color:white}
.badge{padding:4px 8px;border-radius:999px;background:#e0f2fe;color:#0369a1;font-size:12px}.warn{background:#fff7ed;border-left:5px solid #f97316}
@media(max-width:700px){.grid{grid-template-columns:1fr}input.msg{width:100%;margin-bottom:8px}table{font-size:12px}}
</style></head><body><div class="wrap"><h1>🚗 FleetAI Cloud</h1>
<div id="summary"></div>
<div class="card"><input class="msg" id="msg" placeholder="665 стойка стаба AMD справа пробег 243000 стоимость 1000 ремонт 1000"><button onclick="add()">Записать</button><p id="res"></p></div>

<div class="card warn">
<h2>Инвесторы: расчетный период <span id="period"></span></h2>
<div id="investors"></div>
</div>

<div class="card">
<h2>Добавить машину</h2>
<select id="owner_type"><option value="own">Моя машина</option><option value="investor">Машина инвестора</option></select>
<input id="code" placeholder="Код 777">
<input id="brand" placeholder="Марка">
<input id="model" placeholder="Модель">
<input id="plate" placeholder="Госномер">
<input id="year" placeholder="Год">
<input id="purchase_date" placeholder="Дата покупки">
<input id="purchase_price" placeholder="Цена покупки">
<input id="mileage" placeholder="Пробег">
<input id="investor_name" placeholder="Имя инвестора">
<input id="investor_percent" placeholder="% инвестора">
<button onclick="addCar()">Добавить авто</button>
<p id="carRes"></p>
</div>

<div class="card">
<h2>Машины</h2>
<div class="tabs">
<button id="tab_all" class="active" onclick="loadCars('all')">Все</button>
<button id="tab_own" onclick="loadCars('own')">Мои</button>
<button id="tab_investor" onclick="loadCars('investor')">Инвесторов</button>
</div>
<table id="cars"></table>
</div>

<div class="card"><h2>Последние операции</h2><table id="ops"></table></div>
</div><script>
let currentFilter='all';
async function api(u,o){let r=await fetch(u,o);return await r.json()}
function rub(n){return (n||0).toLocaleString('ru-RU')+' ₽'}
async function loadSummary(){
 let s=await api('/api/summary'); summary.innerHTML=`<div class="grid"><div class="stat">Всего <b>${s.cars}</b></div><div class="stat">Мои <b>${s.own_cars}</b></div><div class="stat">Инвесторов <b>${s.investor_cars}</b></div><div class="stat">Доход <b>${rub(s.income)}</b></div><div class="stat">Прибыль <b>${rub(s.profit)}</b></div><div class="stat">Доп. вложения <b>${rub(s.car_investments)}</b></div></div>`;
}
async function loadInvestors(){
 let d=await api('/api/investors'); period.innerText=`${d.period_start} — ${d.period_end}`;
 if(!d.investors.length){investors.innerHTML='Пока нет машин инвесторов'; return}
 investors.innerHTML=d.investors.map(i=>`
 <div class="card">
 <h3>${i.investor_name}</h3>
 <b>Доход:</b> ${rub(i.income)} |
 <b>Расходы:</b> ${rub(i.expenses)} |
 <b>Прибыль:</b> ${rub(i.profit)} |
 <b>К выплате инвестору:</b> ${rub(i.investor_amount)} |
 <b>Тебе:</b> ${rub(i.owner_amount)}
 <br><br><button onclick="closePeriod('${i.investor_name}')">Закрыть период</button>
 <table><tr><th>Машина</th><th>%</th><th>Доход</th><th>Расход</th><th>Прибыль</th><th>Инвестору</th></tr>
 ${i.cars.map(c=>`<tr><td>${c.code} ${c.car}</td><td>${c.percent}%</td><td>${rub(c.income)}</td><td>${rub(c.expenses)}</td><td>${rub(c.profit)}</td><td>${rub(c.investor_amount)}</td></tr>`).join('')}
 </table>
 </div>`).join('');
}
async function closePeriod(name){
 let r=await api('/api/close-period',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({investor_name:name})});
 alert(r.message); loadInvestors();
}
async function loadCars(filter='all'){
 currentFilter=filter;
 ['all','own','investor'].forEach(x=>document.getElementById('tab_'+x).classList.remove('active'));
 document.getElementById('tab_'+filter).classList.add('active');
 let url='/api/cars'; if(filter!=='all') url+='?owner_type='+filter;
 let c=await api(url);
 cars.innerHTML='<tr><th>Тип</th><th>Код</th><th>Авто</th><th>Госномер</th><th>Инвестор</th><th>%</th><th>Пробег</th><th>Стоимость</th><th>Доп. вложения</th><th>Доход</th><th>Расход</th><th>Прибыль</th></tr>'+c.map(x=>`<tr><td><span class="badge">${x.owner_type==='investor'?'Инвестор':'Моя'}</span></td><td>${x.code}</td><td>${x.brand||''} ${x.model||''}</td><td>${x.plate||''}</td><td>${x.investor_name||''}</td><td>${x.investor_percent||0}</td><td>${x.mileage||0}</td><td>${rub(x.real_cost)}</td><td>${rub(x.car_investments)}</td><td>${rub(x.income)}</td><td>${rub(x.expenses)}</td><td>${rub(x.profit)}</td></tr>`).join('');
}
async function loadOps(){
 let o=await api('/api/operations'); ops.innerHTML='<tr><th>Дата</th><th>Машина</th><th>Тип</th><th>Описание</th><th>Сумма</th><th>Сообщение</th></tr>'+o.map(x=>`<tr><td>${x.date}</td><td>${x.car_code}</td><td>${x.type}</td><td>${x.description||''}</td><td>${rub(x.amount)}</td><td>${x.raw||''}</td></tr>`).join('');
}
async function load(){await loadSummary(); await loadInvestors(); await loadCars(currentFilter); await loadOps();}
async function add(){let m=msg.value; let r=await api('/api/add',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({message:m})}); res.innerText=r.message; msg.value=''; load()}
async function addCar(){
 let payload={owner_type:owner_type.value,code:code.value,brand:brand.value,model:model.value,plate:plate.value,year:year.value,purchase_date:purchase_date.value,purchase_price:purchase_price.value,mileage:mileage.value,investor_name:investor_name.value,investor_percent:investor_percent.value};
 let r=await api('/api/add-car',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(payload)});
 carRes.innerText=r.message;
 if(r.ok){['code','brand','model','plate','year','purchase_date','purchase_price','mileage','investor_name','investor_percent'].forEach(id=>document.getElementById(id).value='')}
 load();
}
msg.addEventListener('keydown',e=>{if(e.key==='Enter')add()}); load();
</script></body></html>
"""

init_data()

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.getenv("PORT", 8000)))
