import os
from datetime import timedelta
from urllib.parse import urlsplit
from werkzeug.middleware.proxy_fix import ProxyFix

from flask import Flask, request, jsonify, session, redirect, render_template_string, url_for
from .db import init_db
from .routes import bp
from .admin_auth import verify_admin_password, is_admin
from .login_limiter import login_blocked, record_login_failure, clear_login_failures
from .admin_policy import requires_owner, DANGEROUS_WIALON_COMMAND


LOGIN_HTML = """
<!doctype html><html lang="ru"><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>FleetAI — вход</title>
<form method="post" style="max-width:340px;margin:12vh auto;font-family:sans-serif">
<h2>Вход администратора</h2>
<label>Пароль <input type="password" name="password" required autocomplete="current-password"></label>
<button type="submit">Войти</button>
{% if error %}<p role="alert">{{ error }}</p>{% endif %}
</form></html>
"""


def create_app():
    app = Flask(__name__)
    # Trust forwarded scheme only when explicitly enabled for a known single proxy.
    # Never enable this for a directly exposed application server.
    if os.getenv("FLEETAI_TRUST_PROXY") == "1":
        app.wsgi_app = ProxyFix(app.wsgi_app, x_proto=1, x_for=0, x_host=0, x_port=0, x_prefix=0)
    app.secret_key = os.getenv("FLASK_SECRET_KEY") or os.urandom(32)
    app.config.update(
        SESSION_COOKIE_HTTPONLY=True,
        SESSION_COOKIE_SAMESITE="Lax",
        SESSION_COOKIE_SECURE=os.getenv("FLASK_ENV") != "development",
        PERMANENT_SESSION_LIFETIME=timedelta(hours=8),
    )
    init_db()

    @app.route("/admin/login", methods=["GET", "POST"])
    def admin_login():
        if request.method == "GET":
            return render_template_string(LOGIN_HTML, error=None)
        login_source = request.headers.get("Origin") or request.headers.get("Referer")
        if login_source:
            source_url = urlsplit(login_source)
            if (source_url.scheme, source_url.netloc) != (request.scheme, request.host):
                return render_template_string(LOGIN_HTML, error="Недопустимый источник запроса"), 403
        if not os.getenv("FLASK_SECRET_KEY") or not os.getenv("FLEETAI_ADMIN_PASSWORD_HASH"):
            return render_template_string(LOGIN_HTML, error="Вход не настроен на сервере"), 503
        client_ip = request.remote_addr or "unknown"
        if login_blocked(client_ip):
            return render_template_string(LOGIN_HTML, error="Слишком много попыток. Попробуйте через 15 минут"), 429
        if not verify_admin_password(request.form.get("password", "")):
            record_login_failure(client_ip)
            return render_template_string(LOGIN_HTML, error="Неверный пароль"), 401
        clear_login_failures(client_ip)
        session.clear()
        session["fleetai_admin"] = True
        session.permanent = True
        return redirect("/")

    @app.route("/admin/logout", methods=["POST"])
    def admin_logout():
        source = request.headers.get("Origin") or request.headers.get("Referer")
        if source:
            source_url = urlsplit(source)
            if (source_url.scheme, source_url.netloc) != (request.scheme, request.host):
                return jsonify({"ok": False, "message": "Недопустимый источник запроса"}), 403
        session.clear()
        return redirect(url_for("admin_login"))

    @app.before_request
    def protect_sensitive_routes():
        rule = request.url_rule.rule if request.url_rule else request.path
        # A text confirmation cannot establish engine-off safety.
        # Never dispatch a remote engine-block command from this endpoint.
        if rule == DANGEROUS_WIALON_COMMAND and request.method == "POST":
            data = request.get_json(silent=True) or {}
            action = data.get("action", "") if isinstance(data, dict) else ""
            if isinstance(action, str) and action.strip().lower() == "block":
                return jsonify({"ok": False, "message": "Удалённая блокировка отключена до аппаратной проверки безопасности"}), 403
        if not requires_owner(rule, request.method):
            return None
        if not is_admin():
            if not rule.startswith("/api/"):
                return redirect(url_for("admin_login"))
            return jsonify({"ok": False, "message": "Требуется вход администратора"}), 401
        if request.method in ("POST", "PUT", "PATCH", "DELETE"):
            source = request.headers.get("Origin") or request.headers.get("Referer")
            if not source:
                return jsonify({"ok": False, "message": "Отсутствует источник запроса"}), 403
            source_url = urlsplit(source)
            if (source_url.scheme, source_url.netloc) != (request.scheme, request.host):
                return jsonify({"ok": False, "message": "Недопустимый источник запроса"}), 403
        return None

    @app.after_request
    def protect_admin_responses(response):
        rule = request.url_rule.rule if request.url_rule else request.path
        if rule.startswith("/admin/") or requires_owner(rule, request.method):
            response.headers["Cache-Control"] = "no-store"
            response.headers["X-Content-Type-Options"] = "nosniff"
            response.headers["X-Frame-Options"] = "DENY"
            response.headers["Referrer-Policy"] = "same-origin"
        return response

    app.register_blueprint(bp)
    return app
