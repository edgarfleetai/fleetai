"""FleetAI 4.0 dashboard: a separate, read-only reporting site.

Run: gunicorn dashboard.app:app
Environment:
  DASHBOARD_DATABASE_URL  read-only PostgreSQL URL (SELECT-only role)
  DASHBOARD_SECRET_KEY    random string for signing the session cookie
  DASHBOARD_PUBLIC_URL    https://<this-service>.onrender.com (exact origin)
  WIALON_TOKEN            optional, for live positions
  ANTHROPIC_API_KEY       optional, turns on the AI assistant
"""
import hashlib
import hmac
import os
import secrets
import threading
import time
from datetime import timedelta
from pathlib import Path
from urllib.parse import urlsplit

from flask import Flask, abort, jsonify, redirect, request, send_file, session
from werkzeug.security import check_password_hash

from . import accrual, actions, assistant, board, contracts, data, finance, history, invreport, ops, payfix, rent, service, tasks, wialon

STATIC = Path(__file__).resolve().parent / "static"
ACTION_NAMES = {"topup": "Пополнение кошелька водителя", "fine": "Штраф водителю", "assign": "Назначение водителя",
                "add_car": "Новая машина", "close_period": "Закрытие периода"}
ACTION_LOG_FIELDS = ("car_code", "code", "amount", "payment_method", "reason", "driver", "start_date", "daily_rent",
                     "opening_balance", "plate", "investor_name", "investor_percent")
SESSION_HOURS = 8
MAX_FAILS, FAIL_WINDOW = 5, 15 * 60

LOGIN_HTML = """<!doctype html><html lang="ru"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1"><title>Вход — FleetAI 4.0</title>
<style>
:root{--bg:#0b0d0c;--panel:#14171a;--line:#2a2f33;--fg:#eef2ee;--muted:#9aa39c;--lime:#c8f560;--bad:#f07a6a}
*{box-sizing:border-box}body{margin:0;min-height:100vh;display:grid;place-items:center;background:radial-gradient(1200px 600px at 20% -10%,#1d2a12 0,transparent 60%),var(--bg);color:var(--fg);font:15px/1.4 system-ui,-apple-system,Segoe UI,Roboto,sans-serif;padding:16px}
form{width:min(360px,100%);background:var(--panel);border:1px solid var(--line);border-radius:18px;padding:24px;display:flex;flex-direction:column;gap:12px}
h1{margin:0 0 4px;font-size:22px}.logo{display:inline-grid;place-items:center;width:32px;height:32px;border-radius:9px;background:var(--lime);color:#111;font-weight:800;margin-right:8px;font-size:13px}
label{font-size:13px;color:var(--muted);display:flex;flex-direction:column;gap:6px}
input{font:inherit;color:var(--fg);background:#0f1214;border:1px solid var(--line);border-radius:10px;padding:10px 12px}
input:focus{outline:2px solid var(--lime);outline-offset:1px}
button{font:inherit;font-weight:600;border:0;border-radius:10px;padding:11px;background:var(--lime);color:#111;cursor:pointer}
.err{color:var(--bad);font-size:13.5px}.note{color:var(--muted);font-size:12.5px}
</style></head><body><form method="post" action="/login">
<h1><span class="logo">FA</span>FleetAI 4.0</h1>
__ERR__
<label>Имя<input name="username" autocomplete="username" required autofocus></label>
<label>Пароль<input name="password" type="password" autocomplete="current-password" required></label>
<input type="hidden" name="csrf" value="__CSRF__"><button>Войти</button>
<div class="note">Тот же логин и пароль, что в FleetAI. Сайт только показывает данные.</div>
</form></body></html>"""


def create_app(config=None):
    app = Flask(__name__, static_folder=None)
    app.config.update(
        SECRET_KEY=os.environ.get("DASHBOARD_SECRET_KEY"),
        DATABASE_URL=os.environ.get("DASHBOARD_DATABASE_URL"),
        PUBLIC_URL=(os.environ.get("DASHBOARD_PUBLIC_URL") or "").rstrip("/"),
        SESSION_COOKIE_NAME="__Host-fa4",
        SESSION_COOKIE_SECURE=True, SESSION_COOKIE_HTTPONLY=True, SESSION_COOKIE_SAMESITE="Lax",
        PERMANENT_SESSION_LIFETIME=timedelta(hours=SESSION_HOURS),
    )
    if config:
        app.config.update(config)
    if not app.config["SECRET_KEY"] or len(app.config["SECRET_KEY"]) < 32:
        raise RuntimeError("DASHBOARD_SECRET_KEY must be set (32+ characters)")
    if not app.config["DATABASE_URL"]:
        raise RuntimeError("DASHBOARD_DATABASE_URL must be set")
    public = urlsplit(app.config["PUBLIC_URL"])
    if not app.testing and (public.scheme != "https" or not public.netloc or public.path):
        raise RuntimeError("DASHBOARD_PUBLIC_URL must be an https origin, e.g. https://name.onrender.com")
    engine = data.make_engine(app.config["DATABASE_URL"])
    writes_enabled = (os.environ.get("DASHBOARD_READ_ONLY") or "").strip() != "1"
    ops_save = app.config.get("OPS_SAVE")
    if writes_enabled and not ops_save:
        # Operations are saved by the old FleetAI's own save_operation; point its
        # session factory at this database. Reads keep the read-only engine.
        ops.configure_writes(app.config["DATABASE_URL"])
    fails = {}
    cache, cache_lock = {}, threading.Lock()
    CACHE_SECONDS = 150  # warm loop refreshes every ~65 s; writes clear it at once

    key_locks = {}

    def key_lock(key):
        with cache_lock:
            return key_locks.setdefault(key, threading.Lock())

    def fresh(key):
        ttl = 900 if key == "service" else CACHE_SECONDS
        with cache_lock:
            hit = cache.get(key)
            return hit[1] if hit and time.time() - hit[0] < ttl else None

    def cached(key, fn):
        """Heavy read-only calculations are reused; one calculation per key at a
        time — a request waits for the one already running instead of starting
        a second (two at once used to exceed the 30 s worker timeout)."""
        value = fresh(key)
        if value is not None:
            return value
        with key_lock(key):
            value = fresh(key)
            if value is not None:
                return value
            value = fn()
            with cache_lock:
                cache[key] = (time.time(), value)
            return value

    def clear_cache():
        with cache_lock:
            cache.clear()

    def refresh(key, fn):
        with key_lock(key):
            value = fn()
            with cache_lock:
                cache[key] = (time.time(), value)

    def warm_loop():
        """Keep the heavy pages pre-calculated so the home page opens at once."""
        jobs = (("finance:current", lambda: finance.fleet_finance(engine, "current")),
                ("rent", lambda: rent.rent_overview(engine)),
                ("journal:90", lambda: finance.journal(engine, 90)))
        cycle = 0
        last_accrual = time.time() - 1740   # first run a minute after start, when the app is fully set up
        while True:
            if writes_enabled and not ops_save and app.config.get("RENT_ACCRUAL", True) \
                    and time.time() - last_accrual > 1800:
                last_accrual = time.time()
                try:   # daily rent for every car with a driver (FleetAI's cron stopped)
                    done = accrual.accrue_all()
                    if done:
                        accrual_audit(done, "автоматически")
                        clear_cache()
                except Exception as error:
                    app.logger.warning("rent accrual failed: %s", type(error).__name__)
            # mileage/maintenance reads Wialon history: every ~10 minutes is enough
            extra = (("service", lambda: service_data()),) if cycle % 12 == 0 else ()
            if writes_enabled and not ops_save:
                try:   # catches changes made through the bot / old site (at most hourly)
                    from fleetai import db as fleet_db
                    if history.snapshot_and_compare(engine, fleet_db.engine):
                        clear_cache()
                except Exception as error:
                    app.logger.warning("snapshot failed: %s", type(error).__name__)
            for key, fn in jobs + extra:
                try:
                    refresh(key, fn)
                except Exception as error:  # keep warming; a request will show the error
                    app.logger.warning("cache warm %s failed: %s", key, type(error).__name__)
            cycle += 1
            time.sleep(45)

    if not app.testing and app.config.get("WARM_CACHE", True):
        threading.Thread(target=warm_loop, name="fa4-cache-warm", daemon=True).start()
    wialon_fetch = app.config.get("WIALON_FETCH") or wialon.fetch_units
    odo_fetch = app.config.get("ODO_FETCH") or wialon.fetch_odometers

    def same_origin():
        origin = request.headers.get("Origin")
        if origin is not None:
            return origin == app.config["PUBLIC_URL"]
        return request.headers.get("Sec-Fetch-Site") == "same-origin"

    def fingerprint(password_hash):
        return hashlib.sha256(password_hash.encode()).hexdigest()[:32]

    def current_owner():
        user, fp, iat = session.get("u"), session.get("fp"), session.get("iat", 0)
        if not user or not fp or time.time() - iat > SESSION_HOURS * 3600:
            return None
        owner = data.find_owner(engine, user)
        # A password change in FleetAI ends dashboard sessions too.
        if not owner or not hmac.compare_digest(fingerprint(owner["password_hash"]), fp):
            return None
        return owner["username"]

    def login_page(error="", status=200):
        token = session.get("csrf") or secrets.token_urlsafe(32)
        session["csrf"] = token
        html = LOGIN_HTML.replace("__CSRF__", token).replace(
            "__ERR__", f'<div class="err">{error}</div>' if error else "")
        return html, status, {"Content-Type": "text/html; charset=utf-8"}

    @app.after_request
    def headers(resp):
        resp.headers["X-Content-Type-Options"] = "nosniff"
        resp.headers["Referrer-Policy"] = "same-origin"
        resp.headers["X-Frame-Options"] = "DENY"
        resp.headers["Content-Security-Policy"] = (
            "default-src 'self'; script-src 'self' 'unsafe-inline'; "
            "style-src 'self' 'unsafe-inline' https://fonts.googleapis.com; font-src https://fonts.gstatic.com; "
            "img-src 'self' data:; connect-src 'self'; frame-ancestors 'none'; base-uri 'none'; form-action 'self'")
        if not app.testing:
            resp.headers["Strict-Transport-Security"] = "max-age=31536000"
        resp.headers["Cache-Control"] = "no-store"
        return resp

    @app.get("/healthz")
    def healthz():
        return jsonify(ok=True)

    @app.route("/login", methods=["GET", "POST"])
    def login():
        if request.method == "GET":
            return redirect("/") if current_owner() else login_page()
        if not same_origin() or not hmac.compare_digest(session.get("csrf", ""), request.form.get("csrf", "")):
            return login_page("Сессия устарела, попробуйте ещё раз.", 403)
        username = (request.form.get("username") or "").strip().casefold()[:128]
        password = (request.form.get("password") or "")[:1024]
        key = (request.remote_addr or "?") + "|" + username
        now = time.time()
        recent = [t for t in fails.get(key, []) if now - t < FAIL_WINDOW]
        if len(recent) >= MAX_FAILS:
            return login_page("Слишком много попыток. Подождите 15 минут.", 429)
        owner = data.find_owner(engine, username) if username else None
        if not owner or not password or not check_password_hash(owner["password_hash"], password):
            fails[key] = recent + [now]
            return login_page("Неверное имя или пароль.", 401)
        fails.pop(key, None)
        session.clear()
        session.permanent = True
        session.update(u=owner["username"], fp=fingerprint(owner["password_hash"]), iat=int(now),
                       csrf=secrets.token_urlsafe(32))
        return redirect("/", code=303)

    @app.post("/logout")
    def logout():
        if same_origin() and hmac.compare_digest(session.get("csrf", ""), request.headers.get("X-CSRF", "")):
            session.clear()
            return jsonify(ok=True)
        abort(403)

    @app.get("/")
    def index():
        if not current_owner():
            return redirect("/login")
        return send_file(STATIC / "index.html", mimetype="text/html", max_age=0)

    def api_owner():
        owner = current_owner()
        if not owner:
            abort(401)
        return owner

    @app.get("/api/v4/fleet")
    def fleet():
        owner = api_owner()
        result = data.load_fleet(engine)
        result.update(owner=owner, csrf=session.get("csrf", ""), generated_at=int(time.time()))
        return jsonify(result)

    @app.get("/api/v4/finance")
    def finance_view():
        api_owner()
        period = "previous" if request.args.get("period") == "previous" else "current"
        return jsonify(cached("finance:" + period, lambda: finance.fleet_finance(engine, period)))

    @app.get("/api/v4/investors/report")
    def investor_report_view():
        api_owner()
        key = request.args.get("investor", "")
        if key not in invreport.NAMES:
            abort(404)
        try:
            idx = max(0, min(int(request.args.get("period", 0) or 0), invreport.MAX_PERIODS - 1))
        except ValueError:
            idx = 0
        return jsonify(cached(f"invreport:{key}:{idx}", lambda: invreport.investor_report(engine, key, idx)))

    @app.get("/api/v4/journal")
    def journal_view():
        api_owner()
        days = max(1, min(int(request.args.get("days", 90) or 90), 400))
        return jsonify(cached(f"journal:{days}", lambda: finance.journal(engine, days)))

    @app.get("/api/v4/repairs")
    def repairs_view():
        api_owner()
        days = int(request.args.get("days", 180) or 180)
        days = days if days in (180, 365, 3650) else 180
        return jsonify(cached(f"repairs:{days}", lambda: finance.repairs(engine, days)))

    @app.get("/api/v4/rent")
    def rent_view():
        api_owner()
        return jsonify(cached("rent", lambda: rent.rent_overview(engine)))

    def accrual_audit(done, how):
        for x in done:
            parts = []
            if x["charged"]:
                parts.append(f"списано {x['charged']} дн. × {x['daily']} ₽")
            if x["downtime"]:
                parts.append(f"простой {x['downtime']} дн.")
            history.log("rent_accrual", f"Аренда {x['car']} ({how}): " + ", ".join(parts), car_code=x["car"],
                        actor=current_owner_safe(), source="dashboard")

    def current_owner_safe():
        try:
            return current_owner() or "система"
        except Exception:
            return "система"

    @app.post("/api/v4/rent/accrue")
    def rent_accrue():
        write_guard()
        done = accrual.accrue_all()
        accrual_audit(done, "вручную")
        clear_cache()
        days = sum(x["charged"] for x in done)
        total = sum(x["charged"] * x["daily"] for x in done)
        return jsonify(ok=True, cars=done, message=(f"Досписано: {days} дн. на {total:,} ₽ по {len(done)} маш.".replace(",", " ")
                                                    if done else "Всё уже списано по сегодняшний день"))

    @app.get("/api/v4/rent/unposted")
    def rent_unposted():
        api_owner()
        return jsonify(ok=True, payments=payfix.unposted(engine))

    @app.post("/api/v4/rent/unposted")
    def rent_unposted_credit():
        write_guard()
        ids = (request.get_json(silent=True) or {}).get("data", {}).get("ids") or []
        try:
            ids = [int(x) for x in ids][:200]
        except (TypeError, ValueError):
            return jsonify(ok=False, message="Неверный список"), 400
        done = payfix.credit(engine, ids)
        for op_id, car, amount in done:
            audit("wallet_fix", f"Зачтена в баланс водителя оплата #{op_id}: {car} {amount} ₽", car=car, op_ids=[op_id])
        clear_cache()
        total = sum(a for _, _, a in done)
        return jsonify(ok=True, count=len(done), total=total * 100,
                       message=f"Зачтено оплат: {len(done)} на {total:,} ₽".replace(",", " ") if done else "Нечего зачитывать")

    @app.get("/api/v4/contracts")
    def contracts_view():
        api_owner()
        out = rent.contracts(engine)
        cit = contracts.citizenships(engine)
        for c in out["contracts"]:
            c["citizenship"] = cit.get(c["id"], "RU")
        out["old_site"] = OLD_SITE
        return jsonify(out)

    @app.get("/api/v4/contracts/prefill")
    def contract_prefill():
        api_owner()
        found = contracts.prefill(engine, request.args.get("car"))
        if not found:
            return jsonify(ok=False, message="Машина не найдена"), 404
        return jsonify(ok=True, data=found, countries={k: [v[0], v[1], v[2]] for k, v in contracts.COUNTRIES.items()})

    @app.get("/api/v4/contracts/<cid>")
    def contract_one(cid):
        api_owner()
        found = contracts.contract(engine, cid)
        if not found:
            return jsonify(ok=False, message="Договор не найден"), 404
        return jsonify(ok=True, data=found, countries={k: [v[0], v[1], v[2]] for k, v in contracts.COUNTRIES.items()})

    @app.get("/api/v4/contracts/<cid>/link")
    def contract_link(cid):
        api_owner()
        url = contracts.driver_url(engine, cid, OLD_SITE)
        if not url:
            return jsonify(ok=False, message="Договор не найден"), 404
        return jsonify(ok=True, url=url)

    @app.get("/api/v4/cars/<code>/driver-link")
    @app.post("/api/v4/cars/<code>/driver-link")
    @app.post("/api/v4/cars/<code>/driver-link/<what>")
    def driver_link(code, what=None):
        """One-time 24 h link into the driver's cabinet (old FleetAI) for drivers without Telegram."""
        from fleetai import auth as fleet_auth
        from fleetai import db as fleet_db
        if request.method == "GET":
            api_owner()
            with fleet_db.Session() as s:
                return jsonify(ok=True, **fleet_auth.driver_link_status(s, code))
        write_guard()
        if what not in (None, "revoke"):
            return jsonify(ok=False, message="Неверный запрос"), 400
        with fleet_db.Session() as s:
            if what == "revoke":
                n = fleet_auth.revoke_driver_links(s, code)
                s.commit()
                audit("driver_link", f"Закрыт доступ в кабинет по ссылке: {code}", car=code)
                return jsonify(ok=True, message="Доступ закрыт" if n else "Открытых ссылок не было")
            try:
                raw, driver = fleet_auth.issue_driver_link(s, code)
            except ValueError as error:
                s.rollback()
                return jsonify(ok=False, message=str(error)), 400
            s.commit()
        from urllib.parse import quote
        audit("driver_link", f"Выдана ссылка в кабинет водителя {code}", car=code)
        return jsonify(ok=True, url=OLD_SITE + "/auth/driver#token=" + quote(raw, safe=""), driver=driver,
                       message="Ссылка действует 24 часа и открывается один раз")

    @app.get("/api/v4/contracts/<cid>/pdf")
    def contract_pdf(cid):
        api_owner()
        body = contracts.pdf(engine, cid)
        if body is None:
            abort(404)
        name = "dogovor_" + "".join(ch for ch in cid if ch.isalnum() or ch == "-") + ".pdf"
        return app.response_class(body, mimetype="application/pdf",
                                  headers={"Content-Disposition": f'inline; filename="{name}"'})

    @app.post("/api/v4/contracts")
    @app.post("/api/v4/contracts/<cid>/<what>")
    def contract_change(cid=None, what=None):
        write_guard()
        body = (request.get_json(silent=True) or {}).get("data") or {}
        try:
            if what == "signed":
                c = contracts.mark_signed(engine, cid)
                audit("contract", f"Договор {cid} подписан на бумаге", car=str(c.get("car_code") or "").strip())
                return jsonify(ok=True, id=cid, message="Отмечен как подписанный")
            if cid is not None and what != "save":
                return jsonify(ok=False, message="Неверный запрос"), 400
            new_id, missing = contracts.save(engine, body, contract_id=cid, allow_incomplete=bool(body.get("draft")))
            audit("contract", ("Изменён" if cid else "Создан") + f" договор {new_id}"
                  + (" (черновик)" if missing else ""), car=str(body.get("car_code") or new_id.split("-")[2]))
            return jsonify(ok=True, id=new_id, missing=missing,
                           message="Черновик сохранён" if missing else "Договор готов")
        except LookupError as error:
            return jsonify(ok=False, message=str(error)), 404
        except ValueError as error:
            try:
                fields = contracts._clean(body)[3] if what != "signed" else []
            except ValueError:
                fields = []
            return jsonify(ok=False, message=str(error), missing=fields), 400

    OLD_SITE = str(app.config.get("OLD_SITE_URL") or os.getenv("FLEETAI_OLD_URL") or "https://fleetai-1.onrender.com").rstrip("/")

    def audit(kind, summary, car="", op_ids=None):
        if not writes_enabled or ops_save:
            return
        history.log(kind, summary, car_code=car, actor=current_owner() or "", source="dashboard",
                    detail={"op_ids": op_ids or []})

    def op_row(op_id):
        from sqlalchemy import text as sql
        with engine.connect() as conn:
            r = conn.execute(sql("SELECT car_code, amount, raw_message, description FROM operations WHERE id = :i"),
                             {"i": op_id}).mappings().first()
        return {"car": str(r["car_code"] or "").strip(), "amount": int(r["amount"] or 0),
                "raw": (r["raw_message"] or "")[:200], "description": (r["description"] or "")[:200]} if r else None

    def write_guard():
        api_owner()
        if not writes_enabled:
            abort(403)
        if not same_origin() or not hmac.compare_digest(session.get("csrf", ""), request.headers.get("X-CSRF", "")):
            abort(403)

    @app.post("/api/v4/ops/preview")
    def ops_preview():
        write_guard()
        message = str((request.get_json(silent=True) or {}).get("message") or "")[:ops.MAX_LEN]
        items = ops.parse_all(message, engine)
        return jsonify(ok=bool(items) and not any(i["problem"] for i in items),
                       items=ops.public(items), fingerprint=ops.fingerprint(message))

    @app.post("/api/v4/ops/commit")
    def ops_commit():
        write_guard()
        body = request.get_json(silent=True) or {}
        message = str(body.get("message") or "")[:ops.MAX_LEN]
        key = str(body.get("key") or "")[:64]
        if len(key) < 16 or body.get("fingerprint") != ops.fingerprint(message):
            return jsonify(ok=False, results=[{"ok": False, "message": "Команда изменилась после проверки — проверьте ещё раз"}]), 409
        before = history.max_op_id(engine)
        ok, results = ops.commit(message, key, engine, save=ops_save)
        clear_cache()
        new_ids = history.op_ids_since(engine, before)
        for r in results:
            if r.get("ok") and r.get("raw"):
                audit("operation", "Записано: " + r["raw"], car=r["raw"].split()[0], op_ids=new_ids)
        return jsonify(ok=ok, results=results), (200 if ok else 400)

    @app.post("/api/v4/act/<name>")
    def run_action(name):
        write_guard()
        body = request.get_json(silent=True) or {}
        key = str(body.get("key") or "")[:64]
        if len(key) < 16:
            return jsonify(ok=False, message="Нет ключа операции"), 400
        before = history.max_op_id(engine)
        payload = body.get("data") or {}
        status, result = actions.run(app, name, payload, name + ":" + key,
                                     views=app.config.get("ACTION_VIEWS"))
        clear_cache()
        if status < 400 and result.get("ok", True) and isinstance(payload, dict):
            car = str(payload.get("car_code") or payload.get("code") or "")
            shown = {k: v for k, v in payload.items() if k in ACTION_LOG_FIELDS}
            audit("action:" + name, f"{ACTION_NAMES.get(name, name)}: " +
                  ", ".join(f"{k}={v}" for k, v in shown.items()), car=car,
                  op_ids=history.op_ids_since(engine, before))
        return jsonify(result), status

    @app.post("/api/v4/op/<int:op_id>/<what>")
    def change_operation(op_id, what):
        write_guard()
        body = request.get_json(silent=True) or {}
        key = str(body.get("key") or "")[:64]
        if len(key) < 16 or what not in ("delete", "edit"):
            return jsonify(ok=False, message="Неверный запрос"), 400
        views = app.config.get("ACTION_VIEWS")
        old = op_row(op_id)
        before = history.max_op_id(engine)
        if what == "delete":
            status, result = actions.delete_operation(app, engine, op_id, key, views=views)
        else:
            status, result = actions.edit_operation(app, engine, op_id, body.get("data") or {}, key,
                                                    views=views, save=ops_save)
        clear_cache()
        if status < 400 and old:
            was = f'#{op_id} {old["car"]} {old["amount"]} ₽ «{old["raw"] or old["description"]}»'
            if what == "delete":
                audit("op_deleted", "Удалена операция " + was, car=old["car"], op_ids=[op_id])
            else:
                new = str((body.get("data") or {}).get("message") or "")[:300]
                audit("op_edited", f"Исправлена операция {was} → «{new}»", car=old["car"],
                      op_ids=[op_id] + history.op_ids_since(engine, before))
        return jsonify(result), status

    @app.get("/api/v4/board")
    def board_list():
        api_owner()
        return jsonify(cards=board.list_cards(engine))

    @app.post("/api/v4/board")
    @app.post("/api/v4/board/<int:card_id>")
    @app.post("/api/v4/board/<int:card_id>/<what>")
    def board_change(card_id=None, what=None):
        write_guard()
        data = (request.get_json(silent=True) or {}).get("data") or {}
        try:
            if card_id is None:
                new_id = board.create_card(data)
                audit("board", f"Новый кандидат в водители: {data.get('name', '')}", car=data.get("car_code", ""))
                return jsonify(ok=True, id=new_id, message="Водитель добавлен")
            if what == "delete":
                n = board.delete_card(card_id)
                audit("board", f"Удалена карточка водителя #{card_id}")
                return jsonify(ok=bool(n), message="Карточка удалена" if n else "Карточка не найдена"), (200 if n else 404)
            n = board.update_card(card_id, data)
            shown = {k: v for k, v in data.items() if k in ("name", "stage", "car_code")}
            audit("board", f"Карточка водителя #{card_id}: " + ", ".join(f"{k}={v}" for k, v in shown.items()))
            return jsonify(ok=bool(n), message="Сохранено" if n else "Карточка не найдена"), (200 if n else 404)
        except ValueError as error:
            return jsonify(ok=False, message=str(error)), 400

    @app.get("/api/v4/history")
    def history_view():
        api_owner()
        days = max(1, min(int(request.args.get("days", 30) or 30), 365))
        return jsonify(events=history.events(engine, request.args.get("car") or None, days))

    @app.get("/api/v4/tasks")
    def tasks_view():
        api_owner()
        return jsonify(tasks=tasks.list_tasks(engine))

    @app.post("/api/v4/tasks")
    @app.post("/api/v4/tasks/<int:task_id>/<what>")
    def tasks_change(task_id=None, what=None):
        write_guard()
        body = (request.get_json(silent=True) or {}).get("data") or {}
        try:
            if task_id is None:
                new_id, created = tasks.create_task(body, source="owner")
                if created:
                    audit("task", "Новая задача: " + str(body.get("title", ""))[:200], car=str(body.get("car_code") or ""))
                return jsonify(ok=True, id=new_id, message="Задача добавлена" if created else "Такая задача уже есть")
            if what not in ("delete", "done", "open"):
                return jsonify(ok=False, message="Неверный запрос"), 400
            row = tasks.delete_task(task_id) if what == "delete" else tasks.set_status(task_id, what)
            if not row:
                return jsonify(ok=False, message="Задача не найдена"), 404
            word = {"delete": "Удалена", "done": "Выполнена", "open": "Снова открыта"}[what]
            audit("task", f"{word} задача: {row['title']}", car=row["car_code"])
            return jsonify(ok=True, message=word)
        except ValueError as error:
            return jsonify(ok=False, message=str(error)), 400

    def assistant_create_task(values):
        if not writes_enabled:
            raise ValueError("Сайт в режиме только чтения — задачи не создаются")
        new_id, created = tasks.create_task(values, source="assistant")
        if created and not ops_save:
            history.log("task", "Помощник поставил задачу: " + str(values.get("title"))[:200],
                        car_code=values.get("car_code") or "", actor="ИИ-помощник", source="assistant",
                        detail={"op_ids": []})
        return new_id, created

    def assistant_positions():
        units, error = wialon_fetch()
        return data.match_units_to_cars(units, data.load_fleet(engine)["cars"]), error

    helper = assistant.Assistant({
        "fleet": lambda: data.load_fleet(engine),
        "finance": lambda period: cached("finance:" + period, lambda: finance.fleet_finance(engine, period)),
        "rent": lambda: cached("rent", lambda: rent.rent_overview(engine)),
        "journal": lambda days: cached(f"journal:{days}", lambda: finance.journal(engine, days)),
        "repairs": lambda days: cached(f"repairs:{days}", lambda: finance.repairs(engine, days)),
        "service": lambda: cached("service", service_data),
        "history": lambda car, days: history.events(engine, car, days),
        "positions": assistant_positions,
        "tasks": lambda status: tasks.list_tasks(engine, status),
        "create_task": assistant_create_task,
        "preview": lambda message: ops.parse_all(message, engine),
    }, client_factory=app.config.get("ASSISTANT_CLIENT"), sync=bool(app.config.get("ASSISTANT_SYNC")),
        logger=app.logger)

    def assistant_on():
        return bool(app.config.get("ASSISTANT_CLIENT")) or helper.configured()

    @app.get("/api/v4/assistant")
    def assistant_status():
        api_owner()
        return jsonify(ok=True, enabled=assistant_on(), model=assistant.MODEL)

    @app.post("/api/v4/assistant")
    def assistant_ask():
        write_guard()   # every question costs money: same login / CSRF / origin checks as writes
        if not assistant_on():
            return jsonify(ok=False, message="Помощник не подключён: добавьте ANTHROPIC_API_KEY в Render"), 503
        body = request.get_json(silent=True) or {}
        try:
            job_id, conv_id = helper.ask(current_owner(), body.get("message"), body.get("conv"))
        except ValueError as error:
            return jsonify(ok=False, message=str(error)), 400
        return jsonify(ok=True, job=job_id, conv=conv_id)

    @app.get("/api/v4/assistant/job/<job_id>")
    def assistant_job(job_id):
        owner = api_owner()
        j = helper.job(owner, job_id[:40])
        if not j:
            return jsonify(ok=False, message="Ответ не найден — спросите ещё раз"), 404
        return jsonify(ok=True, **j)

    @app.errorhandler(403)
    def forbidden(_):
        return jsonify(ok=False, error="Запрещено"), 403

    def service_data():
        units, _ = wialon_fetch()
        cars_now = data.load_fleet(engine)["cars"]
        by_car = {u["car_code"]: u["id"] for u in data.match_units_to_cars(units, cars_now) if u.get("car_code")}
        write_engine = None
        if writes_enabled and not ops_save:
            from fleetai import db as fleet_db
            write_engine = fleet_db.engine
        return service.overview(engine, by_car, odo_fetch, write_engine=write_engine)

    @app.get("/api/v4/service")
    def service_view():
        api_owner()
        return jsonify(cached("service", service_data))

    @app.get("/api/v4/positions")
    def positions():
        api_owner()
        units, error = wialon_fetch()
        cars = data.load_fleet(engine)["cars"]
        return jsonify(ok=error is None, error=error, units=data.match_units_to_cars(units, cars),
                       generated_at=int(time.time()))

    @app.errorhandler(401)
    def unauthorized(_):
        return jsonify(ok=False, error="Нужен вход"), 401

    return app


app = create_app() if os.environ.get("DASHBOARD_DATABASE_URL") else None
