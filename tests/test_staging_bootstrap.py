"""Only synthetic credentials and isolated SQLite; never run the Render launcher."""
import pytest
from sqlalchemy import select
from werkzeug.security import check_password_hash

from fleetai import db
from fleetai.auth_models import Owner

SYNTHETIC_PASSWORD = 'Synthetic staging test password only!'


def staging_module():
    import importlib.util
    assert importlib.util.find_spec('fleetai.staging_start') is not None, 'Staging launcher is missing'
    from fleetai import staging_start
    return staging_start


@pytest.fixture
def staging_env():
    return {
        'RENDER': 'true',
        'RENDER_SERVICE_NAME': 'fleetai-security-staging',
        'RENDER_SERVICE_ID': 'srv-synthetic-only',
        'FLEETAI_STAGING_SERVICE_ID': 'srv-synthetic-only',
        'FLEETAI_PUBLIC_BASE_URL': 'https://fleetai-security-staging.onrender.com',
        'FLEETAI_STAGING_DB_CONFIRMED': '1',
        'FLEETAI_STAGING_DB_HOST': 'dpg-syntheticonly-a',
        'FLEETAI_STAGING_DB_NAME': 'fleetai_staging_synthetic',
        'DATABASE_URL': 'postgresql://synthetic_writer:synthetic_database_password@dpg-syntheticonly-a/fleetai_staging_synthetic?sslmode=require',
        'PORT': '10000',
    }


def test_preflight_accepts_explicit_staging_identity_without_connecting(staging_env):
    staging = staging_module()
    config = staging.validate_environment(staging_env)
    assert config.public_base_url == staging_env['FLEETAI_PUBLIC_BASE_URL']
    assert config.port == 10000
    assert staging_env['DATABASE_URL'] not in repr(config)
    assert '***' not in repr(config)


@pytest.mark.parametrize('key,value', [
    ('RENDER', ''),
    ('RENDER_SERVICE_NAME', 'fleetai-1'),
    ('RENDER_SERVICE_ID', 'srv-another-service'),
    ('FLEETAI_STAGING_SERVICE_ID', ''),
    ('FLEETAI_PUBLIC_BASE_URL', ''),
    ('FLEETAI_PUBLIC_BASE_URL', 'https://fleetai-1.onrender.com'),
    ('FLEETAI_PUBLIC_BASE_URL', 'http://fleetai-security-staging.onrender.com'),
    ('FLEETAI_PUBLIC_BASE_URL', 'https://fleetai-security-staging.onrender.com/auth/login'),
    ('PUBLIC_BASE_URL', 'https://fleetai-1.onrender.com'),
    ('FLEETAI_STAGING_DB_CONFIRMED', '0'),
    ('FLEETAI_STAGING_DB_HOST', 'dpg-otherdatabase-a'),
    ('FLEETAI_STAGING_DB_NAME', 'another_database'),
    ('DATABASE_URL', 'sqlite:///fleet.db'),
    ('DATABASE_URL', 'postgresql://synthetic_writer:synthetic_database_password@dpg-syntheticonly-a/fleetai_staging_synthetic?host=other-host'),
    ('DATABASE_URL', 'postgresql://synthetic_writer:synthetic_database_password@dpg-syntheticonly-a/fleetai_staging_synthetic?sslmode=disable'),
    ('DATABASE_URL', 'postgresql://synthetic_writer:synthetic_database_password@dpg-syntheticonly-a/fleetai_staging_synthetic?sslmode=require&sslmode=disable'),
    ('DATABASE_URL', 'postgresql://synthetic_writer:synthetic_database_password@dpg-syntheticonly-a/fleetai_staging_synthetic?sslmode=require&options=-csearch_path=other'),
    ('FLASK_DEBUG', '1'),
    ('FLASK_ENV', 'development'),
    ('FLASK_TESTING', 'true'),
    ('TESTING', '1'),
    ('TBANK_TOKEN', 'synthetic-forbidden-integration'),
    ('TELEGRAM_BOT_TOKEN', 'synthetic-forbidden-integration'),
    ('WIALON_TOKEN', 'synthetic-forbidden-integration'),
    ('CRON_SECRET', 'synthetic-forbidden-integration'),
    ('PORT', '10000 --some-command'),
    ('PORT', '70000'),
    ('FLEETAI_BOOTSTRAP_OWNER_ENABLED', 'yes'),
    ('FLEETAI_BOOTSTRAP_OWNER_PASSWORD', SYNTHETIC_PASSWORD),
])
def test_preflight_fails_closed_before_database_use(staging_env, key, value):
    staging = staging_module()
    staging_env[key] = value
    with pytest.raises(staging.StagingConfigurationError) as error:
        staging.validate_environment(staging_env)
    assert staging_env.get('DATABASE_URL', '***') not in str(error.value)
    assert SYNTHETIC_PASSWORD not in str(error.value)


@pytest.mark.parametrize('password', ['', 'short', 'X' * 1025])
def test_enabled_bootstrap_requires_valid_password(staging_env, password):
    staging = staging_module()
    staging_env.update(FLEETAI_BOOTSTRAP_OWNER_ENABLED='1', FLEETAI_BOOTSTRAP_OWNER_PASSWORD=password)
    with pytest.raises(staging.StagingConfigurationError):
        staging.validate_environment(staging_env)


def test_readonly_url_cannot_redirect_to_another_database_or_writer(staging_env):
    staging = staging_module()
    staging_env['FINANCE_READONLY_DATABASE_URL'] = staging_env['DATABASE_URL']
    with pytest.raises(staging.StagingConfigurationError):
        staging.validate_environment(staging_env)
    staging_env['FINANCE_READONLY_DATABASE_URL'] = staging_env['DATABASE_URL'].replace('synthetic_writer', 'synthetic_reader').replace('dpg-syntheticonly-a', 'dpg-other-a')
    with pytest.raises(staging.StagingConfigurationError):
        staging.validate_environment(staging_env)
    staging_env['FINANCE_READONLY_DATABASE_URL'] = staging_env['DATABASE_URL'].replace('synthetic_writer', 'synthetic_reader')
    staging.validate_environment(staging_env)



def test_explicit_seed_opt_out_never_runs_legacy_seed(tmp_path, monkeypatch):
    from fleetai import create_app
    calls = []
    monkeypatch.setattr(db, 'seed_cars', lambda: calls.append('legacy seed'))
    url = 'sqlite:///' + str(tmp_path / 'seed-opt-out.sqlite')
    app = create_app({'DATABASE_URL': url, 'SEED_LEGACY_CARS': False})
    assert not app.testing
    assert calls == [], 'Staging startup must not seed real fleet/financial values'
    create_app({'DATABASE_URL': url})
    assert calls == ['legacy seed'], 'Default application initialization must remain unchanged'


def test_shared_owner_creation_hashes_password_and_refuses_replacement(secure_app):
    from fleetai import auth
    assert callable(getattr(auth, 'create_owner', None)), 'Shared owner helper is missing'
    with db.Session() as session:
        auth.create_owner(session, 'ADMIN', SYNTHETIC_PASSWORD)
        session.commit()
        owner = session.scalar(select(Owner))
        original_hash = owner.password_hash
        assert owner.id == 1 and owner.username == 'admin'
        assert original_hash.startswith('scrypt:')
        assert SYNTHETIC_PASSWORD not in original_hash
        assert check_password_hash(original_hash, SYNTHETIC_PASSWORD)
        with pytest.raises(auth.OwnerAlreadyExists):
            auth.create_owner(session, 'another-owner', 'Another synthetic password only!')
        session.rollback()
        assert session.scalar(select(Owner.password_hash)) == original_hash
        assert len(session.scalars(select(Owner)).all()) == 1


def test_environment_bootstrap_is_once_only_and_scrubs_process_secret(secure_app, staging_env, capsys):
    staging = staging_module()
    bootstrap = getattr(staging, 'bootstrap_owner_from_environment', None)
    assert callable(bootstrap), 'Environment owner bootstrap is missing'
    staging_env.update(FLEETAI_BOOTSTRAP_OWNER_ENABLED='1',
                       FLEETAI_BOOTSTRAP_OWNER_PASSWORD=SYNTHETIC_PASSWORD)
    assert bootstrap(staging_env) == 'created'
    assert all(key not in staging_env for key in staging.BOOTSTRAP_KEYS)
    with db.Session() as session:
        owner = session.scalar(select(Owner))
        original = owner.password_hash
        assert owner.username == 'admin' and owner.id == 1
        assert original.startswith('scrypt:')
        assert check_password_hash(original, SYNTHETIC_PASSWORD)
    staging_env.update(FLEETAI_BOOTSTRAP_OWNER_ENABLED='1',
                       FLEETAI_BOOTSTRAP_OWNER_PASSWORD='Different synthetic password only!')
    assert bootstrap(staging_env) == 'already-exists'
    with db.Session() as session:
        assert session.scalar(select(Owner.password_hash)) == original
        assert len(session.scalars(select(Owner)).all()) == 1
    assert all(key not in staging_env for key in staging.BOOTSTRAP_KEYS)
    output = capsys.readouterr()
    assert SYNTHETIC_PASSWORD not in output.out + output.err
    assert 'Different synthetic password only!' not in output.out + output.err


def test_launcher_prepares_once_scrubs_secrets_and_executes_only_gunicorn(secure_app, staging_env, monkeypatch):
    staging = staging_module()
    assert callable(getattr(staging, 'main', None)), 'Staging start command is missing'
    staging_env.update(FLEETAI_BOOTSTRAP_OWNER_ENABLED='1',
                       FLEETAI_BOOTSTRAP_OWNER_PASSWORD=SYNTHETIC_PASSWORD)
    monkeypatch.setattr(staging.os, 'environ', staging_env)
    prepared = []
    monkeypatch.setattr(staging, '_create_application', lambda config: prepared.append(config) or secure_app)
    executed = []
    def fake_exec(executable, args):
        assert all(key not in staging_env for key in staging.BOOTSTRAP_KEYS)
        assert SYNTHETIC_PASSWORD not in repr(args)
        executed.append((executable, args))
    monkeypatch.setattr(staging.os, 'execv', fake_exec)
    assert staging.main() == 0
    assert len(prepared) == 1
    assert len(executed) == 1
    executable, args = executed[0]
    assert args[:3] == [executable, '-m', 'gunicorn']
    assert 'fleetai.staging_start:create_staging_app()' in args
    assert '0.0.0.0:10000' in args
    assert args[args.index('--workers') + 1] == '1'


@pytest.mark.parametrize('extra', [
    {'DATABASE_URL': 'postgresql://synthetic_writer:***@dpg-syntheticonly-a/fleetai_staging_synthetic?sslmode=require&host='},
    {'PGHOSTADDR': '192.0.2.1'},
    {'PGSERVICE': 'another_database'},
    {'PGOPTIONS': '-csearch_path=another_schema'},
    {'GUNICORN_CMD_ARGS': '--reload'},
])
def test_preflight_rejects_implicit_connection_and_server_overrides(staging_env, extra):
    staging_env.update(extra)
    staging = staging_module()
    with pytest.raises(staging.StagingConfigurationError):
        staging.validate_environment(staging_env)


def test_finance_reader_cannot_hide_writer_identity_with_url_encoding(staging_env):
    staging = staging_module()
    staging_env['FINANCE_READONLY_DATABASE_URL'] = staging_env['DATABASE_URL'].replace(
        'synthetic_writer:', 'synthetic%5Fwriter:')
    with pytest.raises(staging.StagingConfigurationError):
        staging.validate_environment(staging_env)


def test_disabled_bootstrap_does_not_touch_database(staging_env, monkeypatch):
    staging = staging_module()
    def forbidden_session():
        pytest.fail('Disabled bootstrap must not open a session')
    monkeypatch.setattr(db, 'Session', forbidden_session)
    assert staging.bootstrap_owner_from_environment(staging_env) == 'disabled'


def test_existing_different_owner_is_preserved(secure_app, staging_env):
    from fleetai.auth import create_owner
    staging = staging_module()
    with db.Session() as session:
        create_owner(session, 'original-owner', SYNTHETIC_PASSWORD)
        session.commit()
        original_hash = session.scalar(select(Owner.password_hash))
    staging_env.update(FLEETAI_BOOTSTRAP_OWNER_ENABLED='1',
                       FLEETAI_BOOTSTRAP_OWNER_PASSWORD=SYNTHETIC_PASSWORD)
    with pytest.raises(staging.StagingConfigurationError, match='Existing owner is not admin'):
        staging.bootstrap_owner_from_environment(staging_env)
    with db.Session() as session:
        owner = session.scalar(select(Owner))
        assert owner.username == 'original-owner' and owner.password_hash == original_hash
    assert all(key not in staging_env for key in staging.BOOTSTRAP_KEYS)


@pytest.mark.parametrize('bad_password', ['short', 'X' * 1025, None])
def test_shared_owner_helper_refuses_invalid_password(secure_app, bad_password):
    from fleetai.auth import create_owner
    with db.Session() as session:
        with pytest.raises(ValueError):
            create_owner(session, 'admin', bad_password)
        session.rollback()
        assert session.scalar(select(Owner.id)) is None


def test_bootstrap_admin_can_use_existing_https_login_without_finance_writes(secure_app, staging_env):
    from fleetai.models import Car
    staging = staging_module()
    def snapshot(session):
        return {table.name: sorted((tuple(row) for row in session.execute(select(table))), key=repr)
                for table in db.Base.metadata.sorted_tables if not table.name.startswith('auth_')}
    with db.Session() as session:
        # Existing synthetic records must survive bootstrap untouched.
        session.add(Car(code='SYNTHETIC-ONLY', driver='Synthetic Test Driver'))
        session.commit()
        before = snapshot(session)
    staging_env.update(FLEETAI_BOOTSTRAP_OWNER_ENABLED='1',
                       FLEETAI_BOOTSTRAP_OWNER_PASSWORD=SYNTHETIC_PASSWORD)
    assert staging.bootstrap_owner_from_environment(staging_env) == 'created'
    secure_app.config.update(PUBLIC_BASE_URL=staging.PUBLIC_ORIGIN,
                             SERVER_NAME='fleetai-security-staging.onrender.com')
    client = secure_app.test_client()
    response = client.post('/auth/login', data={'username': 'admin', 'password': SYNTHETIC_PASSWORD},
                           base_url=staging.PUBLIC_ORIGIN, headers={'Origin': staging.PUBLIC_ORIGIN})
    assert response.status_code == 303
    cookie = response.headers['Set-Cookie']
    assert '__Host-fleetai_session=' in cookie
    assert all(flag in cookie for flag in ('Secure', 'HttpOnly', 'SameSite=Lax', 'Path=/'))
    assert 'Domain=' not in cookie
    assert client.get('/auth/session', base_url=staging.PUBLIC_ORIGIN).json['kind'] == 'owner'
    assert SYNTHETIC_PASSWORD not in response.get_data(as_text=True) + cookie
    assert not any('bootstrap' in rule.rule for rule in secure_app.url_map.iter_rules())
    with db.Session() as session:
        assert before == snapshot(session)
        car = session.scalar(select(Car).where(Car.code == 'SYNTHETIC-ONLY'))
        assert car.driver == 'Synthetic Test Driver'


def test_factory_preserves_secure_defaults_and_disables_only_legacy_seed(secure_app, staging_env, monkeypatch):
    import fleetai
    staging = staging_module()
    captured = []
    monkeypatch.setattr(fleetai, 'create_app', lambda config: captured.append(config) or secure_app)
    monkeypatch.setattr(staging.os, 'environ', staging_env)
    assert staging.create_staging_app() is secure_app
    assert captured == [{'DATABASE_URL': staging_env['DATABASE_URL'],
                         'PUBLIC_BASE_URL': staging.PUBLIC_ORIGIN, 'SEED_LEGACY_CARS': False}]
    staging_env.update(FLEETAI_BOOTSTRAP_OWNER_ENABLED='1',
                       FLEETAI_BOOTSTRAP_OWNER_PASSWORD=SYNTHETIC_PASSWORD)
    with pytest.raises(staging.StagingConfigurationError, match='Use staging launcher'):
        staging.create_staging_app()
    assert len(captured) == 1


def test_launcher_fails_before_app_import_on_wrong_origin(staging_env, monkeypatch, capsys):
    staging = staging_module()
    staging_env.update(FLEETAI_PUBLIC_BASE_URL='https://fleetai-1.onrender.com',
                       FLEETAI_BOOTSTRAP_OWNER_ENABLED='1',
                       FLEETAI_BOOTSTRAP_OWNER_PASSWORD=SYNTHETIC_PASSWORD)
    monkeypatch.setattr(staging.os, 'environ', staging_env)
    def forbidden_app(config):
        pytest.fail('Must reject configuration before application/DB initialization')
    monkeypatch.setattr(staging, '_create_application', forbidden_app)
    assert staging.main() == 1
    assert all(key not in staging_env for key in staging.BOOTSTRAP_KEYS)
    output = capsys.readouterr()
    assert 'Staging startup refused' in output.err
    assert SYNTHETIC_PASSWORD not in output.out + output.err


def test_launcher_suppresses_sensitive_database_exceptions(staging_env, monkeypatch, capsys):
    staging = staging_module()
    staging_env.update(FLEETAI_BOOTSTRAP_OWNER_ENABLED='1',
                       FLEETAI_BOOTSTRAP_OWNER_PASSWORD=SYNTHETIC_PASSWORD)
    monkeypatch.setattr(staging.os, 'environ', staging_env)
    def fail_app(config):
        raise RuntimeError(SYNTHETIC_PASSWORD + staging_env['DATABASE_URL'])
    monkeypatch.setattr(staging, '_create_application', fail_app)
    assert staging.main() == 1
    output = capsys.readouterr()
    assert SYNTHETIC_PASSWORD not in output.out + output.err
    assert staging_env['DATABASE_URL'] not in output.out + output.err
    assert all(key not in staging_env for key in staging.BOOTSTRAP_KEYS)


@pytest.mark.parametrize('winning_username', ['admin', 'different-owner'])
def test_bootstrap_handles_owner_created_between_lookups(secure_app, staging_env, monkeypatch, winning_username):
    """A real second transaction wins after the launcher's first owner lookup."""
    from fleetai import auth
    staging = staging_module()
    original_create = auth.create_owner
    winning_password = 'Concurrent synthetic password only!'
    winning_hash = []
    def concurrent_creation(session, username, password):
        # Release the read transaction, then commit another startup's owner.
        session.rollback()
        with db.Session() as winner:
            original_create(winner, winning_username, winning_password)
            winner.commit()
            winning_hash.append(winner.scalar(select(Owner.password_hash)))
        # The shared helper's second lookup sees the committed winner.
        return original_create(session, username, password)
    monkeypatch.setattr(auth, 'create_owner', concurrent_creation)
    staging_env.update(FLEETAI_BOOTSTRAP_OWNER_ENABLED='1',
                       FLEETAI_BOOTSTRAP_OWNER_PASSWORD=SYNTHETIC_PASSWORD)
    if winning_username == 'admin':
        assert staging.bootstrap_owner_from_environment(staging_env) == 'already-exists'
    else:
        with pytest.raises(staging.StagingConfigurationError, match='Owner creation refused'):
            staging.bootstrap_owner_from_environment(staging_env)
    assert all(key not in staging_env for key in staging.BOOTSTRAP_KEYS)
    with db.Session() as session:
        owners = session.scalars(select(Owner)).all()
        assert len(owners) == 1
        assert owners[0].username == winning_username
        assert owners[0].password_hash == winning_hash[0]
        assert check_password_hash(owners[0].password_hash, winning_password)
        assert not check_password_hash(owners[0].password_hash, SYNTHETIC_PASSWORD)
