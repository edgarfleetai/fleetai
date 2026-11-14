"""Late independent findings: binding serialization, driver scope, test parents."""
from datetime import datetime, timedelta
import pytest
from sqlalchemy import text


def seed_binding_link(app):
    from fleetai import db
    from fleetai.models import Car
    with db.Session() as session:
        session.add(Car(code='BIND1', driver='Synthetic Driver', daily_rent=0))
        session.execute(text('INSERT INTO driver_telegram_links(id,car_code,driver_name,link_token,created_at,expires_at) VALUES (1,:car,:driver,:token,:now,:expires)'),
            {'car':'BIND1','driver':'Synthetic Driver','token':'synthetic-enrollment',
             'now':datetime(2026,1,1), 'expires':datetime(2099,1,1)})
        session.commit()


def test_driver_response_never_includes_same_name_debts_from_another_car(secure_app):
    from fleetai import auth, db
    from fleetai.models import Car, DriverDebt
    with db.Session() as session:
        first = Car(code='SCOPE1', driver='Same Display Name', daily_rent=0)
        session.add_all([first, Car(code='SCOPE2',driver='Same Display Name',daily_rent=0),
            DriverDebt(car_code='SCOPE1',driver_name='Same Display Name',original_amount=100,balance=100,status='open'),
            DriverDebt(car_code='SCOPE2',driver_name='Same Display Name',original_amount=900,balance=900,status='open')])
        session.execute(text('INSERT INTO driver_telegram_bindings(id,car_code,driver_name,telegram_chat_id) VALUES (1,:car,:driver,:chat)'),
            {'car':'SCOPE1','driver':'Same Display Name','chat':'12345'})
        session.commit()
        ticket = auth.issue_driver_login(session, first, '12345')
        session.commit()
    client = secure_app.test_client()
    assert client.post('/auth/driver/consume',base_url='https://localhost',json={'ticket':ticket}).status_code == 303
    csrf = client.get('/auth/session',base_url='https://localhost').json['csrf_token']
    response = client.get('/api/driver-mvp/SCOPE1',base_url='https://localhost',headers={'X-CSRF-Token':csrf})
    assert response.status_code == 200
    assert response.json['separate_debt'] == 100
    assert response.json['total_due'] == 100


def test_test_marked_parent_debt_excludes_ordinary_payment_but_not_orphan(secure_app):
    from fleetai import auth, db
    from fleetai.models import DriverDebt, DriverDebtPayment
    with db.Session() as session:
        session.add_all([DriverDebt(id=1,car_code='700',driver_name='Synthetic',reason='Тестовый долг',balance=100),
                         DriverDebt(id=2,car_code='700',driver_name='Synthetic',reason='Аренда',balance=100)])
        session.add_all([DriverDebtPayment(id=1,debt_id=1,car_code='700',amount=100,comment='Оплата долга',date=datetime(2026,1,1)),
                         DriverDebtPayment(id=2,debt_id=2,car_code='700',amount=100,comment='Оплата долга',date=datetime(2026,1,1)),
                         DriverDebtPayment(id=3,debt_id=999,car_code='700',amount=100,comment='Оплата долга',date=datetime(2026,1,1))])
        token, _ = auth.issue_hermes_credential(session,'synthetic parent filter')
        session.commit()
    response = secure_app.test_client().get('/api/integrations/hermes/v1/payments?source=debt_payments',
        base_url='https://localhost',headers={'Authorization':'Bearer '+token})
    assert response.status_code == 200
    assert [row['id'] for row in response.json['data']] == ['debt_payment:2','debt_payment:3']


def test_binding_redemption_is_single_use(secure_app):
    from fleetai.driver_binding import redeem_binding_link
    from fleetai import db
    seed_binding_link(secure_app)
    with db.Session() as session:
        car, error = redeem_binding_link(session,'synthetic-enrollment','12345')
        assert car.code == 'BIND1' and error is None
        session.commit()
    with db.Session() as session:
        car, error = redeem_binding_link(session,'synthetic-enrollment','12345')
        assert car is None and error is not None
        assert session.execute(text('SELECT count(*) FROM driver_telegram_bindings')).scalar() == 1


def test_binding_redemption_waits_then_revalidates_assignment(secure_app, monkeypatch):
    from concurrent.futures import ThreadPoolExecutor
    from threading import Event, current_thread
    from fleetai.driver_binding import redeem_binding_link
    from fleetai import auth, db
    seed_binding_link(secure_app)
    reached, proceed = Event(), Event()
    real_lock = auth.lock_driver_assignment
    def lock(session, code):
        if current_thread().name.startswith('redemption'):
            reached.set()
            assert proceed.wait(10)
        return real_lock(session, code)
    monkeypatch.setattr(auth,'lock_driver_assignment',lock)
    def redeem():
        with db.Session() as session:
            result = redeem_binding_link(session,'synthetic-enrollment','12345')
            session.commit()
            return result[0] is None
    with ThreadPoolExecutor(max_workers=1,thread_name_prefix='redemption') as pool:
        future = pool.submit(redeem)
        assert reached.wait(10)
        try:
            with db.Session() as session:
                # Explicit same-name assignment must serialize even without a driver UPDATE.
                auth.revoke_driver_access(session,'BIND1')
                session.commit()
        finally:
            proceed.set()
        assert future.result(timeout=10) is True
    with db.Session() as session:
        assert session.execute(text('SELECT count(*) FROM driver_telegram_bindings')).scalar() == 0


def test_concurrent_binding_redemption_has_one_winner(secure_app):
    from concurrent.futures import ThreadPoolExecutor
    from threading import Barrier
    from fleetai.driver_binding import redeem_binding_link
    from fleetai import db
    seed_binding_link(secure_app)
    gate = Barrier(2)
    def redeem():
        with db.Session() as session:
            gate.wait(timeout=10)
            car, error = redeem_binding_link(session,'synthetic-enrollment','12345')
            session.commit()
            return car is not None
    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(lambda _:redeem(),range(2)))
    assert sorted(results) == [False,True]
    with db.Session() as session:
        assert session.execute(text('SELECT count(*) FROM driver_telegram_bindings')).scalar() == 1
