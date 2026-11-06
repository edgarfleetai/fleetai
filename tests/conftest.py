"""Test bootstrap: isolate SQLAlchemy and reject all real external transports."""
import os
from pathlib import Path
import socket
import tempfile

import pytest
from flask import Flask
from flask.testing import FlaskClient


class SameOriginTestBrowser(FlaskClient):
    """Test browsers send Fetch Metadata; negative cases explicitly remove it."""
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.environ_base['HTTP_SEC_FETCH_SITE'] = 'same-origin'


Flask.test_client_class = SameOriginTestBrowser

ROOT = Path(__file__).resolve().parents[1]
DATA = ROOT / '.test-data'
DATA.mkdir(exist_ok=True)
os.environ['DATABASE_URL'] = 'sqlite:///' + str(DATA / f'bootstrap-{os.getpid()}.sqlite')
os.environ['TMPDIR'] = str(DATA)
os.environ['PYTHONDONTWRITEBYTECODE'] = '1'
tempfile.tempdir = str(DATA)
# The application under test must never inherit service credentials.
for name in tuple(os.environ):
    if (name.startswith(('TBANK_', 'TELEGRAM_', 'CRON_', 'SMSRU_', 'FLEETAI_AUTH_'))
            or name in {'FINANCE_READONLY_DATABASE_URL', 'FLEETAI_PUBLIC_BASE_URL'}):
        os.environ.pop(name, None)


def denied_network(*args, **kwargs):
    raise AssertionError('External network forbidden in FleetAI security tests')


socket.socket.connect = denied_network
socket.socket.connect_ex = denied_network
socket.create_connection = denied_network

from sqlalchemy import event
from sqlalchemy.engine import Engine


@event.listens_for(Engine, 'do_connect')
def only_isolated_sqlite(dialect, connection_record, args, kwargs):
    if dialect.name != 'sqlite':
        raise AssertionError('Only isolated SQLite is allowed in security tests')
    database = str(args[0]) if args else ''
    if database == ':memory:':
        return
    path = Path(database).resolve()
    if not path.is_relative_to(DATA.resolve()):
        raise AssertionError('SQLite path outside .test-data is forbidden')


@pytest.fixture(autouse=True)
def no_external_requests(monkeypatch):
    import requests
    monkeypatch.setattr(requests.sessions.Session, 'request', denied_network)


@pytest.fixture
def secure_app(tmp_path):
    from fleetai import create_app
    app = create_app({
        'TESTING': True,
        'DATABASE_URL': 'sqlite:///' + str(tmp_path / 'security.sqlite'),
        'INIT_LEGACY_DB': False,
        'AUTH_PASSWORD_METHOD': 'pbkdf2:sha256:1000',
        'SERVER_NAME': 'localhost',
        'PREFERRED_URL_SCHEME': 'https',
    })
    yield app
    from fleetai import db
    db.engine.dispose()
