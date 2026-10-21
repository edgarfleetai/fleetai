"""Isolated driver-app API. No production FleetAI DB, no active SMS or KYC."""
from flask import Flask, jsonify, request
import os
import sqlite3
from identity import initialize as initialize_identity, account_for_session, revoke_session

def create_app(config=None):
    app = Flask(__name__)
    app.config.update(MAX_CONTENT_LENGTH=16 * 1024, DRIVER_APP_DB_PATH=None)
    if config:
        app.config.update(config)

    def get_identity_db():
        path = app.config.get("DRIVER_APP_DB_PATH")
        if not path:
            return None
        db = sqlite3.connect(path, timeout=5, isolation_level=None)
        db.row_factory = sqlite3.Row
        initialize_identity(db)
        return db

    def bearer_token():
        header = request.headers.get("Authorization", "")
        if not header.startswith("Bearer "):
            return None
        token = header[7:].strip()
        if not token or " " in token:
            return None
        return token

    @app.get("/health")
    def health():
        return jsonify(status="ok", service="klever-driver-api")

    @app.get("/v1/public/vehicles")
    def public_vehicles():
        return jsonify([])

    @app.post("/v1/auth/otp/request")
    def request_otp():
        return jsonify(error="SMS registration is not configured"), 503

    @app.post("/v1/auth/otp/verify")
    def verify_otp():
        return jsonify(error="SMS registration is not configured"), 503

    @app.get("/v1/me")
    def me():
        token = bearer_token()
        if not token:
            return jsonify(error="Unauthorized"), 401
        db = get_identity_db()
        if db is None:
            return jsonify(error="Identity service is not configured"), 503
        try:
            account = account_for_session(db, token)
            if not account:
                return jsonify(error="Unauthorized"), 401
            return jsonify(account_id=account["id"], verification_status=account["verification_status"])
        finally:
            db.close()

    @app.post("/v1/auth/logout")
    def logout():
        token = bearer_token()
        if not token:
            return jsonify(error="Unauthorized"), 401
        db = get_identity_db()
        if db is None:
            return jsonify(error="Identity service is not configured"), 503
        try:
            if not revoke_session(db, token):
                return jsonify(error="Unauthorized"), 401
            return "", 204
        finally:
            db.close()

    @app.post("/v1/bookings")
    def create_booking():
        return jsonify(error="Booking is not configured"), 503

    @app.post("/v1/verification")
    def verification():
        return jsonify(error="Identity verification is not configured"), 503

    return app

app = create_app()
if __name__ == "__main__":
    app.run(debug=False)
