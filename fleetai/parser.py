import re
from datetime import datetime

from .parts_catalog import PARTS, BRANDS

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



def _number_tokens(text, car_code=None, mileage=None):
    result = []

    for match in re.finditer(r"\b(\d{1,9})\b", text):
        value = int(match.group(1))

        if car_code and str(value) == str(car_code):
            continue
        if mileage and value == mileage:
            continue

        result.append({
            "value": value,
            "start": match.start(),
            "end": match.end(),
        })

    return result


def _detect_all_parts(text):
    """
    Находит все разные детали из PARTS вместе с их позициями в строке.

    Длинные алиасы имеют приоритет, чтобы «масляный фильтр»
    не превращался одновременно в «масло» и «фильтр».
    """
    candidates = []

    for alias, value in sorted(
        PARTS.items(),
        key=lambda item: len(item[0]),
        reverse=True,
    ):
        start = 0

        while True:
            position = text.find(alias, start)
            if position < 0:
                break

            end = position + len(alias)

            overlaps = any(
                not (end <= item["start"] or position >= item["end"])
                for item in candidates
            )

            if not overlaps:
                part_name, category = value
                candidates.append({
                    "alias": alias,
                    "part": part_name,
                    "category": category,
                    "start": position,
                    "end": end,
                })

            start = end

    candidates.sort(key=lambda item: item["start"])

    # Убираем повтор одного и того же нормального названия подряд.
    unique = []
    seen_ranges = set()

    for item in candidates:
        key = (
            item["part"].strip().lower(),
            item["start"],
            item["end"],
        )
        if key not in seen_ranges:
            unique.append(item)
            seen_ranges.add(key)

    return unique


def _extract_multiple_repair_parts(
    text,
    car_code=None,
    mileage=None,
    default_brand="",
    default_position="",
):
    """
    Разбирает одну команду с несколькими деталями и отдельной работой.

    Пример:
    621 замена масла 2500 фильтра 500 ремонт 700

    Результат:
    масло 2500 + фильтр 500 + работа 700 = 3700.
    """
    detected = _detect_all_parts(text)

    if not detected:
        return [], 0

    numbers = _number_tokens(
        text,
        car_code=car_code,
        mileage=mileage,
    )

    labor_match = re.search(
        r"\b(?:работа|работы|ремонт|за работу)\s*(?:цена|стоимость)?\s*(\d{1,9})\b",
        text,
    )
    labor = int(labor_match.group(1)) if labor_match else 0

    labor_span = (
        (labor_match.start(1), labor_match.end(1))
        if labor_match
        else None
    )

    used_spans = set()

    if labor_span:
        used_spans.add(labor_span)

    result = []

    # Первый проход: цена рядом с каждой конкретной деталью.
    for index, item in enumerate(detected):
        next_part_start = (
            detected[index + 1]["start"]
            if index + 1 < len(detected)
            else len(text)
        )

        price = 0

        explicit_match = re.search(
            r"\b(?:цена|стоимость|за)\s*(\d{1,9})\b",
            text[item["end"]:next_part_start],
        )

        if explicit_match:
            absolute_start = item["end"] + explicit_match.start(1)
            absolute_end = item["end"] + explicit_match.end(1)
            span = (absolute_start, absolute_end)

            if span not in used_spans:
                price = int(explicit_match.group(1))
                used_spans.add(span)

        if price == 0:
            for number in numbers:
                span = (number["start"], number["end"])

                if span in used_spans:
                    continue

                if item["end"] <= number["start"] < next_part_start:
                    price = number["value"]
                    used_spans.add(span)
                    break

        result.append({
            "part": item["part"],
            "category": item["category"],
            "brand": default_brand,
            "position": default_position,
            "price": price,
            "labor": 0,
        })

    # Второй проход: если из-за сложного алиаса цена одной детали
    # не привязалась, распределяем оставшиеся числа по пустым деталям.
    remaining_numbers = [
        number
        for number in numbers
        if (number["start"], number["end"]) not in used_spans
    ]

    for item in result:
        if item["price"] == 0 and remaining_numbers:
            number = remaining_numbers.pop(0)
            item["price"] = number["value"]
            used_spans.add((number["start"], number["end"]))

    # Работа учитывается один раз.
    if result and labor:
        result[0]["labor"] = labor

    return result, labor


def _repair_amount_fallback(
    text,
    parts,
    labor,
    car_code=None,
    mileage=None,
):
    """
    Страховка от потери сумм.

    Если в команде есть несколько денежных значений, а часть не была
    привязана к деталям, добавляет их к первой детали, чтобы общий расход
    совпадал с исходной командой.
    """
    numbers = _number_tokens(
        text,
        car_code=car_code,
        mileage=mileage,
    )

    labor_removed = False
    money_values = []

    for number in numbers:
        value = number["value"]

        if labor and not labor_removed and value == labor:
            labor_removed = True
            continue

        money_values.append(value)

    expected_parts_total = sum(money_values)
    parsed_parts_total = sum(
        item.get("price", 0) or 0
        for item in parts
    )

    missing = max(expected_parts_total - parsed_parts_total, 0)

    if missing and parts:
        empty_part = next(
            (
                item
                for item in parts
                if not (item.get("price") or 0)
            ),
            None,
        )

        if empty_part:
            empty_part["price"] = missing
        else:
            parts[0]["price"] = (
                (parts[0].get("price") or 0)
                + missing
            )

    return parts

def parse_message(message):
    raw = (message or "").strip()
    text = raw.lower().replace(",", " ").replace(".", " ")

    data = {
        "raw": raw, "car_code": None, "type": "unknown", "category": "", "description": "",
        "part": "", "brand": "", "position": "", "part_price": 0, "labor": 0,
        "parts": [], "from_warehouse": False,
        "total": 0, "income": 0, "mileage": None, "share_type": "shared",
        "investor_name": "", "investor_percent": 0, "days": 0,
        "start_date": None, "end_date": None, "active": 0,
        "total_cost": 0, "investor_paid": 0, "park_paid": 0,
        "investor_debt_to_park": 0, "park_debt_to_investor": 0,
    }

    car = re.match(r"^\s*(\d{3})\b", text)
    if car:
        data["car_code"] = car.group(1).strip()

    if "со склада" in text or "из склада" in text:
        data["from_warehouse"] = True

    # Пробег можно писать разными способами:
    # "пробег 400234", "на пробеге 400234", "пробег: 400 234",
    # "пр 400234", "400234 км пробег".
    mileage_patterns = [
        r"\b(?:на\s+)?пробег(?:е)?\s*[:№-]?\s*(\d[\d\s]{3,8})\b",
        r"\bпр\.?\s*[:№-]?\s*(\d[\d\s]{3,8})\b",
        r"\b(\d[\d\s]{3,8})\s*км\s*(?:пробег)?\b",
    ]

    mileage = None

    for pattern in mileage_patterns:
        match = re.search(pattern, text)
        if match:
            raw_mileage = re.sub(r"\s+", "", match.group(1))
            if raw_mileage.isdigit():
                value = int(raw_mileage)
                if 1000 <= value <= 9999999:
                    mileage = value
                    break

    if mileage is not None:
        data["mileage"] = mileage

    if "справа" in text or "правая" in text:
        data["position"] = "Правая"
    elif "слева" in text or "левая" in text:
        data["position"] = "Левая"

    for brand in BRANDS:
        if re.search(r"\b" + re.escape(brand) + r"\b", text):
            data["brand"] = brand.upper()
            break


    # Строгие быстрые команды FleetAI:
    # 636 I+25000  -> инвестор внес деньги
    # 636 I-10000  -> выплата инвестору
    m_i_plus = re.search(r"\bi\s*\+\s*(\d{2,9})\b", text, re.I)
    if m_i_plus:
        data["type"] = "investor_investment"
        data["category"] = "Вложение инвестора"
        data["total"] = int(m_i_plus.group(1))
        data["description"] = "Вложение инвестора"
        return data

    m_i_minus = re.search(r"\bi\s*-\s*(\d{2,9})\b", text, re.I)
    if m_i_minus:
        data["type"] = "investor_payout"
        data["category"] = "Выплата инвестору"
        data["total"] = int(m_i_minus.group(1))
        data["description"] = "Выплата инвестору"
        return data

    # Завершение текущего простоя должно проверяться раньше обычного слова "простой".
    if any(phrase in text for phrase in [
        "конец простоя", "закончить простой", "завершить простой",
        "вышла с простоя", "вышел с простоя", "вышли с простоя",
        "закончил простой", "закончила простой", "простой закончен",
        "снова работает", "вышла на линию", "вышел на линию",
    ]):
        data["type"] = "downtime_end"
        data["category"] = "Простой"
        data["description"] = "Завершение простоя"
        return data

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

    if "инвестор" in text and any(w in text for w in ["вложил", "внес", "дал", "оплатил", "оплатила"]):
        data["type"] = "investor_investment"
        data["category"] = "Вложение инвестора"
        nums = parse_amounts(text, data["car_code"])
        data["total"] = nums[0] if nums else 0
        pct = re.search(r"(\d{1,3})\s*%", text)
        data["investor_percent"] = int(pct.group(1)) if pct else 0

        # Важно: фраза "636 инвестор вложил 25000" НЕ означает,
        # что инвестора зовут "Вложил". Если имя не указано явно,
        # имя берем из карточки машины уже в routes.py.
        verbs = {"вложил", "вложила", "внес", "внесла", "дал", "дала", "оплатил", "оплатила"}
        name = re.search(r"инвестор\s+([а-яa-zё]+)", text)
        if name and name.group(1) not in verbs:
            data["investor_name"] = name.group(1).capitalize()
        else:
            data["investor_name"] = ""

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

    # Обычные эксплуатационные расходы, не связанные с ремонтом.
    # Этот блок расположен раньше ремонта, чтобы фразы вроде
    # «затраты на дорогу 1500» не превращались в ремонт.
    expense_categories = [
        (
            [
                "затраты на дорогу",
                "расходы на дорогу",
                "расход на дорогу",
                "дорога",
                "проезд",
                "платная дорога",
                "платная трасса",
                "трасса",
            ],
            "Дорожные расходы",
        ),
        (
            [
                "парковка",
                "паркинг",
                "стоянка",
            ],
            "Парковка",
        ),
        (
            [
                "доставка",
                "курьер",
                "перевозка детали",
            ],
            "Доставка",
        ),
        (
            [
                "диагностика",
                "компьютерная диагностика",
            ],
            "Диагностика",
        ),
        (
            [
                "мойка",
                "химчистка",
            ],
            "Мойка и уход",
        ),
        (
            [
                "бензин",
                "дизель",
                "топливо",
                "заправка",
                "газ",
                "метан",
                "пропан",
            ],
            "Топливо",
        ),
        (
            [
                "эвакуатор",
                "буксировка",
            ],
            "Эвакуатор",
        ),
        (
            [
                "шиномонтаж",
                "балансировка",
            ],
            "Шиномонтаж",
        ),
        (
            [
                "страховка",
                "осаго",
                "каско",
            ],
            "Страховка",
        ),
        (
            [
                "штраф",
                "гибдд",
            ],
            "Штраф",
        ),
        (
            [
                "комиссия",
                "комиссия банка",
                "комиссия сервиса",
            ],
            "Комиссия",
        ),
        (
            [
                "оформление",
                "документы",
                "госпошлина",
                "регистрация",
            ],
            "Документы",
        ),
        (
            [
                "телефон",
                "связь",
                "сим карта",
                "интернет",
            ],
            "Связь",
        ),
        (
            [
                "аренда места",
                "аренда гаража",
                "гараж",
            ],
            "Аренда",
        ),
    ]

    matched_expense_category = None
    matched_expense_phrase = None

    for phrases, category in expense_categories:
        for phrase in sorted(phrases, key=len, reverse=True):
            if phrase in text:
                matched_expense_category = category
                matched_expense_phrase = phrase
                break

        if matched_expense_category:
            break

    # Универсальная форма:
    # «расход 1500 на ...», «затраты 1500 на ...»,
    # «потратил 1500 на ...», если это не ремонт и не допрасход инвестора.
    generic_expense_match = re.search(
        r"\b(?:расходы?|затраты?|потратил|потратили|оплатил|оплатили)\b",
        text,
    )

    repair_context = any(
        word in text
        for word in [
            "ремонт",
            "замена",
            "поменял",
            "поменяли",
            "починил",
            "починили",
            "деталь",
            "запчаст",
        ]
    )

    if matched_expense_category or (
        generic_expense_match
        and not repair_context
        and "инвестор" not in text
    ):
        data["type"] = "expense"
        data["category"] = (
            matched_expense_category
            or "Прочие расходы"
        )

        nums = parse_amounts(
            text,
            data["car_code"],
        )

        if data.get("mileage"):
            nums = [
                number
                for number in nums
                if number != data["mileage"]
            ]

        data["total"] = nums[-1] if nums else 0

        # Сохраняем понятное назначение расхода.
        description = text

        if data["car_code"]:
            description = re.sub(
                r"^\s*" + re.escape(data["car_code"]) + r"\b",
                "",
                description,
            ).strip()

        description = re.sub(
            r"\b(?:цена|стоимость|сумма)\s*\d+\s*(?:р|руб|рублей)?\b",
            "",
            description,
        )
        description = re.sub(
            r"\b\d+\s*(?:р|руб|рублей)\b",
            "",
            description,
        )
        description = re.sub(
            r"\s+",
            " ",
            description,
        ).strip(" ,.-")

        if description:
            data["description"] = (
                f"{data['category']}: {description}"
            )
        else:
            data["description"] = data["category"]

        return data


    # Сначала пытаемся распознать сразу несколько деталей.
    repair_words_present = any(
        word in text
        for word in [
            "замена",
            "поменял",
            "поменяли",
            "ремонт",
            "починил",
            "починили",
            "купил",
            "установил",
            "затраты",
            "затратил",
            "стоило",
        ]
    )

    detected_parts, detected_labor = _extract_multiple_repair_parts(
        text,
        car_code=data["car_code"],
        mileage=data["mileage"],
        default_brand=data["brand"],
        default_position=data["position"],
    )

    detected_parts = _repair_amount_fallback(
        text,
        detected_parts,
        detected_labor,
        car_code=data["car_code"],
        mileage=data["mileage"],
    )

    if detected_parts and repair_words_present:
        data["parts"] = detected_parts
        data["part"] = detected_parts[0]["part"]
        data["category"] = detected_parts[0]["category"]
        data["part_price"] = sum(
            item["price"] or 0
            for item in detected_parts
        )
        data["labor"] = detected_labor

        # Контрольная сумма по исходной команде.
        # Для ремонта все денежные значения складываются:
        # детали + работа. Код машины и пробег исключаются.
        repair_numbers = _number_tokens(
            text,
            car_code=data["car_code"],
            mileage=data["mileage"],
        )
        command_total = sum(
            number["value"]
            for number in repair_numbers
        )

        parsed_total = data["part_price"] + data["labor"]

        # Если часть цены детали не привязалась, общий расход всё равно
        # должен совпасть с числами, которые пользователь написал.
        data["total"] = max(parsed_total, command_total)

        missing_part_amount = max(
            data["total"] - data["labor"] - data["part_price"],
            0,
        )

        if missing_part_amount:
            empty_part = next(
                (
                    item
                    for item in detected_parts
                    if not (item.get("price") or 0)
                ),
                None,
            )

            if empty_part:
                empty_part["price"] = missing_part_amount
            else:
                detected_parts[0]["price"] = (
                    (detected_parts[0].get("price") or 0)
                    + missing_part_amount
                )

            data["part_price"] += missing_part_amount

        if len(detected_parts) == 1:
            data["description"] = (
                "Замена "
                + detected_parts[0]["part"].lower()
            )
        else:
            names = ", ".join(
                item["part"].lower()
                for item in detected_parts
            )
            data["description"] = (
                f"Ремонт / замена: {names}"
            )

        data["type"] = (
            "service"
            if all(
                item["category"] == "ТО"
                for item in detected_parts
            )
            else "repair"
        )

        return data

    # Одиночная известная деталь.
    for key, val in sorted(
        PARTS.items(),
        key=lambda item: len(item[0]),
        reverse=True,
    ):
        if key in text:
            data["part"], data["category"] = val
            data["description"] = (
                "Замена " + data["part"].lower()
            )
            data["type"] = (
                "service"
                if data["category"] == "ТО"
                else "repair"
            )
            break

    if not data["part"] and repair_words_present:
        data["type"] = "repair"
        data["category"] = "Ремонт"

        candidate = text
        if data["car_code"]:
            candidate = re.sub(
                r"^\s*" + re.escape(data["car_code"]) + r"\b",
                "",
                candidate,
            ).strip()

        candidate = re.sub(
            r"\b(замена|поменял|поменяли|ремонт|починил|починили)\b",
            "",
            candidate,
        ).strip()
        candidate = re.sub(
            r"\b(цена|стоимость|работа|пробег)\s*\d+\b",
            "",
            candidate,
        ).strip()
        candidate = re.sub(
            r"\b\d{2,9}\b",
            "",
            candidate,
        ).strip(" -—.,")

        if candidate:
            data["part"] = candidate[:120].capitalize()
            data["description"] = (
                "Ремонт / замена: " + data["part"].lower()
            )
        else:
            data["description"] = "Ремонт / замена"

    price = re.search(
        r"(стоимость|цена)\s*(\d+)",
        text,
    )
    labor = re.search(
        r"(работа|ремонт)\s*(\d+)",
        text,
    )

    if price:
        data["part_price"] = int(price.group(2))
    if labor:
        data["labor"] = int(labor.group(2))

    if data["part"] and data["part_price"] == 0:
        nums = parse_amounts(
            text,
            data["car_code"],
        )
        if data["mileage"]:
            nums = [
                number
                for number in nums
                if number != data["mileage"]
            ]

        if data["labor"]:
            removed = False
            filtered = []
            for number in nums:
                if (
                    not removed
                    and number == data["labor"]
                ):
                    removed = True
                    continue
                filtered.append(number)
            nums = filtered

        if nums:
            data["part_price"] = nums[0]

    data["total"] = (
        data["part_price"]
        + data["labor"]
    )

    if data["part"]:
        data["parts"] = [{
            "part": data["part"],
            "category": data["category"],
            "brand": data["brand"],
            "position": data["position"],
            "price": data["part_price"],
            "labor": data["labor"],
        }]

    return data
