import re
from datetime import datetime

PARTS = {
    "стойка стаба": ("Стойка стабилизатора", "Подвеска"),
    "стойки стаба": ("Стойка стабилизатора", "Подвеска"),
    "стаба": ("Стойка стабилизатора", "Подвеска"),
    "амортизатор": ("Амортизатор", "Подвеска"),
    "колодки": ("Тормозные колодки", "Тормоза"),
    "масло": ("Масло двигателя", "ТО"),
    "масло двигателя": ("Масло двигателя", "ТО"),
    "салонный": ("Салонный фильтр", "ТО"),
    "воздушный": ("Воздушный фильтр", "ТО"),
    "масляный": ("Масляный фильтр", "ТО"),
    "масленый": ("Масляный фильтр", "ТО"),
}

BRANDS = ["amd", "ctr", "mann", "mando", "lynx", "hi-q", "hiq", "sachs", "kyb", "gates", "bosch", "ngk", "denso", "shell", "лукойл"]

MONTHS_RU = {
    "января": 1, "январь": 1, "февраля": 2, "февраль": 2, "марта": 3, "март": 3,
    "апреля": 4, "апрель": 4, "мая": 5, "май": 5, "июня": 6, "июнь": 6,
    "июля": 7, "июль": 7, "августа": 8, "август": 8, "сентября": 9, "сентябрь": 9,
    "октября": 10, "октябрь": 10, "ноября": 11, "ноябрь": 11, "декабря": 12, "декабрь": 12,
}


def parse_amounts(text, car_code=None):
    nums = [int(x) for x in re.findall(r"\b\d{2,9}\b", text)]
    if car_code:
        nums = [n for n in nums if str(n) != str(car_code)]
    return nums


def parse_russian_date_piece(piece, default_month=None):
    piece = (piece or "").strip().lower()
    now = datetime.now()
    year = now.year

    m = re.search(r"(\d{1,2})[./-](\d{1,2})(?:[./-](\d{2,4}))?", piece)
    if m:
        day = int(m.group(1))
        month = int(m.group(2))
        if m.group(3):
            year = int(m.group(3))
            if year < 100:
                year += 2000
        return datetime(year, month, day)

    m = re.search(r"(\d{1,2})\s+([а-яё]+)", piece)
    if m:
        day = int(m.group(1))
        month = MONTHS_RU.get(m.group(2))
        if month:
            return datetime(year, month, day)

    m = re.search(r"\b(\d{1,2})\b", piece)
    if m and default_month:
        return datetime(year, default_month, int(m.group(1)))

    return None


def clean_downtime_reason(text):
    reason = text
    reason = re.sub(r"^\s*\d{3}\b", "", reason).strip()
    reason = re.sub(r"\b(простой|стояла|стоял|стоит|не работала|не работал|в простое)\b", "", reason).strip()
    reason = re.sub(r"\bс\s+.+?\s+по\s+.+?(?=\s|$)", "", reason).strip()
    reason = re.sub(r"\bс\s+(\d{1,2}[./-]\d{1,2}(?:[./-]\d{2,4})?|\d{1,2}\s+[а-яё]+)\b", "", reason).strip()
    return reason.strip(" -—.,") or "Простой"


def parse_downtime_period(text):
    today = datetime.now()

    m = re.search(r"\bс\s+(.+?)\s+по\s+(.+?)(?=\s+(?:ремонт|коробка|двигатель|дтп|ожид|замена|из-за|из за)|$)", text)
    if m:
        start_piece = m.group(1).strip()
        end_piece = m.group(2).strip()

        if any(x in end_piece for x in ["настоящее", "сегодня", "сейчас"]):
            start_dt = parse_russian_date_piece(start_piece)
            if start_dt:
                days = max((today.date() - start_dt.date()).days, 1)
                return start_dt, None, days, clean_downtime_reason(text), 1

        end_month_match = re.search(r"([а-яё]+)", end_piece)
        default_month = MONTHS_RU.get(end_month_match.group(1)) if end_month_match else None
        start_dt = parse_russian_date_piece(start_piece, default_month=default_month)
        end_dt = parse_russian_date_piece(end_piece)

        if start_dt and not end_dt:
            end_dt = parse_russian_date_piece(end_piece, default_month=start_dt.month)
        if not start_dt and end_dt:
            start_dt = parse_russian_date_piece(start_piece, default_month=end_dt.month)

        if start_dt and end_dt:
            if end_dt < start_dt:
                end_dt = end_dt.replace(year=end_dt.year + 1)
            days = max((end_dt.date() - start_dt.date()).days, 1)
            return start_dt, end_dt, days, clean_downtime_reason(text), 0

    m_open = re.search(r"\bс\s+(\d{1,2}[./-]\d{1,2}(?:[./-]\d{2,4})?|\d{1,2}\s+[а-яё]+)", text)
    if m_open:
        start_dt = parse_russian_date_piece(m_open.group(1).strip())
        if start_dt:
            days = max((today.date() - start_dt.date()).days, 1)
            return start_dt, None, days, clean_downtime_reason(text), 1

    return None, None, 0, "", 0


def parse_message(message):
    raw = (message or "").strip()
    text = raw.lower().replace(",", " ").replace(".", " ")

    data = {
        "raw": raw, "car_code": None, "type": "unknown", "category": "", "description": "",
        "part": "", "brand": "", "position": "", "part_price": 0, "labor": 0,
        "total": 0, "income": 0, "mileage": None, "share_type": "shared",
        "investor_name": "", "investor_percent": 0, "days": 0,
        "start_date": None, "end_date": None, "active": 0,
        "total_cost": 0, "investor_paid": 0, "park_paid": 0,
        "investor_debt_to_park": 0, "park_debt_to_investor": 0,
    }

    car = re.match(r"^\s*(\d{3})\b", text)
    if car:
        data["car_code"] = car.group(1).strip()

    mileage = re.search(r"пробег\s*(\d{4,7})", text)
    if mileage:
        data["mileage"] = int(mileage.group(1))

    if "справа" in text or "правая" in text:
        data["position"] = "Правая"
    elif "слева" in text or "левая" in text:
        data["position"] = "Левая"

    for brand in BRANDS:
        if re.search(r"\b" + re.escape(brand) + r"\b", text):
            data["brand"] = brand.upper()
            break

    if any(x in text for x in ["простой", "стояла", "стоял", "стоит", "в простое", "не работала", "не работал"]):
        data["type"] = "downtime"
        data["category"] = "Простой"
        start_dt, end_dt, days, reason, active = parse_downtime_period(text)
        data["start_date"] = start_dt
        data["end_date"] = end_dt
        data["days"] = days
        data["description"] = reason
        data["active"] = active
        return data

    if any(w in text for w in ["доп расходы", "доп расход", "запуск", "расход за инвестора", "доплата"]):
        data["type"] = "investor_expense_split"
        data["category"] = "Взаиморасчет"
        nums = parse_amounts(text, data["car_code"])
        total_cost = nums[0] if nums else 0

        investor_paid = 0
        m_inv = re.search(r"(инвестор|инвестора|дал|дала|оплатил|оплатила|внес)\s*(\d{2,9})", text)
        if m_inv:
            investor_paid = int(m_inv.group(2))
        elif len(nums) > 1:
            investor_paid = nums[1]

        park_paid = max(total_cost - investor_paid, 0)
        data["total"] = total_cost
        data["description"] = "Доп. расходы / взаиморасчет"
        data["total_cost"] = total_cost
        data["investor_paid"] = investor_paid
        data["park_paid"] = park_paid
        data["investor_debt_to_park"] = park_paid
        return data

    investment_words = ["доп вложение", "дополнительное вложение", "дополнительные вложения", "допы", "доп", "вложение", "вложения", "кап вложение", "капиталка", "гбо"]
    if any(re.search(r"\b" + re.escape(w) + r"\b", text) for w in investment_words):
        data["type"] = "car_investment"
        data["category"] = "Доп. вложение"
        nums = parse_amounts(text, data["car_code"])
        data["total"] = nums[-1] if nums else 0
        data["description"] = "Дополнительное вложение"
        return data

    if "инвестор" in text and any(w in text for w in ["вложил", "внес", "дал"]):
        data["type"] = "investor_investment"
        data["category"] = "Вложение инвестора"
        nums = parse_amounts(text, data["car_code"])
        data["total"] = nums[0] if nums else 0
        pct = re.search(r"(\d{1,3})\s*%", text)
        data["investor_percent"] = int(pct.group(1)) if pct else 0
        name = re.search(r"инвестор\s+([а-яa-zё]+)", text)
        data["investor_name"] = name.group(1).capitalize() if name else ""
        data["description"] = "Вложение инвестора"
        return data

    if "выплата" in text:
        data["type"] = "investor_payout"
        data["category"] = "Выплата инвестору"
        nums = parse_amounts(text, data["car_code"])
        data["total"] = nums[-1] if nums else 0
        name = re.search(r"выплата\s+([а-яa-zё]+)", text)
        data["investor_name"] = name.group(1).capitalize() if name else ""
        data["description"] = "Выплата инвестору"
        return data

    if any(w in text for w in ["получил", "расчет", "расчёт", "недельный", "перевел", "перевёл", "прибыль", "доход", "заработал", "пришло"]):
        data["type"] = "income"
        data["category"] = "Доход"
        nums = parse_amounts(text, data["car_code"])
        data["income"] = nums[-1] if nums else 0
        data["total"] = data["income"]
        data["description"] = "Доход"
        return data

    expense_words = {"штраф": "Штраф", "страховка": "Страховка", "осаго": "Страховка", "мойка": "Мойка", "бензин": "Топливо", "газ": "Топливо", "эвакуатор": "Эвакуатор", "шиномонтаж": "Шиномонтаж", "расход": "Расход"}
    for word, cat in expense_words.items():
        if word in text:
            data["type"] = "expense"
            data["category"] = cat
            data["description"] = cat
            nums = parse_amounts(text, data["car_code"])
            data["total"] = nums[-1] if nums else 0
            return data

    if any(word in text for word in ["замена", "поменял", "поменяли", "ремонт"]):
        data["type"] = "repair"
        data["category"] = "Ремонт"
        data["description"] = "Ремонт / замена"
        nums = parse_amounts(text, data["car_code"])
        if data["mileage"]:
            nums = [n for n in nums if n != data["mileage"]]
        data["total"] = sum(nums) if nums else 0
        return data

    for key, val in sorted(PARTS.items(), key=lambda x: len(x[0]), reverse=True):
        if key in text:
            data["part"], data["category"] = val
            data["description"] = "Замена " + data["part"].lower()
            data["type"] = "service" if data["category"] == "ТО" else "repair"
            break

    price = re.search(r"(стоимость|цена)\s*(\d+)", text)
    labor = re.search(r"(работа|ремонт)\s*(\d+)", text)

    if price:
        data["part_price"] = int(price.group(2))
    if labor:
        data["labor"] = int(labor.group(2))

    if data["part"] and data["part_price"] == 0:
        nums = parse_amounts(text, data["car_code"])
        if data["mileage"]:
            nums = [n for n in nums if n != data["mileage"]]
        if nums:
            data["part_price"] = nums[0]
        if len(nums) > 1 and data["labor"] == 0:
            data["labor"] = nums[1]

    data["total"] = data["part_price"] + data["labor"]
    return data
