"""Validate a finance voice draft against a known car before any write."""
from .voice_finance_draft import parse_finance_voice


def preview_finance_voice(text, car_lookup):
    result = parse_finance_voice(text)
    if not result['ok']:
        return result
    draft = result['draft']
    car = car_lookup(draft['car_code'])
    if car is None:
        return {'ok': False, 'error': 'Автомобиль не найден', 'writes_performed': False}
    label = 'расход на ремонт' if draft['kind'] == 'repair_expense' else 'поступление'
    return {'ok': True, 'draft': draft, 'car_code': car.code,
            'confirmation_text': f"Машина {car.code}: {label} {draft['amount_rub']} ₽. {draft['description']}. Подтвердить запись?",
            'requires_confirmation': True, 'writes_performed': False}
