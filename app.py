import os
import re
from datetime import datetime
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

    # NEW: разделение своих и инвесторских авто
    owner_type = Column(String, default="own")  # own / investor
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
    # Render/Postgres create_all не добавляет новые колонки в существующую таблицу.
    # Поэтому добавляем их вручную, если таблица уже была создана.
    with engine.begin() as conn:
        try:
            conn.execute(sql_text("ALTER TABLE cars ADD COLUMN owner_type VARCHAR DEFAULT 'own'"))
        except Exception:
            pass
        try:
            conn.execute(sql_text("ALTER TABLE cars ADD COLUMN investor_name VARCHAR DEFAULT ''"))
        except Exception:
            pass
        try:
            conn.execute(sql_text("ALTER TABLE cars ADD COLUMN investor_percent INTEGER DEFAULT 0"))
        except Exception:
            pass

def parse_message(message):
    raw = message.strip()
    text = raw.lower().replace(",", " ").replace(".", " ")
    data = dict(raw=raw, car_code=None, type="unknown", category="", description="", part="",
                brand="", position="", part_price=0, labor=0, total=0, income=0, mileage=None)

    car = re.match(r"^(\d{3})\b", text)
    if car:
        data["car_code"] = car.group(1)

    m = re.search(r"пробег\s*(\d{4,7})", text)
    if m:
        data["mileage"] = int(m.group(1))

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

    if data["type"] == "income":
        s.add(Income(operation_id=op.id, car_code=data["car_code"], amount=data["income"], income_type=data["description"]))

    if data["type"] in ("repair", "service", "expense"):
        s.add(Expense(operation_id=op.id, car_code=data["car_code"], category=data["category"], amount=data["total"]))

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
    s.close()
    return jsonify(dict(cars=cars, own_cars=own_cars, investor_cars=investor_cars, income=income, expenses=expenses, profit=income-expenses))

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
        rows.append(dict(code=c.code, brand=c.brand, model=c.model, plate=c.plate, mileage=c.current_mileage,
                         status=c.status, income=income, expenses=expenses, profit=income-expenses,
                         owner_type=c.owner_type or "own", investor_name=c.investor_name or "",
                         investor_percent=c.investor_percent or 0))
    s.close()
    return jsonify(rows)

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
body{font-family:Arial;background:#f3f5f7;margin:0;color:#111827}.wrap{max-width:1200px;margin:auto;padding:24px}
.card{background:white;border-radius:16px;padding:18px;margin:14px 0;box-shadow:0 2px 12px #0001}.grid{display:grid;grid-template-columns:repeat(5,1fr);gap:12px}
.stat{background:#111827;color:white;border-radius:14px;padding:16px}.stat b{font-size:26px;display:block;margin-top:8px}
input,select{padding:12px;font-size:16px;border:1px solid #ddd;border-radius:10px;margin:4px}input.msg{width:78%;font-size:18px}button{padding:12px 16px;font-size:16px;border:0;border-radius:10px;background:#2563eb;color:white;cursor:pointer}
table{width:100%;border-collapse:collapse}td,th{padding:9px;border-bottom:1px solid #eee;text-align:left}.tabs button{background:#e5e7eb;color:#111}.tabs button.active{background:#2563eb;color:white}
.badge{padding:4px 8px;border-radius:999px;background:#e0f2fe;color:#0369a1;font-size:12px}@media(max-width:700px){.grid{grid-template-columns:1fr}input.msg{width:100%;margin-bottom:8px}table{font-size:12px}}
</style></head><body><div class="wrap"><h1>🚗 FleetAI Cloud</h1>
<div id="summary"></div>
<div class="card"><input class="msg" id="msg" placeholder="665 стойка стаба AMD справа пробег 243000 стоимость 1000 ремонт 1000"><button onclick="add()">Записать</button><p id="res"></p></div>

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
 let s=await api('/api/summary'); summary.innerHTML=`<div class="grid"><div class="stat">Всего <b>${s.cars}</b></div><div class="stat">Мои <b>${s.own_cars}</b></div><div class="stat">Инвесторов <b>${s.investor_cars}</b></div><div class="stat">Доход <b>${rub(s.income)}</b></div><div class="stat">Прибыль <b>${rub(s.profit)}</b></div></div>`;
}
async function loadCars(filter='all'){
 currentFilter=filter;
 ['all','own','investor'].forEach(x=>document.getElementById('tab_'+x).classList.remove('active'));
 document.getElementById('tab_'+filter).classList.add('active');
 let url='/api/cars'; if(filter!=='all') url+='?owner_type='+filter;
 let c=await api(url);
 cars.innerHTML='<tr><th>Тип</th><th>Код</th><th>Авто</th><th>Госномер</th><th>Инвестор</th><th>%</th><th>Пробег</th><th>Доход</th><th>Расход</th><th>Прибыль</th></tr>'+c.map(x=>`<tr><td><span class="badge">${x.owner_type==='investor'?'Инвестор':'Моя'}</span></td><td>${x.code}</td><td>${x.brand||''} ${x.model||''}</td><td>${x.plate||''}</td><td>${x.investor_name||''}</td><td>${x.investor_percent||0}</td><td>${x.mileage||0}</td><td>${rub(x.income)}</td><td>${rub(x.expenses)}</td><td>${rub(x.profit)}</td></tr>`).join('');
}
async function loadOps(){
 let o=await api('/api/operations'); ops.innerHTML='<tr><th>Дата</th><th>Машина</th><th>Тип</th><th>Описание</th><th>Сумма</th><th>Сообщение</th></tr>'+o.map(x=>`<tr><td>${x.date}</td><td>${x.car_code}</td><td>${x.type}</td><td>${x.description||''}</td><td>${rub(x.amount)}</td><td>${x.raw||''}</td></tr>`).join('');
}
async function load(){await loadSummary(); await loadCars(currentFilter); await loadOps();}
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
