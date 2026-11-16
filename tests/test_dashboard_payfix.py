"""Driver payments saved as plain income ("897 получил 12500") that never reached the wallet."""
from datetime import datetime, timedelta

from sqlalchemy import create_engine, text

from test_dashboard_ai import make_app
from test_dashboard_v4 import BASE, csrf_headers, fin_dash, login, op_change  # noqa: F401  (fixture)


def seed(url):
    eng = create_engine(url)
    t0 = datetime.now() - timedelta(days=5)
    with eng.begin() as c:
        c.execute(text("INSERT INTO driver_wallet_transactions (driver_name, car_code, amount, transaction_type, source, "
                       "external_id, comment, date) VALUES ('Иван', '897', 5000, 'driver_change_balance', 'x', '', 'start', :d),"
                       "('Иван', '897', -1857, 'daily_rent', 'system', '', 'DAILY_RENT:x', :d2)"),
                  {'d': t0, 'd2': t0 + timedelta(days=1)})
        rows = [(10, t0 - timedelta(days=3), 13000, '897 получил 13000', 'Доход'),          # before this driver: no
                (11, t0 + timedelta(days=2), 12500, '897 получил 12500', 'Доход'),          # yes
                (12, t0 + timedelta(days=2, minutes=3), 12500, '897 получил 12500', 'Доход'),  # looks like a duplicate
                (13, t0 + timedelta(days=3), 10000, '897 получил залог 10000', 'Доход'),    # deposit: no
                (14, t0 + timedelta(days=3), 9000, '897 пополнение [DRIVER_TOPUP:897:1]', 'Аренда')]  # already a top-up
        for i, d, a, raw, cat in rows:
            c.execute(text("INSERT INTO operations (id, date, car_code, type, category, description, amount, raw_message) "
                           "VALUES (:i, :d, '897', 'income', :cat, 'Доход', :a, :r)"), dict(i=i, d=d, a=a, r=raw, cat=cat))
            c.execute(text("INSERT INTO income (operation_id, car_code, date, amount, income_type) VALUES (:i, '897', :d, :a, 'x')"),
                      dict(i=i, d=d, a=a))
    return eng


def wallet(eng):
    with eng.connect() as c:
        return c.execute(text("SELECT COALESCE(SUM(amount), 0) FROM driver_wallet_transactions WHERE car_code = '897'")).scalar()


def test_unposted_payments_are_found_and_credited_once(fin_dash):
    eng = seed(fin_dash.engine_url)
    c = make_app(fin_dash.engine_url).test_client()
    assert c.get('/api/v4/rent/unposted', base_url=BASE).status_code == 401
    login(c)
    got = c.get('/api/v4/rent/unposted', base_url=BASE).get_json()['payments']
    assert [(x['id'], x['maybe_duplicate']) for x in got] == [(11, False), (12, True)]
    assert got[0]['amount'] == 1_250_000 and got[0]['driver'] == 'Иван'
    ops_before = eng.connect().execute(text("SELECT count(*) FROM operations")).scalar()
    before = wallet(eng)
    assert c.post('/api/v4/rent/unposted', base_url=BASE, json={'data': {'ids': [11]}}).status_code == 403   # no CSRF
    r = c.post('/api/v4/rent/unposted', base_url=BASE, headers=csrf_headers(c), json={'data': {'ids': [11, 10, 13, 999]}})
    assert r.get_json()['count'] == 1                                    # only real candidates are credited
    assert wallet(eng) == before + 12500
    assert eng.connect().execute(text("SELECT count(*) FROM operations")).scalar() == ops_before   # no new income
    again = c.post('/api/v4/rent/unposted', base_url=BASE, headers=csrf_headers(c), json={'data': {'ids': [11]}})
    assert again.get_json()['count'] == 0 and wallet(eng) == before + 12500
    left = c.get('/api/v4/rent/unposted', base_url=BASE).get_json()['payments']
    assert [(x['id'], x['maybe_duplicate']) for x in left] == [(12, True)]   # its credited twin keeps it flagged
    hist = ' '.join(e['summary'] for e in c.get('/api/v4/history', base_url=BASE).get_json()['events'])
    assert 'Зачтена в баланс водителя оплата #11: 897 12500 ₽' in hist


def test_deleting_a_credited_payment_takes_the_credit_back(fin_dash):
    eng = seed(fin_dash.engine_url)
    c = make_app(fin_dash.engine_url).test_client()
    login(c)
    h = csrf_headers(c)
    before = wallet(eng)
    c.post('/api/v4/rent/unposted', base_url=BASE, headers=h, json={'data': {'ids': [11]}})
    assert wallet(eng) == before + 12500
    r = op_change(c, h, 11, 'delete', {}, 'payfix-del-000001')
    assert r.status_code == 200 and 'Зачёт в кошелёк водителя отменён' in r.get_json()['message']
    assert wallet(eng) == before


def test_rent_view_shows_how_far_rent_is_accrued(fin_dash):
    seed(fin_dash.engine_url)
    c = make_app(fin_dash.engine_url).test_client()
    login(c)
    row = {x['code']: x for x in c.get('/api/v4/rent', base_url=BASE).get_json()['rentals']}['897']
    assert row['accrued_to'] == (datetime.now() - timedelta(days=4)).date().isoformat()
