"""FleetAI 4.0 dashboard: owner-only, read-only, real data mapping."""
import re

import pytest
from sqlalchemy import create_engine, text
from werkzeug.security import generate_password_hash

PASSWORD = 'Synthetic dashboard password 2026!'
BASE = 'https://localhost'


@pytest.fixture
def dash(tmp_path):
    url = 'sqlite:///' + str(tmp_path / 'dash.sqlite')
    eng = create_engine(url)
    with eng.begin() as c:
        c.execute(text("""CREATE TABLE cars (id INTEGER PRIMARY KEY, code TEXT, brand TEXT, model TEXT, plate TEXT,
            year INTEGER, status TEXT, driver TEXT, owner_type TEXT, investor_name TEXT, investor_percent INTEGER,
            weekly_payment INTEGER, daily_rent INTEGER, driver_deposit INTEGER, current_mileage INTEGER)"""))
        c.execute(text("CREATE TABLE auth_owners (id INTEGER PRIMARY KEY, username TEXT, password_hash TEXT)"))
        rows = [
            ('621', 'hyundai', 'solaris', 'т621су716', None, 'Работает', 'Сергей В.', 'investor', 'илья', 75, 0, 1857, 10000, 120000),
            ('686', 'Lada', 'Granta', '686', None, 'Работает', 'Тимур', 'own', 'Марк', 70, 11000, 0, 8000, 0),
            ('636', 'hyundai', 'solaris', 'к636те716', None, 'Ремонт', '', 'investor', 'илья', 75, 0, 1857, 0, 0),
            ('119', 'Kia', 'Rio', 'В119ЕН716', 2018, 'Простой', '', 'own', '', 0, 0, 0, 0, 0),
        ]
        for r in rows:
            c.execute(text("""INSERT INTO cars (code, brand, model, plate, year, status, driver, owner_type, investor_name,
                investor_percent, weekly_payment, daily_rent, driver_deposit, current_mileage)
                VALUES (:a,:b,:c,:d,:e,:f,:g,:h,:i,:j,:k,:l,:m,:n)"""), dict(zip('abcdefghijklmn', r)))
        c.execute(text("INSERT INTO auth_owners VALUES (1, 'owner', :h)"),
                  {'h': generate_password_hash(PASSWORD, method='pbkdf2:sha256:1000')})
    calls = []

    def fake_wialon():
        calls.append(1)
        return ([{'id': 50496, 'name': 'Hyundai А621СУ 716', 'lat': 55.79, 'lon': 49.12, 'speed_kmh': 0, 'course': 0, 'time': 1},
                 {'id': 50484, 'name': 'Kia Х167СО716', 'lat': None, 'lon': None, 'speed_kmh': None, 'course': None, 'time': None}], None)

    from dashboard.app import create_app
    app = create_app({'TESTING': True, 'SECRET_KEY': 'x' * 40, 'DATABASE_URL': url,
                      'PUBLIC_URL': BASE, 'WIALON_FETCH': fake_wialon})
    app.calls = calls
    app.engine_url = url
    return app


def login(client, password=PASSWORD):
    form = client.get('/login', base_url=BASE).get_data(as_text=True)
    csrf = re.search(r'name="csrf" value="([^"]+)"', form).group(1)
    return client.post('/login', base_url=BASE, headers={'Origin': BASE},
                       data={'username': 'Owner', 'password': password, 'csrf': csrf})


def test_requires_login(dash):
    c = dash.test_client()
    assert c.get('/', base_url=BASE).status_code == 302
    assert c.get('/api/v4/fleet', base_url=BASE).status_code == 401
    assert c.get('/api/v4/positions', base_url=BASE).status_code == 401
    assert dash.calls == []


def test_wrong_password_and_foreign_origin_rejected(dash):
    c = dash.test_client()
    assert login(c, 'wrong password').status_code == 401
    form = c.get('/login', base_url=BASE).get_data(as_text=True)
    csrf = re.search(r'name="csrf" value="([^"]+)"', form).group(1)
    r = c.post('/login', base_url=BASE, headers={'Origin': 'https://evil.invalid'},
               data={'username': 'owner', 'password': PASSWORD, 'csrf': csrf})
    assert r.status_code == 403
    assert c.get('/api/v4/fleet', base_url=BASE).status_code == 401


def test_login_rate_limited(dash):
    c = dash.test_client()
    for _ in range(5):
        assert login(c, 'wrong password').status_code == 401
    assert login(c).status_code == 429


def test_owner_sees_real_fleet(dash):
    c = dash.test_client()
    assert login(c).status_code == 303
    page = c.get('/', base_url=BASE)
    assert page.status_code == 200 and b'/api/v4/fleet' in page.data
    data = c.get('/api/v4/fleet', base_url=BASE).get_json()
    cars = {x['code']: x for x in data['cars']}
    assert set(cars) == {'267', '621', '636', '686'}   # 119 hidden (now 665); 267 not in DB yet
    assert cars['267']['status'] == 'nodata' and cars['267']['in_db'] is False and cars['267']['plate'] == 'Х267СО716'
    assert cars['621']['status'] == 'rented' and cars['621']['owner'] == 'ilya'
    assert cars['621']['rate'] == '1 857 ₽/сут' and cars['621']['deposit'] == 1_000_000
    assert cars['636']['status'] == 'repair'
    assert cars['686']['owner'] == 'mark' and 'исправить тип' in cars['686']['flag']
    assert all(x['balance'] is None for x in data['cars'])   # wallet not connected: no invented numbers
    assert sorted(d['name'] for d in data['drivers']) == ['Сергей В.', 'Тимур']


def test_positions_matched_to_cars(dash):
    c = dash.test_client()
    login(c)
    data = c.get('/api/v4/positions', base_url=BASE).get_json()
    units = {u['id']: u for u in data['units']}
    assert units[50496]['car_code'] == '621'
    assert units[50484]['car_code'] == '267'   # Wialon typo Х167СО716 -> 267


def test_dashboard_never_writes(dash):
    before = create_engine(dash.engine_url).connect().execute(text('SELECT count(*) FROM cars')).scalar()
    c = dash.test_client()
    login(c)
    for path in ('/', '/api/v4/fleet', '/api/v4/positions'):
        c.get(path, base_url=BASE)
    after = create_engine(dash.engine_url).connect().execute(text('SELECT count(*) FROM cars')).scalar()
    assert before == after
    import dashboard.data as d
    import inspect
    source = inspect.getsource(d).upper()
    assert not re.search(r'\b(INSERT|UPDATE|DELETE|ALTER|DROP|CREATE)\b', source.replace('CREATE_ENGINE', ''))


def test_wialon_client_refuses_commands():
    from dashboard import wialon
    with pytest.raises(ValueError):
        wialon._call('unit/exec_cmd', {})


def test_logout_needs_csrf(dash):
    c = dash.test_client()
    login(c)
    assert c.post('/logout', base_url=BASE, headers={'Origin': BASE}).status_code == 403
    csrf = c.get('/api/v4/fleet', base_url=BASE).get_json()['csrf']
    assert c.post('/logout', base_url=BASE, headers={'Origin': BASE, 'X-CSRF': csrf}).status_code == 200
    assert c.get('/api/v4/fleet', base_url=BASE).status_code == 401


def test_security_headers(dash):
    r = dash.test_client().get('/login', base_url=BASE)
    assert "frame-ancestors 'none'" in r.headers['Content-Security-Policy']
    assert r.headers['X-Frame-Options'] == 'DENY'


def test_dashboard_page_script_parses(tmp_path):
    """A syntax error in the single-page script leaves the dashboard blank."""
    import shutil
    import subprocess
    from pathlib import Path
    node = shutil.which('node')
    if not node:
        pytest.skip('node is not installed')
    html = (Path(__file__).resolve().parents[1] / 'dashboard' / 'static' / 'index.html').read_text(encoding='utf-8')
    script = '\n'.join(re.findall(r'<script>(.*?)</script>', html, re.S))
    assert script.strip()
    js = tmp_path / 'page.js'
    js.write_text(script, encoding='utf-8')
    result = subprocess.run([node, '--check', str(js)], capture_output=True, text=True)
    assert result.returncode == 0, result.stderr[-2000:]


def test_267_in_database_is_personal_use(dash):
    eng = create_engine(dash.engine_url)
    with eng.begin() as c:
        c.execute(text("""INSERT INTO cars (code, brand, model, plate, status, driver, owner_type, investor_name,
            investor_percent, weekly_payment, daily_rent, driver_deposit, current_mileage)
            VALUES ('267','Kia','Rio','Х267СО716','Работает','','own','',0,0,0,0,0)"""))
    c = dash.test_client()
    login(c)
    cars = {x['code']: x for x in c.get('/api/v4/fleet', base_url=BASE).get_json()['cars']}
    assert cars['267']['status'] == 'personal' and cars['267'].get('in_db', True) is True
    assert cars['267']['plates'] == ['С665ХК716', 'Х267СО716']


@pytest.fixture
def fin_dash(tmp_path):
    from datetime import datetime
    from fleetai.models import Base
    url = 'sqlite:///' + str(tmp_path / 'fin.sqlite')
    eng = create_engine(url)
    Base.metadata.create_all(eng)
    with eng.begin() as c:
        c.execute(text("CREATE TABLE IF NOT EXISTS auth_owners (id INTEGER PRIMARY KEY, username TEXT, password_hash TEXT)"))
        c.execute(text("INSERT INTO auth_owners VALUES (1, 'owner', :h)"),
                  {'h': generate_password_hash(PASSWORD, method='pbkdf2:sha256:1000')})
        c.execute(text("""INSERT INTO cars (id, code, brand, model, plate, status, driver, owner_type, investor_name,
            investor_percent, settlement_day) VALUES
            (1,'621','Hyundai','Solaris','Т621СУ716','Работает','Сергей','investor','илья',75,15),
            (2,'897','Kia','Rio','К897УР716','Работает','Иван','own','',0,15)"""))
        now = datetime.now()
        c.execute(text("INSERT INTO operations (id, date, car_code, type, category, description, amount) VALUES "
                       "(1, :d, '621', 'income', 'Аренда', 'оплата', 13000), (2, :d, '621', 'repair', 'Ремонт', 'колодки', 2000)"),
                  {'d': now})
        c.execute(text("INSERT INTO income (operation_id, car_code, date, amount, income_type) VALUES (1, '621', :d, 13000, 'rent')"), {'d': now})
        c.execute(text("INSERT INTO expenses (operation_id, car_code, date, category, amount, share_type) VALUES (2, '621', :d, 'Ремонт', 2000, 'shared')"), {'d': now})
    from dashboard.app import create_app
    app = create_app({'TESTING': True, 'SECRET_KEY': 'x' * 40, 'DATABASE_URL': url, 'PUBLIC_URL': BASE,
                      'WIALON_FETCH': lambda: ([], None)})
    app.engine_url = url
    return app


def test_finance_matches_old_fleetai_calculation(fin_dash):
    from sqlalchemy.orm import Session
    from fleetai.finance import calculate_period_for_car, period_bounds_for_car
    from fleetai.models import Car
    c = fin_dash.test_client()
    assert c.get('/api/v4/finance', base_url=BASE).status_code == 401
    login(c)
    data = c.get('/api/v4/finance', base_url=BASE).get_json()
    row = {x['code']: x for x in data['cars']}['621']
    with Session(create_engine(fin_dash.engine_url)) as s:
        car = s.query(Car).filter_by(code='621').one()
        calc = calculate_period_for_car(s, car, *period_bounds_for_car(car))
    assert row['income'] == calc['income'] * 100 == 1_300_000
    assert row['expenses'] == calc['expenses'] * 100 == 200_000
    assert row['investor_amount'] == calc['investor_amount'] * 100
    assert row['period_share'] == 825_000 and row['period_due'] == 825_000   # (13000-2000)*75%, this period only
    assert row['gps'] == 50_000 and row['garage'] in (150_000,) and row['recurring_booked'] is False


def test_journal_and_repairs(fin_dash):
    c = fin_dash.test_client()
    login(c)
    ops = c.get('/api/v4/journal?days=30', base_url=BASE).get_json()['operations']
    assert [(o['label'], o['dir'], o['amount']) for o in ops][:2] in (
        [('Доход', 'in', 1_300_000), ('Ремонт', 'out', 200_000)], [('Ремонт', 'out', 200_000), ('Доход', 'in', 1_300_000)])
    rep = c.get('/api/v4/repairs', base_url=BASE).get_json()
    assert rep['expenses'][0]['amount'] == 200_000 and rep['expenses'][0]['description'] == 'колодки'


def test_finance_module_has_no_write_sql():
    import inspect
    import dashboard.finance as f
    import dashboard.rent as r
    src = (inspect.getsource(f) + inspect.getsource(r)).upper()
    assert not re.search(r'\b(INSERT|UPDATE|DELETE|ALTER|DROP|CREATE TABLE|COMMIT)\b', src)


def test_rent_uses_old_fleetai_calculation(fin_dash):
    from datetime import datetime
    eng = create_engine(fin_dash.engine_url)
    with eng.begin() as c:
        # SQLite lower() is ASCII-only (PostgreSQL is not), so the test driver name is Latin.
        c.execute(text("UPDATE cars SET daily_rent = 1857, driver_deposit = 10000, driver = 'Sergey' WHERE code = '621'"))
        c.execute(text("INSERT INTO driver_wallet_transactions (driver_name, car_code, amount, transaction_type, source, date) "
                       "VALUES ('Sergey', '621', 5000, 'topup', 'manual', :d)"), {'d': datetime.now()})
        c.execute(text("INSERT INTO driver_debts (driver_name, car_code, original_amount, paid_amount, balance, status, reason, created_at) "
                       "VALUES ('Sergey', '621', 3000, 0, 3000, 'open', 'штраф', :d)"), {'d': datetime.now()})
    c = fin_dash.test_client()
    assert c.get('/api/v4/rent', base_url=BASE).status_code == 401
    login(c)
    rows = {r['code']: r for r in c.get('/api/v4/rent', base_url=BASE).get_json()['rentals']}
    assert set(rows) == {'621', '897'}
    r = rows['621']
    assert r['wallet'] == 500_000 and r['deposit'] == 1_000_000 and r['debt_total'] == 300_000
    assert r['daily_rent'] == 185_700 and r['debts'][0]['reason'] == 'штраф'


def test_contracts_hide_personal_data(fin_dash):
    eng = create_engine(fin_dash.engine_url)
    with eng.begin() as c:
        c.execute(text("""CREATE TABLE driver_contracts (id TEXT PRIMARY KEY, public_token TEXT, car_code TEXT, status TEXT,
            driver_name TEXT, passport_number TEXT, phone TEXT, daily_rent INTEGER, deposit INTEGER, rental_start_date TEXT,
            signed_at TIMESTAMP, created_at TIMESTAMP, updated_at TIMESTAMP, pdf_data BLOB)"""))
        c.execute(text("INSERT INTO driver_contracts VALUES ('c1','tok','621','signed','Сергей','123456','+79990000000',1857,10000,'01.11.2026',NULL,'2026-11-01','2026-11-01',NULL)"))
    c = fin_dash.test_client()
    login(c)
    resp = c.get('/api/v4/contracts', base_url=BASE)
    body = resp.get_data(as_text=True)
    assert resp.get_json()['contracts'][0]['driver'] == 'Сергей'
    assert '123456' not in body and '7999' not in body and 'tok' not in body
