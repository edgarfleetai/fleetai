"""Read-only performance audit of finance queries.

Run against a local/test database only:
    python -m scripts.finance_query_audit

This module deliberately does not change application behavior or schema.
"""
import os
import time
from collections import Counter
from sqlalchemy import event
from fleetai.db import Session, engine
from fleetai.models import Car
from fleetai.finance import car_finance, calculate_period_for_car, period_bounds_for_car


def main():
    if os.getenv("FLEETAI_ALLOW_PERF_AUDIT") != "1":
        raise SystemExit("Set FLEETAI_ALLOW_PERF_AUDIT=1 to run read-only audit")
    counts = Counter()
    timings = []

    def before(conn, cursor, statement, parameters, context, executemany):
        context._audit_started = time.perf_counter()
        counts[statement.split(None, 1)[0].upper() if statement.strip() else "OTHER"] += 1

    def after(conn, cursor, statement, parameters, context, executemany):
        timings.append((time.perf_counter() - context._audit_started) * 1000)

    event.listen(engine, "before_cursor_execute", before)
    event.listen(engine, "after_cursor_execute", after)
    try:
        with Session() as session:
            cars = session.query(Car).order_by(Car.id).all()
            for car in cars:
                start = time.perf_counter()
                car_finance(session, car.code)
                finance_ms = (time.perf_counter() - start) * 1000
                print(f"car={car.code} finance_ms={finance_ms:.1f}")
                try:
                    bounds = period_bounds_for_car(car)
                    start_date, end_date = bounds[:2]
                    start = time.perf_counter()
                    calculate_period_for_car(session, car, start_date, end_date)
                    print(f"car={car.code} period_ms={(time.perf_counter()-start)*1000:.1f}")
                except (TypeError, ValueError) as exc:
                    print(f"car={car.code} period_skipped={exc}")
        print(f"sql_counts={dict(counts)}")
        print(f"sql_total_ms={sum(timings):.1f} sql_calls={len(timings)}")
    finally:
        event.remove(engine, "before_cursor_execute", before)
        event.remove(engine, "after_cursor_execute", after)


if __name__ == "__main__":
    main()
