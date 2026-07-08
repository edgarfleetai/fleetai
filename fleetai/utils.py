from sqlalchemy import func
from .models import Car


def only_int(value):
    try:
        return int(value or 0)
    except Exception:
        return 0


def normalize_code(value):
    return str(value or "").strip()


def find_car(session, code):
    code = normalize_code(code)
    if not code:
        return None
    return session.query(Car).filter(func.trim(Car.code) == code).first()
