"""Financial risk summary for proposed driver changes. No writes."""
from sqlalchemy import func
from .models import DriverWalletTransaction, DriverDebt


def review_driver_finances(db, cars):
    reviews = []
    for car in cars:
        code = str(car.code).strip()
        name = (car.driver or '').strip()
        wallet = db.query(func.coalesce(func.sum(DriverWalletTransaction.amount), 0)).filter(
            func.trim(DriverWalletTransaction.car_code) == code).scalar()
        debts = db.query(func.coalesce(func.sum(DriverDebt.balance), 0)).filter(
            func.trim(DriverDebt.car_code) == code,
            DriverDebt.driver_name == name,
            DriverDebt.status == 'open').scalar() if name else 0
        reviews.append({
            'car_code': code,
            'driver': name,
            'wallet_balance_rub': int(wallet or 0),
            'open_driver_debt_rub': int(debts or 0),
            'daily_rent_rub': int(car.daily_rent or 0),
            'deposit_rub': int(car.driver_deposit or 0),
        })
    return {
        'cars': reviews,
        'requires_financial_confirmation': True,
        'execution_enabled': False,
        'warning': 'Данные для сверки: остаток кошелька, долг, аренда и депозит не переносятся автоматически.',
    }
