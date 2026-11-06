"""Admission-time races and ambiguous-key protection outside wallet snapshots."""
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime

import pytest
from flask import g
from sqlalchemy import text

from test_security_integration import seed_driver_binding, driver_client, owner_client
from test_driver_financial_race import route_endpoint


def seed_document():
    from fleetai import db
    with db.Session() as session:
        session.execute(text("INSERT INTO vehicle_documents(car_code,license_filename,license_mime_type,license_data,uploaded_at) VALUES ('700','synthetic.pdf','application/pdf',:data,:when)"),
            {'data':b'%PDF-1.4 synthetic audit document','when':datetime(2026,11,6,12)})
        session.commit()


@pytest.mark.parametrize('endpoint,path,method', [
    ('api_vehicle_license_status','/api/vehicle-license/700/status','GET'),
    ('api_vehicle_license_download','/api/vehicle-license/700','GET'),
    ('api_driver_create_bank_payment','/api/driver-mvp/700/bank-payment','POST'),
])
def test_admitted_driver_cannot_use_document_or_payment_after_assignment(secure_app, monkeypatch, endpoint, path, method):
    from fleetai import db, tbank
    from fleetai.models import DriverBankPayment
    seed_driver_binding()
    seed_document()
    old, headers = driver_client(secure_app)
    owner, owner_headers = owner_client(secure_app)
    external_calls = []
    monkeypatch.setattr(tbank,'create_payment',lambda **kw: external_calls.append(True) or
        {'PaymentId':'synthetic-remote-id','PaymentURL':'https://payment.invalid/synthetic','Status':'NEW'})
    original = secure_app.view_functions[route_endpoint(secure_app,endpoint)]
    reached = []
    def handler(**kwargs):
        assert g.principal.kind == 'driver'
        with ThreadPoolExecutor(1) as pool:
            reply = pool.submit(owner.post,'/api/driver-assignment',base_url='https://localhost',headers=owner_headers,
                json={'car_code':'700','driver':'Synthetic Replacement','daily_rent':100,'opening_balance':0}).result(timeout=20)
        assert reply.status_code == 200
        reached.append(True)
        return original(**kwargs)
    monkeypatch.setitem(secure_app.view_functions,route_endpoint(secure_app,endpoint),handler)
    response = old.open(path,method=method,base_url='https://localhost',headers=headers,json={'amount':100} if method=='POST' else None)
    assert reached == [True]
    assert response.status_code in (401,403)
    assert external_calls == [], 'Authorization must be revalidated before any bank call'
    with db.Session() as session:
        assert session.query(DriverBankPayment).count() == 0


@pytest.mark.parametrize('path', ['/api/vehicle-license/700/status','/api/vehicle-license/700'])
def test_current_driver_keeps_document_access(secure_app, path):
    seed_driver_binding()
    seed_document()
    client,_ = driver_client(secure_app)
    response = client.get(path,base_url='https://localhost')
    assert response.status_code == 200
    if path.endswith('/status'):
        assert response.json['has_license'] is True
        assert response.json['uploaded_at'].startswith('2026-11-06T')
    else:
        assert response.data == b'%PDF-1.4 synthetic audit document'


def insert_alias():
    from fleetai import db
    from fleetai.models import Car
    with db.Session() as session:
        # Model pre-upgrade/corrupt legacy data for the independent auth guard.
        # Normal startup/write-path index enforcement is tested separately.
        session.execute(text('DROP INDEX IF EXISTS auth_car_code_trim_unique'))
        session.add(Car(code=' 700 ',driver='Synthetic Other Person',daily_rent=100))
        session.commit()


def test_alias_added_after_login_denies_driver_financial_access(secure_app):
    seed_driver_binding()
    client, headers = driver_client(secure_app)
    insert_alias()
    response = client.get('/api/driver-mvp/700',base_url='https://localhost',headers=headers)
    assert response.status_code in (401,403)
    assert 'transactions' not in (response.get_json() or {})


def test_alias_added_after_admission_is_rejected_under_lock(secure_app, monkeypatch):
    seed_driver_binding()
    client, headers = driver_client(secure_app)
    original = secure_app.view_functions[route_endpoint(secure_app,'api_driver_mvp')]
    def handler(**kwargs):
        assert g.principal.kind == 'driver'
        with ThreadPoolExecutor(1) as pool:
            pool.submit(insert_alias).result(timeout=20)
        return original(**kwargs)
    monkeypatch.setitem(secure_app.view_functions,route_endpoint(secure_app,'api_driver_mvp'),handler)
    assert client.get('/api/driver-mvp/700',base_url='https://localhost',headers=headers).status_code in (401,403)


def test_ambiguous_code_cannot_issue_new_login_ticket(secure_app):
    from fleetai import auth, db
    from fleetai.models import Car
    seed_driver_binding()
    insert_alias()
    with db.Session() as session:
        with pytest.raises(ValueError):
            auth.issue_driver_login(session,session.query(Car).filter_by(code='700').one(),'12345')


def test_alias_added_after_ticket_issue_prevents_consumption(secure_app):
    from fleetai import auth, db
    from fleetai.models import Car
    seed_driver_binding()
    with db.Session() as session:
        raw = auth.issue_driver_login(session,session.query(Car).filter_by(code='700').one(),'12345')
        session.commit()
    insert_alias()
    response = secure_app.test_client().post('/auth/driver/consume',base_url='https://localhost',
        headers={'Origin':'https://localhost'},json={'ticket':raw})
    assert response.status_code in (401,403)


def test_deployed_auth_requires_explicit_canonical_https_origin(secure_app, monkeypatch):
    from fleetai.auth import _same_origin
    secure_app.config['TESTING'] = False
    secure_app.config.pop('PUBLIC_BASE_URL',None)
    monkeypatch.delenv('FLEETAI_PUBLIC_BASE_URL',raising=False)
    with secure_app.test_request_context('/auth/login',base_url='https://unconfigured.invalid',headers={'Origin':'https://unconfigured.invalid'}):
        assert _same_origin(require_proof=True) is False


def test_canonical_https_origin_emits_hsts_without_trusting_forwarded_scheme(secure_app):
    secure_app.config['PUBLIC_BASE_URL']='https://localhost'
    response = secure_app.test_client().get('/auth/login',base_url='http://localhost',headers={'X-Forwarded-Proto':'https'})
    assert response.headers.get('Strict-Transport-Security') == 'max-age=31536000'


def test_database_rejects_new_trim_equivalent_car_code(secure_app):
    from fleetai import db
    from fleetai.models import Car
    from sqlalchemy.exc import IntegrityError
    seed_driver_binding()
    with db.Session() as session:
        session.add(Car(code=' 700 ', driver='Synthetic Unrelated'))
        with pytest.raises(IntegrityError):
            session.commit()
        session.rollback()


def test_schema_upgrade_fails_closed_for_preexisting_trim_aliases(secure_app):
    from fleetai import db
    from sqlalchemy.exc import IntegrityError
    seed_driver_binding()
    insert_alias()  # Explicit pre-upgrade fixture, not the normal write path.
    with pytest.raises(IntegrityError):
        db.init_db(seed=False)


def test_concurrent_trim_equivalent_vehicle_inserts_have_one_winner(secure_app):
    from threading import Barrier
    from fleetai import db
    from fleetai.models import Car
    from sqlalchemy.exc import IntegrityError
    gate = Barrier(2)
    def create(code):
        with db.Session() as session:
            session.add(Car(code=code, driver='Synthetic New'))
            gate.wait(timeout=15)
            try:
                session.commit()
            except IntegrityError:
                session.rollback()
                return False
            return True
    with ThreadPoolExecutor(2) as pool:
        assert sorted(pool.map(create, [' 702', '702 '])) == [False, True]
