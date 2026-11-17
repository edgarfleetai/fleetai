"""Daily rent accrual for every car with a driver (owner's decision, 17.11.2026).

The old FleetAI writes daily rent only from its nightly cron (cars in
auto_rent_vehicle_settings) or when a dispatcher top-up runs; the cron stopped
around 05.11, so wallets of several cars stopped going down. The dashboard now
calls the same FleetAI function, _sync_daily_rent: one entry per calendar day,
downtime days written as 0, missed days caught up, safe to repeat. Each car is
processed under its row lock so two dashboard workers never charge a day twice.
No Telegram messages are sent.
"""
import threading

from sqlalchemy import func

from .data import RETIRED_CODES

_lock = threading.Lock()


def accrue_all(write_engine=None):
    """-> [{"car", "driver", "charged", "downtime"}] for cars where something was written."""
    from fleetai import db as fleet_db
    from fleetai.auth import lock_driver_assignment
    from fleetai.models import Car
    from fleetai.routes import _sync_daily_rent, effective_daily_rent
    out = []
    with _lock:
        with fleet_db.Session() as s:
            codes = [str(c[0]) for c in s.query(Car.code).filter(func.coalesce(Car.driver, "") != "").all()]
        for code in codes:
            if code.strip() in RETIRED_CODES:
                continue
            with fleet_db.Session() as s:
                try:
                    lock_driver_assignment(s, code)                 # row lock: one writer per car
                    car = s.query(Car).filter(Car.code == code).first()
                    if not car or not (car.driver or "").strip() or int(effective_daily_rent(car) or 0) <= 0:
                        s.rollback()
                        continue
                    driver, daily = (car.driver or "").strip(), int(effective_daily_rent(car) or 0)
                    r = _sync_daily_rent(s, car, commit=False)
                    s.commit()
                except Exception:
                    s.rollback()
                    raise
                if r.get("charged") or r.get("skipped_downtime"):
                    out.append({"car": code.strip(), "driver": driver, "daily": daily,
                                "charged": int(r.get("charged") or 0), "downtime": int(r.get("skipped_downtime") or 0)})
    return out
