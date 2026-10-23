"""Conservative confirmation preflight. Does not modify assignments."""
from .driver_move_guard import is_preview_current
from .driver_move_preview import preview_driver_move


def validate_driver_move_confirmation(cars, source, target, swap, fingerprint, approved):
    if approved is not True:
        return {'ok': False, 'error': 'Нужно явное подтверждение операции'}
    if not is_preview_current(cars, fingerprint):
        return {'ok': False, 'error': 'Назначения изменились. Запросите новый предпросмотр'}
    assignments = {str(car.code).strip(): (car.driver or '').strip() for car in cars}
    preview = preview_driver_move(assignments, source, target, swap=swap)
    if not preview['ok']:
        return preview
    return {'ok': True, 'ready_for_transaction': True, 'writes_performed': False,
            'changes': preview['changes'],
            'warning': 'Это только проверка подтверждения. Сохранение отключено до сверки финансов и журнала операций.'}
