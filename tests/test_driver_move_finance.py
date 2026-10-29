from types import SimpleNamespace
from fleetai.db import Base, engine, Session
from fleetai.models import Car, DriverWalletTransaction, DriverDebt
from fleetai.driver_move_finance import review_driver_finances


def test_financial_review_uses_live_records():
    Base.metadata.create_all(engine)
    with Session() as db:
        car = Car(code='TST992', driver='Тест', daily_rent=1857, driver_deposit=5000)
        db.add(car)
        db.add(DriverWalletTransaction(car_code='TST992', driver_name='Тест', amount=-2500))
        db.add(DriverDebt(car_code='TST992', driver_name='Тест', balance=1000, status='open'))
        db.flush()
        result = review_driver_finances(db, [car])
        row = result['cars'][0]
        assert row['wallet_balance_rub'] == -2500
        assert row['open_driver_debt_rub'] == 1000
        assert row['daily_rent_rub'] == 1857
        assert row['deposit_rub'] == 5000
        assert result['execution_enabled'] is False
        db.rollback()
