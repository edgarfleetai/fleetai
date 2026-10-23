"""Conservative classification of voice payments before money is posted."""
import re


def classify_voice_payment(text):
    if not isinstance(text, str) or len(text) > 500:
        return {'ok': False, 'error': 'Неверная команда'}
    normalized = ' '.join(text.lower().replace('ё', 'е').split())
    wallet = bool(re.search(r'\b(пополнил|пополнение|кошелек|баланс водителя)\b', normalized))
    debt = bool(re.search(r'\b(долг|долга|задолженность|погасил)\b', normalized))
    if wallet and debt:
        return {'ok': False, 'error': 'Уточните: пополнение кошелька или погашение долга'}
    if wallet:
        return {'ok': True, 'kind': 'driver_wallet_topup', 'requires_driver_review': True,
                'execution_enabled': False}
    if debt:
        return {'ok': True, 'kind': 'driver_debt_payment', 'requires_debt_selection': True,
                'execution_enabled': False}
    return {'ok': True, 'kind': 'generic_income', 'execution_enabled': True}
