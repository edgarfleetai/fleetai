"""Hermes-only finance reads. Never import legacy handlers or use an ORM session."""
from contextlib import contextmanager
from datetime import date, datetime, time, timedelta
import re
import os
from zoneinfo import ZoneInfo

from flask import Blueprint, current_app, g, jsonify, request
from sqlalchemy import select, func, and_, create_engine
from sqlalchemy.exc import SQLAlchemyError
from werkzeug.exceptions import ServiceUnavailable
from . import db
from .models import Car, DriverDebt, DriverWalletTransaction, DriverDebtPayment, Operation

MOSCOW = ZoneInfo("Europe/Moscow")


def read_engine():
    """Deployed reads require an explicitly provisioned SELECT-only datasource."""
    configured = (current_app.config.get('FINANCE_READONLY_DATABASE_URL') or
                  os.getenv('FINANCE_READONLY_DATABASE_URL'))
    if not configured:
        if current_app.testing:
            return db.engine
        raise ServiceUnavailable('A dedicated finance read-only datasource is required')
    engine = current_app.extensions.get('fleetai_finance_readonly_engine')
    if engine is None:
        url = str(configured)
        if url.startswith('postgres://'):
            url = url.replace('postgres://', 'postgresql+psycopg://', 1)
        elif url.startswith('postgresql://'):
            url = url.replace('postgresql://', 'postgresql+psycopg://', 1)
        try:
            engine = create_engine(url, future=True, pool_pre_ping=True)
        except Exception:
            raise ServiceUnavailable('Finance datasource is unavailable') from None
        current_app.extensions['fleetai_finance_readonly_engine'] = engine
    return engine


@contextmanager
def readonly_connection():
    """Enforce read-only at the DB boundary; restore pooled SQLite state."""
    with read_engine().connect() as connection:
        dialect = connection.dialect.name
        previous = None
        try:
            if dialect == "sqlite":
                previous = int(connection.exec_driver_sql("PRAGMA query_only").scalar_one())
                connection.rollback()
                connection.exec_driver_sql("PRAGMA query_only = ON")
                connection.rollback()
                connection.exec_driver_sql("BEGIN")
            elif dialect == "postgresql":
                connection.begin()
                connection.exec_driver_sql("SET TRANSACTION READ ONLY")
            else:
                raise RuntimeError("Read-only finance supports SQLite and PostgreSQL only")
            yield connection
        finally:
            connection.rollback()
            if previous is not None:
                try:
                    connection.exec_driver_sql("PRAGMA query_only = " + ("ON" if previous else "OFF"))
                    connection.rollback()
                except Exception:
                    connection.invalidate()
                    raise


def parameters():
    allowed = {"car_code", "from", "to", "limit", "after_id"}
    if request.path.endswith("/payments"):
        allowed.add("source")
    if set(request.args) - allowed or any(len(request.args.getlist(key)) != 1 for key in request.args):
        raise ValueError("Unknown or repeated query parameter")
    result = {}
    for key, default, minimum, maximum in [("limit", "50", 1, 100), ("after_id", "0", 0, 9223372036854775807)]:
        value = request.args.get(key, default)
        if not re.fullmatch(r"[0-9]{1,19}", value) or not minimum <= int(value) <= maximum:
            raise ValueError("Invalid " + key)
        result[key] = int(value)
    if "car_code" in request.args:
        code = request.args["car_code"]
        if not re.fullmatch(r"[\w-]{1,32}", code):
            raise ValueError("Invalid car_code")
        result["car_code"] = code
    for key in ("from", "to"):
        if key in request.args:
            value = request.args[key]
            if not re.fullmatch(r"\d{4}-\d{2}-\d{2}", value):
                raise ValueError("Dates must be YYYY-MM-DD")
            result[key] = date.fromisoformat(value)
    if result.get("from", date.min) > result.get("to", date.max):
        raise ValueError("from exceeds to")
    if result.get("to") == date.max:
        raise ValueError("to must precede 9999-12-31")
    if request.path.endswith("/payments"):
        result["source"] = request.args.get("source", "operations")
        if result["source"] not in ("operations", "debt_payments"):
            raise ValueError("source must be operations or debt_payments; feeds cannot be combined")
    return result


def filters(table, timestamp, params):
    clauses = []
    if "car_code" in params:
        clauses.append(table.c.car_code == params["car_code"])
    if "from" in params:
        clauses.append(timestamp >= datetime.combine(params["from"], time.min))
    if "to" in params:
        clauses.append(timestamp < datetime.combine(params["to"] + timedelta(days=1), time.min))
    return clauses


def iso(value):
    if value is None:
        return None
    # Legacy dates are stored without offsets; their assumed zone is explicit.
    return (value.replace(tzinfo=MOSCOW) if value.tzinfo is None else value.astimezone(MOSCOW)).isoformat()


def envelope(rows, params, render, **metadata):
    has_more = len(rows) > params["limit"]
    page = rows[:params["limit"]]
    return jsonify(data=[render(row) for row in page], currency="RUB", timezone="Europe/Moscow",
                   as_of=datetime.now(MOSCOW).isoformat(),
                   pagination={"limit": params["limit"], "after_id": params["after_id"],
                               "has_more": has_more, "next_after_id": page[-1]["id"] if has_more else None},
                   **metadata)

bp = Blueprint("hermes_finance", __name__, url_prefix="/api/integrations/hermes/v1")


@bp.errorhandler(SQLAlchemyError)
@bp.errorhandler(ServiceUnavailable)
def finance_unavailable(error):
    # Never return driver errors, DSNs, SQL parameters or credentials.
    return jsonify(error='finance_datasource_unavailable'), 503


@bp.before_request
def require_finance_reader():
    principal = getattr(g, "principal", None)
    if principal is None:
        return jsonify(error="authentication_required"), 401
    field = principal.get if isinstance(principal, dict) else lambda key, default=None: getattr(principal, key, default)
    scopes = field("scopes", ())
    if field("kind") != "hermes" or not isinstance(scopes, (list, tuple, set, frozenset)) or "finance:read" not in scopes:
        return jsonify(error="finance_read_required"), 403


def exclude_test(*columns):
    """Conservative visible-marker exclusion, not inferred reconciliation."""
    # SQLite LOWER is ASCII-only: cover known Russian marker capitalization too.
    tokens = ("test", "simulator", "тест", "Тест", "ТЕСТ", "эмулятор", "Эмулятор", "ЭМУЛЯТОР", "simulation", "demo")
    return and_(*(~func.lower(func.coalesce(column, "")).contains(token) for column in columns for token in tokens))


def read_page(table, params, timestamp, *conditions):
    statement = select(table).where(table.c.id > params["after_id"], *filters(table, timestamp, params), *conditions).order_by(table.c.id).limit(params["limit"] + 1)
    with readonly_connection() as connection:
        return connection.execute(statement).mappings().all()


def rent_accruals(params):
    table = DriverWalletTransaction.__table__
    rows = read_page(table, params, table.c.date, table.c.transaction_type == "daily_rent", table.c.amount < 0,
                     exclude_test(table.c.source, table.c.comment, table.c.external_id))
    return envelope(rows, params, lambda row: {
        "id": f"wallet:{row['id']}", "car_code": row["car_code"],
        "recorded_driver_name": row["driver_name"], "date": iso(row["date"]),
        "amount_minor": int(row["amount"]) * 100, "posted": True,
        "source": row["source"], "source_confidence": "unverified",
    }, ledger="persisted_daily_rent", zero_markers="excluded", projected=False)


def payments(params):
    debt_feed = params["source"] == "debt_payments"
    table = DriverDebtPayment.__table__ if debt_feed else Operation.__table__
    conditions = [table.c.amount > 0]
    if debt_feed:
        conditions.append(exclude_test(table.c.comment))
    else:
        conditions.extend([table.c.type == "income", table.c.category == "Аренда",
                           exclude_test(table.c.raw_message, table.c.description)])
    rows = read_page(table, params, table.c.date, *conditions)

    def render(row):
        value = {"id": f"{'debt_payment' if debt_feed else 'operation'}:{row['id']}",
                 "car_code": row["car_code"], "date": iso(row["date"]),
                 "amount_minor": int(row["amount"]) * 100, "source_confidence": "unverified",
                 "bank_confirmed": None, "reconciliation_required": True}
        if debt_feed:
            value["debt_id"] = f"debt:{row['debt_id']}"
        return value

    return envelope(rows, params, render, feed=params["source"], not_additive_with_operations=debt_feed,
                    excluded_representations=["income", "driver_wallet_transactions", "driver_bank_payments"],
                    completeness="selected_ledger_only", cross_ledger_reconciliation="not_available")


def balances(params):
    car = Car.__table__
    wallet = DriverWalletTransaction.__table__
    debt = DriverDebt.__table__
    # from is a movement window, NEVER an opening-balance reset.
    cutoff_params = {key: value for key, value in params.items() if key != "from"}
    wallet_conditions = [wallet.c.car_code == car.c.code,
                         exclude_test(wallet.c.source, wallet.c.comment, wallet.c.external_id),
                         *filters(wallet, wallet.c.date, cutoff_params)]
    wallet_balance = select(func.coalesce(func.sum(wallet.c.amount), 0)).where(*wallet_conditions).correlate(car).scalar_subquery()
    period_net = select(func.coalesce(func.sum(wallet.c.amount), 0)).where(
        wallet.c.car_code == car.c.code, exclude_test(wallet.c.source, wallet.c.comment, wallet.c.external_id),
        *filters(wallet, wallet.c.date, params)).correlate(car).scalar_subquery()
    last_rent = select(func.max(wallet.c.date)).where(*wallet_conditions, wallet.c.transaction_type == "daily_rent", wallet.c.amount < 0).correlate(car).scalar_subquery()
    fixed_debt = select(func.coalesce(func.sum(debt.c.balance), 0)).where(
        debt.c.car_code == car.c.code, exclude_test(debt.c.reason, debt.c.comment)).correlate(car).scalar_subquery()
    statement = select(car.c.id, car.c.code, car.c.driver, wallet_balance.label("wallet_balance"),
                       period_net.label("period_net"), last_rent.label("last_rent"), fixed_debt.label("fixed_debt")).where(car.c.id > params["after_id"])
    if "car_code" in params:
        statement = statement.where(car.c.code == params["car_code"])
    statement = statement.order_by(car.c.id).limit(params["limit"] + 1)
    with readonly_connection() as connection:
        rows = connection.execute(statement).mappings().all()
    reference_day = min(params.get("to", date.max), datetime.now(MOSCOW).date())

    def render(row):
        last = row["last_rent"]
        return {"id": f"car:{row['id']}", "car_code": row["code"], "current_driver_name": row["driver"],
                "account_scope": "car_legacy_all_assignments", "driver_ownership_verified": False,
                "wallet_balance_amount_minor": int(row["wallet_balance"]) * 100,
                "wallet_period_net_amount_minor": int(row["period_net"]) * 100,
                "fixed_debt_remaining_amount_minor": int(row["fixed_debt"]) * 100,
                "fixed_debt_temporality": "current_not_historical", "ledgers_additive": False,
                "last_posted_rent_date": last.date().isoformat() if last else None,
                "stale": last is None or last.date() < reference_day,
                "source_confidence": "unverified", "reconciliation_required": True}

    return envelope(rows, params, render, ledger="car_wallet", projected=False,
                    wallet_cutoff_date=params["to"].isoformat() if "to" in params else None,
                    period_from=params["from"].isoformat() if "from" in params else None,
                    excludes_known_test_markers=True, completeness="persisted_unverified_ledger_only")


@bp.get("/debts")
@bp.get("/balances")
@bp.get("/rent-accruals")
@bp.get("/payments")
def finance_read():
    try:
        params = parameters()
    except ValueError as error:
        return jsonify(error="invalid_query", detail=str(error)), 400
    if request.path.endswith("/payments"):
        return payments(params)
    if request.path.endswith("/rent-accruals"):
        return rent_accruals(params)
    if request.path.endswith("/balances"):
        return balances(params)
    table = DriverDebt.__table__
    rows = read_page(table, params, table.c.created_at, exclude_test(table.c.reason, table.c.comment))
    return envelope(rows, params, lambda row: {
        "id": f"debt:{row['id']}", "car_code": row["car_code"], "driver_name": row["driver_name"],
        "original_amount_minor": int(row["original_amount"] or 0) * 100,
        "paid_amount_minor": int(row["paid_amount"] or 0) * 100,
        "remaining_amount_minor": int(row["balance"] or 0) * 100,
        "status": row["status"], "created_at": iso(row["created_at"]),
        "closed_at": iso(row["closed_at"]), "source_confidence": "unverified",
    }, ledger="fixed_driver_debts", includes_rental_obligations=False)
