"""Classify driver assignment changes that require a manual financial closeout."""


def financial_closeout_requirements(review):
    required = []
    for car in review.get('cars', []):
        code = car['car_code']
        if car.get('wallet_balance_rub'):
            required.append({'car_code': code, 'item': 'wallet', 'amount_rub': car['wallet_balance_rub']})
        if car.get('open_driver_debt_rub'):
            required.append({'car_code': code, 'item': 'debt', 'amount_rub': car['open_driver_debt_rub']})
        if car.get('deposit_rub'):
            required.append({'car_code': code, 'item': 'deposit', 'amount_rub': car['deposit_rub']})
        if car.get('daily_rent_rub'):
            required.append({'car_code': code, 'item': 'rent_schedule', 'amount_rub': car['daily_rent_rub']})
    return {'automatic_execution_allowed': not bool(required), 'manual_review_items': required,
            'note': 'Не переносите старые начисления, долги и депозиты между автомобилями без сверки.'}
