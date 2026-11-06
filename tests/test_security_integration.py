"""Full-application security boundaries (no production data/transports)."""
import pytest


@pytest.mark.parametrize('path,method', [
    ('/api/driver-debts', 'GET'),
    ('/api/operations', 'GET'),
    ('/api/cars', 'GET'),
    ('/api/driver-wallet/topup', 'POST'),
    ('/api/driver-debt-payment', 'POST'),
    ('/api/driver-assignment', 'POST'),
])
def test_anonymous_financial_access_denied_before_handler(secure_app, path, method):
    client = secure_app.test_client()
    response = client.open(path, method=method, base_url='https://localhost', json={})
    assert response.status_code == 401


def seed_driver_binding():
    from fleetai.db import Session
    from fleetai.models import Car
    from sqlalchemy import text
    with Session() as session:
        session.add(Car(code='700', driver='Synthetic Driver', daily_rent=100))
        session.add(Car(code='701', driver='Other Synthetic Driver', daily_rent=100))
        session.execute(text('INSERT INTO driver_telegram_bindings (id,car_code,driver_name,telegram_chat_id) VALUES (1,:code,:driver,:chat)'), {'code':'700','driver':'Synthetic Driver','chat':'12345'})
        session.commit()


def test_verified_bound_telegram_can_request_short_lived_login(secure_app, monkeypatch):
    from fleetai import routes
    secure_app.config.update(TELEGRAM_WEBHOOK_SECRET='synthetic-webhook-secret', PUBLIC_BASE_URL='https://localhost')
    seed_driver_binding()
    sent = []
    monkeypatch.setattr(routes, 'send_telegram_to_chat', lambda chat, message: sent.append((chat,message)) or True)
    response = secure_app.test_client().post('/api/telegram/webhook', base_url='https://localhost', headers={'X-Telegram-Bot-Api-Secret-Token':'synthetic-webhook-secret'}, json={'message':{'text':'/login','chat':{'id':12345,'type':'private'},'from':{'id':12345}}})
    assert response.status_code == 200
    assert len(sent) == 1
    assert 'https://localhost/auth/driver#' in sent[0][1]


def owner_client(app):
    runner = app.test_cli_runner()
    result = runner.invoke(args=['auth', 'bootstrap-owner', '--username', 'owner'], input='Synthetic owner password 123!\nSynthetic owner password 123!\n')
    assert result.exit_code == 0
    client = app.test_client()
    response = client.post('/auth/login', base_url='https://localhost', data={'username':'owner','password':'Synthetic owner password 123!'}, headers={'Origin':'https://localhost'})
    assert response.status_code == 303
    state = client.get('/auth/session', base_url='https://localhost').get_json()
    return client, {'X-CSRF-Token':state['csrf_token'], 'Origin':'https://localhost'}


def hermes_headers(app):
    from fleetai import auth, db
    with app.app_context(), db.Session() as session:
        raw, record = auth.issue_hermes_credential(session, 'synthetic integration credential')
        credential_id = record.id
        session.commit()
    return {'Authorization':'Bearer ' + raw}, credential_id


def driver_client(app):
    from fleetai import auth, db
    from fleetai.models import Car
    with app.app_context(), db.Session() as session:
        car = session.query(Car).filter_by(code='700').one()
        ticket = auth.issue_driver_login(session, car, '12345')
        session.commit()
    client = app.test_client()
    response = client.post('/auth/driver/consume', base_url='https://localhost', json={'ticket':ticket}, headers={'Origin':'https://localhost'})
    assert response.status_code == 303
    csrf = client.get('/auth/session', base_url='https://localhost').get_json()['csrf_token']
    return client, {'X-CSRF-Token':csrf,'Origin':'https://localhost'}


def test_owner_ui_csrf_and_actual_financial_write(secure_app):
    from fleetai import db
    from fleetai.models import Operation
    seed_driver_binding()
    client, headers = owner_client(secure_app)
    root = client.get('/', base_url='https://localhost')
    assert root.status_code == 200
    assert root.get_data(as_text=True).index('/auth/client.js') < root.get_data(as_text=True).index('async function')
    assert client.get('/api/driver-debts', base_url='https://localhost').status_code == 200
    payload = {'car_code':'700','amount':120,'payment_method':'cash'}
    assert client.post('/api/driver-wallet/topup', base_url='https://localhost', json=payload).status_code == 403
    with db.Session() as session:
        assert session.query(Operation).count() == 0
    posted = client.post('/api/driver-wallet/topup', base_url='https://localhost', json=payload, headers=headers)
    assert posted.status_code == 200
    assert posted.get_json()['ok'] is True
    with db.Session() as session:
        assert session.query(Operation).filter_by(type='income',amount=120).count() == 1
    assert client.get('/api/cars', base_url='https://localhost').status_code == 403
    assert client.get('/api/cars', base_url='https://localhost', headers=headers).status_code == 200
    cross = dict(headers, Origin='https://attacker.invalid')
    assert client.post('/api/driver-wallet/topup', base_url='https://localhost', json=payload, headers=cross).status_code == 403


def test_hermes_real_credential_only_new_reads_and_no_legacy_fallback(secure_app):
    import sqlite3
    from fleetai import db, auth
    seed_driver_binding()
    owner, _ = owner_client(secure_app)
    headers, credential_id = hermes_headers(secure_app)
    def snapshot():
        with sqlite3.connect(db.engine.url.database) as conn:
            return list(conn.iterdump())
    before = snapshot()
    for endpoint in ['debts','balances','rent-accruals','payments']:
        for method in ['GET','HEAD','OPTIONS']:
            response = owner.open('/api/integrations/hermes/v1/' + endpoint, method=method, base_url='https://localhost', headers=headers)
            assert response.status_code == 200
        assert owner.post('/api/integrations/hermes/v1/' + endpoint, base_url='https://localhost', headers=headers).status_code in (403,405)
    assert snapshot() == before
    for path, method in [('/api/cars','GET'),('/api/operations','GET'),('/api/driver-mvp/700','GET'),('/api/driver-wallet/topup','POST'),('/api/driver-assignment','POST'),('/auth/session','GET')]:
        assert owner.open(path, method=method, base_url='https://localhost', headers=headers, json={}).status_code == 403
    assert owner.get('/api/driver-debts', base_url='https://localhost', headers={'Authorization':'Bearer invalid'}).status_code == 401
    with db.Session() as session:
        assert auth.revoke_hermes_credential(session, credential_id)
        session.commit()
    assert owner.get('/api/integrations/hermes/v1/debts', base_url='https://localhost', headers=headers).status_code == 401


def test_driver_only_assigned_vehicle_and_revoked_after_assignment(secure_app):
    from fleetai import db
    from fleetai.models import Car
    seed_driver_binding()
    client, headers = driver_client(secure_app)
    assert client.get('/driver?code=700', base_url='https://localhost').status_code == 200
    assert client.get('/api/driver-mvp/700', base_url='https://localhost', headers=headers).status_code == 200
    assert client.get('/api/driver-mvp/701', base_url='https://localhost', headers=headers).status_code == 403
    assert client.get('/api/operations', base_url='https://localhost', headers=headers).status_code == 403
    assert client.post('/api/driver-wallet/topup', base_url='https://localhost', headers=headers, json={}).status_code == 403
    assert client.get('/api/integrations/hermes/v1/debts', base_url='https://localhost', headers=headers).status_code == 403
    with db.Session() as session:
        car = session.query(Car).filter_by(code='700').one()
        car.driver = 'New Synthetic Driver'
        session.commit()
    assert client.get('/api/driver-mvp/700', base_url='https://localhost', headers=headers).status_code == 401


def test_same_name_explicit_assignment_also_revokes_sessions_and_binding(secure_app):
    from fleetai import db
    from sqlalchemy import text
    seed_driver_binding()
    driver, driver_headers = driver_client(secure_app)
    owner, owner_headers = owner_client(secure_app)
    response = owner.post('/api/driver-assignment', base_url='https://localhost', headers=owner_headers, json={'car_code':'700','driver':'Synthetic Driver','daily_rent':100,'opening_balance':0})
    assert response.status_code == 200
    assert driver.get('/api/driver-mvp/700', base_url='https://localhost', headers=driver_headers).status_code == 401
    with db.Session() as session:
        assert session.execute(text("SELECT COUNT(*) FROM driver_telegram_bindings WHERE car_code='700'")).scalar_one() == 0


def test_every_nonpublic_api_denies_anonymous_before_side_effects(secure_app):
    import sqlite3
    from fleetai import db
    from fleetai.security_policy import CONTRACT_ENDPOINTS
    public = CONTRACT_ENDPOINTS | {'api_telegram_webhook','tbank_webhook'}
    client = secure_app.test_client()
    def snapshot():
        with sqlite3.connect(db.engine.url.database) as conn:
            return list(conn.iterdump())
    before = snapshot()
    checked = []
    for rule in secure_app.url_map.iter_rules():
        if not rule.rule.startswith('/api/') or rule.endpoint.rsplit('.',1)[-1] in public:
            continue
        values = {name: (1 if converter.__class__.__name__ == 'IntegerConverter' else '700') for name, converter in rule._converters.items()}
        path = rule.build(values)[1]
        for method in sorted(rule.methods - {'HEAD','OPTIONS'}):
            response = client.open(path, method=method, base_url='https://localhost', json={})
            assert response.status_code in (401,403,404), (method,path,response.status_code)
            checked.append((method,path))
    assert len(checked) >= 90
    assert snapshot() == before


def test_legacy_rent_and_period_read_handlers_are_unchanged():
    import ast
    from pathlib import Path
    import subprocess
    root = Path(__file__).resolve().parents[1]
    old = subprocess.run(['git','show','053144753b64e2b30c8cbeb2d102aed76b692da8:fleetai/routes.py'], cwd=root, check=True, capture_output=True, text=True).stdout
    new = (root/'fleetai/routes.py').read_text()
    names = {'_sync_daily_rent','calculate_driver_payment','calculate_rental_interval','api_summary','api_cars','api_cars_monthly_finance','api_car','api_driver_mvp'}
    def functions(text, *, allow_assignment_transaction=False):
        tree = ast.parse(text)
        if allow_assignment_transaction:
            rent = next(node for node in tree.body if isinstance(node, ast.FunctionDef) and node.name == '_sync_daily_rent')
            # Only the optional transaction boundary is permitted to differ.
            assert not rent.args.kwonlyargs
            rent.args.kwonlyargs.append(ast.arg(arg='commit'))
            rent.args.kw_defaults.append(ast.Constant(value=True))
            commits = [node for node in ast.walk(rent) if isinstance(node, ast.Expr)
                       and ast.dump(node.value) == ast.dump(ast.parse('session.commit()').body[0].value)]
            assert len(commits) == 2
            for node in commits:
                node.value = ast.parse('session.commit() if commit else session.flush()').body[0].value
        return {node.name:ast.dump(node, include_attributes=False) for node in tree.body if isinstance(node,ast.FunctionDef) and node.name in names}
    assert functions(old, allow_assignment_transaction=True) == functions(new)
    assert len(functions(old)) == len(names)


def test_factory_uses_only_explicit_test_database(secure_app):
    from fleetai import db
    assert db.engine.dialect.name == 'sqlite'
    assert '.test-data' in str(db.engine.url)
    assert secure_app.config['TESTING'] is True
