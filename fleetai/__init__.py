from flask import Flask, request, jsonify
from .db import init_db
from .routes import bp
from .admin_security import verify_admin_key


def create_app():
    app = Flask(__name__)
    init_db()

    @app.before_request
    def protect_manual_wallet_topup():
        # Fail closed for manual financial adjustments.
        # T-Bank payment callbacks are not affected.
        if request.path == "/api/driver-wallet/topup" and request.method == "POST":
            provided = request.headers.get("X-FleetAI-Admin-Key")
            if not verify_admin_key(provided):
                return jsonify({
                    "ok": False,
                    "message": "Требуется авторизация сотрудника",
                }), 403

    app.register_blueprint(bp)
    return app
