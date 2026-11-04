from flask import Flask
from .db import init_db
from .routes import bp
from .dashboard_readonly import dashboard_bp


def create_app():
    app = Flask(__name__)
    init_db()
    app.register_blueprint(bp)
    app.register_blueprint(dashboard_bp)
    return app
