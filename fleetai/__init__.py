import os
from datetime import timedelta

from flask import Flask, request, jsonify, session, redirect, render_template_string, url_for
from .db import init_db
from .routes import bp
from .admin_auth import verify_admin_password, is_admin


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
        if not verify_admin_password(request.form.get("password", "")):
            return render_template_string(LOGIN_HTML, error="Неверный пароль"), 401
        session.clear()
        session["fleetai_admin"] = True
        session.permanent = True
        return redirect("/")

    @app.route("/admin/logout", methods=["POST"])
    def admin_logout():
        session.clear()
        return redirect(url_for("admin_login"))

    @app.before_request
    def protect_manual_wallet_topup():
        if request.path == "/api/driver-wallet/topup" and request.method == "POST":
            if not is_admin():
                return jsonify({"ok": False, "message": "Требуется вход администратора"}), 401

    app.register_blueprint(bp)
    return app
