"""Daily rent accrual run by the dashboard with FleetAI's own _sync_daily_rent."""
from datetime import datetime, timedelta

from sqlalchemy import create_engine, text

from test_dashboard_ai import make_app
from test_dashboard_v4 import BASE, csrf_headers, fin_dash, login  # noqa: F401  (fixture)


def seed(url, days_ago=5):
    from fleetai.routes import moscow_now
    eng = create_engine(url)
    start = moscow_now().date() - timedelta(days=days_ago)
    with eng.begin() as c:
        c.execute(text("UPDATE cars SET daily_rent = 1857"))
        c.execute(text("UPDATE cars SET driver = '' WHERE code = '621'"))           # no driver: nothing to charge
        c.execute(text("INSERT INTO driver_wallet_transactions (driver_name, car_code, amount, transaction_type, source, "
                       "external_id, comment, date) VALUES ('Иван', '897', 0, 'daily_rent', 'system', '', :c, :d)"),
                  {'c': f'V7_START:{start.isoformat()}', 'd': datetime.now() - timedelta(days=days_ago)})
    return eng


def wallet(eng, code='897'):
    with eng.connect() as c:
        return c.execute(text("SELECT COALESCE(SUM(amount), 0) FROM driver_wallet_transactions WHERE car_code = :c"),
                         {'c': code}).scalar()


def test_missed_days_are_charged_once(fin_dash):
    eng = seed(fin_dash.engine_url, days_ago=5)
    c = make_app(fin_dash.engine_url).test_client()
    login(c)
    assert c.post('/api/v4/rent/accrue', base_url=BASE, json={'data': {}}).status_code == 403    # no CSRF
    r = c.post('/api/v4/rent/accrue', base_url=BASE, headers=csrf_headers(c), json={'data': {}}).get_json()
    assert r['ok'] and [(x['car'], x['charged']) for x in r['cars']] == [('897', 5)]
    assert wallet(eng) == -5 * 1857 and wallet(eng, '621') == 0
    again = c.post('/api/v4/rent/accrue', base_url=BASE, headers=csrf_headers(c), json={'data': {}}).get_json()
    assert again['cars'] == [] and wallet(eng) == -5 * 1857                    # safe to repeat
    hist = ' '.join(e['summary'] for e in c.get('/api/v4/history', base_url=BASE).get_json()['events'])
    assert 'Аренда 897 (вручную): списано 5 дн. × 1857 ₽' in hist


def test_downtime_days_are_not_charged(fin_dash):
    from fleetai.routes import moscow_now
    eng = seed(fin_dash.engine_url, days_ago=3)
    today = moscow_now().date()
    with eng.begin() as c:
        c.execute(text("INSERT INTO operations (date, car_code, type, category, description, amount) VALUES "
                       "(:d, '897', 'downtime', 'Простой', 'ремонт', 0)"), {'d': datetime.combine(today - timedelta(days=1), datetime.min.time())})
    from dashboard import accrual
    from fleetai import db as fleet_db
    fleet_db.configure_database(fin_dash.engine_url)
    done = accrual.accrue_all()
    got = {x['car']: x for x in done}['897']
    assert got['charged'] + got['downtime'] == 3
