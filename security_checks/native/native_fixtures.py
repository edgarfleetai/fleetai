"""Native PostgreSQL fixtures: isolated cluster only; no application edits."""
import json
import os
from pathlib import Path
import secrets
import socket
import time

import psycopg
from psycopg import sql
import pytest
import requests
from sqlalchemy import event, text
from sqlalchemy.engine import Engine, URL
from werkzeug.security import generate_password_hash

ROOT = Path(__file__).resolve().parents[2]
if os.environ.get('FLEETAI_NATIVE_OPT_IN') != 'synthetic-only':
    raise RuntimeError('Use run_native.py with both explicit safety flags')
PRIVATE = Path(os.environ['FLEETAI_NATIVE_PRIVATE_CONFIG']).resolve(strict=True)
assert not PRIVATE.is_relative_to(ROOT)
assert PRIVATE.stat().st_uid == os.getuid() and PRIVATE.stat().st_mode & 0o077 == 0
CONFIG = json.loads(PRIVATE.read_text())
SOCKET = Path(CONFIG['socket_dir']).resolve()
assert SOCKET.parent == PRIVATE.parent
assert SOCKET.stat().st_uid == os.getuid() and SOCKET.stat().st_mode & 0o077 == 0
assert CONFIG['database'] == 'fleetai_native_synthetic'
assert SOCKET.is_dir() and len(str(SOCKET)) < 90
WRITER_URL = URL.create('postgresql+psycopg', username=CONFIG['writer'], password=CONFIG['writer_password'],
    database=CONFIG['database'], query={'host':str(SOCKET),'port':str(CONFIG['port']),
    'connect_timeout':'5','application_name':'fleetai-native-writer'})
READER_URL = URL.create('postgresql+psycopg', username=CONFIG['reader'], password=CONFIG['reader_password'],
    database=CONFIG['database'], query={'host':str(SOCKET),'port':str(CONFIG['port']),
    'connect_timeout':'5','application_name':'fleetai-native-reader'})
os.environ['DATABASE_URL'] = WRITER_URL.render_as_string(hide_password=False)
from isolation import install
ATTEMPTS = install(CONFIG, worker=True)
LOCK_EVIDENCE = []


@event.listens_for(Engine, 'do_connect')
def only_native_cluster(dialect, record, args, kwargs):
    assert dialect.name == 'postgresql', 'Only the designated native cluster is permitted'
    options = psycopg.conninfo.conninfo_to_dict(args[0]) if args and args[0] else {}
    options.update(kwargs)
    assert options.get('host') == str(SOCKET)
    assert str(options.get('port')) == str(CONFIG['port'])
    assert options.get('dbname') == CONFIG['database']
    assert options.get('user') in (CONFIG['writer'], CONFIG['reader'])
    assert dialect.driver == 'psycopg'


def admin():
    return psycopg.connect(host=str(SOCKET), port=CONFIG['port'], dbname=CONFIG['database'],
        user=CONFIG['admin'], password=CONFIG['admin_password'], connect_timeout=5,
        application_name='fleetai-native-observer')


def reader_connection():
    return psycopg.connect(host=str(SOCKET), port=CONFIG['port'], dbname=CONFIG['database'],
        user=CONFIG['reader'], password=CONFIG['reader_password'], connect_timeout=5)


@pytest.fixture(scope='session')
def native_app():
    from fleetai import create_app, db
    from sqlalchemy.pool import QueuePool
    # Disable only built-in real-fleet sample seeding; use the actual production
    # factory mode, schema initialization, migrations, blueprints and policies.
    original_seed = db.seed_cars
    db.seed_cars = lambda: None
    try:
        app = create_app({'TESTING':False, 'PROPAGATE_EXCEPTIONS':False,
            'DATABASE_URL':WRITER_URL.render_as_string(hide_password=False),
            'FINANCE_READONLY_DATABASE_URL':READER_URL.render_as_string(hide_password=False),
            'PUBLIC_BASE_URL':'https://localhost','SERVER_NAME':'localhost',
            'PREFERRED_URL_SCHEME':'https'})
    finally:
        db.seed_cars = original_seed
    assert app.testing is False
    assert isinstance(db.engine.pool, QueuePool)
    with admin() as connection:
        assert connection.execute('SHOW data_directory').fetchone()[0] == CONFIG['data_dir']
        assert connection.execute('SHOW listen_addresses').fetchone()[0] == ''
        connection.execute(sql.SQL('GRANT USAGE ON SCHEMA public TO {}').format(sql.Identifier(CONFIG['reader'])))
        connection.execute(sql.SQL('GRANT SELECT ON TABLE cars,driver_debts,driver_debt_payments,driver_wallet_transactions,operations TO {}').format(sql.Identifier(CONFIG['reader'])))
    yield app
    evidence = PRIVATE.parent.parent / 'lock-observer.json'
    evidence.write_text(json.dumps(LOCK_EVIDENCE, indent=2) + '\n')
    readonly = app.extensions.get('fleetai_finance_readonly_engine')
    if readonly:
        readonly.dispose()
    db.engine.dispose()


@pytest.fixture(autouse=True)
def fresh_synthetic_data(native_app, monkeypatch):
    from datetime import datetime
    from fleetai import db, routes
    from fleetai.models import Car, DriverWalletTransaction, DriverDebt, DriverDebtPayment, Operation
    from fleetai.auth_models import Owner
    with admin() as connection:
        tables = [row[0] for row in connection.execute("SELECT tablename FROM pg_tables WHERE schemaname='public'")]
        connection.execute(sql.SQL('TRUNCATE {} RESTART IDENTITY CASCADE').format(
            sql.SQL(',').join(sql.Identifier('public', name) for name in tables)))
    monkeypatch.setattr(routes, 'moscow_now', lambda: datetime(2026,11,6,12))
    password = secrets.token_urlsafe(24)
    native_app.config['AUDIT_OWNER_PASSWORD'] = password
    with db.Session() as session:
        session.add_all([Car(code='700',driver='Synthetic Driver',daily_rent=100),
                         Car(code='701',driver='Synthetic Other',daily_rent=100)])
        session.add(Owner(id=1,username='audit-owner',password_hash=generate_password_hash(password)))
        session.add_all([DriverWalletTransaction(car_code='700',driver_name='Synthetic Driver',amount=1000,
            transaction_type='opening_balance',source='manual',date=datetime(2026,11,5)),
            DriverWalletTransaction(car_code='700',driver_name='Synthetic Driver',amount=-100,
            transaction_type='daily_rent',source='system',date=datetime(2026,11,6))])
        session.add(DriverDebt(id=1,car_code='700',driver_name='Synthetic Driver',original_amount=100,balance=80,status='open',reason='Аренда'))
        session.add(DriverDebtPayment(debt_id=1,car_code='700',driver_name='Synthetic Driver',amount=20,date=datetime(2026,11,6)))
        session.add(Operation(car_code='700',type='income',category='Аренда',amount=100,date=datetime(2026,11,6),description='Synthetic ledger payment'))
        session.execute(text("INSERT INTO driver_telegram_bindings(id,car_code,driver_name,telegram_chat_id) VALUES (1,'700','Synthetic Driver','12345')"))
        session.commit()
    assert not ATTEMPTS, 'Setup attempted a forbidden external transport'
    yield
    assert not ATTEMPTS, 'A test attempted an external integration call'


def owner_client(app):
    client = app.test_client()
    response = client.post('/auth/login',base_url='https://localhost',headers={'Origin':'https://localhost'},
        data={'username':'audit-owner','password':app.config['AUDIT_OWNER_PASSWORD']})
    assert response.status_code == 303
    state = client.get('/auth/session',base_url='https://localhost').get_json()
    return client, {'Origin':'https://localhost','X-CSRF-Token':state['csrf_token']}


def driver_client(app):
    from fleetai import auth, db
    from fleetai.models import Car
    with db.Session() as session:
        raw = auth.issue_driver_login(session,session.query(Car).filter_by(code='700').one(),'12345')
        session.commit()
    client = app.test_client()
    response = client.post('/auth/driver/consume',base_url='https://localhost',headers={'Origin':'https://localhost'},json={'ticket':raw})
    assert response.status_code == 303
    state = client.get('/auth/session',base_url='https://localhost').get_json()
    return client, {'Origin':'https://localhost','X-CSRF-Token':state['csrf_token']}


def hermes_headers():
    from fleetai import auth, db
    with db.Session() as session:
        raw, _ = auth.issue_hermes_credential(session,'Synthetic native audit')
        session.commit()
    return {'Authorization':'Bearer '+raw}


def wait_for_real_lock(waiter, blocker=None, timeout=12):
    deadline = time.monotonic()+timeout
    with admin() as connection:
        connection.autocommit = True
        while time.monotonic() < deadline:
            row = connection.execute('SELECT wait_event_type,pg_blocking_pids(pid) FROM pg_stat_activity WHERE pid=%s',(waiter,)).fetchone()
            if row and row[0]=='Lock' and row[1] and (blocker is None or blocker in row[1]):
                LOCK_EVIDENCE.append({'waiter_pid':waiter, 'expected_blocker_pid':blocker,
                    'wait_event_type':row[0], 'blocking_pids':row[1]})
                return
            time.sleep(0.02)
    raise AssertionError('Native PostgreSQL did not show the expected real lock wait')


def ledger_snapshot():
    with admin() as connection:
        names = [r[0] for r in connection.execute("SELECT tablename FROM pg_tables WHERE schemaname='public' ORDER BY tablename")]
        return {name:connection.execute(sql.SQL('SELECT row_to_json(t)::text FROM {} t ORDER BY row_to_json(t)::text').format(sql.Identifier('public',name))).fetchall() for name in names}
