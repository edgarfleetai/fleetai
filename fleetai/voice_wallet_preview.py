"""Review driver wallet top-up against the current car assignment, without writes."""
from sqlalchemy import select, func
from .models import Car, DriverWalletTransaction


def preview_wallet_topup(db, *, car_code, amount_rub, payment_method='cash'):
    if not isinstance(car_code, str) or not car_code.isdigit() or len(car_code) not in (3, 4):
        return {'ok': False, 'error': 'Укажите номер машины'}
    if type(amount_rub) is not int or not 0 < amount_rub <= 1000000:
        return {'ok': False, 'error': 'Недопустимая сумма'}
    if payment_method not in ('cash', 'transfer', 'other'):
        return {'ok': False, 'error': 'Неизвестный способ оплаты'}
    car = db.execute(select(Car).where(Car.code == car_code)).scalar_one_or_none()
    if car is None or not (car.driver or '').strip():
        return {'ok': False, 'error': 'Машина или водитель не найдены'}
    balance = db.execute(select(func.coalesce(func.sum(DriverWalletTransaction.amount), 0)).where(
        DriverWalletTransaction.car_code == car_code)).scalar_one()
    driver = car.driver.strip()
    return {'ok': True, 'car_code': car_code, 'driver_name': driver,
            'amount_rub': amount_rub, 'payment_method': payment_method,
            'current_wallet_balance': int(balance),
            'projected_balance_before_rent_sync': int(balance) + amount_rub,
            'requires_confirmation': True, 'requires_rent_sync': True,
            'writes_performed': False,
            'confirmation_text': f'Пополнить кошелёк водителя {driver} (машина {car_code}) на {amount_rub} ₽?'}
