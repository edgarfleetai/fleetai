"""Rental contracts in the dashboard: the owner fills them in, or sends the driver a link.

Rows go into the existing driver_contracts table; citizenship and migration/patent
data go into dashboard_contract_extra. Validation, hash and PDF are shared with the
driver's contract page in the old FleetAI (fleetai.contract_extra), so both produce
the same document.

Personal data is returned only by contract(), for the owner, never in the list,
the history log or the assistant.
"""
import hashlib
import os
import re
import secrets
import uuid
from datetime import datetime

from sqlalchemy import inspect, text

from fleetai import contract_extra as cx

COUNTRIES = cx.COUNTRIES
INT_FIELDS = ("daily_rent", "deposit")


def _write_engine():
    from fleetai import db as fleet_db
    return fleet_db.engine


def _now():
    return datetime.now().replace(microsecond=0)


def _ensure(eng):
    from fleetai import db as fleet_db
    from fleetai.routes import _ensure_driver_contract_tables
    with fleet_db.Session() as s:
        _ensure_driver_contract_tables(s)
    cx.ensure(eng)


def _money(value, name):
    s = str(value if value is not None else "").replace(" ", "").replace(" ", "")
    if s == "":
        return 0
    if not s.isdigit():
        raise ValueError(f"{name}: целое число рублей")
    return int(s)


def prefill(read_engine, code):
    """What the form can fill in by itself for a car: vehicle, owner, rent, current driver."""
    from fleetai.routes import FLEET_CONTRACT_OWNERS, FLEET_CONTRACT_VEHICLES
    code = str(code or "").strip()
    with read_engine.connect() as conn:
        car = conn.execute(text("SELECT code, brand, model, plate, year, driver, daily_rent, driver_deposit "
                                "FROM cars WHERE TRIM(code) = :c LIMIT 1"), {"c": code}).mappings().first()
    if not car:
        return None
    v = FLEET_CONTRACT_VEHICLES.get(code, {})
    owner = FLEET_CONTRACT_OWNERS.get(code, ("", "Собственник", ""))
    return {"car_code": code, "car_make": v.get("car_make") or car["brand"] or "",
            "car_model": v.get("car_model") or car["model"] or "", "car_plate": v.get("car_plate") or car["plate"] or "",
            "car_vin": v.get("car_vin", ""), "car_year": v.get("car_year") or str(car["year"] or ""),
            "car_sts": v.get("car_sts", ""), "driver_name": car["driver"] or "",
            "daily_rent": int(car["daily_rent"] or 0), "deposit": int(car["driver_deposit"] or 0),
            "owner_name": owner[0], "owner_basis": owner[1], "owner_poa": owner[2],
            "rental_start_date": datetime.now().strftime("%Y-%m-%d")}


def _clean(data):
    cit = str(data.get("citizenship") or "RU").upper()
    vals, ext, missing = cx.clean({k: data.get(k) for k in cx.BASE_FIELDS + cx.EXTRA_FIELDS}, cit)
    if not vals["phone"]:
        # a paper contract may carry a foreign number; signing by call needs a Russian one
        digits = re.sub(r"\D", "", str(data.get("phone") or ""))
        vals["phone"] = digits if 10 <= len(digits) <= 15 else ""
        if not vals["phone"] and "phone" not in missing:
            missing.append("phone")
    vals["daily_rent"] = _money(data.get("daily_rent"), "Аренда в сутки")
    vals["deposit"] = _money(data.get("deposit"), "Залог")
    return cit, vals, ext, missing


def save(read_engine, data, contract_id=None, allow_incomplete=False):
    """Create or update an unsigned contract. Returns (id, missing_fields)."""
    from fleetai.routes import FLEET_CONTRACT_OWNERS, LESSOR_INN, LESSOR_OGRNIP
    cit, vals, ext, missing = _clean(data)
    if missing and not allow_incomplete:
        raise ValueError("Заполните обязательные поля")
    eng = _write_engine()
    _ensure(eng)
    now = _now()
    with eng.begin() as conn:
        if contract_id:
            row = conn.execute(text("SELECT id, status, car_code FROM driver_contracts WHERE id = :i"),
                               {"i": contract_id}).mappings().first()
            if not row:
                raise LookupError("Договор не найден")
            if row["status"] == "signed":
                raise ValueError("Подписанный договор нельзя изменить")
        else:
            code = str(data.get("car_code") or "").strip()
            if not conn.execute(text("SELECT code FROM cars WHERE TRIM(code) = :c"), {"c": code}).first():
                raise ValueError("Выберите машину")
            contract_id = "KP-" + now.strftime("%Y%m%d") + "-" + code + "-" + uuid.uuid4().hex[:6].upper()
            owner = FLEET_CONTRACT_OWNERS.get(code, ("", "Не указано", ""))
            conn.execute(text(
                "INSERT INTO driver_contracts (id, public_token, car_code, status, owner_name, owner_basis, owner_poa, "
                "lessor_name, lessor_inn, lessor_ogrnip, created_at, updated_at) VALUES (:id, :tok, :code, 'draft', "
                ":on, :ob, :op, :ln, :inn, :og, :now, :now)"),
                {"id": contract_id, "tok": secrets.token_urlsafe(32), "code": code, "on": owner[0], "ob": owner[1],
                 "op": owner[2], "ln": (os.getenv("LESSOR_FULL_NAME") or "ИП Лебедкин Эдгар Алексеевич").strip(),
                 "inn": LESSOR_INN, "og": LESSOR_OGRNIP, "now": now})
        fields = cx.BASE_FIELDS + INT_FIELDS
        sets = ", ".join(f"{k} = :{k}" for k in fields)
        conn.execute(text(f"UPDATE driver_contracts SET {sets}, status = :st, updated_at = :now WHERE id = :id"),
                     dict({k: vals.get(k, "") for k in fields}, st="draft" if missing else "ready", now=now, id=contract_id))
        cx.store(conn, contract_id, cit, ext)
        full = _load(conn, contract_id)
        conn.execute(text("UPDATE driver_contracts SET canonical_sha256 = :h WHERE id = :id"),
                     {"h": cx.contract_hash(full), "id": contract_id})
    return contract_id, missing


def _load(conn, contract_id):
    row = conn.execute(text("SELECT * FROM driver_contracts WHERE id = :i"), {"i": contract_id}).mappings().first()
    if not row:
        return None
    out = cx.merged(conn, row)
    out["has_pdf"] = bool(row.get("pdf_data"))
    for k in ("pdf_data", "public_token", "otp_hash"):
        out.pop(k, None)
    return out


def contract(read_engine, contract_id):
    """Full contract with personal data — owner only."""
    if not inspect(read_engine).has_table("driver_contracts"):
        return None
    with read_engine.connect() as conn:
        c = _load(conn, contract_id)
    if not c:
        return None
    for k in ("signed_at", "created_at", "updated_at", "otp_expires_at", "otp_last_sent_at"):
        c[k] = c[k].isoformat(timespec="minutes") if isinstance(c.get(k), datetime) else (str(c[k]) if c.get(k) else "")
    for k in ("sms_id", "otp_attempts"):
        c.pop(k, None)
    return c


def driver_url(read_engine, contract_id, old_site):
    """Link for the driver to check, fill in and sign the contract by phone call (old FleetAI)."""
    with read_engine.connect() as conn:
        row = conn.execute(text("SELECT public_token, status FROM driver_contracts WHERE id = :i"),
                           {"i": contract_id}).mappings().first()
    if not row:
        return None
    return old_site + "/driver-contract?token=" + row["public_token"]


def citizenships(read_engine):
    """id -> citizenship code, for the list (no personal data)."""
    if not inspect(read_engine).has_table("dashboard_contract_extra"):
        return {}
    with read_engine.connect() as conn:
        return {r[0]: r[1] for r in conn.execute(text("SELECT contract_id, citizenship FROM dashboard_contract_extra"))}


def mark_signed(read_engine, contract_id):
    """Signed on paper: store the PDF that was printed and lock the contract."""
    eng = _write_engine()
    _ensure(eng)
    with eng.begin() as conn:
        c = _load(conn, contract_id)
        if not c:
            raise LookupError("Договор не найден")
        if c["status"] == "signed":
            raise ValueError("Договор уже подписан")
        if c["status"] != "ready":
            raise ValueError("Сначала заполните договор полностью")
        h = cx.contract_hash(c)
        c["canonical_sha256"] = h
        pdf = cx.build_pdf(c)
        conn.execute(text("UPDATE driver_contracts SET status = 'signed', signed_at = :now, updated_at = :now, "
                          "canonical_sha256 = :h, pdf_data = :pdf, pdf_sha256 = :ph WHERE id = :id"),
                     {"now": _now(), "h": h, "pdf": pdf, "ph": hashlib.sha256(pdf).hexdigest(), "id": contract_id})
    return c


def pdf(read_engine, contract_id):
    """The stored PDF of a signed contract, otherwise a fresh one for printing."""
    with read_engine.connect() as conn:
        row = conn.execute(text("SELECT status, pdf_data FROM driver_contracts WHERE id = :i"),
                           {"i": contract_id}).mappings().first()
        if not row:
            return None
        if row["status"] == "signed" and row["pdf_data"]:
            return bytes(row["pdf_data"])
        c = _load(conn, contract_id)
    c["canonical_sha256"] = cx.contract_hash(c)
    return cx.build_pdf(c)
