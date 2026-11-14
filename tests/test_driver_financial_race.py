"""Driver financial reads must serialize with assignment revocation."""
from concurrent.futures import ThreadPoolExecutor
from threading import Event, current_thread

import pytest
from flask import g
from sqlalchemy import event, text

from test_security_integration import seed_driver_binding, driver_client, owner_client


def route_endpoint(app, name):
    return next(rule.endpoint for rule in app.url_map.iter_rules()
                if rule.endpoint.rsplit('.', 1)[-1] == name)


@pytest.mark.parametrize('endpoint,suffix', [('api_driver_mvp',''), ('api_driver_blocking_preview','/blocking-preview')])
@pytest.mark.parametrize('change', ['replacement', 'same_name', 'raw_sql_aba', 'expired', 'binding_removed'])
def test_admitted_driver_request_revalidates_under_assignment_lock(secure_app, monkeypatch, endpoint, suffix, change):
    """Revoke after the real before_request, before the real financial handler."""
    from fleetai import db
    from fleetai.auth_models import AuthSession
    monkeypatch.setenv('DRIVER_MVP_CAR', '700')
    seed_driver_binding()
    old_driver, driver_headers = driver_client(secure_app)
    owner, owner_headers = owner_client(secure_app)
    original = secure_app.view_functions[route_endpoint(secure_app, endpoint)]
    observations = []

    def alter_assignment(session_hash):
        if change in {'replacement', 'same_name'}:
            response = owner.post('/api/driver-assignment', base_url='https://localhost', headers=owner_headers,
                json={'car_code':'700', 'driver':'Synthetic Replacement' if change=='replacement' else 'Synthetic Driver',
                      'daily_rent':100, 'opening_balance':500})
            assert response.status_code == 200
        else:
            with db.Session() as session:
                if change == 'raw_sql_aba':
                    session.execute(text("UPDATE cars SET driver='Synthetic Other' WHERE code='700'"))
                    session.execute(text("UPDATE cars SET driver='Synthetic Driver' WHERE code='700'"))
                elif change == 'expired':
                    session.get(AuthSession, session_hash).expires_at = 0
                else:
                    session.execute(text("DELETE FROM driver_telegram_bindings WHERE car_code='700'"))
                session.commit()

    def interleaved_handler(**kwargs):
        assert g.principal.kind == 'driver'
        session_hash = g.principal.session_hash
        with ThreadPoolExecutor(max_workers=1) as pool:
            pool.submit(alter_assignment, session_hash).result(timeout=30)
        result = original(**kwargs)
        observations.append(True)
        return result

    monkeypatch.setitem(secure_app.view_functions, route_endpoint(secure_app, endpoint), interleaved_handler)
    response = old_driver.get('/api/driver-mvp/700'+suffix, base_url='https://localhost', headers=driver_headers)
    assert observations == [True], 'The admitted request must reach the real handler'
    assert response.status_code in (401, 403), 'A stale session must not receive financial data after assignment/session invalidation'
    body = response.get_json() or {}
    assert not {'car', 'balance', 'transactions', 'unpaid_debt'}.intersection(body), 'No partial financial snapshot on denial'


def test_driver_snapshot_holds_lock_through_both_rent_syncs_and_serialization(secure_app, monkeypatch):
    """The reverse ordering: writer must wait until the old snapshot is complete."""
    from fleetai import auth, db, routes
    seed_driver_binding()
    old_driver, driver_headers = driver_client(secure_app)
    owner, owner_headers = owner_client(secure_app)
    writer_attempting = Event()
    phases = []
    future = None
    real_lock = auth.lock_driver_assignment
    real_sync = routes._sync_daily_rent
    real_jsonify = routes.jsonify

    def in_writer():
        return current_thread().name.startswith('snapshot-writer')

    def lock(session, code):
        if in_writer():
            writer_attempting.set()
        return real_lock(session, code)

    def on_commit(session):
        if not in_writer():
            assert 'serialized' in phases, 'Driver transaction must not commit before the complete JSON snapshot'
            phases.append('committed')

    def jsonify(*args, **kwargs):
        response = real_jsonify(*args, **kwargs)
        if not in_writer():
            phases.append('serialized')
        return response

    with ThreadPoolExecutor(max_workers=1, thread_name_prefix='snapshot-writer') as pool:
        def sync(session, car, **kwargs):
            nonlocal future
            if in_writer():
                return real_sync(session, car, **kwargs)
            assert kwargs.get('commit') is False, 'Both snapshot syncs must retain the assignment transaction'
            phases.append('sync-start')
            if future is None:
                future = pool.submit(owner.post, '/api/driver-assignment', base_url='https://localhost', headers=owner_headers,
                    json={'car_code':'700','driver':'Synthetic Replacement','daily_rent':100,'opening_balance':500})
                assert writer_attempting.wait(15), 'Concurrent assignment must reach the shared lock'
            result = real_sync(session, car, **kwargs)
            assert not future.done(), 'Assignment must not finish while the snapshot holds its lock'
            phases.append('sync-end')
            return result

        monkeypatch.setattr(auth, 'lock_driver_assignment', lock)
        monkeypatch.setattr(routes, '_sync_daily_rent', sync)
        monkeypatch.setattr(routes, 'jsonify', jsonify)
        event.listen(db.Session.class_, 'after_commit', on_commit)
        try:
            response = old_driver.get('/api/driver-mvp/700', base_url='https://localhost', headers=driver_headers)
        finally:
            event.remove(db.Session.class_, 'after_commit', on_commit)
        assert response.status_code == 200
        assert response.json['car']['driver'] == 'Synthetic Driver'
        assert phases == ['sync-start','sync-end','sync-start','sync-end','serialized','committed']
        assert future.result(timeout=30).status_code == 200
    assert old_driver.get('/auth/session', base_url='https://localhost').status_code == 401
