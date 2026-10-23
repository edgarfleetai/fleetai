"""Produce a compact read-only confirmation summary for iPhone Shortcuts."""


def mobile_move_summary(preview):
    if not isinstance(preview, dict) or not preview.get('ok'):
        return {'ready': False, 'message': 'Не удалось подготовить перестановку',
                'confirmation_enabled': False}
    lines = ['Предпросмотр перестановки водителей:']
    for change in preview.get('changes', []):
        lines.append(f"Машина {change['car']}: {change.get('before') or 'нет водителя'} → {change.get('after') or 'нет водителя'}")
    plan = preview.get('closeout_plan') or {}
    for item in plan.get('steps', []):
        lines.append(f"{item['car_code']}: кошелёк {item['wallet_balance_rub']} ₽; долг {item['existing_debt_rub']} ₽; депозит {item['deposit_to_reconcile_rub']} ₽; аренда {item['rent_per_day_rub']} ₽/день")
    lines.append('Это только предпросмотр. Водители не переставлены. Требуется финансовая сверка.')
    return {'ready': True, 'message': '\n'.join(lines), 'confirmation_enabled': False,
            'writes_performed': False, 'fingerprint': preview.get('assignment_fingerprint')}
