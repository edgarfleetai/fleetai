"""Blueprint-only tests. Every database is disposable SQLite under .test-data."""
from datetime import datetime
from pathlib import Path
import importlib
import os
import tempfile

import pytest

ROOT = Path(__file__).resolve().parents[1]
os.environ["DATABASE_URL"] = "sqlite:///" + str(ROOT / ".test-data" / "finance-readonly-import.sqlite")
PREFIX = "/api/integrations/hermes/v1"


def test_deployed_mode_requires_dedicated_readonly_datasource(finance_client, monkeypatch):
    from fleetai import db
    client, engine, app = finance_client
    app.config['TESTING'] = False
    app.config.pop('FINANCE_READONLY_DATABASE_URL', None)
    monkeypatch.delenv('FINANCE_READONLY_DATABASE_URL', raising=False)
    monkeypatch.setattr(db.engine, 'connect', lambda: pytest.fail('Must not fall back to the writer engine'))
    response = client.get(PREFIX + '/debts')
    assert response.status_code == 503


def test_dedicated_readonly_datasource_does_not_use_writer_connection(finance_client, monkeypatch):
    from fleetai import db
    from fleetai.models import DriverDebt
    client, engine, app = finance_client
    insert(engine, DriverDebt, car_code='700', driver_name='Synthetic', balance=50)
    app.config['FINANCE_READONLY_DATABASE_URL'] = str(engine.url)
    monkeypatch.setattr(db.engine, 'connect', lambda: pytest.fail('The configured readonly engine must be used'))
    try:
        response = client.get(PREFIX + '/debts')
        assert response.status_code == 200
        assert response.json['data'][0]['remaining_amount_minor'] == 5000
    finally:
        readonly = app.extensions.get('fleetai_finance_readonly_engine')
        if readonly is not None:
            readonly.dispose()



@pytest.fixture
def finance_client(monkeypatch):
    from flask import Flask, g
    from sqlalchemy import create_engine
    from fleetai import db
    from fleetai.models import Base

    (ROOT / ".test-data").mkdir(exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="finance-readonly-", dir=ROOT / ".test-data") as directory:
        engine = create_engine("sqlite:///" + str(Path(directory) / "isolated.sqlite"))
        Base.metadata.create_all(engine)
        monkeypatch.setattr(db, "engine", engine)
        app = Flask(__name__)
        app.config["TESTING"] = True
        app.config["TEST_PRINCIPAL"] = {"kind": "hermes", "scopes": ["finance:read"]}

        @app.before_request
        def inject_principal():
            g.principal = app.config["TEST_PRINCIPAL"]

        module = importlib.import_module("fleetai.finance_readonly")
        app.register_blueprint(module.bp)
        yield app.test_client(), engine, app
        engine.dispose()


def insert(engine, model, **values):
    with engine.begin() as connection:
        connection.execute(model.__table__.insert().values(**values))


def test_debts_money_dates_and_cursor(finance_client):
    from fleetai.models import DriverDebt
    client, engine, _ = finance_client
    for id_, code, when in [(1, "665", datetime(2026, 1, 2)), (2, "665", datetime(2026, 1, 3, 23, 59)), (3, "119", datetime(2026, 1, 3))]:
        insert(engine, DriverDebt, id=id_, car_code=code, driver_name="Old driver", original_amount=120, paid_amount=20, balance=100, status="open", created_at=when)
    response = client.get(PREFIX + "/debts?car_code=665&from=2026-01-02&to=2026-01-03&limit=1").get_json()
    assert response["currency"] == "RUB"
    assert response["timezone"] == "Europe/Moscow"
    assert response["data"][0]["id"] == "debt:1"
    assert response["data"][0]["original_amount_minor"] == 12000
    assert response["data"][0]["paid_amount_minor"] == 2000
    assert response["data"][0]["remaining_amount_minor"] == 10000
    assert response["pagination"]["next_after_id"] == 1
    following = client.get(PREFIX + "/debts?car_code=665&limit=1&after_id=1").get_json()
    assert [row["id"] for row in following["data"]] == ["debt:2"]
    assert following["pagination"]["has_more"] is False


@pytest.mark.parametrize("query", ["limit=0", "limit=101", "limit=x", "after_id=-1", "from=20260102", "to=2026-02-30", "from=2026-02-02&to=2026-01-01", "car_code=", "car_code=a%20b", "unknown=yes", "limit=1&limit=2"])
def test_validation(finance_client, query):
    client, _, _ = finance_client
    for endpoint in ("debts", "balances", "rent-accruals", "payments"):
        assert client.get(PREFIX + "/" + endpoint + "?" + query).status_code == 400


def test_posted_rent_only_signed_and_not_test(finance_client):
    from fleetai.models import DriverWalletTransaction as Wallet
    client, engine, _ = finance_client
    for id_, amount, kind, source in [(1, -1800, "daily_rent", "system"), (2, 0, "daily_rent", "system"), (3, -10, "daily_rent", "test"), (4, 500, "topup", "manual"), (5, 10, "daily_rent", "manual")]:
        insert(engine, Wallet, id=id_, car_code="665", amount=amount, transaction_type=kind, source=source, date=datetime(2026, 1, 2))
    response = client.get(PREFIX + "/rent-accruals?from=2026-01-02&to=2026-01-02").get_json()
    assert [row["id"] for row in response["data"]] == ["wallet:1"]
    assert response["data"][0]["amount_minor"] == -180000
    assert response["data"][0]["posted"] is True
    assert response["data"][0]["date"].endswith("+03:00")
    assert response["zero_markers"] == "excluded"
    assert client.get(PREFIX + "/rent-accruals?from=2026-01-03").get_json()["data"] == []


def test_payments_canonical_not_income_or_wallet_and_separate_debt_feed(finance_client):
    from fleetai.models import Operation, Income, DriverWalletTransaction as Wallet, DriverDebtPayment
    client, engine, _ = finance_client
    for id_, marker in [(1, "manual"), (2, "[BANK_SIMULATOR] abc"), (3, "[DRIVER_PORTAL_TEST]"), (4, "[TBANK_PAYMENT:real]"), (5, "Тестовая оплата")]:
        insert(engine, Operation, id=id_, date=datetime(2026, 1, 2), car_code="665", type="income", category="Аренда", amount=123, raw_message=marker)
    insert(engine, Operation, id=6, date=datetime(2026, 1, 2), car_code="665", type="expense", category="Аренда", amount=100)
    insert(engine, Operation, id=7, date=datetime(2026, 1, 2), car_code="665", type="income", category="Продажа", amount=100)
    for id_ in (1, 2):
        insert(engine, Income, id=id_, operation_id=1, amount=123, car_code="665")
    insert(engine, Wallet, car_code="665", amount=123, transaction_type="topup", source="manual")
    insert(engine, DriverDebtPayment, id=1, debt_id=8, driver_name="Driver", car_code="665", amount=50, date=datetime(2026, 1, 2))
    body = client.get(PREFIX + "/payments").get_json()
    assert [row["id"] for row in body["data"]] == ["operation:1", "operation:4"]
    assert body["data"][0]["amount_minor"] == 12300
    assert body["data"][1]["bank_confirmed"] is None
    assert all(row["source_confidence"] == "unverified" and row["reconciliation_required"] for row in body["data"])
    assert body["feed"] == "operations"
    debts = client.get(PREFIX + "/payments?source=debt_payments&car_code=665").get_json()
    assert [row["id"] for row in debts["data"]] == ["debt_payment:1"]
    assert debts["data"][0]["debt_id"] == "debt:8"
    assert debts["not_additive_with_operations"] is True
    assert client.get(PREFIX + "/payments?source=all").status_code == 400


def test_balances_signed_car_ledger_and_fixed_debts_never_added(finance_client):
    from fleetai.models import Car, DriverDebt, DriverWalletTransaction as Wallet
    client, engine, _ = finance_client
    insert(engine, Car, id=1, code="665", driver="Current driver", daily_rent=1800)
    insert(engine, Car, id=2, code="119", driver="Other driver")
    for id_, amount, when, kind, source in [(1, 2000, datetime(2026, 1, 1), "topup", "manual"), (2, -1800, datetime(2026, 1, 2), "daily_rent", "system"), (3, -500, datetime(2026, 1, 3), "debt", "manual"), (4, 99999, datetime(2026, 1, 2), "topup", "test")]:
        insert(engine, Wallet, id=id_, car_code="665", driver_name="Previous driver", amount=amount, date=when, transaction_type=kind, source=source)
    insert(engine, DriverDebt, car_code="665", driver_name="Previous driver", original_amount=900, paid_amount=100, balance=800)
    body = client.get(PREFIX + "/balances?car_code=665").get_json()
    row = body["data"][0]
    assert row["wallet_balance_amount_minor"] == -30000
    assert row["fixed_debt_remaining_amount_minor"] == 80000
    assert row["current_driver_name"] == "Current driver"
    assert row["account_scope"] == "car_legacy_all_assignments"
    assert row["last_posted_rent_date"] == "2026-01-02"
    assert row["stale"] is True
    assert "total_due_amount_minor" not in row
    cutoff = client.get(PREFIX + "/balances?car_code=665&from=2026-01-02&to=2026-01-02").get_json()["data"][0]
    assert cutoff["wallet_balance_amount_minor"] == 20000
    assert cutoff["wallet_period_net_amount_minor"] == -180000
    assert cutoff["fixed_debt_temporality"] == "current_not_historical"
    assert client.get(PREFIX + "/balances?car_code=119").get_json()["data"][0]["last_posted_rent_date"] is None


def test_fixed_debt_markers_excluded(finance_client):
    from fleetai.models import DriverDebt
    client, engine, _ = finance_client
    insert(engine, DriverDebt, driver_name="Driver", original_amount=10, balance=10, reason="Тестовый долг", car_code="665")
    insert(engine, DriverDebt, driver_name="Driver", original_amount=10, balance=10, comment="[BANK_SIMULATOR]", car_code="665")
    assert client.get(PREFIX + "/debts").get_json()["data"] == []


def test_no_writes_no_network_no_legacy_calls_get_head_options(finance_client, monkeypatch):
    import socket
    import sqlite3
    import requests
    from sqlalchemy import event
    from fleetai import routes
    from fleetai.models import Car, DriverDebt, DriverWalletTransaction as Wallet, Operation
    client, engine, _ = finance_client
    insert(engine, Car, code="665", driver="Driver", daily_rent=1800, last_payment_date="2026-01-01")
    insert(engine, Wallet, car_code="665", amount=-1800, transaction_type="daily_rent", source="system", date=datetime(2026, 1, 1))
    insert(engine, Operation, car_code="665", type="income", category="Аренда", amount=100, date=datetime(2026, 1, 1))
    insert(engine, DriverDebt, car_code="665", driver_name="Driver", original_amount=200, balance=200)

    def fail(*args, **kwargs):
        raise AssertionError("Forbidden network/legacy financial call")

    monkeypatch.setattr(socket.socket, "connect", fail)
    monkeypatch.setattr(requests.sessions.Session, "request", fail)
    for name in ("driver_wallet_snapshot", "_sync_daily_rent", "calculate_driver_payment", "api_driver_debts", "api_driver_mvp"):
        monkeypatch.setattr(routes, name, fail)

    def snapshot():
        with sqlite3.connect(engine.url.database) as connection:
            return list(connection.iterdump())

    statements = []
    def record(connection, cursor, statement, parameters, context, many):
        statements.append(statement)

    before = snapshot()
    event.listen(engine, "before_cursor_execute", record)
    try:
        for endpoint in ("debts", "balances", "rent-accruals", "payments"):
            for method in ("GET", "HEAD", "OPTIONS"):
                assert client.open(PREFIX + "/" + endpoint, method=method).status_code == 200
        assert snapshot() == before
        assert statements
        assert all(statement.split()[0].upper() in {"SELECT", "PRAGMA", "BEGIN"} for statement in statements)
        assert any("query_only = ON" in statement for statement in statements)
        with engine.connect() as connection:
            assert connection.exec_driver_sql("PRAGMA query_only").scalar_one() == 0
    finally:
        event.remove(engine, "before_cursor_execute", record)
    # A real writer still works after returning the read connection to its pool.
    insert(engine, Car, code="119")


def test_sqlite_readonly_rejects_writes_and_restores_after_error(finance_client):
    from sqlalchemy.exc import OperationalError
    from fleetai.finance_readonly import readonly_connection
    _, engine, app = finance_client
    with app.app_context(), pytest.raises(OperationalError, match="readonly"):
        with readonly_connection() as connection:
            connection.exec_driver_sql("DELETE FROM cars")
    with engine.connect() as connection:
        assert connection.exec_driver_sql("PRAGMA query_only").scalar_one() == 0
    # Preserve a caller's preexisting query_only=ON, rather than resetting it.
    with engine.connect() as connection:
        connection.exec_driver_sql("PRAGMA query_only = ON")
    try:
        with app.app_context(), readonly_connection() as connection:
            assert connection.exec_driver_sql("PRAGMA query_only").scalar_one() == 1
        with engine.connect() as connection:
            assert connection.exec_driver_sql("PRAGMA query_only").scalar_one() == 1
    finally:
        with engine.connect() as connection:
            connection.exec_driver_sql("PRAGMA query_only = OFF")


def test_object_principal_contract(finance_client):
    from types import SimpleNamespace
    client, _, app = finance_client
    app.config["TEST_PRINCIPAL"] = SimpleNamespace(kind="hermes", scopes=frozenset({"finance:read"}))
    assert client.get(PREFIX + "/debts").status_code == 200
    app.config["TEST_PRINCIPAL"] = {"kind": "hermes", "scopes": "finance:read"}
    assert client.get(PREFIX + "/debts").status_code == 403


def test_page_bound_and_stable_cursor_for_each_registry(finance_client):
    from fleetai.models import Car, DriverDebt, DriverDebtPayment, DriverWalletTransaction as Wallet, Operation
    client, engine, _ = finance_client
    for id_ in range(1, 102):
        insert(engine, Car, id=id_, code=str(id_))
        insert(engine, DriverDebt, id=id_, driver_name="Driver", car_code=str(id_), original_amount=1, balance=1)
        insert(engine, DriverDebtPayment, id=id_, debt_id=id_, car_code=str(id_), amount=1)
        insert(engine, Wallet, id=id_, car_code=str(id_), amount=-1, transaction_type="daily_rent", source="manual")
        insert(engine, Operation, id=id_, car_code=str(id_), amount=1, type="income", category="Аренда")
    for endpoint in ("debts", "balances", "rent-accruals", "payments", "payments?source=debt_payments"):
        delimiter = "&" if "?" in endpoint else "?"
        first = client.get(PREFIX + "/" + endpoint + delimiter + "limit=100").get_json()
        assert len(first["data"]) == 100
        assert first["pagination"]["next_after_id"] == 100
        second = client.get(PREFIX + "/" + endpoint + delimiter + "limit=100&after_id=100").get_json()
        assert len(second["data"]) == 1
        assert second["pagination"]["next_after_id"] is None
        assert second["pagination"]["has_more"] is False
        assert set(row["id"] for row in first["data"]).isdisjoint(row["id"] for row in second["data"])


def test_blueprint_requires_scoped_hermes(finance_client):
    client, _, app = finance_client
    for principal, expected in [(None, 401), ({"kind": "owner", "scopes": ["finance:read"]}, 403),
                                ({"kind": "driver", "scopes": ["finance:read"]}, 403),
                                ({"kind": "hermes", "scopes": []}, 403)]:
        app.config["TEST_PRINCIPAL"] = principal
        for endpoint in ("debts", "balances", "rent-accruals", "payments"):
            for method in ("GET", "HEAD", "OPTIONS"):
                assert client.open(PREFIX + "/" + endpoint, method=method).status_code == expected
    app.config["TEST_PRINCIPAL"] = {"kind": "hermes", "scopes": ["finance:read"]}
    for endpoint in ("debts", "balances", "rent-accruals", "payments"):
        assert client.get(PREFIX + "/" + endpoint).status_code == 200
        assert client.post(PREFIX + "/" + endpoint).status_code == 405
