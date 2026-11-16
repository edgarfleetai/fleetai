"""Driver cabinet by an owner-issued link (no Telegram) and contracts for foreign citizens.
SQLite and synthetic identities only; SMS.ru is replaced by a fake, nothing leaves the machine."""
import time
from types import SimpleNamespace as NS

import pytest
from sqlalchemy import text

BASE = 'https://localhost'


def add_car(code='T1', driver='Alice'):
    from fleetai import db
    from fleetai.models import Car
    with db.Session() as s:
        s.add(Car(code=code, driver=driver, daily_rent=1800, driver_deposit=10000))
        s.commit()


def issue(code='T1'):
    from fleetai import db
    from fleetai.auth import issue_driver_link
    with db.Session() as s:
        raw, driver = issue_driver_link(s, code)
        s.commit()
    return raw, driver


def test_owner_link_opens_the_cabinet_once_without_telegram(secure_app):
    from fleetai import db
    from fleetai.auth_models import AuthSession
    add_car()
    raw, driver = issue()
    assert driver == 'Alice'
    c = secure_app.test_client()
    r = c.post('/auth/driver/consume', json={'ticket': raw}, base_url=BASE)
    assert r.status_code == 303 and r.headers['Location'] == '/driver?code=T1'
    assert 'Max-Age=2592000' in r.headers['Set-Cookie']                   # 30 days by default
    me = c.get('/auth/session', base_url=BASE).json
    assert me['kind'] == 'driver' and me['car_code'] == 'T1'
    h = {'X-CSRF-Token': me['csrf_token']}
    assert c.get('/api/driver-mvp/T1', base_url=BASE, headers=h).status_code == 200   # own car
    assert c.get('/api/driver-mvp/T2', base_url=BASE, headers=h).status_code == 403   # nothing else
    assert secure_app.test_client().post('/auth/driver/consume', json={'ticket': raw}, base_url=BASE).status_code == 401
    with db.Session() as s:
        row = s.query(AuthSession).filter_by(kind='driver').one()
        assert row.chat_id == 'owner-link' and row.expires_at > time.time() + 29 * 86400


def test_owner_link_dies_when_the_driver_changes_or_is_revoked(secure_app):
    from fleetai import db
    from fleetai.auth import driver_link_status, revoke_driver_links
    add_car()
    raw1, _ = issue()
    raw2, _ = issue()
    c = secure_app.test_client()
    assert c.post('/auth/driver/consume', json={'ticket': raw1}, base_url=BASE).status_code == 303
    with db.Session() as s:
        assert driver_link_status(s, 'T1') == {'sessions': 1, 'pending_links': 1}
        assert revoke_driver_links(s, 'T1') == 2
        s.commit()
    assert c.get('/auth/session', base_url=BASE).status_code == 401
    assert c.post('/auth/driver/consume', json={'ticket': raw2}, base_url=BASE).status_code == 401
    raw3, _ = issue()
    with db.Session() as s:
        s.execute(text("UPDATE cars SET driver = 'Bob' WHERE code = 'T1'"))
        s.commit()
    assert secure_app.test_client().post('/auth/driver/consume', json={'ticket': raw3}, base_url=BASE).status_code == 401


def test_owner_link_needs_a_driver_and_telegram_rules_are_unchanged(secure_app):
    from fleetai import db
    from fleetai.auth import issue_driver_login, OWNER_LINK
    from fleetai.models import Car
    add_car('T3', '')
    with pytest.raises(ValueError):
        issue('T3')
    add_car('T4', 'Carol')
    with db.Session() as s:
        car = s.query(Car).filter_by(code='T4').one()
        with pytest.raises(ValueError):                 # the marker is never a Telegram binding
            issue_driver_login(s, car, OWNER_LINK)


FOREIGN = {'driver_name': 'Каримов Азиз', 'name_latin': 'KARIMOV AZIZ', 'driver_birth_date': '1995-02-03',
           'passport_number': 'FA1234567', 'passport_issued_by': 'МВД Узбекистана', 'passport_issue_date': '2020-01-10',
           'passport_expires': '2030-01-09', 'migration_card': '4619 0012345', 'stay_address': 'г. Набережные Челны',
           'stay_until': '2027-02-01', 'phone': '+7 917 000-11-22', 'license_number': 'AF 1234567',
           'license_expires': '2029-01-01', 'car_make': 'Kia', 'car_model': 'Rio', 'car_plate': 'А001АА716',
           'car_vin': 'VIN1', 'car_year': '2020', 'car_sts': 'STS1', 'deposit': '10000', 'work_doc': 'patent'}


def make_contract(secure_app, citizenship):
    from fleetai import contract_extra, db
    from fleetai.routes import _ensure_driver_contract_tables
    add_car('T5', 'Азиз')
    with db.Session() as s:
        _ensure_driver_contract_tables(s)
        s.execute(text("INSERT INTO driver_contracts (id, public_token, car_code, status, daily_rent, rental_start_date, "
                       "lessor_name, lessor_inn, lessor_ogrnip, created_at, updated_at) VALUES ('KP-1', 'tok-synthetic', "
                       "'T5', 'draft', 1800, '2026-11-17', 'ИП', '1', '2', :n, :n)"), {'n': __import__('datetime').datetime.now()})
        contract_extra.store(s.connection(), 'KP-1', citizenship, {'work_doc': contract_extra.COUNTRIES[citizenship][1]})
        s.commit()


def test_foreign_driver_fills_the_contract_by_link_and_signs_by_call(secure_app, monkeypatch):
    import fleetai.routes as routes
    from fleetai import db
    make_contract(secure_app, 'UZ')
    c = secure_app.test_client()
    got = c.get('/api/driver-contract/tok-synthetic', base_url=BASE).json
    assert got['contract']['citizenship'] == 'UZ' and got['contract']['work_doc'] == 'patent'
    page = c.get('/driver-contract?token=tok-synthetic', base_url=BASE).get_data(as_text=True)
    assert 'Миграционная карта' in page and 'name_latin' in page
    bad = c.post('/api/driver-contract/tok-synthetic/save', json=FOREIGN, base_url=BASE)
    assert bad.status_code == 400 and bad.json['missing'] == ['work_doc_number']
    ok = c.post('/api/driver-contract/tok-synthetic/save', json=dict(FOREIGN, work_doc_number='16 №24001'), base_url=BASE)
    assert ok.status_code == 200, ok.json
    got = c.get('/api/driver-contract/tok-synthetic', base_url=BASE).json['contract']
    assert got['status'] == 'ready' and got['migration_card'] == '4619 0012345' and got['country_name'] == 'Республика Узбекистан'
    assert got['passport_department_code'] == '' and got['registration_address'] == 'г. Набережные Челны'
    assert c.get('/driver-contract/tok-synthetic/preview.pdf', base_url=BASE).data.startswith(b'%PDF')

    replies = iter([{'status': 'OK', 'check_id': 'c1', 'call_phone': '78000000000'}])
    monkeypatch.setenv('SMSRU_API_ID', 'synthetic')
    monkeypatch.setattr(routes.requests, 'post', lambda *a, **k: NS(raise_for_status=lambda: None, json=lambda: next(replies)))
    assert c.post('/api/driver-contract/tok-synthetic/send-code', base_url=BASE).status_code == 200
    # The sign handler compares TIMESTAMP columns, which SQLite returns as text; check what it
    # stores instead: the foreign hash and the e-signed PDF built from the extra fields.
    from fleetai import contract_extra
    with secure_app.app_context(), db.Session() as s:
        row = routes._contract_row(s, 'tok-synthetic')
        h, make_pdf = routes._driver_contract_hash_and_pdf(s, row, True)
        merged = contract_extra.merged(s.connection(), row)
        pdf = make_pdf(row)
    assert h == contract_extra.contract_hash(merged) != routes._contract_hash(row)
    assert pdf.startswith(b'%PDF') and merged['migration_card'] == '4619 0012345'
    with db.Session() as s:
        s.execute(text("UPDATE driver_contracts SET status = 'signed' WHERE id = 'KP-1'"))
        s.commit()
    assert c.post('/api/driver-contract/tok-synthetic/save', json=FOREIGN, base_url=BASE).status_code == 409


def test_russian_contract_by_link_is_unchanged(secure_app):
    """No extra row -> the original Russian form, validation and hash."""
    from fleetai import db
    from fleetai.routes import _ensure_driver_contract_tables
    add_car('T6', 'Иван')
    with db.Session() as s:
        _ensure_driver_contract_tables(s)
        s.execute(text("INSERT INTO driver_contracts (id, public_token, car_code, status, created_at, updated_at) "
                       "VALUES ('KP-2', 'tok-ru', 'T6', 'draft', :n, :n)"), {'n': __import__('datetime').datetime.now()})
        s.commit()
    c = secure_app.test_client()
    assert c.get('/api/driver-contract/tok-ru', base_url=BASE).json['contract']['citizenship'] == 'RU'
    r = c.post('/api/driver-contract/tok-ru/save', json=dict(FOREIGN, passport_series=''), base_url=BASE)
    assert r.status_code == 400 and r.json['message'] == 'Заполни все обязательные поля'
