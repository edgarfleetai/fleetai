from sqlalchemy import text as sql_text
from db import Base, engine, Session
from models import Car
from utils import find_car


MIGRATIONS = [
    "ALTER TABLE cars ADD COLUMN owner_type VARCHAR DEFAULT 'own'",
    "ALTER TABLE cars ADD COLUMN investor_name VARCHAR DEFAULT ''",
    "ALTER TABLE cars ADD COLUMN investor_percent INTEGER DEFAULT 0",
    "ALTER TABLE cars ADD COLUMN driver VARCHAR DEFAULT ''",
    "ALTER TABLE cars ADD COLUMN settlement_day INTEGER DEFAULT 15",

    "ALTER TABLE cars ADD COLUMN weekly_payment INTEGER DEFAULT 0",
    "ALTER TABLE cars ADD COLUMN payment_weekday INTEGER DEFAULT 0",
    "ALTER TABLE cars ADD COLUMN next_payment_date VARCHAR DEFAULT ''",
    "ALTER TABLE cars ADD COLUMN payment_notifications INTEGER DEFAULT 1", 
    
    "ALTER TABLE expenses ADD COLUMN share_type VARCHAR DEFAULT 'shared'",
    "ALTER TABLE car_investments ADD COLUMN investor_name VARCHAR DEFAULT ''",
    "ALTER TABLE downtime ADD COLUMN operation_id INTEGER",
    "ALTER TABLE downtime ADD COLUMN active INTEGER DEFAULT 0",
]


def ensure_schema():
    Base.metadata.create_all(engine)

    for sql in MIGRATIONS:
        try:
            with engine.begin() as conn:
                conn.execute(sql_text(sql))
        except Exception:
            pass


def init_seed():
    session = Session()
    seed = [
        ("897", "Kia", "Rio", "К897УР716", 2018, "11.2025", 900000, 180000),
        ("119", "Kia", "Rio", "В119ЕН716", 2018, "21.03.2025", 790000, 253000),
        ("665", "Kia", "Rio", "С665ХК716", 2020, "04.2024", 1575000, 240000),
        ("404", "Hyundai", "Solaris", "Н404ЕК716", 2017, "09.04.2026", 575000, 410000),
        ("218", "Hyundai", "Solaris", "Е218РТ716", None, "22.04.2026", 420000, 280000),
    ]

    for code, brand, model, plate, year, purchase_date, purchase_price, mileage in seed:
        if not find_car(session, code):
            session.add(Car(
                code=code,
                brand=brand,
                model=model,
                plate=plate,
                year=year,
                purchase_date=purchase_date,
                purchase_price=purchase_price,
                purchase_mileage=mileage,
                current_mileage=mileage,
                owner_type="own",
                settlement_day=15,
                status="Работает",
            ))

    session.commit()
    session.close()
