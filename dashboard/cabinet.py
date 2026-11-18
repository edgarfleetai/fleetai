"""Driver cabinet on the new site (owner's decision, 18.11.2026: the old site is being retired).

Same database and the same access rules as the old FleetAI cabinet:
- the driver enters by a one-time link the owner issues (``/d#token=…``, 24 h, single use);
- the session lives in ``auth_sessions`` (kind ``driver``) and is re-checked on every request
  under the car's row lock: current driver, epoch, link not revoked (fleetai.auth);
- a driver sees only the car the link was issued for.

Reads write nothing: daily rent is accrued by the dashboard's own background job
(dashboard/accrual.py), not by opening the cabinet. The only writes are the login
itself (ticket consumed, session created), logout, and a pending bank payment row
when the driver presses "Оплатить" (it is credited by the bank webhook, exactly once).
"""
import hmac
import time
import uuid
from datetime import datetime
from urllib.parse import quote

from flask import abort, jsonify, request, send_file
from sqlalchemy import func, text, update

COOKIE = "__Host-fa4d"
MAX_PAYMENT = 200_000


def _tbank_ready():
    from fleetai import tbank
    return bool(tbank.TBANK_TERMINAL_KEY and tbank.TBANK_TERMINAL_PASSWORD)


def _tbank_init(amount_rub, order_id, description, back_url):
    """T-Bank acquiring Init; the driver comes back to the new cabinet after paying."""
    import requests
    from fleetai import tbank
    payload = {"TerminalKey": tbank.TBANK_TERMINAL_KEY, "Amount": int(amount_rub) * 100, "OrderId": order_id,
               "Description": description, "SuccessURL": back_url + "?payment=success",
               "FailURL": back_url + "?payment=failed"}
    payload["Token"] = tbank._acquiring_token(payload)
    r = requests.post(f"{tbank.TBANK_ACQUIRING_URL}/Init", json=payload, timeout=30,
                      verify=tbank._get_acquiring_ca_bundle())
    r.raise_for_status()
    result = r.json()
    if not result.get("Success"):
        raise RuntimeError("Банк отклонил платёж")
    return result


def register(app, engine, *, same_origin, public_url, writes_enabled, static_dir, current_owner):
    from fleetai import auth as fa
    from fleetai import db as fleet_db
    from fleetai.auth_models import AuthSession, DriverTicket
    from fleetai.models import Car, DriverBankPayment, DriverWalletTransaction

    def tbank_init():
        return app.config.get("TBANK_INIT") or _tbank_init

    def pay_ready():
        flag = app.config.get("TBANK_READY")
        return writes_enabled and (_tbank_ready() if flag is None else bool(flag))

    def raw_cookie():
        raw = request.cookies.get(COOKIE, "")
        return raw if raw and len(raw) <= 256 else ""

    def open_car(s):
        """(car, auth row) for the signed-in driver, revalidated under the car's lock; else (None, None)."""
        raw = raw_cookie()
        if not raw:
            return None, None
        row = s.get(AuthSession, fa._hash(raw))
        if not row or row.kind != "driver" or row.revoked_at is not None or row.expires_at <= time.time():
            return None, None
        principal = fa.Principal("driver", row.car_code, row.csrf_token, session_hash=row.token_hash)
        car = fa.lock_driver_financial_car(s, principal, row.car_code)
        return (car, row) if car is not None else (None, None)

    def gone():
        resp = jsonify(ok=False, message="Вход закрыт. Попросите у диспетчера новую ссылку.")
        resp.delete_cookie(COOKIE, path="/", secure=True, httponly=True, samesite="Lax")
        return resp, 401

    def csrf_ok(row):
        return same_origin() and hmac.compare_digest(row.csrf_token or "", request.headers.get("X-CSRF", ""))

    @app.get("/d")
    def driver_page():
        if request.query_string and set(request.args) - {"payment", "code"}:
            abort(400)      # the link token travels only in the #fragment, never to the server
        return send_file(static_dir / "driver.html", mimetype="text/html", max_age=0)

    @app.post("/d/login")
    def driver_login():
        if not same_origin():
            abort(403)
        if not writes_enabled:
            return jsonify(ok=False, message="Вход временно недоступен"), 503
        ticket = (request.get_json(silent=True) or {}).get("ticket")
        bad = (jsonify(ok=False, message="Ссылка недействительна или уже использована. "
                                         "Попросите новую у диспетчера."), 401)
        if not isinstance(ticket, str) or not ticket or len(ticket) > 256:
            return bad
        with fleet_db.Session() as s:
            t = s.get(DriverTicket, fa._hash(ticket))
            if not t or t.chat_id != fa.OWNER_LINK or t.consumed_at is not None or t.revoked_at is not None \
                    or t.expires_at <= time.time():
                return bad
            current = fa.lock_driver_assignment(s, t.car_code)
            now = time.time()
            if (t.expires_at <= now or not current or not fa._driver_code_unambiguous(s, t.car_code)
                    or current.driver != t.driver_name or fa._epoch(s, t.car_code) != t.epoch):
                s.rollback()
                return bad
            used = s.execute(update(DriverTicket).where(
                DriverTicket.token_hash == t.token_hash, DriverTicket.consumed_at.is_(None),
                DriverTicket.revoked_at.is_(None), DriverTicket.expires_at > now).values(consumed_at=now))
            if used.rowcount != 1:
                s.rollback()
                return bad
            ttl = fa.link_session_ttl()
            raw = fa._new_session(s, "driver", ttl=ttl, car_code=t.car_code, driver_name=t.driver_name,
                                  chat_id=fa.OWNER_LINK, epoch=t.epoch)
            s.commit()
        resp = jsonify(ok=True)
        resp.set_cookie(COOKIE, raw, max_age=ttl, path="/", secure=True, httponly=True, samesite="Lax")
        return resp

    def snapshot(s, car):
        code = car.code.strip()
        from fleetai.routes import calculate_driver_payment, driver_debt_summary, effective_daily_rent
        balance = int(s.query(func.coalesce(func.sum(DriverWalletTransaction.amount), 0))
                      .filter(func.trim(DriverWalletTransaction.car_code) == code).scalar() or 0)
        daily = int(effective_daily_rent(car) or 0)
        try:
            due = int((calculate_driver_payment(s, car) or {}).get("amount_due", 0) or 0)
        except Exception:
            due = 0
        debts = [d for d in driver_debt_summary(s, car.driver or "")
                 if (d.get("car_code") or "").strip() == code and d.get("balance")]
        txs = (s.query(DriverWalletTransaction).filter(func.trim(DriverWalletTransaction.car_code) == code)
               .order_by(DriverWalletTransaction.date.desc(), DriverWalletTransaction.id.desc()).limit(60).all())
        contract = s.execute(text(
            "SELECT id, signed_at, rental_start_date FROM driver_contracts "
            "WHERE car_code = :c AND driver_name = :d AND status = 'signed' "
            "ORDER BY signed_at DESC LIMIT 1"), {"c": car.code, "d": car.driver}).mappings().first()             if _has_table(s, "driver_contracts") else None
        signed = contract and contract["signed_at"]
        return {
            "car": {"code": code, "brand": car.brand or "", "model": car.model or "", "plate": car.plate or ""},
            "driver": car.driver or "", "balance": balance * 100, "daily_rent": daily * 100,
            "days_left": max(balance // daily, 0) if daily > 0 else None, "rent_due": due * 100,
            "debts": [{"reason": d.get("reason") or d.get("comment") or "Долг", "balance": int(d["balance"]) * 100}
                      for d in debts],
            "transactions": [{"date": t.date.isoformat(timespec="minutes") if t.date else "",
                              "amount": int(t.amount or 0) * 100, "type": t.transaction_type or "",
                              "comment": t.comment or ""} for t in txs],
            "contract": {"signed_at": (signed.isoformat() if hasattr(signed, "isoformat") else str(signed or ""))[:10],
                         "start": contract["rental_start_date"] or ""} if contract else None,
            "max_payment": MAX_PAYMENT * 100,
        }

    @app.get("/api/d/me")
    def driver_me():
        preview = request.args.get("code")
        with fleet_db.Session() as s:
            try:
                if preview is not None:
                    # the owner looks at a driver's cabinet: read only, no payments
                    if not current_owner():
                        abort(401)
                    car = s.query(Car).filter(func.trim(Car.code) == preview.strip()).first()
                    if car is None or not (car.driver or "").strip():
                        abort(404)
                    return jsonify(ok=True, preview=True, pay_ready=False, csrf="", **snapshot(s, car))
                car, row = open_car(s)
                if car is None:
                    return gone()
                out = dict(ok=True, preview=False, pay_ready=pay_ready(), csrf=row.csrf_token, **snapshot(s, car))
            finally:
                s.rollback()          # read only: releases the row lock, writes nothing
        return jsonify(out)

    @app.get("/api/d/contract.pdf")
    def driver_contract():
        with fleet_db.Session() as s:
            try:
                car, _ = open_car(s)
                if car is None:
                    return gone()
                cid = s.execute(text(
                    "SELECT id FROM driver_contracts WHERE car_code = :c AND driver_name = :d AND status = 'signed' "
                    "ORDER BY signed_at DESC LIMIT 1"), {"c": car.code, "d": car.driver}).scalar() \
                    if _has_table(s, "driver_contracts") else None
            finally:
                s.rollback()
        if not cid:
            abort(404)
        from . import contracts
        body = contracts.pdf(engine, cid)
        if body is None:
            abort(404)
        return app.response_class(body, mimetype="application/pdf",
                                  headers={"Content-Disposition": 'inline; filename="dogovor.pdf"'})

    @app.post("/api/d/pay")
    def driver_pay():
        try:
            amount = int((request.get_json(silent=True) or {}).get("amount") or 0)
        except (TypeError, ValueError):
            amount = 0
        with fleet_db.Session() as s:
            car, row = open_car(s)
            if car is None:
                s.rollback()
                return gone()
            if not csrf_ok(row):
                s.rollback()
                abort(403)
            if not pay_ready():
                s.rollback()
                return jsonify(ok=False, message="Оплата картой пока не подключена. Оплатите, как раньше."), 503
            if not 1 <= amount <= MAX_PAYMENT:
                s.rollback()
                return jsonify(ok=False, message=f"Сумма от 1 до {MAX_PAYMENT:,} ₽".replace(",", " ")), 400
            code, driver = car.code, car.driver or ""
            s.rollback()                  # do not hold the car lock while the bank answers
        order_id = f"fleetai-{code.strip()}-{uuid.uuid4().hex[:16]}"
        try:
            res = tbank_init()(amount, order_id, f"Пополнение баланса автомобиля {code.strip()}", public_url + "/d")
        except Exception as error:
            app.logger.warning("tbank init failed: %s", type(error).__name__)
            return jsonify(ok=False, message="Банк сейчас не отвечает. Попробуйте через пару минут."), 502
        pid, url = str(res.get("PaymentId") or "").strip(), str(res.get("PaymentURL") or "").strip()
        if not pid or not url.startswith("https://"):
            return jsonify(ok=False, message="Банк не создал платёж. Попробуйте ещё раз."), 502
        with fleet_db.Session() as s:
            s.add(DriverBankPayment(payment_id=pid, car_code=code, driver_name=driver, amount=amount,
                                    status="pending", provider="tbank", created_at=datetime.now()))
            s.commit()
        return jsonify(ok=True, payment_url=url)

    @app.post("/api/d/logout")
    def driver_logout():
        with fleet_db.Session() as s:
            row = s.get(AuthSession, fa._hash(raw_cookie())) if raw_cookie() else None
            if row and row.kind == "driver" and csrf_ok(row):
                row.revoked_at = time.time()
                s.commit()
        resp = jsonify(ok=True)
        resp.delete_cookie(COOKIE, path="/", secure=True, httponly=True, samesite="Lax")
        return resp

    def link_url(raw):
        return public_url + "/d#token=" + quote(raw, safe="")

    return link_url


def _has_table(s, name):
    from sqlalchemy import inspect
    return inspect(s.get_bind()).has_table(name)
