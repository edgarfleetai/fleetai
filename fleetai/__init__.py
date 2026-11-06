from flask import Flask


def create_app(config=None):
    """Application factory; tests must explicitly select an isolated SQLite DB."""
    app = Flask(__name__)
    app.config.from_mapping(INIT_LEGACY_DB=True)
    if config:
        app.config.update(config)
    if app.config.get('TESTING'):
        from pathlib import Path
        from sqlalchemy.engine import make_url
        url = app.config.get('DATABASE_URL', '')
        if not url.startswith('sqlite:'):
            raise ValueError('Tests require an explicit isolated SQLite database')
        parsed = make_url(url)
        root = Path(__file__).resolve().parents[1] / '.test-data'
        if (parsed.database != ':memory:' and
                (not parsed.database or not Path(parsed.database).resolve().is_relative_to(root.resolve()))):
            raise ValueError('Tests require an isolated database inside .test-data')
        app.config['INIT_LEGACY_DB'] = False
    from . import db
    if app.config.get('DATABASE_URL'):
        db.configure_database(app.config['DATABASE_URL'])
    from . import models  # Register tables after the explicit database is bound.
    from .auth import init_auth
    init_auth(app)
    if app.config['INIT_LEGACY_DB']:
        db.init_db()
    else:
        if not app.config.get('TESTING'):
            raise ValueError('Skipping legacy initialization is only supported in isolated tests')
        db.init_db(seed=False)
    from .routes import bp
    app.register_blueprint(bp)
    from .finance_readonly import bp as finance_readonly_bp
    app.register_blueprint(finance_readonly_bp)
    from .security_policy import register_policy
    register_policy(app)
    return app
