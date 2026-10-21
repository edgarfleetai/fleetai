"""Isolated driver-app API scaffold. Never connects to FleetAI production DB."""
from flask import Flask, jsonify, request

def create_app():
    app = Flask(__name__)
    app.config["MAX_CONTENT_LENGTH"] = 16 * 1024
    @app.get("/health")
    def health():
        return jsonify(status="ok", service="klever-driver-api")
    @app.get("/v1/public/vehicles")
    def public_vehicles():
        # No mock fleet listings: only approved real data may be published later.
        return jsonify([])
    @app.post("/v1/auth/otp/request")
    def request_otp():
        return jsonify(error="SMS registration is not configured"), 503
    @app.post("/v1/auth/otp/verify")
    def verify_otp():
        return jsonify(error="SMS registration is not configured"), 503
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
