"""Rental contracts filled in by the owner in the dashboard (Russian and foreign citizens)."""
from test_dashboard_ai import make_app
from test_dashboard_v4 import BASE, csrf_headers, fin_dash, login  # noqa: F401  (fixture)

RU = {'car_code': '897', 'citizenship': 'RU', 'driver_name': 'Иванов Иван Иванович', 'driver_birth_date': '1990-05-01',
      'passport_series': '9200', 'passport_number': '123456', 'passport_issued_by': 'МВД по РТ',
      'passport_issue_date': '2015-06-01', 'passport_department_code': '160-001', 'registration_address': 'г. Казань',
      'phone': '8 900 111-22-33', 'license_number': '16 00 123456', 'license_expires': '2030-01-01',
      'rental_start_date': '2026-11-17', 'daily_rent': '1857', 'deposit': '10000'}
UZ = {'car_code': '621', 'citizenship': 'UZ', 'driver_name': 'Каримов Азиз', 'name_latin': 'KARIMOV AZIZ',
      'driver_birth_date': '1995-02-03', 'passport_number': 'FA1234567', 'passport_issued_by': 'МВД Узбекистана',
      'passport_issue_date': '2020-01-10', 'passport_expires': '2030-01-09', 'migration_card': '4619 0012345',
      'stay_address': 'г. Набережные Челны, пр. Мира 1', 'stay_until': '2027-02-01', 'work_doc': 'patent',
      'phone': '+7 917 000-11-22', 'license_number': 'AF 1234567', 'license_expires': '2029-01-01',
      'license_country': 'Республика Узбекистан', 'rental_start_date': '2026-11-17', 'daily_rent': '2000'}


def post(c, url, data):
    return c.post(url, base_url=BASE, headers=csrf_headers(c), json={'data': data})


def test_russian_contract_is_created_and_personal_data_stays_out_of_list_and_history(fin_dash):
    c = make_app(fin_dash.engine_url).test_client()
    assert c.get('/api/v4/contracts/x', base_url=BASE).status_code == 401
    login(c)
    assert c.post('/api/v4/contracts', base_url=BASE, json={'data': RU}).status_code == 403      # no CSRF
    r = post(c, '/api/v4/contracts', RU).get_json()
    assert r['ok'] and r['missing'] == [], r
    one = c.get('/api/v4/contracts/' + r['id'], base_url=BASE).get_json()['data']
    assert one['status'] == 'ready' and one['passport_number'] == '123456' and one['phone'] == '79001112233'
    assert one['daily_rent'] == 1857 and one['citizenship'] == 'RU' and 'public_token' not in one
    lst = c.get('/api/v4/contracts', base_url=BASE)
    assert '123456' not in lst.get_data(as_text=True)
    assert [x['citizenship'] for x in lst.get_json()['contracts'] if x['id'] == r['id']] == ['RU']
    hist = ' '.join(e['summary'] for e in c.get('/api/v4/history', base_url=BASE).get_json()['events'])
    assert 'Создан договор' in hist and '123456' not in hist and 'Иванов' not in hist
    pdf = c.get(f"/api/v4/contracts/{r['id']}/pdf", base_url=BASE)
    assert pdf.status_code == 200 and pdf.data.startswith(b'%PDF')


def test_uzbek_contract_needs_migration_documents_and_patent(fin_dash):
    c = make_app(fin_dash.engine_url).test_client()
    login(c)
    bad = post(c, '/api/v4/contracts', UZ)
    assert bad.status_code == 400 and 'work_doc_number' in bad.get_json()['missing']
    draft = post(c, '/api/v4/contracts', dict(UZ, draft=1)).get_json()
    assert draft['ok'] and draft['missing'] == ['work_doc_number']
    cid = draft['id']
    assert c.get('/api/v4/contracts/' + cid, base_url=BASE).get_json()['data']['status'] == 'draft'
    ok = post(c, f'/api/v4/contracts/{cid}/save', dict(UZ, work_doc_number='16 №2400123456')).get_json()
    assert ok['ok'] and ok['missing'] == []
    one = c.get('/api/v4/contracts/' + cid, base_url=BASE).get_json()['data']
    assert one['status'] == 'ready' and one['citizenship'] == 'UZ' and one['country_name'] == 'Республика Узбекистан'
    assert one['migration_card'] == '4619 0012345' and one['registration_address'] == UZ['stay_address']
    assert one['passport_department_code'] == ''
    assert c.get(f'/api/v4/contracts/{cid}/pdf', base_url=BASE).data.startswith(b'%PDF')


def test_kyrgyz_citizen_needs_no_patent(fin_dash):
    c = make_app(fin_dash.engine_url).test_client()
    login(c)
    r = post(c, '/api/v4/contracts', dict(UZ, citizenship='KG', work_doc='eaeu')).get_json()
    assert r['ok'] and r['missing'] == []
    assert c.get('/api/v4/contracts/' + r['id'], base_url=BASE).get_json()['data']['work_doc'] == 'eaeu'


def test_paper_signed_contract_is_locked_and_keeps_its_pdf(fin_dash):
    c = make_app(fin_dash.engine_url).test_client()
    login(c)
    cid = post(c, '/api/v4/contracts', RU).get_json()['id']
    assert post(c, f'/api/v4/contracts/{cid}/signed', {}).get_json()['ok']
    one = c.get('/api/v4/contracts/' + cid, base_url=BASE).get_json()['data']
    assert one['status'] == 'signed' and one['signed_at'] and one['has_pdf']
    assert post(c, f'/api/v4/contracts/{cid}/save', RU).status_code == 400
    assert post(c, f'/api/v4/contracts/{cid}/signed', {}).status_code == 400
    assert c.get(f'/api/v4/contracts/{cid}/pdf', base_url=BASE).data.startswith(b'%PDF')


def test_contract_money_is_whole_rubles_and_unknown_car_is_refused(fin_dash):
    c = make_app(fin_dash.engine_url).test_client()
    login(c)
    assert post(c, '/api/v4/contracts', dict(RU, daily_rent='1857.5')).status_code == 400
    assert post(c, '/api/v4/contracts', dict(RU, car_code='000')).status_code == 400
    assert post(c, '/api/v4/contracts', dict(RU, citizenship='XX')).status_code == 400
    assert post(c, '/api/v4/contracts/nope/save', RU).status_code == 404
    pre = c.get('/api/v4/contracts/prefill?car=897', base_url=BASE).get_json()
    assert pre['ok'] and pre['data']['car_code'] == '897' and set(pre['countries']) >= {'RU', 'UZ', 'TJ', 'KG', 'TM'}


def test_driver_cabinet_link_is_issued_once_and_can_be_revoked(fin_dash):
    from sqlalchemy import create_engine, text
    c = make_app(fin_dash.engine_url).test_client()
    login(c)
    assert c.post('/api/v4/cars/897/driver-link', base_url=BASE, json={'data': {}}).status_code == 403   # no CSRF
    r = post(c, '/api/v4/cars/897/driver-link', {}).get_json()
    assert r['ok'] and r['url'].startswith(BASE + '/d#token=')
    raw = r['url'].split('#token=')[1]
    eng = create_engine(fin_dash.engine_url)
    with eng.connect() as conn:
        rows = conn.execute(text("SELECT token_hash, chat_id FROM auth_driver_tickets")).all()
    assert [x[1] for x in rows] == ['owner-link'] and raw not in str(rows)                   # only the hash is stored
    assert c.get('/api/v4/cars/897/driver-link', base_url=BASE).get_json()['pending_links'] == 1
    hist = ' '.join(e['summary'] for e in c.get('/api/v4/history', base_url=BASE).get_json()['events'])
    assert 'Выдана ссылка в кабинет водителя 897' in hist and raw not in hist
    assert post(c, '/api/v4/cars/897/driver-link/revoke', {}).get_json()['message'] == 'Доступ закрыт'
    assert c.get('/api/v4/cars/897/driver-link', base_url=BASE).get_json()['pending_links'] == 0
    assert post(c, '/api/v4/cars/000/driver-link', {}).status_code == 400


def test_contract_link_for_the_driver(fin_dash):
    c = make_app(fin_dash.engine_url).test_client()
    login(c)
    cid = post(c, '/api/v4/contracts', {'car_code': '621', 'citizenship': 'TJ', 'draft': 1}).get_json()['id']
    url = c.get(f'/api/v4/contracts/{cid}/link', base_url=BASE).get_json()['url']
    assert url.startswith('https://fleetai-1.onrender.com/driver-contract?token=') and len(url.split('=')[1]) > 30
    assert c.get('/api/v4/contracts/nope/link', base_url=BASE).status_code == 404
    lst = c.get('/api/v4/contracts', base_url=BASE).get_data(as_text=True)
    assert url.split('=')[1] not in lst                                                    # token only on request
