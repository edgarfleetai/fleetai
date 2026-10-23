import os
import secrets
from datetime import timedelta
from pathlib import Path
from urllib.parse import urlsplit
from werkzeug.middleware.proxy_fix import ProxyFix

from flask import Flask, request, jsonify, session, redirect, render_template_string, url_for
from .db import init_db
from .routes import bp
from .mcp_readonly import bp_mcp
from .assistant_voice_api import bp_assistant_voice
from .driver_move_api import bp_driver_move
from .voice_finance_api import bp_voice_finance
from .voice_wallet_api import bp_voice_wallet
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

    @app.route("/dashboard-preview", methods=["GET"])
    def dashboard_preview():
        # Read-only UI prototype: uses hardcoded demo data, no database access.
        html = Path(__file__).with_name("dashboard_preview.html").read_text(encoding="utf-8")
        return app.response_class(html, mimetype="text/html", headers={"Cache-Control": "no-store", "X-Frame-Options": "DENY"})

    @app.route("/api/assistant/capabilities", methods=["GET"])
    def assistant_capabilities():
        """Owner-only read-only integration discovery; no model calls or mutations."""
        if not is_admin():
            return jsonify({"ok": False, "message": "Требуется вход администратора"}), 401
        return jsonify({
            "ok": True,
            "enabled": False,
            "mode": "read_only",
            "model_connected": False,
            "data_sources": {
                "cars": "/api/overview-readonly",
                "finances": "/api/finance-ledger-readonly",
                "investors": "/api/investor-ledger-readonly",
                "repairs": "/api/repair-history-readonly",
            },
            "actions_enabled": [],
            "message": "Интерфейс подключения готов. ИИ-модель ещё не подключена.",
        })

    @app.route("/api/admin/csrf-token", methods=["GET"])
    def admin_csrf_token():
        if not is_admin():
            return jsonify({"ok": False, "message": "Требуется вход администратора"}), 401
        token = session.get("fleetai_csrf_token")
        if not token:
            token = secrets.token_urlsafe(32)
            session["fleetai_csrf_token"] = token
        return jsonify({"ok": True, "csrf_token": token})

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
        session["fleetai_csrf_token"] = secrets.token_urlsafe(32)
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
        # MCP performs its own constant-time bearer authentication and never writes.
        if rule == "/mcp" and request.method == "POST":
            return None
        if rule in ("/.well-known/oauth-protected-resource", "/.well-known/oauth-protected-resource/mcp") and request.method == "GET":
            return None
        # Isolated staging is owner-only and read-only.
        if os.getenv("FLEETAI_STAGING_LOCKDOWN") == "1":
            if rule not in ("/admin/login", "/admin/logout", "/static/<path:filename>"):
                if not is_admin():
                    if rule.startswith("/api/"):
                        return jsonify({"ok": False, "message": "Требуется вход администратора"}), 401
                    return redirect(url_for("admin_login"))
                if request.method not in ("GET", "HEAD", "OPTIONS"):
                    return jsonify({"ok": False, "message": "Тестовый стенд доступен только для чтения"}), 403
        if not requires_owner(rule, request.method):
            return None
        if not is_admin():
            if not rule.startswith("/api/"):
                return redirect(url_for("admin_login"))
            return jsonify({"ok": False, "message": "Требуется вход администратора"}), 401
        if request.method in ("POST", "PUT", "PATCH", "DELETE"):
            if os.getenv("FLEETAI_REQUIRE_CSRF_TOKEN") == "1":
                expected = session.get("fleetai_csrf_token", "")
                supplied = request.headers.get("X-FleetAI-CSRF-Token", "")
                if not expected or not supplied or not secrets.compare_digest(expected, supplied):
                    return jsonify({"ok": False, "message": "Неверный CSRF-токен"}), 403
            # Browser Fetch Metadata offers defense-in-depth even when Origin is absent.
            # Do not trust it as a substitute for a session-bound CSRF token.
            fetch_site = request.headers.get("Sec-Fetch-Site", "").lower()
            if fetch_site == "cross-site":
                return jsonify({"ok": False, "message": "Межсайтовый запрос запрещён"}), 403
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
        if rule.startswith("/admin/") or rule == "/api/admin/csrf-token" or requires_owner(rule, request.method):
            response.headers["Cache-Control"] = "no-store"
            response.headers["X-Content-Type-Options"] = "nosniff"
            response.headers["X-Frame-Options"] = "DENY"
            response.headers["Referrer-Policy"] = "same-origin"
        return response

    app.register_blueprint(bp)
    app.register_blueprint(bp_mcp)
    app.register_blueprint(bp_assistant_voice)
    app.register_blueprint(bp_driver_move)
    app.register_blueprint(bp_voice_finance)
    app.register_blueprint(bp_voice_wallet)
    return app
