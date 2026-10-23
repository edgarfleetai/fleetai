"""Pure preview of driver assignment changes; never writes to DB."""


def preview_driver_move(assignments, source, target, swap=False):
    source, target = str(source).strip(), str(target).strip()
    if source == target:
        return {'ok': False, 'error': 'Укажите разные машины'}
    if source not in assignments or target not in assignments:
        return {'ok': False, 'error': 'Автомобиль не найден'}
    old_source = (assignments[source] or '').strip()
    old_target = (assignments[target] or '').strip()
    if not old_source:
        return {'ok': False, 'error': 'На исходной машине нет водителя'}
    if old_target and not swap:
        return {'ok': False, 'error': 'Целевая машина занята; для обмена нужна отдельная команда'}
    if swap and not old_target:
        return {'ok': False, 'error': 'Для обмена нужны два водителя'}
    return {'ok': True, 'requires_confirmation': True, 'writes_performed': False,
            'execution_enabled': False,
            'requires_wallet_review': True,
            'warning': 'Перестановка затрагивает кошельки, начисления аренды и Telegram-привязки. До сверки расчетов запись заблокирована.',
            'changes': [
                {'car': source, 'before': old_source, 'after': old_target if swap else ''},
                {'car': target, 'before': old_target, 'after': old_source},
            ]}
