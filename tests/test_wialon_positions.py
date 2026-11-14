"""Read-only Wialon positions: owner-only, no DB writes, no vehicle commands."""
import re

PASSWORD = 'Synthetic owner password 123!'


def owner_client(app):
    """Owner login through the current form flow (GET issues the login proof)."""
    result = app.test_cli_runner().invoke(args=['auth', 'bootstrap-owner', '--username', 'owner'],
                                          input=PASSWORD + '\n' + PASSWORD + '\n')
    assert result.exit_code == 0
    client = app.test_client()
    form = client.get('/auth/login', base_url='https://localhost').get_data(as_text=True)
    proof = re.search(r'name="login_proof" value="([^"]+)"', form).group(1)
    response = client.post('/auth/login', base_url='https://localhost',
                           data={'username': 'owner', 'password': PASSWORD, 'login_proof': proof},
                           headers={'Origin': 'https://localhost'})
    assert response.status_code == 303, response.get_data(as_text=True)
    state = client.get('/auth/session', base_url='https://localhost').get_json()
    return client, {'X-CSRF-Token': state['csrf_token'], 'Origin': 'https://localhost'}

ITEMS = [
    {'id': 50613, 'nm': 'Kia С665ХК716', 'pos': {'y': 55.79, 'x': 49.12, 's': 42, 'c': 90, 't': 1794650000}},
    {'id': 50484, 'nm': 'Kia Х267СО716', 'pos': None},
]


def fake_wialon(calls):
    def call(svc, params, sid=None):
        calls.append(svc)
        return {'eid': 'synthetic-sid'} if svc == 'token/login' else {'items': ITEMS}
    return call


def test_parsing_keeps_units_without_position():
    from fleetai import routes
    units = routes._wialon_positions_from_items(ITEMS)
    assert units[0] == {'id': 50613, 'name': 'Kia С665ХК716', 'lat': 55.79, 'lon': 49.12,
                        'speed_kmh': 42, 'course': 90, 'time': 1794650000}
    assert units[1]['lat'] is None and units[1]['lon'] is None


def test_anonymous_gets_401_before_wialon(secure_app, monkeypatch):
    from fleetai import routes
    calls = []
    monkeypatch.setattr(routes, '_wialon_call', fake_wialon(calls))
    response = secure_app.test_client().get('/api/wialon/positions', base_url='https://localhost')
    assert response.status_code == 401 and calls == []


def test_owner_reads_positions_with_only_read_calls(secure_app, monkeypatch):
    from fleetai import routes
    calls = []
    monkeypatch.setattr(routes, '_wialon_call', fake_wialon(calls))
    monkeypatch.setenv('WIALON_TOKEN', 'synthetic-wialon-token')
    client, headers = owner_client(secure_app)
    response = client.get('/api/wialon/positions', base_url='https://localhost', headers=headers)
    data = response.get_json()
    assert response.status_code == 200, data
    assert data['count'] == 2 and data['commands_sent'] is False
    assert calls == ['token/login', 'core/search_items']
    assert 'synthetic-wialon-token' not in response.get_data(as_text=True)


def test_owner_without_csrf_is_rejected(secure_app, monkeypatch):
    from fleetai import routes
    calls = []
    monkeypatch.setattr(routes, '_wialon_call', fake_wialon(calls))
    client, _ = owner_client(secure_app)
    response = client.get('/api/wialon/positions', base_url='https://localhost')
    assert response.status_code == 403 and calls == []


def test_login_without_or_with_wrong_proof_is_forbidden(secure_app):
    secure_app.test_cli_runner().invoke(args=['auth', 'bootstrap-owner', '--username', 'owner'],
                                        input=PASSWORD + '\n' + PASSWORD + '\n')
    client = secure_app.test_client()
    missing = client.post('/auth/login', base_url='https://localhost',
                          data={'username': 'owner', 'password': PASSWORD, 'login_proof': None},
                          headers={'Origin': 'https://localhost'})
    assert missing.status_code == 403
    client.get('/auth/login', base_url='https://localhost')
    wrong = client.post('/auth/login', base_url='https://localhost',
                        data={'username': 'owner', 'password': PASSWORD, 'login_proof': 'forged'},
                        headers={'Origin': 'https://localhost'})
    assert wrong.status_code == 403


def test_monitor_page_owner_only_and_uses_read_only_api(secure_app):
    anonymous = secure_app.test_client().get('/monitor', base_url='https://localhost')
    assert anonymous.status_code in (302, 303) and '/auth/login' in anonymous.headers['Location']
    client, _ = owner_client(secure_app)
    page = client.get('/monitor', base_url='https://localhost')
    text = page.get_data(as_text=True)
    assert page.status_code == 200 and '/api/wialon/positions' in text
    assert '/auth/client.js' in text  # CSRF header is added to the page fetch
    assert 'send_cmd' not in text and '/command' not in text
