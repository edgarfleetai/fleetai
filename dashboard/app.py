"""FleetAI 4.0 dashboard: a separate, read-only reporting site.

Run: gunicorn dashboard.app:app
Environment:
  DASHBOARD_DATABASE_URL  read-only PostgreSQL URL (SELECT-only role)
  DASHBOARD_SECRET_KEY    random string for signing the session cookie
  DASHBOARD_PUBLIC_URL    https://<this-service>.onrender.com (exact origin)
  WIALON_TOKEN            optional, for live positions
"""
import hashlib
import hmac
import os
import secrets
import time
from datetime import timedelta
from pathlib import Path
from urllib.parse import urlsplit

from flask import Flask, abort, jsonify, redirect, request, send_file, session
from werkzeug.security import check_password_hash

from . import data, finance, ops, rent, wialon

STATIC = Path(__file__).resolve().parent / "static"
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
    wialon_fetch = app.config.get("WIALON_FETCH") or wialon.fetch_units

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
        return jsonify(finance.fleet_finance(engine, period))

    @app.get("/api/v4/journal")
    def journal_view():
        api_owner()
        days = max(1, min(int(request.args.get("days", 90) or 90), 400))
        return jsonify(finance.journal(engine, days))

    @app.get("/api/v4/repairs")
    def repairs_view():
        api_owner()
        return jsonify(finance.repairs(engine))

    @app.get("/api/v4/rent")
    def rent_view():
        api_owner()
        return jsonify(rent.rent_overview(engine))

    @app.get("/api/v4/contracts")
    def contracts_view():
        api_owner()
        return jsonify(rent.contracts(engine))

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
        ok, results = ops.commit(message, key, engine, save=ops_save)
        return jsonify(ok=ok, results=results), (200 if ok else 400)

    @app.errorhandler(403)
    def forbidden(_):
        return jsonify(ok=False, error="Запрещено"), 403

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
