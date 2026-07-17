import os

from sqlalchemy import create_engine, text as sql_text
from sqlalchemy.orm import declarative_base, sessionmaker


DATABASE_URL = os.getenv("DATABASE_URL", "sqlite:///fleet.db")

if DATABASE_URL.startswith("postgres://"):
    DATABASE_URL = DATABASE_URL.replace(
        "postgres://",
        "postgresql+psycopg://",
        1,
    )
elif (
    DATABASE_URL.startswith("postgresql://")
    and not DATABASE_URL.startswith("postgresql+psycopg://")
):
    DATABASE_URL = DATABASE_URL.replace(
        "postgresql://",
        "postgresql+psycopg://",
        1,
    )


engine = create_engine(
    DATABASE_URL,
    future=True,
    pool_pre_ping=True,
)

Session = sessionmaker(bind=engine)
Base = declarative_base()


def run_migrations():
    """
    Добавляет недостающие столбцы в старые таблицы.

    Ошибки вида "столбец уже существует" специально пропускаются,
    чтобы приложение могло запускаться после каждого обновления.
    """
    migrations = [
        "ALTER TABLE cars ADD COLUMN owner_type VARCHAR DEFAULT 'own'",
        "ALTER TABLE cars ADD COLUMN investor_name VARCHAR DEFAULT ''",
        "ALTER TABLE cars ADD COLUMN investor_percent INTEGER DEFAULT 0",
        "ALTER TABLE cars ADD COLUMN driver VARCHAR DEFAULT ''",
        "ALTER TABLE cars ADD COLUMN settlement_day INTEGER DEFAULT 15",

        "ALTER TABLE cars ADD COLUMN weekly_payment INTEGER DEFAULT 0",
        "ALTER TABLE cars ADD COLUMN daily_rent INTEGER DEFAULT 0",
        "ALTER TABLE cars ADD COLUMN payment_weekday INTEGER DEFAULT 0",
        "ALTER TABLE cars ADD COLUMN last_payment_date VARCHAR DEFAULT ''",
        "ALTER TABLE cars ADD COLUMN next_payment_date VARCHAR DEFAULT ''",
        "ALTER TABLE cars ADD COLUMN payment_notifications INTEGER DEFAULT 1",
        "ALTER TABLE cars ADD COLUMN driver_deposit INTEGER DEFAULT 0",

        "ALTER TABLE expenses ADD COLUMN share_type VARCHAR DEFAULT 'shared'",
        "ALTER TABLE car_investments ADD COLUMN investor_name VARCHAR DEFAULT ''",
        "ALTER TABLE downtime ADD COLUMN operation_id INTEGER",
        "ALTER TABLE downtime ADD COLUMN active INTEGER DEFAULT 0",

        "ALTER TABLE warehouse_items ADD COLUMN variant VARCHAR DEFAULT ''",
        "ALTER TABLE warehouse_movements ADD COLUMN variant VARCHAR DEFAULT ''",
    ]

    for migration_sql in migrations:
        try:
            with engine.begin() as connection:
                connection.execute(sql_text(migration_sql))
        except Exception:
            # Чаще всего это означает, что столбец уже существует.
            pass


def init_db():
    """
    Создаёт все таблицы из models.py.

    В том числе автоматически создаются:
    - warehouse_items;
    - warehouse_movements.
    """
    from .models import Base

    Base.metadata.create_all(engine)
    run_migrations()
    seed_cars()


def seed_cars():
    from .models import Car
    from .utils import find_car

    session = Session()

    try:
        seed = [
            (
                "897",
                "Kia",
                "Rio",
                "К897УР716",
                2018,
                "11.2025",
                900000,
                180000,
            ),
            (
                "119",
                "Kia",
                "Rio",
                "В119ЕН716",
                2018,
                "21.03.2025",
                790000,
                253000,
            ),
            (
                "665",
                "Kia",
                "Rio",
                "С665ХК716",
                2020,
                "04.2024",
                1575000,
                240000,
            ),
            (
                "404",
                "Hyundai",
                "Solaris",
                "Н404ЕК716",
                2017,
                "09.04.2026",
                575000,
                410000,
            ),
            (
                "218",
                "Hyundai",
                "Solaris",
                "Е218РТ716",
                None,
                "22.04.2026",
                420000,
                280000,
            ),
        ]

        for (
            code,
            brand,
            model,
            plate,
            year,
            purchase_date,
            purchase_price,
            mileage,
        ) in seed:
            if find_car(session, code):
                continue

            session.add(
                Car(
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
                )
            )

        session.commit()

    except Exception:
        session.rollback()
        raise

    finally:
        session.close()
