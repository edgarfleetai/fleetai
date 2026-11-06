"""Remaining independent-review findings, disposable SQLite only."""
from datetime import datetime
import pytest
from sqlalchemy import Column, MetaData, Table, event, inspect, text


def owner_client(app):
    result = app.test_cli_runner().invoke(args=['auth','bootstrap-owner','--username','owner'],
        input='Synthetic review password 123!\nSynthetic review password 123!\n')
    assert result.exit_code == 0
    client = app.test_client()
    assert client.post('/auth/login', base_url='https://localhost', data={
        'username':'owner','password':'Synthetic review password 123!'}).status_code == 303
    return client


def test_new_owner_api_get_is_csrf_protected_by_default(secure_app):
    secure_app.add_url_rule('/api/synthetic-future-read', 'synthetic_future_read', lambda: {'ok':True})
    client = owner_client(secure_app)
    assert client.get('/api/synthetic-future-read', base_url='https://localhost').status_code == 403
    token = client.get('/auth/session', base_url='https://localhost').json['csrf_token']
    assert client.get('/api/synthetic-future-read', base_url='https://localhost',
        headers={'X-CSRF-Token':token}).status_code == 200


def test_owner_wialon_preview_cannot_mutate_without_csrf(secure_app, monkeypatch):
    from fleetai import routes
    client = owner_client(secure_app)
    monkeypatch.setattr(routes, '_evaluate_665_stationary_block_preview',
        lambda *args, **kwargs: pytest.fail('Mutating preview must not run without CSRF'))
    response = client.get('/api/wialon/665/block-preview', base_url='https://localhost')
    assert response.status_code == 403


def test_pdf_navigation_is_authorized_and_read_only_without_csrf_header(secure_app):
    from fleetai import db, routes
    from fleetai.models import Car
    with db.Session() as session:
        session.add(Car(code='PDF1', driver='Synthetic'))
        routes._ensure_vehicle_documents_table(session)
        session.execute(text('INSERT INTO vehicle_documents(car_code,license_filename,license_mime_type,license_data,uploaded_at) VALUES (:car,:filename,:mime,:data,:date)'),
            {'car':'PDF1','filename':'synthetic.pdf','mime':'application/pdf','data':b'%PDF-1.4 synthetic','date':datetime(2026,1,1)})
        session.commit()
    client = owner_client(secure_app)
    statements = []
    def record(conn, cursor, statement, parameters, context, many):
        statements.append(statement.strip().upper())
    event.listen(db.engine, 'before_cursor_execute', record)
    try:
        response = client.get('/api/vehicle-license/PDF1', base_url='https://localhost')
        assert response.status_code == 200
        assert response.mimetype == 'application/pdf'
        assert response.data == b'%PDF-1.4 synthetic'
    finally:
        event.remove(db.engine, 'before_cursor_execute', record)
    assert not any(s.startswith(('CREATE ', 'ALTER ', 'INSERT ', 'UPDATE ', 'DELETE ')) for s in statements)
    assert secure_app.test_client().get('/api/vehicle-license/PDF1', base_url='https://localhost').status_code == 401


def test_legacy_driver_column_migrated_before_revocation_triggers(tmp_path, monkeypatch):
    from fleetai import db
    from fleetai.models import Car
    import fleetai.auth  # Register auth metadata, never execute service calls.
    db.configure_database('sqlite:///' + str(tmp_path/'legacy-upgrade.sqlite'))
    columns = [Column(c.name, c.type, primary_key=c.primary_key, nullable=c.nullable)
               for c in Car.__table__.columns if c.name != 'driver']
    legacy_car = Table('cars', MetaData(), *columns)
    legacy_car.create(db.engine)
    assert 'driver' not in {c['name'] for c in inspect(db.engine).get_columns('cars')}
    seen = []
    def require_migrated(conn, cursor, statement, parameters, context, many):
        if statement.strip().upper().startswith('CREATE TRIGGER'):
            assert 'driver' in {c['name'] for c in inspect(conn).get_columns('cars')}
            seen.append(statement)
    event.listen(db.engine, 'before_cursor_execute', require_migrated)
    monkeypatch.setattr(db, 'seed_cars', lambda: None)
    try:
        db.init_db()
    finally:
        event.remove(db.engine, 'before_cursor_execute', require_migrated)
    assert seen
    assert 'driver' in {c['name'] for c in inspect(db.engine).get_columns('cars')}
