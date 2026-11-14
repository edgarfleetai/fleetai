"""Synthetic auth tests: all databases are explicit local SQLite files."""
import os
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
os.environ.setdefault('DATABASE_URL', 'sqlite:///' + str(ROOT / '.test-data' / 'auth-import.sqlite'))

import pytest
from sqlalchemy import text
from flask import Flask
from fleetai import db


@pytest.fixture
def app(tmp_path):
    from fleetai.auth import init_auth
    from sqlalchemy import create_engine
    path = ROOT / '.test-data'
    path.mkdir(exist_ok=True)
    import uuid
    target = path / ('auth-' + uuid.uuid4().hex + '.sqlite')
    engine = create_engine('sqlite:///' + str(target))
    old = db.Session.kw.get('bind')
    db.Session.configure(bind=engine)
    app = Flask(__name__)
    app.config.update(TESTING=True, AUTH_PASSWORD_METHOD='pbkdf2:sha256:1000')
    init_auth(app)
    db.Base.metadata.create_all(engine)
    from fleetai.auth import _install_assignment_triggers
    with engine.begin() as connection:
        _install_assignment_triggers(db.Base.metadata, connection)
    with engine.begin() as conn:
        conn.execute(text('CREATE TABLE IF NOT EXISTS driver_telegram_bindings (id INTEGER PRIMARY KEY, car_code VARCHAR, driver_name VARCHAR, telegram_chat_id VARCHAR, linked_at TIMESTAMP)'))
    yield app
    db.Session.configure(bind=old)
    engine.dispose()
    target.unlink(missing_ok=True)


def bootstrap(app):
    result = app.test_cli_runner().invoke(args=['auth', 'bootstrap-owner', '--username', 'owner'], input='synthetic-long-password\nsynthetic-long-password\n')
    assert result.exit_code == 0, result.output


def login(app):
    bootstrap(app)
    client = app.test_client()
    response = client.post('/auth/login', data={'username': 'owner', 'password': 'synthetic-long-password'}, base_url='https://localhost')
    assert response.status_code == 303
    return client, response


def test_hermes_credential_hashed_scoped_revoked_no_cookie_fallback(app):
    from fleetai.auth import issue_hermes_credential, revoke_hermes_credential
    client, _ = login(app)
    with db.Session() as session:
        raw, record = issue_hermes_credential(session, 'synthetic')
        record_id = record.id
        assert raw not in str(record.__dict__)
        session.commit()
    headers = {'Authorization': 'Bearer ' + raw}
    response = client.get('/auth/session', headers=headers, base_url='https://localhost')
    assert response.json['kind'] == 'hermes'
    assert response.json['scopes'] == ['finance:read']
    assert response.json['csrf_token'] is None
    with db.Session() as session:
        assert revoke_hermes_credential(session, record_id)
        session.commit()
    assert client.get('/auth/session', headers=headers, base_url='https://localhost').status_code == 401
    assert client.get('/auth/session', headers={'Authorization': 'Bearer bogus'}, base_url='https://localhost').status_code == 401
    assert client.get('/auth/session', base_url='https://localhost').status_code == 200


def seed_driver():
    from fleetai.models import Car
    with db.Session() as session:
        car = Car(code='T1', driver='Alice')
        session.add(car)
        session.execute(text("INSERT INTO driver_telegram_bindings(car_code,driver_name,telegram_chat_id) VALUES ('T1','Alice','123')"))
        session.commit()


def test_driver_ticket_verified_single_use_fragment_and_scoped_session(app):
    from fleetai.auth import issue_driver_login
    from fleetai.models import Car
    seed_driver()
    with app.app_context(), db.Session() as session:
        car = session.scalar(db.select(Car)) if hasattr(db, 'select') else session.query(Car).filter_by(code='T1').one()
        with pytest.raises(ValueError):
            issue_driver_login(session, car, 'wrong-chat')
        token = issue_driver_login(session, car, '123')
        session.commit()
    client = app.test_client()
    assert client.get('/auth/driver?token=' + token).status_code == 400
    assert client.get('/auth/driver').status_code == 200
    response = client.post('/auth/driver/consume', json={'ticket': token}, base_url='https://localhost')
    assert response.status_code == 303
    assert response.headers['Location'] == '/driver?code=T1'
    current = client.get('/auth/session', base_url='https://localhost').json
    assert current['kind'] == 'driver'
    assert current['car_code'] == 'T1'
    assert current['scopes'] == []
    assert client.post('/auth/driver/consume', json={'ticket': token}, base_url='https://localhost').status_code == 401


@pytest.mark.parametrize('mode', ['orm', 'sql', 'explicit', 'unflushed'])
def test_driver_assignment_epoch_revokes_tickets_and_sessions_even_aba(app, mode):
    from fleetai.auth import issue_driver_login, revoke_driver_access
    from fleetai.models import Car
    seed_driver()
    with db.Session() as session:
        car = session.query(Car).filter_by(code='T1').one()
        token1 = issue_driver_login(session, car, '123')
        token2 = issue_driver_login(session, car, '123')
        session.commit()
    client = app.test_client()
    assert client.post('/auth/driver/consume', json={'ticket': token1}, base_url='https://localhost').status_code == 303
    with db.Session() as session:
        if mode in ('orm', 'unflushed'):
            car = session.query(Car).filter_by(code='T1').one()
            car.driver = 'Bob'
            if mode == 'orm':
                session.flush()
            car.driver = 'Alice'
        elif mode == 'sql':
            session.execute(text("UPDATE cars SET driver='Bob' WHERE code='T1'"))
            session.execute(text("UPDATE cars SET driver='Alice' WHERE code='T1'"))
        else:
            revoke_driver_access(session, 'T1')
        session.commit()
    assert client.get('/auth/session', base_url='https://localhost').status_code == 401
    assert client.post('/auth/driver/consume', json={'ticket': token2}, base_url='https://localhost').status_code == 401
    with db.Session() as session:
        car = session.query(Car).filter_by(code='T1').one()
        with pytest.raises(ValueError):
            issue_driver_login(session, car, '123')
        assert session.execute(text("SELECT count(*) FROM driver_telegram_bindings WHERE car_code='T1'")).scalar() == 0


def test_persisted_login_rate_limit_account_and_remote_ip_not_forwarded(app):
    bootstrap(app)
    client = app.test_client()
    for n in range(5):
        response = client.post('/auth/login', data={'username': 'owner', 'password': 'bad'},
                               headers={'X-Forwarded-For': 'forged-' + str(n)})
        assert response.status_code == 401
    # New browser and remote address do not bypass per-account protection.
    response = app.test_client().post('/auth/login', data={'username': 'owner', 'password': 'synthetic-long-password'},
                                     environ_overrides={'REMOTE_ADDR': '192.0.2.2'})
    assert response.status_code == 429
    # Different usernames from one real address are also bounded.
    for n in range(16):
        response = app.test_client().post('/auth/login', data={'username': 'unknown-' + str(n), 'password': 'bad'},
                                          headers={'X-Forwarded-For': '192.0.2.' + str(n)})
    assert response.status_code == 429


def test_local_cli_credential_creation_requires_owner_and_confirmation(app):
    from fleetai.auth_models import HermesCredential
    runner = app.test_cli_runner()
    result = runner.invoke(args=['auth', 'create-hermes-credential', '--label', 'synthetic'], input='y\n')
    assert result.exit_code != 0
    bootstrap(app)
    result = runner.invoke(args=['auth', 'create-hermes-credential', '--label', 'synthetic'], input='n\n')
    assert result.exit_code != 0
    with db.Session() as session:
        assert session.query(HermesCredential).count() == 0
    result = runner.invoke(args=['auth', 'create-hermes-credential', '--label', 'synthetic'], input='y\n')
    assert result.exit_code == 0, result.output
    assert 'fh_' in result.output
    with db.Session() as session:
        record = session.query(HermesCredential).one()
        credential_id = record.id
        assert record.token_hash not in result.output
    result = runner.invoke(args=['auth', 'revoke-hermes-credential', '--credential-id', str(credential_id)], input='y\n')
    assert result.exit_code == 0, result.output
    with db.Session() as session:
        assert session.get(HermesCredential, credential_id).revoked_at is not None


def test_driver_consume_rejects_malformed_json_and_cross_site(app):
    client = app.test_client()
    for payload in (['not-an-object'], 123, True):
        response = client.post('/auth/driver/consume', json=payload)
        assert response.status_code == 401
    assert client.post('/auth/driver/consume', json={'ticket': 'synthetic'},
                       headers={'Origin': 'https://evil.invalid'}, base_url='https://localhost').status_code == 403
    landing = client.get('/auth/driver')
    assert "URLSearchParams" in landing.text
    assert "replaceState" in landing.text


def test_csrf_rejects_non_ascii_and_cross_site_and_login_cannot_redirect(app):
    client, _ = login(app)
    csrf = client.get('/auth/session', base_url='https://localhost').json['csrf_token']
    assert client.post('/auth/logout', headers={'X-CSRF-Token': 'é'}, base_url='https://localhost').status_code == 403
    assert client.post('/auth/logout', headers={'X-CSRF-Token': csrf, 'Origin': 'https://evil.invalid'}, base_url='https://localhost').status_code == 403
    assert client.post('/auth/login', data={'username': 'owner', 'password': 'synthetic-long-password'}, headers={'Origin': 'https://evil.invalid'}, base_url='https://localhost').status_code == 403
    response = client.post('/auth/login?next=https://evil.invalid', data={'username': 'owner', 'password': 'synthetic-long-password'}, base_url='https://localhost')
    assert response.headers['Location'] == '/'


def test_expired_ticket_and_session_and_binding_removed_fail_closed(app):
    import time
    from fleetai.auth import issue_driver_login
    from fleetai.auth_models import DriverTicket, AuthSession, Owner
    from fleetai.models import Car
    seed_driver()
    with db.Session() as session:
        car = session.query(Car).filter_by(code='T1').one()
        ticket = issue_driver_login(session, car, '123')
        session.flush()
        record = session.query(DriverTicket).one()
        assert 0 < record.expires_at - time.time() <= 300
        assert ticket not in str(record.__dict__)
        record.expires_at = time.time() - 1
        session.commit()
    client = app.test_client()
    assert client.post('/auth/driver/consume', json={'ticket': ticket}, base_url='https://localhost').status_code == 401
    with db.Session() as session:
        token = issue_driver_login(session, session.query(Car).filter_by(code='T1').one(), '123')
        session.commit()
    assert client.post('/auth/driver/consume', json={'ticket': token}, base_url='https://localhost').status_code == 303
    with db.Session() as session:
        session.execute(text("DELETE FROM driver_telegram_bindings WHERE car_code='T1'"))
        session.commit()
    assert client.get('/auth/session', base_url='https://localhost').status_code == 401
    client, _ = login(app)
    with db.Session() as session:
        owner = session.query(Owner).one()
        assert owner.password_hash != 'synthetic-long-password'
        record = session.query(AuthSession).filter_by(kind='owner').one()
        assert 28700 < record.expires_at - time.time() <= 28800
        assert len(record.token_hash) == 64
        record.expires_at = time.time() - 1
        session.commit()
    assert client.get('/auth/session', base_url='https://localhost').status_code == 401


def test_driver_ticket_concurrent_consumption_has_exactly_one_winner(app):
    from concurrent.futures import ThreadPoolExecutor
    from threading import Barrier
    from fleetai.auth import issue_driver_login
    from fleetai.models import Car
    from fleetai.auth_models import AuthSession
    seed_driver()
    with db.Session() as session:
        ticket = issue_driver_login(session, session.query(Car).filter_by(code='T1').one(), '123')
        session.commit()
    gate = Barrier(2)
    def consume():
        with app.test_client() as client:
            gate.wait(timeout=10)
            return client.post('/auth/driver/consume', json={'ticket': ticket}, base_url='https://localhost').status_code
    with ThreadPoolExecutor(max_workers=2) as pool:
        codes = list(pool.map(lambda _: consume(), range(2)))
    assert sorted(codes) == [303, 401]
    with db.Session() as session:
        assert session.query(AuthSession).filter_by(kind='driver').count() == 1


def test_revocation_rollback_preserves_access_and_reassignment_requires_rebind(app):
    from fleetai.auth import issue_driver_login, revoke_driver_access
    from fleetai.models import Car
    seed_driver()
    with db.Session() as session:
        token = issue_driver_login(session, session.query(Car).filter_by(code='T1').one(), '123')
        session.commit()
    with db.Session() as session:
        revoke_driver_access(session, 'T1')
        session.rollback()
    client = app.test_client()
    assert client.post('/auth/driver/consume', json={'ticket': token}, base_url='https://localhost').status_code == 303
    with db.Session() as session:
        session.execute(text("INSERT INTO driver_telegram_links(car_code,driver_name,link_token) VALUES ('T1','Alice','synthetic-legacy-link')"))
        session.commit()
        car = session.query(Car).filter_by(code='T1').one()
        car.driver = 'Bob'
        revoke_driver_access(session, 'T1')
        session.commit()
        assert session.execute(text("SELECT count(*) FROM driver_telegram_links WHERE car_code='T1'")).scalar() == 0
        # Explicitly authorized rebind to the new assignment allows new login.
        session.execute(text("INSERT INTO driver_telegram_bindings(car_code,driver_name,telegram_chat_id) VALUES ('T1','Bob','456')"))
        fresh = issue_driver_login(session, car, '456')
        session.commit()
    assert client.get('/auth/session', base_url='https://localhost').status_code == 401
    assert client.post('/auth/driver/consume', json={'ticket': fresh}, base_url='https://localhost').status_code == 303


def test_owner_login_session_csrf_and_fail_closed(app):
    client = app.test_client()
    assert client.post('/auth/login', data={'username': 'owner', 'password': ''}).status_code == 401
    client, response = login(app)
    cookie = response.headers['Set-Cookie']
    for attribute in ('__Host-fleetai_session=', 'Secure', 'HttpOnly', 'SameSite=Lax', 'Path=/'):
        assert attribute in cookie
    assert 'Domain=' not in cookie
    current = client.get('/auth/session', base_url='https://localhost')
    assert current.json['kind'] == 'owner'
    assert current.json['csrf_token']
    assert client.post('/auth/logout', base_url='https://localhost').status_code == 403
    assert client.post('/auth/logout', headers={'X-CSRF-Token': current.json['csrf_token']}, base_url='https://localhost').status_code == 303
    assert client.get('/auth/session', base_url='https://localhost').status_code == 401
