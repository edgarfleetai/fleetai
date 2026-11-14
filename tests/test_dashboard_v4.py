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
