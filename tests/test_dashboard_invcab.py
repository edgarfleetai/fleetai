"""Investor cabinet: personal link, read-only results of his own cars, owner preview and revoke."""
from datetime import datetime

from sqlalchemy import create_engine, text

from test_dashboard_ai import make_app
from test_dashboard_v4 import BASE, csrf_headers, fin_dash, login  # noqa: F401  (fixture)

ORIGIN = {'Origin': BASE}


def setup(fin_dash):
    app = make_app(fin_dash.engine_url)
    eng = create_engine(fin_dash.engine_url)
    with eng.begin() as c:
        c.execute(text("INSERT INTO income (car_code, amount, income_type, date) VALUES ('621', 30000, 'rent', :d)"),
                  {'d': datetime.now()})
    owner = app.test_client()
    login(owner)
    return app, eng, owner


def link(owner, key='ilya'):
    r = owner.post(f'/api/v4/investors/{key}/link', base_url=BASE, headers=csrf_headers(owner),
                   json={'data': {}}).get_json()
    assert r['ok'] and r['url'].startswith(BASE + '/i#token=')
    return r['url'].split('#token=')[1]


def tables(eng):
    """Row count of every table except the cabinet's own access table."""
    from sqlalchemy import inspect
    names = [t for t in inspect(eng).get_table_names() if t != 'dashboard_investor_access']
    with eng.connect() as c:
        return {t: c.execute(text(f'SELECT COUNT(*) FROM "{t}"')).scalar() for t in names}


def test_investor_enters_once_and_sees_only_his_results(fin_dash):
    app, eng, owner = setup(fin_dash)
    i = app.test_client()
    assert i.post('/api/v4/investors/ilya/link', base_url=BASE, json={'data': {}}).status_code in (401, 403)
    assert i.get('/api/i/me', base_url=BASE).status_code == 401
    raw = link(owner)
    assert i.get('/i?token=' + raw, base_url=BASE).status_code == 400            # token never in the query
    assert i.get('/i', base_url=BASE).status_code == 200
    assert i.post('/i/login', base_url=BASE, headers={'Origin': 'https://evil.example'},
                  json={'ticket': raw}).status_code == 403
    assert i.post('/i/login', base_url=BASE, headers=ORIGIN, json={'ticket': raw}).get_json()['ok']
    assert app.test_client().post('/i/login', base_url=BASE, headers=ORIGIN,
                                  json={'ticket': raw}).status_code == 401       # single use
    before = tables(eng)
    me = i.get('/api/i/me', base_url=BASE).get_json()
    assert me['name'] == 'Илья' and me['preview'] is False
    assert {c['code'] for c in me['cars']} == {'621'}
    assert me['total']['income'] >= 3_000_000
    assert sum(p['amount'] for p in me['payouts']) == me['total']['payouts']
    assert 'checks' not in me and 'lines' not in me and 'history' not in me      # owner-only parts stay hidden
    pdf = i.get('/api/i/report.pdf', base_url=BASE)
    assert pdf.status_code == 200 and pdf.data.startswith(b'%PDF')
    assert tables(eng) == before                                                 # reading writes nothing
    assert i.get('/api/v4/fleet', base_url=BASE).status_code == 401              # an investor is not the owner
    assert i.get('/api/i/me?investor=ravshan', base_url=BASE).status_code == 401  # nor sees another investor
    assert i.get('/api/v4/investors/report?investor=ilya', base_url=BASE).status_code == 401


def test_owner_revokes_and_previews(fin_dash):
    app, eng, owner = setup(fin_dash)
    i = app.test_client()
    i.post('/i/login', base_url=BASE, headers=ORIGIN, json={'ticket': link(owner)})
    unused = link(owner)
    st = owner.get('/api/v4/investors/ilya/link', base_url=BASE).get_json()
    assert st['sessions'] == 1 and st['pending_links'] == 1
    assert owner.post('/api/v4/investors/ilya/link/revoke', base_url=BASE, headers=csrf_headers(owner),
                      json={'data': {}}).get_json()['ok']
    assert i.get('/api/i/me', base_url=BASE).status_code == 401
    assert app.test_client().post('/i/login', base_url=BASE, headers=ORIGIN,
                                  json={'ticket': unused}).status_code == 401
    me = owner.get('/api/i/me?investor=ilya', base_url=BASE).get_json()
    assert me['preview'] is True and me['csrf'] == ''
    assert owner.get('/api/i/me?investor=nobody', base_url=BASE).status_code == 404
    assert owner.get('/api/v4/investors/nobody/link', base_url=BASE).status_code == 404


def test_investor_logs_out(fin_dash):
    app, eng, owner = setup(fin_dash)
    i = app.test_client()
    i.post('/i/login', base_url=BASE, headers=ORIGIN, json={'ticket': link(owner)})
    csrf = i.get('/api/i/me', base_url=BASE).get_json()['csrf']
    assert csrf
    assert i.post('/api/i/logout', base_url=BASE, headers={**ORIGIN, 'X-CSRF': csrf}).get_json()['ok']
    assert i.get('/api/i/me', base_url=BASE).status_code == 401
