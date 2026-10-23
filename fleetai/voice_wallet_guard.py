"""Guard against driver reassignment between voice preview and confirmation."""


def validate_wallet_confirmation(preview, *, current_driver, current_car_code, approved):
    if approved is not True:
        return {'ok': False, 'error': 'Операция не подтверждена'}
    if not isinstance(preview, dict) or preview.get('ok') is not True:
        return {'ok': False, 'error': 'Нет действительного предпросмотра'}
    if not isinstance(current_driver, str) or not current_driver.strip():
        return {'ok': False, 'error': 'У машины больше нет водителя'}
    if preview.get('car_code') != current_car_code or preview.get('driver_name') != current_driver.strip():
        return {'ok': False, 'error': 'Водитель или машина изменились; создайте новый предпросмотр'}
    if preview.get('writes_performed') is not False or preview.get('requires_confirmation') is not True:
        return {'ok': False, 'error': 'Неверное состояние предпросмотра'}
    return {'ok': True, 'requires_rent_sync': True}
