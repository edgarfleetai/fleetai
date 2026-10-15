import os
from datetime import timedelta
from urllib.parse import urlsplit

from flask import Flask, request, jsonify, session, redirect, render_template_string, url_for
from .db import init_db
from .routes import bp
from .admin_auth import verify_admin_password, is_admin
from .login_limiter import login_blocked, record_login_failure, clear_login_failures


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
        session.clear()
        return redirect(url_for("admin_login"))

    @app.before_request
    def protect_dispatcher_wallet():
        protected = {
            ("/driver-topup", "GET"),
            ("/api/driver-wallet/cars", "GET"),
            ("/api/driver-wallet/topup", "POST"),
        }
        if (request.path, request.method) not in protected:
            return None
        if not is_admin():
            if request.path == "/driver-topup":
                return redirect(url_for("admin_login"))
            return jsonify({"ok": False, "message": "Требуется вход администратора"}), 401
        if request.method == "POST":
            source = request.headers.get("Origin") or request.headers.get("Referer")
            if not source:
                return jsonify({"ok": False, "message": "Отсутствует источник запроса"}), 403
            source_url = urlsplit(source)
            if source_url.scheme != request.scheme or source_url.netloc != request.host:
                return jsonify({"ok": False, "message": "Недопустимый источник запроса"}), 403
        return None

    app.register_blueprint(bp)
    return app
