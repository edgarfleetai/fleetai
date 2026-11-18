"""Driver cabinet on the new site: one-time link login, read-only data, bank payment, owner preview."""
from datetime import datetime

from sqlalchemy import create_engine, text

from test_dashboard_ai import make_app
from test_dashboard_v4 import BASE, csrf_headers, fin_dash, login  # noqa: F401  (fixture)

ORIGIN = {'Origin': BASE}


def link(owner, code='621'):
    r = owner.post(f'/api/v4/cars/{code}/driver-link', base_url=BASE, headers=csrf_headers(owner),
                   json={'data': {}}).get_json()
    assert r['ok'] and r['url'].startswith(BASE + '/d#token=')
    return r['url'].split('#token=')[1]


def setup(fin_dash, **cfg):
    app = make_app(fin_dash.engine_url, **cfg)
    eng = create_engine(fin_dash.engine_url)
    with eng.begin() as c:
        c.execute(text("INSERT INTO driver_wallet_transactions (driver_name, car_code, amount, transaction_type, source, "
                       "comment, date) VALUES ('Сергей', '621', 5000, 'topup', 'bank', 'оплата', :d), "
                       "('Сергей', '621', -2000, 'daily_rent', 'system', 'аренда', :d), "
                       "('Иван', '897', 9999, 'topup', 'bank', 'чужая', :d)"), {'d': datetime.now()})
    owner = app.test_client()
    login(owner)
    return app, eng, owner


def count(eng, table):
    with eng.connect() as c:
        return c.execute(text(f"SELECT COUNT(*) FROM {table}")).scalar()


def test_driver_enters_once_by_link_and_sees_only_his_car(fin_dash):
    app, eng, owner = setup(fin_dash)
    raw = link(owner)
    d = app.test_client()
    assert d.get('/api/d/me', base_url=BASE).status_code == 401
    assert d.get('/d?token=' + raw, base_url=BASE).status_code == 400              # token never in the query
    assert d.get('/d', base_url=BASE).status_code == 200
    assert d.post('/d/login', base_url=BASE, headers={'Origin': 'https://evil.example'},
                  json={'ticket': raw}).status_code == 403                       # foreign site
    assert d.post('/d/login', base_url=BASE, headers=ORIGIN, json={'ticket': raw}).get_json()['ok']
    other = app.test_client()
    assert other.post('/d/login', base_url=BASE, headers=ORIGIN, json={'ticket': raw}).status_code == 401  # used
    wallet = count(eng, 'driver_wallet_transactions')
    me = d.get('/api/d/me', base_url=BASE).get_json()
    assert me['car']['code'] == '621' and me['driver'] == 'Сергей' and me['balance'] == 300_000
    assert [t['amount'] for t in me['transactions']] == [500_000, -200_000] or \
        sorted(t['amount'] for t in me['transactions']) == [-200_000, 500_000]
    assert 'чужая' not in str(me) and me['preview'] is False
    assert count(eng, 'driver_wallet_transactions') == wallet                    # reading writes nothing
    assert d.get('/api/v4/fleet', base_url=BASE).status_code == 401              # a driver is not the owner
    assert d.get('/api/d/me?code=897', base_url=BASE).status_code == 401         # nor can he peek at another car


def test_access_ends_when_the_driver_changes_or_is_revoked(fin_dash):
    app, eng, owner = setup(fin_dash)
    d = app.test_client()
    d.post('/d/login', base_url=BASE, headers=ORIGIN, json={'ticket': link(owner)})
    assert d.get('/api/d/me', base_url=BASE).status_code == 200
    owner.post('/api/v4/cars/621/driver-link/revoke', base_url=BASE, headers=csrf_headers(owner), json={'data': {}})
    assert d.get('/api/d/me', base_url=BASE).status_code == 401
    d2 = app.test_client()
    d2.post('/d/login', base_url=BASE, headers=ORIGIN, json={'ticket': link(owner)})
    assert d2.get('/api/d/me', base_url=BASE).status_code == 200
    with eng.begin() as c:
        c.execute(text("UPDATE cars SET driver = 'Новый' WHERE code = '621'"))
    assert d2.get('/api/d/me', base_url=BASE).status_code == 401


def test_payment_creates_one_pending_bank_payment(fin_dash):
    calls = []

    def fake_init(amount, order_id, description, back_url):
        calls.append((amount, back_url))
        return {'PaymentId': 'P-1', 'PaymentURL': 'https://securepay.tinkoff.ru/new/P-1'}

    app, eng, owner = setup(fin_dash, TBANK_INIT=fake_init, TBANK_READY=True)
    d = app.test_client()
    d.post('/d/login', base_url=BASE, headers=ORIGIN, json={'ticket': link(owner)})
    me = d.get('/api/d/me', base_url=BASE).get_json()
    assert me['pay_ready'] is True
    assert d.post('/api/d/pay', base_url=BASE, headers=ORIGIN, json={'amount': 1500}).status_code == 403  # no CSRF
    assert d.post('/api/d/pay', base_url=BASE, headers={'Origin': 'https://evil.example', 'X-CSRF': me['csrf']},
                  json={'amount': 1500}).status_code == 403
    h = {**ORIGIN, 'X-CSRF': me['csrf']}
    assert d.post('/api/d/pay', base_url=BASE, headers=h, json={'amount': 0}).status_code == 400
    assert d.post('/api/d/pay', base_url=BASE, headers=h, json={'amount': 300000}).status_code == 400
    r = d.post('/api/d/pay', base_url=BASE, headers=h, json={'amount': 1500}).get_json()
    assert r == {'ok': True, 'payment_url': 'https://securepay.tinkoff.ru/new/P-1'}
    assert calls == [(1500, BASE + '/d')]
    with eng.connect() as c:
        rows = c.execute(text("SELECT payment_id, car_code, driver_name, amount, status FROM driver_bank_payments")).all()
    assert [tuple(x) for x in rows] == [('P-1', '621', 'Сергей', 1500, 'pending')]
    # nothing is credited until the bank confirms through the webhook
    assert d.get('/api/d/me', base_url=BASE).get_json()['balance'] == 300_000


def test_payment_is_off_until_bank_keys_are_set(fin_dash):
    app, eng, owner = setup(fin_dash, TBANK_READY=False)
    d = app.test_client()
    d.post('/d/login', base_url=BASE, headers=ORIGIN, json={'ticket': link(owner)})
    me = d.get('/api/d/me', base_url=BASE).get_json()
    assert me['pay_ready'] is False
    r = d.post('/api/d/pay', base_url=BASE, headers={**ORIGIN, 'X-CSRF': me['csrf']}, json={'amount': 100})
    assert r.status_code == 503 and count(eng, 'driver_bank_payments') == 0


def test_owner_previews_a_cabinet_and_driver_logs_out(fin_dash):
    app, eng, owner = setup(fin_dash)
    me = owner.get('/api/d/me?code=621', base_url=BASE).get_json()
    assert me['preview'] is True and me['pay_ready'] is False and me['balance'] == 300_000 and me['csrf'] == ''
    assert app.test_client().get('/api/d/me?code=621', base_url=BASE).status_code == 401
    d = app.test_client()
    d.post('/d/login', base_url=BASE, headers=ORIGIN, json={'ticket': link(owner)})
    csrf = d.get('/api/d/me', base_url=BASE).get_json()['csrf']
    assert d.post('/api/d/logout', base_url=BASE, headers={**ORIGIN, 'X-CSRF': csrf}).get_json()['ok']
    assert d.get('/api/d/me', base_url=BASE).status_code == 401
