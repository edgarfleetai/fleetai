import os
import re
from sqlalchemy import create_engine, inspect, text as sql_text
from sqlalchemy.orm import declarative_base, sessionmaker

DATABASE_URL = os.getenv("DATABASE_URL", "sqlite:///fleet.db")

if DATABASE_URL.startswith("postgres://"):
    DATABASE_URL = DATABASE_URL.replace("postgres://", "postgresql+psycopg://", 1)
elif DATABASE_URL.startswith("postgresql://") and not DATABASE_URL.startswith("postgresql+psycopg://"):
    DATABASE_URL = DATABASE_URL.replace("postgresql://", "postgresql+psycopg://", 1)

engine = create_engine(DATABASE_URL, future=True, pool_pre_ping=True)
Session = sessionmaker(bind=engine)
Base = declarative_base()


def configure_database(url):
    """Bind the existing session factory; used by explicitly isolated app tests."""
    global engine, DATABASE_URL
    if not isinstance(url, str) or not url:
        raise ValueError('An explicit database URL is required')
    if url.startswith('postgres://'):
        url = url.replace('postgres://', 'postgresql+psycopg://', 1)
    elif url.startswith('postgresql://'):
        url = url.replace('postgresql://', 'postgresql+psycopg://', 1)
    engine.dispose()
    DATABASE_URL = url
    engine = create_engine(url, future=True, pool_pre_ping=True)
    Session.configure(bind=engine)


def run_migrations(connection=None):
    if connection is None:
        with engine.begin() as conn:
            return run_migrations(conn)
    migrations = [
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

        """CREATE TABLE IF NOT EXISTS driver_telegram_links (
            id INTEGER PRIMARY KEY,
            car_code VARCHAR NOT NULL,
            driver_name VARCHAR DEFAULT '',
            link_token VARCHAR UNIQUE NOT NULL,
            created_at TIMESTAMP,
            expires_at TIMESTAMP,
            used_at TIMESTAMP
        )""",

        """CREATE TABLE IF NOT EXISTS driver_telegram_bindings (
            id INTEGER PRIMARY KEY,
            car_code VARCHAR NOT NULL,
            driver_name VARCHAR DEFAULT '',
            telegram_chat_id VARCHAR NOT NULL,
            telegram_username VARCHAR DEFAULT '',
            telegram_first_name VARCHAR DEFAULT '',
            linked_at TIMESTAMP,
            last_alert_level VARCHAR DEFAULT '',
            last_alert_at TIMESTAMP
        )""",
    ]

    for sql in migrations:
        alter = re.match(r'ALTER TABLE (\w+) ADD COLUMN (\w+) ', sql)
        if alter:
            table, column = alter.groups()
            if column in {c['name'] for c in inspect(connection).get_columns(table)}:
                continue
        # Missing permissions or an unsupported schema must stop initialization,
        # not leave the application serving partially protected data.
        connection.execute(sql_text(sql))


def init_db(seed=True):
    from .models import Base
    from .auth import _install_assignment_triggers
    with engine.begin() as connection:
        if connection.dialect.name == 'postgresql':
            # Serialize schema startup across multiple web workers.
            connection.execute(sql_text('SELECT pg_advisory_xact_lock(684593120)'))
        Base.metadata.create_all(connection)
        run_migrations(connection)
        _install_assignment_triggers(Base.metadata, connection)
    if seed:
        seed_cars()


def seed_cars():
    from .models import Car
    from .utils import find_car

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
                settlement_day=15,
                owner_type="own",
                status="Работает",
            ))

    session.commit()
    session.close()
