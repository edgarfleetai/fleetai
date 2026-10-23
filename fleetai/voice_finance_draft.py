"""Parse voice income/repair into drafts only; no database writes."""
import re

_AMOUNT = r'(\d[\d ]{0,12})\s*(?:рублей|рубля|рубль|руб|р\b|₽|тысяч(?:у|и)?)'


def parse_finance_voice(text):
    if not isinstance(text, str) or not text.strip() or len(text) > 500:
        return {'ok': False, 'error': 'Слишком длинная или пустая команда'}
    normalized = ' '.join(text.lower().replace('ё', 'е').split())
    codes = re.findall(r'(?<!\d)(\d{3,4})(?!\d)', normalized)
    if len(codes) != 1:
        return {'ok': False, 'error': 'Нужно указать ровно одну машину'}
    amounts = list(re.finditer(_AMOUNT, normalized))
    if len(amounts) != 1:
        return {'ok': False, 'error': 'Укажите одну сумму в рублях'}
    match = amounts[0]
    amount = int(match.group(1).replace(' ', ''))
    if 'тысяч' in match.group(0):
        amount *= 1000
    if not 0 < amount <= 10000000:
        return {'ok': False, 'error': 'Недопустимая сумма'}
    expense = bool(re.search(r'\b(ремонт|починил|замена|заменил|потратил|расход)\b', normalized))
    income = bool(re.search(r'\b(получил|поступило|приход|заработал|доход)\b', normalized))
    if expense == income:
        return {'ok': False, 'error': 'Не удалось однозначно определить доход или расход'}
    kind = 'repair_expense' if expense else 'income'
    return {'ok': True, 'draft': {'kind': kind, 'car_code': codes[0],
        'amount_rub': amount, 'description': text.strip(),
        'requires_confirmation': True, 'writes_performed': False}}
