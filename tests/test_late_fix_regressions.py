"""Offline regressions for assignment transactions and enrollment issuance."""
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime
from threading import Barrier, current_thread

import pytest
from sqlalchemy import event, func, text

from test_security_integration import owner_client


def seed_assignment(*, existing_marker=False):
    from fleetai import db
    from fleetai.models import Car, DriverWalletTransaction
    with db.Session() as session:
        session.add(Car(code='700', driver='Original Driver', daily_rent=100))
        session.add(DriverWalletTransaction(car_code='700', driver_name='Original Driver',
            amount=-300, transaction_type='opening_balance'))
        if existing_marker:
            session.add(DriverWalletTransaction(car_code='700', driver_name='Original Driver', amount=0,
                transaction_type='daily_rent', comment='V7_START:2026-11-05'))
        session.commit()


@pytest.mark.parametrize('drivers', [('Original Driver', 'Original Driver'), ('Second Driver', 'Third Driver')])
@pytest.mark.parametrize('existing_marker', [False, True])
def test_concurrent_assignment_routes_serialize_before_wallet_reads(secure_app, monkeypatch, drivers, existing_marker):
    from fleetai import auth, db, routes
    from fleetai.models import Car, DriverDebt, DriverWalletTransaction
    seed_assignment(existing_marker=existing_marker)
    owner, headers = owner_client(secure_app)
    cookie = owner.get_cookie(auth.COOKIE)
    gate = Barrier(2)
    real_lock = auth.lock_driver_assignment
    first_sessions = set()
    def lock(session, code):
        if current_thread().name.startswith('assignment') and id(session) not in first_sessions:
            first_sessions.add(id(session))
            gate.wait(timeout=10)
        return real_lock(session, code)
    monkeypatch.setattr(auth, 'lock_driver_assignment', lock)
    monkeypatch.setattr(routes, 'moscow_now', lambda: datetime(2026, 11, 6, 12))
    def assign(driver):
        client = secure_app.test_client()
        client.set_cookie(cookie.key, cookie.value)
        response = client.post('/api/driver-assignment', base_url='https://localhost', headers=headers,
            json={'car_code':'700', 'driver':driver, 'daily_rent':100, 'opening_balance':200})
        return response.status_code, response.json.get('old_driver')
    with ThreadPoolExecutor(max_workers=2, thread_name_prefix='assignment') as pool:
        results = list(pool.map(assign, drivers))
    assert [status for status, _ in results] == [200, 200]
    with db.Session() as session:
        balance = session.query(func.sum(DriverWalletTransaction.amount)).filter_by(car_code='700').scalar()
        assert balance == 200, 'concurrent route resets must not apply a stale adjustment twice'
        debts = session.query(DriverDebt).all()
        if drivers[0] != 'Original Driver':
            assert [(d.driver_name, d.balance) for d in debts] == [('Original Driver', 400 if existing_marker else 300)]
            final_driver = session.query(Car).filter_by(code='700').one().driver
            assert set(old for _, old in results) == {'Original Driver', next(d for d in drivers if d != final_driver)}
        else:
            assert debts == []


@pytest.mark.parametrize('existing_marker', [False, True])
def test_assignment_failure_rolls_back_accrual_reset_and_revocation(secure_app, monkeypatch, existing_marker):
    from fleetai import db, routes
    from fleetai.models import Car, DriverWalletTransaction
    seed_assignment(existing_marker=existing_marker)
    monkeypatch.setattr(routes, 'moscow_now', lambda: datetime(2026, 11, 6, 12))
    owner, headers = owner_client(secure_app)
    with db.Session() as session:
        session.execute(text("INSERT INTO driver_telegram_bindings(id,car_code,driver_name,telegram_chat_id) VALUES (1,'700','Original Driver','12345')"))
        session.commit()
    real_set = routes._set_auto_rent_enabled
    reached = []
    def fail_after_settings(*args, **kwargs):
        real_set(*args, **kwargs)
        reached.append(True)
        raise RuntimeError('injected assignment rollback')
    monkeypatch.setattr(routes, '_set_auto_rent_enabled', fail_after_settings)
    response = owner.post('/api/driver-assignment', base_url='https://localhost', headers=headers,
        json={'car_code':'700','driver':'Replacement','daily_rent':100,'opening_balance':200})
    assert response.status_code == 500 and reached == [True]
    with db.Session() as session:
        assert session.query(Car).filter_by(code='700').one().driver == 'Original Driver'
        assert session.query(DriverWalletTransaction).count() == (2 if existing_marker else 1)
        assert session.execute(text('SELECT count(*) FROM driver_telegram_bindings')).scalar() == 1
        assert session.execute(text('SELECT count(*) FROM auth_driver_epochs')).scalar() == 0


@pytest.mark.parametrize('existing_marker', [False, True])
def test_default_rent_sync_still_commits_legacy_accruals(secure_app, monkeypatch, existing_marker):
    from fleetai import db, routes
    from fleetai.models import Car, DriverWalletTransaction
    seed_assignment()
    monkeypatch.setattr(routes, 'moscow_now', lambda: datetime(2026, 11, 6, 12))
    with db.Session() as session:
        if existing_marker:
            session.add(DriverWalletTransaction(car_code='700', driver_name='Original Driver', amount=0,
                transaction_type='daily_rent', comment='V7_START:2026-11-05'))
            session.commit()
        commits = []
        event.listen(session, 'after_commit', lambda s: commits.append(True))
        result = routes._sync_daily_rent(session, session.query(Car).filter_by(code='700').one())
        assert commits == [True]
        assert result['charged'] == int(existing_marker)
    with db.Session() as session:
        rents = session.query(DriverWalletTransaction).filter_by(transaction_type='daily_rent').all()
        assert len(rents) == (2 if existing_marker else 1)
        assert sum(row.amount for row in rents) == (-100 if existing_marker else 0)


@pytest.mark.parametrize('existing_marker', [False, True])
def test_legacy_assignment_get_still_persists_rent(secure_app, monkeypatch, existing_marker):
    from fleetai import db, routes
    from fleetai.models import DriverWalletTransaction
    seed_assignment(existing_marker=existing_marker)
    owner, headers = owner_client(secure_app)
    monkeypatch.setattr(routes, 'moscow_now', lambda: datetime(2026, 11, 6, 12))
    response = owner.get('/api/driver-assignment/700', base_url='https://localhost', headers=headers)
    assert response.status_code == 200
    assert response.json['balance'] == (-400 if existing_marker else -300)
    with db.Session() as session:
        rents = session.query(DriverWalletTransaction).filter_by(transaction_type='daily_rent').all()
        assert len(rents) == (2 if existing_marker else 1)
        assert sum(row.amount for row in rents) == (-100 if existing_marker else 0)


@pytest.mark.parametrize('missing_lock', [False, True])
def test_owner_enrollment_rejects_noncanonical_or_unlocked_car_without_side_effects(secure_app, monkeypatch, missing_lock):
    import sqlite3
    from fleetai import auth, db, routes
    from fleetai.models import Car
    with db.Session() as session:
        session.add(Car(code='700' if missing_lock else ' 700 ', driver='Original Driver', daily_rent=100))
        session.commit()
    owner, headers = owner_client(secure_app)
    calls = []
    monkeypatch.setattr(routes, '_telegram_bot_username', lambda: calls.append('username') or 'offline_bot')
    if missing_lock:
        monkeypatch.setattr(auth, 'lock_driver_assignment', lambda session, code: None)
    def snapshot():
        with sqlite3.connect(db.engine.url.database) as connection:
            return list(connection.iterdump())
    before = snapshot()
    response = owner.post('/api/driver-telegram/link', base_url='https://localhost', headers=headers, json={'car_code':'700'})
    assert response.status_code == 409
    assert response.json['ok'] is False and 'link' not in response.json
    assert calls == [], 'rejection must precede even Telegram username discovery'
    assert snapshot() == before, 'rejected issuance must not mutate any persisted state'


def test_owner_issued_links_redeem_and_cross_car_rebinding_never_resurrects_access(secure_app, monkeypatch):
    from fleetai import auth, db, routes
    from fleetai.models import Car
    with db.Session() as session:
        session.add_all([Car(code='700', driver='Original Driver'), Car(code='701', driver='Other Driver')])
        session.commit()
    owner, headers = owner_client(secure_app)
    monkeypatch.setattr(routes, '_telegram_bot_username', lambda: 'offline_bot')
    monkeypatch.setattr(routes, 'send_telegram_to_chat', lambda *a, **k: True)
    monkeypatch.setattr(routes, '_send_driver_contract_step', lambda *a, **k: None)
    secure_app.config['TELEGRAM_WEBHOOK_SECRET'] = 'offline-webhook'
    stale_sessions, stale_tickets = [], []
    for code in ['700', '701', '700']:
        issued = owner.post('/api/driver-telegram/link', base_url='https://localhost', headers=headers, json={'car_code':code})
        assert issued.status_code == 200
        token = issued.json['link'].split('driver_', 1)[1]
        with db.Session() as session:
            assert session.execute(text('SELECT car_code FROM driver_telegram_links WHERE link_token=:token'), {'token':token}).scalar() == code
        response = secure_app.test_client().post('/api/telegram/webhook', base_url='https://localhost',
            headers={'X-Telegram-Bot-Api-Secret-Token':'offline-webhook'},
            json={'message':{'text':'/start driver_'+token, 'chat':{'id':12345,'type':'private'}, 'from':{'id':12345}}})
        assert response.status_code == 200 and response.json['ok']
        for client in stale_sessions:
            assert client.get('/auth/session', base_url='https://localhost').status_code == 401
        for ticket in stale_tickets:
            assert secure_app.test_client().post('/auth/driver/consume', base_url='https://localhost', json={'ticket':ticket}).status_code == 401
        with db.Session() as session:
            bindings = session.execute(text('SELECT car_code FROM driver_telegram_bindings WHERE telegram_chat_id=:chat'), {'chat':'12345'}).scalars().all()
            assert bindings == [code]
            car = session.query(Car).filter_by(code=code).one()
            ticket = auth.issue_driver_login(session, car, '12345')
            unused = auth.issue_driver_login(session, car, '12345')
            session.commit()
        client = secure_app.test_client()
        assert client.post('/auth/driver/consume', base_url='https://localhost', json={'ticket':ticket}).status_code == 303
        stale_sessions.append(client)
        stale_tickets.append(unused)
