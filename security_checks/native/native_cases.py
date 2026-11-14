"""Additional tests on a genuine, temporary PostgreSQL server."""
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime
from threading import Event, current_thread

import psycopg
from psycopg import sql
import pytest
from sqlalchemy import event, func, text

from native_fixtures import (CONFIG, admin, reader_connection, owner_client, driver_client,
                      hermes_headers, wait_for_real_lock, ledger_snapshot)


def test_native_schema_migrations_repeat_and_triggers(native_app):
    from fleetai import db
    assert db.engine.dialect.name == 'postgresql'
    assert db.engine.dialect.driver == 'psycopg'
    db.init_db(seed=False)
    db.init_db(seed=False)
    with admin() as connection:
        assert connection.execute('SHOW listen_addresses').fetchone()[0] == ''
        assert connection.execute('SHOW transaction_isolation').fetchone()[0] == 'read committed'
        assert connection.execute("SELECT count(*) FROM pg_trigger WHERE tgname='auth_driver_assignment' AND NOT tgisinternal").fetchone()[0] == 1
        assert connection.execute("SELECT count(*) FROM information_schema.columns WHERE table_name='cars' AND column_name='payment_notifications'").fetchone()[0] == 1


@pytest.mark.parametrize('table', ['cars','driver_debts','driver_debt_payments','driver_wallet_transactions','operations'])
@pytest.mark.parametrize('operation', ['INSERT','UPDATE','DELETE'])
def test_select_only_role_denies_each_write_table(native_app, table, operation):
    with reader_connection() as connection:
        assert connection.execute('SHOW transaction_read_only').fetchone()[0] == 'off'
        if operation == 'INSERT':
            statement = sql.SQL('INSERT INTO {} DEFAULT VALUES').format(sql.Identifier(table))
        elif operation == 'UPDATE':
            statement = sql.SQL('UPDATE {} SET id=id WHERE false').format(sql.Identifier(table))
        else:
            statement = sql.SQL('DELETE FROM {} WHERE false').format(sql.Identifier(table))
        with pytest.raises(psycopg.errors.InsufficientPrivilege) as caught:
            connection.execute(statement)
        assert caught.value.sqlstate == '42501'
        connection.rollback()
        assert connection.execute(sql.SQL('SELECT count(*) FROM {}').format(sql.Identifier(table))).fetchone()[0] > 0


@pytest.mark.parametrize('statement', ['CREATE TABLE public.audit_forbidden(id integer)', 'CREATE TEMP TABLE audit_forbidden(id integer)'])
def test_reader_cannot_create_tables_or_temp(native_app, statement):
    with reader_connection() as connection:
        with pytest.raises(psycopg.errors.InsufficientPrivilege):
            connection.execute(statement)


def test_reader_has_no_inherited_admin_or_auth_access(native_app):
    with reader_connection() as connection:
        row = connection.execute('SELECT rolsuper,rolcreaterole,rolcreatedb,rolinherit,rolreplication,rolbypassrls FROM pg_roles WHERE rolname=current_user').fetchone()
        assert row == (False,False,False,False,False,False)
        assert connection.execute('SELECT count(*) FROM pg_auth_members WHERE member=(SELECT oid FROM pg_roles WHERE rolname=current_user)').fetchone()[0] == 0
        with pytest.raises(psycopg.errors.InsufficientPrivilege):
            connection.execute('SELECT * FROM auth_sessions')


@pytest.mark.parametrize('endpoint', ['debts','balances','rent-accruals','payments','payments?source=debt_payments'])
def test_hermes_financial_routes_use_real_select_role_without_writes(native_app, endpoint):
    from fleetai import db
    from fleetai.finance_readonly import read_engine, readonly_connection
    headers = hermes_headers()
    client = native_app.test_client()
    before = ledger_snapshot()
    statements = []
    def record(conn, cursor, statement, parameters, context, many):
        statements.append(statement.split()[0].upper())
    with native_app.app_context():
        engine = read_engine()
        from sqlalchemy.pool import QueuePool
        assert isinstance(engine.pool, QueuePool)
        event.listen(engine,'before_cursor_execute',record)
        try:
            for method in ('GET','HEAD','OPTIONS'):
                response = client.open('/api/integrations/hermes/v1/'+endpoint,method=method,
                    base_url='https://localhost',headers=headers)
                assert response.status_code == 200
                if method == 'GET':
                    assert response.json['data']
            with readonly_connection() as connection:
                assert connection.exec_driver_sql('SELECT current_user').scalar_one() == CONFIG['reader']
                assert connection.exec_driver_sql('SHOW transaction_read_only').scalar_one() == 'on'
        finally:
            event.remove(engine,'before_cursor_execute',record)
    assert statements and set(statements) <= {'SELECT','SET','SHOW'}
    assert ledger_snapshot() == before


def test_hermes_scope_deployed_failclosed_and_no_legacy(native_app, monkeypatch):
    headers = hermes_headers()
    client = native_app.test_client()
    prefix = '/api/integrations/hermes/v1/'
    assert client.get(prefix+'debts',base_url='https://localhost').status_code == 401
    owner, _ = owner_client(native_app)
    assert owner.get(prefix+'debts',base_url='https://localhost').status_code == 403
    assert client.get('/api/driver-mvp/700',base_url='https://localhost',headers=headers).status_code == 403


def test_hermes_post_rejected_without_handler_or_database_changes(native_app, monkeypatch):
    headers = hermes_headers()
    path = '/api/integrations/hermes/v1/debts'
    # Instrument the real registered handler, not a guessed module function.
    rule = next(rule for rule in native_app.url_map.iter_rules() if rule.rule == path)
    reached = []
    def forbidden_handler(*args, **kwargs):
        reached.append(True)
        raise AssertionError('Rejected method must not invoke the finance handler')
    monkeypatch.setitem(native_app.view_functions, rule.endpoint, forbidden_handler)
    before = ledger_snapshot()
    response = native_app.test_client().post(path, base_url='https://localhost', headers=headers, json={})
    assert response.status_code in (403, 405)
    assert reached == []
    assert ledger_snapshot() == before


def test_missing_readonly_datasource_independently_fails_closed(native_app, monkeypatch):
    headers = hermes_headers()
    before = ledger_snapshot()
    monkeypatch.delitem(native_app.config, 'FINANCE_READONLY_DATABASE_URL', raising=False)
    monkeypatch.delenv('FINANCE_READONLY_DATABASE_URL', raising=False)
    response = native_app.test_client().get('/api/integrations/hermes/v1/debts',
        base_url='https://localhost', headers=headers)
    assert response.status_code == 503
    assert ledger_snapshot() == before


def test_readonly_transaction_error_rollback_and_pool_reuse(native_app):
    from fleetai.finance_readonly import read_engine, readonly_connection
    from sqlalchemy.exc import DBAPIError
    from psycopg.pq import TransactionStatus
    with native_app.app_context():
        engine = read_engine()
        with readonly_connection() as connection:
            pid = connection.exec_driver_sql('SELECT pg_backend_pid()').scalar_one()
            raw = connection.connection.driver_connection
            with pytest.raises(DBAPIError):
                connection.exec_driver_sql('DELETE FROM cars WHERE false')
        assert raw.info.transaction_status == TransactionStatus.IDLE
        with readonly_connection() as connection:
            assert connection.exec_driver_sql('SELECT pg_backend_pid()').scalar_one() == pid
            assert connection.exec_driver_sql('SHOW transaction_read_only').scalar_one() == 'on'
        with engine.connect() as connection:
            assert connection.exec_driver_sql('SHOW transaction_read_only').scalar_one() == 'off'
            assert connection.exec_driver_sql('SELECT current_user').scalar_one() == CONFIG['reader']


@pytest.mark.parametrize('driver_name', ['Synthetic Replacement','Synthetic Driver'])
def test_revocation_wins_real_postgres_lock_wait(native_app, monkeypatch, driver_name):
    from fleetai import auth
    reader, reader_headers = driver_client(native_app)
    owner, owner_headers = owner_client(native_app)
    writer_locked, reader_attempting, release_writer = Event(), Event(), Event()
    state = {}
    real_lock = auth.lock_driver_assignment
    def lock(session, code):
        if current_thread().name.startswith('pg-writer'):
            result = real_lock(session, code)
            if 'writer_pid' not in state:
                state['writer_pid'] = session.execute(text('SELECT pg_backend_pid()')).scalar_one()
                writer_locked.set()
                assert release_writer.wait(20)
            return result
        if current_thread().name.startswith('pg-reader'):
            state['reader_pid'] = session.execute(text('SELECT pg_backend_pid()')).scalar_one()
            reader_attempting.set()
        return real_lock(session, code)
    monkeypatch.setattr(auth,'lock_driver_assignment',lock)
    with ThreadPoolExecutor(1,thread_name_prefix='pg-writer') as writers, ThreadPoolExecutor(1,thread_name_prefix='pg-reader') as readers:
        write = writers.submit(owner.post,'/api/driver-assignment',base_url='https://localhost',headers=owner_headers,
            json={'car_code':'700','driver':driver_name,'daily_rent':100,'opening_balance':500})
        try:
            assert writer_locked.wait(15)
            read = readers.submit(reader.get,'/api/driver-mvp/700',base_url='https://localhost',headers=reader_headers)
            assert reader_attempting.wait(15)
            wait_for_real_lock(state['reader_pid'],state['writer_pid'])
        finally:
            release_writer.set()
        assert write.result(timeout=20).status_code == 200
        response = read.result(timeout=20)
        assert response.status_code == 401
        assert 'transactions' not in response.json
    assert reader.get('/auth/session',base_url='https://localhost').status_code == 401


def test_session_expiry_during_real_postgres_lock_wait(native_app, monkeypatch):
    from fleetai import auth, db
    reader, headers = driver_client(native_app)
    locked, attempted, release = Event(), Event(), Event()
    state = {}
    real = auth.lock_driver_assignment
    def held():
        with db.Session() as session:
            real(session,'700')
            state['holder'] = session.execute(text('SELECT pg_backend_pid()')).scalar_one()
            locked.set()
            assert release.wait(20)
            session.rollback()
    def lock(session, code):
        if current_thread().name.startswith('expiry-reader'):
            state['reader'] = session.execute(text('SELECT pg_backend_pid()')).scalar_one()
            attempted.set()
        return real(session,code)
    monkeypatch.setattr(auth,'lock_driver_assignment',lock)
    with ThreadPoolExecutor(1) as holders, ThreadPoolExecutor(1,thread_name_prefix='expiry-reader') as readers:
        holder = holders.submit(held)
        try:
            assert locked.wait(15)
            result = readers.submit(reader.get,'/api/driver-mvp/700',base_url='https://localhost',headers=headers)
            assert attempted.wait(15)
            wait_for_real_lock(state['reader'],state['holder'])
            with admin() as connection:
                connection.execute("UPDATE auth_sessions SET expires_at=0 WHERE kind='driver'")
        finally:
            release.set()
        holder.result(timeout=20)
        assert result.result(timeout=20).status_code == 401


@pytest.mark.parametrize('suffix', ['', '/blocking-preview'])
def test_snapshot_wins_and_writer_really_blocks_until_json(native_app, monkeypatch, suffix):
    from fleetai import auth, db, routes
    monkeypatch.setenv('DRIVER_MVP_CAR','700')
    reader, reader_headers = driver_client(native_app)
    owner, owner_headers = owner_client(native_app)
    ready, attempting, release = Event(), Event(), Event()
    state = {'serialized':False,'commits':0,'syncs':0}
    real_lock, real_sync, real_jsonify = auth.lock_driver_assignment, routes._sync_daily_rent, routes.jsonify
    def is_reader():
        return current_thread().name.startswith('snapshot-reader')
    def lock(session,code):
        if current_thread().name.startswith('snapshot-writer'):
            state['writer_pid'] = session.execute(text('SELECT pg_backend_pid()')).scalar_one()
            attempting.set()
        return real_lock(session,code)
    def sync(session,car,**kwargs):
        if is_reader():
            assert kwargs.get('commit') is False
            state['syncs'] += 1
            if not ready.is_set():
                state['reader_pid'] = session.execute(text('SELECT pg_backend_pid()')).scalar_one()
                ready.set()
                assert release.wait(20)
        return real_sync(session,car,**kwargs)
    def jsonify(*args,**kwargs):
        response = real_jsonify(*args,**kwargs)
        if is_reader(): state['serialized'] = True
        return response
    def after_commit(session):
        if is_reader():
            assert state['serialized'], 'No commit before financial JSON materialization'
            state['commits'] += 1
    monkeypatch.setattr(auth,'lock_driver_assignment',lock)
    monkeypatch.setattr(routes,'_sync_daily_rent',sync)
    monkeypatch.setattr(routes,'jsonify',jsonify)
    event.listen(db.Session.class_,'after_commit',after_commit)
    try:
        with ThreadPoolExecutor(1,thread_name_prefix='snapshot-reader') as readers, ThreadPoolExecutor(1,thread_name_prefix='snapshot-writer') as writers:
            read = readers.submit(reader.get,'/api/driver-mvp/700'+suffix,base_url='https://localhost',headers=reader_headers)
            try:
                assert ready.wait(15)
                write = writers.submit(owner.post,'/api/driver-assignment',base_url='https://localhost',headers=owner_headers,
                    json={'car_code':'700','driver':'Synthetic Replacement','daily_rent':100,'opening_balance':-777})
                assert attempting.wait(15)
                wait_for_real_lock(state['writer_pid'],state['reader_pid'])
            finally:
                release.set()
            response = read.result(timeout=20)
            assert response.status_code == 200
            if not suffix: assert response.json['car']['driver'] == 'Synthetic Driver'
            else: assert response.json['unpaid_debt'] == 0
            assert write.result(timeout=20).status_code == 200
    finally:
        event.remove(db.Session.class_,'after_commit',after_commit)
    assert state['commits'] == 1
    assert state['syncs'] == (1 if suffix else 2)
    assert reader.get('/auth/session',base_url='https://localhost').status_code == 401


@pytest.mark.parametrize('suffix', ['', '/blocking-preview'])
def test_snapshot_exception_rolls_back_and_connection_recovers(native_app, monkeypatch, suffix):
    from flask import g
    from fleetai import routes
    monkeypatch.setenv('DRIVER_MVP_CAR','700')
    client, headers = driver_client(native_app)
    before = ledger_snapshot()
    real = routes.jsonify
    reached = []
    def fail(*args,**kwargs):
        if getattr(g,'principal',None) and g.principal.kind=='driver':
            reached.append(True)
            raise RuntimeError('Synthetic serialization fault')
        return real(*args,**kwargs)
    with monkeypatch.context() as patch:
        patch.setattr(routes,'jsonify',fail)
        assert client.get('/api/driver-mvp/700'+suffix,base_url='https://localhost',headers=headers).status_code == 500
    assert reached == [True]
    assert ledger_snapshot() == before
    assert client.get('/api/driver-mvp/700'+suffix,base_url='https://localhost',headers=headers).status_code == 200
    with admin() as connection:
        assert connection.execute("SELECT count(*) FROM pg_stat_activity WHERE application_name LIKE 'fleetai-native-%' AND state='idle in transaction'").fetchone()[0] == 0


def test_raw_sql_aba_triggers_revoke_and_rollback(native_app):
    from fleetai import db
    client, _ = driver_client(native_app)
    with db.Session() as session:
        session.execute(text("UPDATE cars SET driver='Synthetic Replacement' WHERE code='700'"))
        session.rollback()
    assert client.get('/auth/session',base_url='https://localhost').status_code == 200
    with db.Session() as session:
        session.execute(text("UPDATE cars SET driver='Synthetic Replacement' WHERE code='700'"))
        session.execute(text("UPDATE cars SET driver='Synthetic Driver' WHERE code='700'"))
        session.commit()
    assert client.get('/auth/session',base_url='https://localhost').status_code == 401
    with admin() as connection:
        assert connection.execute("SELECT epoch FROM auth_driver_epochs WHERE car_code='700'").fetchone()[0] == 2


@pytest.mark.parametrize('drivers', [('Synthetic Driver','Synthetic Driver'),('Synthetic B','Synthetic C')])
def test_competing_assignment_routes_preserve_single_reset(native_app, monkeypatch, drivers):
    from threading import Barrier
    from fleetai import auth
    owner, headers = owner_client(native_app)
    gate = Barrier(2)
    seen = set()
    real = auth.lock_driver_assignment
    def lock(session,code):
        if current_thread().name.startswith('competing') and id(session) not in seen:
            seen.add(id(session))
            gate.wait(timeout=15)
        return real(session,code)
    monkeypatch.setattr(auth,'lock_driver_assignment',lock)
    with ThreadPoolExecutor(2,thread_name_prefix='competing') as pool:
        replies = list(pool.map(lambda name:owner.post('/api/driver-assignment',base_url='https://localhost',headers=headers,
            json={'car_code':'700','driver':name,'daily_rent':100,'opening_balance':200}),drivers))
    assert [r.status_code for r in replies] == [200,200]
    with admin() as connection:
        assert connection.execute("SELECT sum(amount) FROM driver_wallet_transactions WHERE car_code='700'").fetchone()[0] == 200


def test_concurrent_ticket_consumption_single_winner(native_app):
    from fleetai import auth, db
    from fleetai.models import Car
    from threading import Barrier
    with db.Session() as session:
        ticket = auth.issue_driver_login(session,session.query(Car).filter_by(code='700').one(),'12345')
        session.commit()
    gate = Barrier(2)
    def consume(_):
        gate.wait(timeout=15)
        return native_app.test_client().post('/auth/driver/consume',base_url='https://localhost',
            headers={'Origin':'https://localhost'},json={'ticket':ticket}).status_code
    with ThreadPoolExecutor(2) as pool:
        assert sorted(pool.map(consume,range(2))) == [303,401]


def test_ticket_cas_failure_rolls_back_and_is_reusable(native_app, monkeypatch):
    from fleetai import auth, db
    from fleetai.models import Car
    with db.Session() as session:
        ticket = auth.issue_driver_login(session,session.query(Car).filter_by(code='700').one(),'12345')
        session.commit()
    real = auth._new_session
    reached = []
    def fail(*args,**kwargs):
        real(*args,**kwargs)
        reached.append(True)
        raise RuntimeError('Synthetic post-CAS session fault')
    with monkeypatch.context() as patch:
        patch.setattr(auth,'_new_session',fail)
        assert native_app.test_client().post('/auth/driver/consume',base_url='https://localhost',
            headers={'Origin':'https://localhost'},json={'ticket':ticket}).status_code == 500
    assert reached == [True]
    with admin() as connection:
        assert connection.execute('SELECT consumed_at FROM auth_driver_tickets').fetchone()[0] is None
        assert connection.execute('SELECT count(*) FROM auth_sessions').fetchone()[0] == 0
    assert native_app.test_client().post('/auth/driver/consume',base_url='https://localhost',
        headers={'Origin':'https://localhost'},json={'ticket':ticket}).status_code == 303


def test_enrollment_cas_failure_preserves_old_binding_and_session(native_app, monkeypatch):
    from fleetai import auth, db, driver_binding
    old, _ = driver_client(native_app)
    with db.Session() as session:
        session.execute(text("INSERT INTO driver_telegram_links(id,car_code,driver_name,link_token,created_at,expires_at) VALUES (1,'701','Synthetic Other','synthetic-native-enrollment',:now,:later)"),
            {'now':datetime(2026,11,6),'later':datetime(2099,1,1)})
        session.commit()
    real = auth.revoke_driver_access
    reached = []
    def fail(*args,**kwargs):
        real(*args,**kwargs)
        reached.append(True)
        raise RuntimeError('Synthetic post-CAS binding fault')
    with monkeypatch.context() as patch:
        patch.setattr(auth,'revoke_driver_access',fail)
        with db.Session() as session:
            with pytest.raises(RuntimeError):
                driver_binding.redeem_binding_link(session,'synthetic-native-enrollment','12345')
            session.rollback()
    assert reached == [True]
    with admin() as connection:
        assert connection.execute('SELECT used_at FROM driver_telegram_links WHERE id=1').fetchone()[0] is None
        assert connection.execute("SELECT car_code FROM driver_telegram_bindings WHERE telegram_chat_id='12345'").fetchone()[0] == '700'
    assert old.get('/auth/session',base_url='https://localhost').status_code == 200
    with db.Session() as session:
        car,error = driver_binding.redeem_binding_link(session,'synthetic-native-enrollment','12345')
        assert car.code=='701' and error is None
        session.commit()
    assert old.get('/auth/session',base_url='https://localhost').status_code == 401


def test_native_unique_trim_index_rejects_existing_car_alias(native_app):
    with admin() as connection:
        with pytest.raises(psycopg.errors.UniqueViolation) as caught:
            connection.execute("INSERT INTO cars(code,driver) VALUES (' 700 ','Synthetic Alias')")
        assert caught.value.sqlstate == '23505'
        connection.rollback()
        assert connection.execute("SELECT count(*) FROM cars WHERE trim(code)='700'").fetchone()[0] == 1


def test_native_competing_trim_alias_inserts_have_single_winner(native_app):
    from threading import Barrier
    from fleetai import db
    from fleetai.models import Car
    from sqlalchemy.exc import IntegrityError
    gate = Barrier(2)
    def insert(code):
        with db.Session() as session:
            session.add(Car(code=code, driver='Synthetic Concurrent Alias'))
            gate.wait(timeout=15)
            try:
                session.commit()
            except IntegrityError as error:
                assert error.orig.sqlstate == '23505'
                session.rollback()
                return False
            return True
    with ThreadPoolExecutor(2) as pool:
        assert sorted(pool.map(insert, [' 702','702 '])) == [False,True]
