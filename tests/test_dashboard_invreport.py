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


def test_duplicates_can_be_removed_from_the_report(fin_dash):
    from test_dashboard_v4 import csrf_headers, op_change
    eng = create_engine(fin_dash.engine_url)
    t = now() - timedelta(hours=1)
    for i in (21, 22):
        add(eng, "INSERT INTO operations (id, date, car_code, type, category, description, amount, raw_message) "
                 "VALUES (:i, :d, '621', 'income', 'Доход', 'Доход', 12000, '621 получил 12000')", i=i, d=t)
        add(eng, "INSERT INTO income (operation_id, car_code, date, amount, income_type) VALUES (:i, '621', :d, 12000, 'x')",
            i=i, d=t)
    for i in (31, 32):
        add(eng, "INSERT INTO operations (id, date, car_code, type, category, description, amount, raw_message) "
                 "VALUES (:i, :d, '621', 'investor_payout', 'Выплата', 'Выплата инвестору', 4000, '621 выплата илье 4000')", i=i, d=t)
        add(eng, "INSERT INTO investor_payouts (operation_id, date, investor_name, car_code, amount) VALUES (:i, :d, 'Илья', '621', 4000)",
            i=i, d=t)
    c = fin_dash.test_client()
    assert c.get('/api/v4/op/21', base_url=BASE).status_code == 401
    login(c)
    h = csrf_headers(c)
    by = {x['title']: x for x in report(c)['checks']}
    assert by['Доход записан дважды?']['ops'] == [[21, 22]]
    assert by['Похоже на двойную выплату']['ops'] == [[31, 32]]
    row = c.get('/api/v4/op/22', base_url=BASE).get_json()
    assert row['id'] == 22 and row['amount'] == 1_200_000 and row['label'] == 'Доход'
    assert c.get('/api/v4/op/999', base_url=BASE).status_code == 404
    assert op_change(c, h, 22, 'delete', {}, 'inv-del-0000000001').status_code == 200
    assert op_change(c, h, 32, 'delete', {}, 'inv-del-0000000002').status_code == 200
    rep = report(c)
    titles_now = titles(rep)
    assert 'Доход записан дважды?' not in titles_now and 'Похоже на двойную выплату' not in titles_now
    assert [p['op'] for p in rep['lines']['payouts']] == [31]
    hist = ' '.join(e['summary'] for e in c.get('/api/v4/history', base_url=BASE).get_json()['events'])
    assert 'Удалена операция #22' in hist and 'Удалена операция #32' in hist


def test_explanations_per_car_are_saved_for_the_report(fin_dash):
    from test_dashboard_v4 import csrf_headers
    c = fin_dash.test_client()
    login(c)
    rep = report(c)
    car = {x['code']: x for x in rep['cars']}['621']
    assert car['expenses'] == 200_000 and car['profit'] == 1_100_000 and car['investor_part'] == 825_000
    url = '/api/v4/investors/notes'
    body = {'data': {'investor': 'ilya', 'start': rep['start'],
                     'notes': {'621': 'Поменяли колодки, водитель платил вовремя.', '897': 'чужая машина'}}}
    assert c.post(url, base_url=BASE, json=body).status_code == 403                       # no CSRF
    r = c.post(url, base_url=BASE, headers=csrf_headers(c), json=body).get_json()
    assert r['ok'] and r['changed'] == ['621']                                            # 897 is not Ilya's
    got = c.get(f"{url}?investor=ilya&start={rep['start']}", base_url=BASE).get_json()['notes']
    assert got == {'621': {'text': 'Поменяли колодки, водитель платил вовремя.', 'updated_at': got['621']['updated_at']}}
    again = c.post(url, base_url=BASE, headers=csrf_headers(c), json=body).get_json()
    assert again['changed'] == []
    assert c.get(f"{url}?investor=ilya&start=bad", base_url=BASE).status_code == 400
    hist = ' '.join(e['summary'] for e in c.get('/api/v4/history', base_url=BASE).get_json()['events'])
    assert 'Объяснение для отчёта Илья' in hist and 'машина 621' in hist


def test_expenses_say_what_the_money_was_spent_on(fin_dash):
    eng = create_engine(fin_dash.engine_url)
    add(eng, "INSERT INTO parts (car_code, operation_id, part_name, brand, position, price, labor) "
             "VALUES ('621', 2, 'Колодки', 'TRW', 'перед', 1500, 500)")
    c = fin_dash.test_client()
    login(c)
    ex = report(c)['lines']['expenses']
    assert ex[0]['what'] == 'колодки'
    assert ex[0]['parts'] == [{'name': 'Колодки', 'brand': 'TRW', 'position': 'перед', 'price': 150_000, 'labor': 50_000}]
