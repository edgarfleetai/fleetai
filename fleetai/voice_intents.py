"""Conservative voice-to-draft parser for iPhone Shortcuts.

No database writes or external model calls. Uncertain phrases are rejected.
"""
import re

MAX_TEXT_LENGTH = 500
AMOUNT = r"(\d[\d\s]{0,11})"
CAR = r"(\d{3,4})"


def parse_voice_draft(text):
    if not isinstance(text, str) or not text.strip() or len(text) > MAX_TEXT_LENGTH:
        return {"ok": False, "error": "Введите короткое описание операции"}
    normalized = " ".join(text.lower().replace("ё", "е").split())
    cars = set(re.findall(r"(?<!\d)\d{3,4}(?!\d)", normalized))
    # Avoid guessing when multiple vehicle identifiers are present.
    if len(cars) != 1:
        return {"ok": False, "error": "Укажите один номер автомобиля"}
    car_code = next(iter(cars))
    if not re.search(r"\b(купил|купила|потратил|потратила|ремонт|замена|заменил|заменили)\b", normalized):
        return {"ok": False, "error": "Пока поддерживается только черновик расхода на ремонт"}
    money = re.findall(r"(\d[\d\s]*?)\s*(?:рублей|рубля|руб|р\b|₽)", normalized)
    if len(money) != 1:
        return {"ok": False, "error": "Укажите одну сумму в рублях"}
    amount = int(re.sub(r"\s+", "", money[0]))
    if amount <= 0 or amount > 10000000:
        return {"ok": False, "error": "Недопустимая сумма"}
    return {
        "ok": True,
        "draft": {
            "kind": "repair_expense",
            "car_code": car_code,
            "amount_rub": amount,
            "description": text.strip(),
            "requires_confirmation": True,
        },
    }
