"""Read-only Russian voice command parser for current driver lookup."""
import re


def parse_driver_lookup(message):
    if not isinstance(message, str) or len(message) > 300:
        return None
    text = " ".join(message.lower().replace("ё", "е").split())
    if not re.search(r"\b(кто|водитель)\b", text):
        return None
    match = re.search(r"\b(?:на|машин[еуы]?|авто)\s*(?:номер\s*)?(\d{3,4})(?!\d)", text)
    if not match:
        return None
    return {"kind": "current_driver", "car_code": match.group(1), "read_only": True}


def current_driver_response(car):
    if car is None:
        return {"ok": False, "error": "Автомобиль не найден"}
    driver = (car.driver or "").strip()
    return {
        "ok": True,
        "car_code": car.code,
        "driver": driver,
        "message": ("На машине " + car.code + " работает " + driver) if driver
                   else ("На машине " + car.code + " водитель не назначен"),
    }
