"""Build a financial closeout checklist; does not mutate financial records."""


def build_closeout_plan(financial_review, changes):
    by_code = {item['car_code']: item for item in financial_review.get('cars', [])}
    steps = []
    for change in changes:
        code = change['car']
        data = by_code.get(code)
        if not data:
            raise ValueError('Нет финансовых данных для автомобиля ' + code)
        if (data.get('driver') or '').strip() != (change.get('before') or '').strip():
            raise ValueError('Назначение изменилось; требуется обновить предпросмотр')
        steps.append({
            'car_code': code,
            'closing_driver': change['before'],
            'incoming_driver': change['after'],
            'wallet_balance_rub': int(data.get('wallet_balance_rub') or 0),
            'existing_debt_rub': int(data.get('open_driver_debt_rub') or 0),
            'deposit_to_reconcile_rub': int(data.get('deposit_rub') or 0),
            'rent_per_day_rub': int(data.get('daily_rent_rub') or 0),
            'requires_manual_settlement': True,
            'next_action': 'Сверить начисления и остаток, согласовать судьбу депозита и дату окончания аренды',
        })
    return {'ok': True, 'steps': steps, 'writes_performed': False,
            'can_execute': False,
            'reason': 'Финансовое закрытие и перенос обязательств требуют отдельного согласования'}
