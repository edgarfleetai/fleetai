"""Investor report for a settlement period, with checks for anything paid in excess."""
from datetime import timedelta

from sqlalchemy import create_engine, text
from sqlalchemy.orm import Session

from test_dashboard_v4 import BASE, fin_dash, login  # noqa: F401  (fixture)


def now():
    from fleetai.finance import moscow_now
    return moscow_now()


def add(eng, sql, **kw):
    with eng.begin() as c:
        c.execute(text(sql), kw)


def report(c, period=0):
    r = c.get(f'/api/v4/investors/report?investor=ilya&period={period}', base_url=BASE)
    assert r.status_code == 200
    return r.get_json()


def titles(rep, level=None):
    return [x['title'] for x in rep['checks'] if level is None or x['level'] == level]


def test_report_matches_old_fleetai_split(fin_dash):
    from fleetai.finance import calculate_period_for_car, period_bounds_for_car
    from fleetai.models import Car
    c = fin_dash.test_client()
    assert c.get('/api/v4/investors/report?investor=ilya', base_url=BASE).status_code == 401
    login(c)
    assert c.get('/api/v4/investors/report?investor=nobody', base_url=BASE).status_code == 404
    rep = report(c)
    car = {x['code']: x for x in rep['cars']}['621']
    with Session(create_engine(fin_dash.engine_url)) as s:
        obj = s.query(Car).filter_by(code='621').one()
        calc = calculate_period_for_car(s, obj, *period_bounds_for_car(obj))
    assert car['income'] == calc['income'] * 100 == 1_300_000
    assert car['shared_expenses'] == calc['shared_expenses'] * 100
    assert car['profit_for_split'] == calc['profit_for_split'] * 100
    assert car['share'] == calc['accrued_to_investor'] * 100 == 825_000
    assert car['gps'] == 50_000 and car['garage'] == 150_000          # 3000 ₽ / 2 cars
    assert car['due'] == 825_000 - 50_000 - 150_000
    assert rep['checks'][0]['level'] == 'ok' and len(rep['periods']) == 12
    assert len(rep['lines']['income']) == 1 and rep['history'][0]['balance'] == 625_000


def test_overpayment_and_duplicate_payouts_are_flagged(fin_dash):
    eng = create_engine(fin_dash.engine_url)
    t = now() - timedelta(hours=2)
    for i, (d, amount, car) in enumerate([(t, 5000, '621'), (t - timedelta(minutes=30), 5000, '621'),
                                          (t, 3000, '897')], start=1):
        add(eng, "INSERT INTO investor_payouts (id, date, investor_name, car_code, amount, comment) "
                 "VALUES (:i, :d, 'Илья', :c, :a, 'выплата')", i=i, d=d, a=amount, c=car)
    c = fin_dash.test_client()
    login(c)
    rep = report(c)
    bad = titles(rep, 'bad')
    assert 'Выплачено больше, чем заработано' in bad and 'Похоже на двойную выплату' in bad
    over = {x['title']: x for x in rep['checks']}['Выплачено больше, чем заработано']
    assert over['amount'] == 1_300_000 - 625_000 and rep['balance'] == -675_000     # 5000+5000+3000 paid, 6250 earned
    stray = {x['title']: x for x in rep['checks']}['Выплаты инвестору записаны не на его машину']
    assert stray['amount'] == 300_000 and stray['level'] == 'warn'
    assert [p['counted'] for p in rep['lines']['payouts']].count(False) == 1


def test_income_checks_deposit_duplicate_and_retired_code(fin_dash):
    eng = create_engine(fin_dash.engine_url)
    t = now() - timedelta(hours=1)
    rows = [(10, '621', 10000, '621 получил залог 10000'), (11, '621', 12000, '621 получил 12000'),
            (12, '621', 12000, '621 получил 12000'), (13, '119', 4000, '119 получил 4000')]
    add(eng, "INSERT INTO cars (id, code, brand, model, owner_type, investor_name, investor_percent, settlement_day) "
             "VALUES (3, '119', 'x', 'x', 'investor', 'илья', 75, 15), (4, '665', 'x', 'x', 'investor', 'илья', 75, 15)")
    for i, car, amount, raw in rows:
        add(eng, "INSERT INTO operations (id, date, car_code, type, category, description, amount, raw_message) "
                 "VALUES (:i, :d, :c, 'income', 'Доход', 'Доход', :a, :r)", i=i, d=t, c=car, a=amount, r=raw)
        add(eng, "INSERT INTO income (operation_id, car_code, date, amount, income_type) VALUES (:i, :c, :d, :a, 'x')",
            i=i, c=car, d=t, a=amount)
    c = fin_dash.test_client()
    login(c)
    rep = report(c)
    by = {x['title']: x for x in rep['checks']}
    assert by['Залог водителя посчитан как доход']['amount'] == 750_000
    assert by['Доход записан дважды?']['amount'] == 900_000
    assert by['Записи на старый номер 119 не входят в расчёт']['level'] == 'info'
    assert 'Лишних выплат не найдено' not in by
    prev = report(c, 1)
    assert prev['start'] < rep['start'] and all(x['income'] == 0 for x in prev['cars'])


def test_invreport_module_has_no_write_sql():
    import inspect
    import re
    import dashboard.invreport as m
    src = inspect.getsource(m)
    assert not re.search(r"\b(INSERT|UPDATE|DELETE)\b|\.add\(|\.commit\(|\.delete\(", src)
