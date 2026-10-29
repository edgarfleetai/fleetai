"""Atomic driver assignment change, disabled when financial state is nontrivial."""
import json
from datetime import datetime
from sqlalchemy import func, select
from .models import Car, DriverWalletTransaction, DriverDebt
from .driver_move_preview import preview_driver_move
from .driver_move_guard import is_preview_current
from .driver_move_idempotency import DriverMoveRequest, validate_request_key
from .driver_move_audit import DriverMoveAudit


def execute_driver_move(db, *, source, target, swap, fingerprint, approved, request_key):
    """Caller owns transaction boundary. Raises ValueError for unsafe operations.

    Intentionally rejects all cars with existing wallet entries, rent or deposits
    until a complete financial closing workflow is implemented.
    """
    if approved is not True or not validate_request_key(request_key):
        raise ValueError('Требуется подтверждение и уникальный ключ запроса')
    if not isinstance(swap, bool):
        raise ValueError('Неверный тип операции')
    codes = sorted(set([str(source).strip(), str(target).strip()]))
    if len(codes) != 2:
        raise ValueError('Нужны две разные машины')
    existing = db.execute(select(DriverMoveRequest).where(
        DriverMoveRequest.request_key == request_key)).scalar_one_or_none()
    if existing is not None:
        raise ValueError('Этот запрос уже был зарегистрирован')
    cars = db.execute(select(Car).where(Car.code.in_(codes)).order_by(Car.code).with_for_update()).scalars().all()
    if len(cars) != 2:
        raise ValueError('Один из автомобилей не найден')
    if not is_preview_current(cars, fingerprint):
        raise ValueError('Назначения изменились, нужен новый предпросмотр')
    assignments = {car.code: car.driver for car in cars}
    preview = preview_driver_move(assignments, str(source).strip(), str(target).strip(), swap=swap)
    if not preview['ok']:
        raise ValueError(preview['error'])
    for car in cars:
        wallet_count = db.query(func.count(DriverWalletTransaction.id)).filter(
            func.trim(DriverWalletTransaction.car_code) == car.code).scalar()
        debt_count = db.query(func.count(DriverDebt.id)).filter(
            func.trim(DriverDebt.car_code) == car.code).scalar()
        if (wallet_count or debt_count or int(car.daily_rent or 0)
                or int(car.driver_deposit or 0) or int(car.weekly_payment or 0)):
            raise ValueError('Финансовые данные автомобиля требуют ручной сверки; автоматическая перестановка запрещена')
    db.add(DriverMoveRequest(
        request_key=request_key, source_car=str(source).strip(), target_car=str(target).strip(),
        expected_fingerprint=fingerprint, action='swap' if swap else 'move', status='completed',
        result_json=json.dumps(preview, ensure_ascii=False), completed_at=datetime.now()))
    for change in preview['changes']:
        db.add(DriverMoveAudit(
            request_key=request_key, car_code=change['car'],
            previous_driver=change['before'], new_driver=change['after'],
            financial_snapshot_json='{}'))
        next(car for car in cars if car.code == change['car']).driver = change['after']
    db.flush()
    return {'ok': True, 'changes': preview['changes'], 'request_key': request_key}
