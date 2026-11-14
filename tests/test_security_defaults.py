"""Safer operational defaults identified by the independent review."""
import pytest


def test_test_factory_refuses_database_outside_test_root():
    from fleetai import create_app
    with pytest.raises(ValueError, match='isolated|test'):
        create_app({'TESTING':True, 'DATABASE_URL':'sqlite:///fleet.db'})


def test_driver_ticket_url_requires_explicit_public_origin(secure_app, monkeypatch):
    from fleetai import routes
    secure_app.config.pop('PUBLIC_BASE_URL', None)
    monkeypatch.delenv('FLEETAI_PUBLIC_BASE_URL', raising=False)
    monkeypatch.setattr('fleetai.auth.issue_driver_login', lambda *args: pytest.fail('No ticket before validating the public origin'))
    with secure_app.app_context(), pytest.raises(ValueError, match='PUBLIC_BASE_URL'):
        routes.driver_login_url(None, None, '12345')


@pytest.mark.parametrize('path,payload', [('/auth/login', {'username':'owner','password':'synthetic'}),
    ('/auth/driver/consume', {'ticket':'synthetic'})])
def test_preauth_posts_require_origin_or_same_origin_browser_proof(secure_app, path, payload):
    response = secure_app.test_client().post(path, base_url='https://localhost', json=payload,
        environ_overrides={'HTTP_ORIGIN':None, 'HTTP_SEC_FETCH_SITE':None})
    assert response.status_code == 403


def test_ticket_expiry_is_rechecked_after_assignment_lock(secure_app, monkeypatch):
    from types import SimpleNamespace
    from fleetai import auth, db
    from fleetai.models import Car
    from sqlalchemy import text
    with db.Session() as session:
        car = Car(code='LOCK1', driver='Synthetic')
        session.add(car)
        session.execute(text('INSERT INTO driver_telegram_bindings(id,car_code,driver_name,telegram_chat_id) VALUES (1,:car,:driver,:chat)'),
            {'car':'LOCK1','driver':'Synthetic','chat':'12345'})
        session.commit()
        ticket = auth.issue_driver_login(session, car, '12345')
        session.commit()
    now = auth.time.time()
    values = iter([now, now + 400])
    monkeypatch.setattr(auth, 'time', SimpleNamespace(time=lambda: next(values, now + 400)))
    response = secure_app.test_client().post('/auth/driver/consume', base_url='https://localhost', json={'ticket':ticket})
    assert response.status_code == 401
