"""Single-owner authentication helpers.

No password or secret is stored in source control.
Configure FLEETAI_ADMIN_PASSWORD_HASH and FLASK_SECRET_KEY on the server.
"""
import os
from functools import wraps
from flask import jsonify, redirect, request, session, url_for
from werkzeug.security import check_password_hash


def admin_credentials_configured():
    return bool(os.getenv("FLEETAI_ADMIN_PASSWORD_HASH") and os.getenv("FLASK_SECRET_KEY"))


def verify_admin_password(password):
    password_hash = os.getenv("FLEETAI_ADMIN_PASSWORD_HASH", "")
    if not password_hash or not password:
        return False
    try:
        return check_password_hash(password_hash, password)
    except (ValueError, TypeError):
        return False


def is_admin():
    return bool(session.get("fleetai_admin") is True)


def require_admin(view):
    @wraps(view)
    def wrapped(*args, **kwargs):
        if not is_admin():
            if request.path.startswith("/api/"):
                return jsonify({"ok": False, "message": "Требуется вход администратора"}), 401
            return redirect(url_for("admin_login"))
        return view(*args, **kwargs)
    return wrapped
