"""Atomic driver-wallet top-up, using the existing rent rules without an inner commit."""
import json
import re
from datetime import datetime
from sqlalchemy import select, func
from .models import Car, DriverWalletTransaction, Operation, Income
from .voice_finance_receipt import VoiceFinanceReceipt
from .voice_wallet_guard import validate_wallet_confirmation
from .routes import _sync_daily_rent_uncommitted


def commit_wallet_topup(db, preview, *, approved, request_key):
    """Caller owns the transaction. All writes are rolled back together on failure."""
    if not isinstance(request_key, str) or not re.fullmatch(r'[A-Za-z0-9_-]{16,128}', request_key):
        raise ValueError('Неверный ключ операции')
    if not isinstance(preview, dict) or preview.get('ok') is not True:
        raise ValueError('Неверный предпросмотр')
    code, amount = preview.get('car_code'), preview.get('amount_rub')
    method = preview.get('payment_method')
    if not isinstance(code, str) or not re.fullmatch(r'\d{3,4}', code):
        raise ValueError('Неверный номер машины')
    if type(amount) is not int or not 0 < amount <= 1000000:
        raise ValueError('Неверная сумма')
    if method not in ('cash', 'transfer', 'other'):
        raise ValueError('Неверный способ оплаты')
    if db.execute(select(VoiceFinanceReceipt).where(VoiceFinanceReceipt.request_key == request_key)).scalar_one_or_none():
        raise ValueError('Операция уже проведена')
    car = db.execute(select(Car).where(Car.code == code).with_for_update()).scalar_one_or_none()
    if car is None:
        raise ValueError('Автомобиль не найден')
    guard = validate_wallet_confirmation(preview, current_driver=car.driver or '',
                                         current_car_code=car.code, approved=approved)
    if not guard['ok']:
        raise ValueError(guard['error'])
    driver = car.driver.strip()
    rent_result = _sync_daily_rent_uncommitted(db, car)
    now = datetime.now()
    db.add(DriverWalletTransaction(driver_name=driver, car_code=code, amount=amount,
                                   transaction_type='dispatcher_topup', source=method,
                                   comment='Голосовое пополнение · подтверждено владельцем', date=now))
    op = Operation(date=now, car_code=code, type='income', category='Аренда',
                   description=f'Пополнение баланса водителя {driver} · голос', amount=amount,
                   raw_message=f'{code} пополнение водителя {amount} [VOICE_TOPUP:{request_key}]')
    db.add(op)
    db.flush()
    db.add(Income(operation_id=op.id, car_code=code, date=now, amount=amount,
                  income_type='Пополнение водителя · голос'))
    db.add(VoiceFinanceReceipt(request_key=request_key, car_code=code,
                               kind='driver_wallet_topup', amount_rub=amount,
                               operation_id=op.id, raw_draft_json=json.dumps(preview, ensure_ascii=False)))
    db.flush()
    db.flush()
    balance = db.execute(select(func.coalesce(func.sum(DriverWalletTransaction.amount), 0)).where(
        DriverWalletTransaction.car_code == code)).scalar_one()
    return {'ok': True, 'operation_id': op.id, 'driver_name': driver,
            'car_code': code, 'amount_rub': amount, 'balance': int(balance),
            'rent_sync': rent_result, 'request_key': request_key}
