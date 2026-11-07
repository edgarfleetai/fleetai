"""Opt-in Render staging launcher. Importing this module never connects to a DB.

Do not use in production. Render environment changes and launching this module
require separate owner approval. No HTTP bootstrap route is registered.
"""
from dataclasses import dataclass, field
import os
import re
from urllib.parse import parse_qsl, unquote, urlsplit

PUBLIC_ORIGIN = 'https://fleetai-security-staging.onrender.com'
BOOTSTRAP_KEYS = ('FLEETAI_BOOTSTRAP_OWNER_ENABLED', 'FLEETAI_BOOTSTRAP_OWNER_PASSWORD')


class StagingConfigurationError(ValueError):
    """Only fixed, non-secret diagnostic messages may be used here."""


@dataclass(frozen=True)
class StagingConfig:
    database_url: str = field(repr=False)
    public_base_url: str = PUBLIC_ORIGIN
    port: int = 10000


def _database_identity(raw, expected_host, expected_database):
    try:
        url = urlsplit(raw)
        query = parse_qsl(url.query, keep_blank_values=True, strict_parsing=True, max_num_fields=4)
        if (url.scheme not in {'postgres', 'postgresql', 'postgresql+psycopg'}
                or url.hostname != expected_host or url.port not in {None, 5432}
                or url.path != '/' + expected_database or url.fragment
                or not url.username or not url.password
                or len(query) not in {1, 2}
                or dict(query).get('sslmode') not in {'require', 'verify-full'}
                or len(dict(query)) != len(query)
                or any(k not in {'sslmode', 'channel_binding'} for k, _ in query)
                or ('channel_binding' in dict(query) and dict(query)['channel_binding'] != 'require')):
            raise ValueError
        return unquote(url.username)
    except (ValueError, TypeError):
        raise StagingConfigurationError('Database identity/TLS configuration refused') from None


def validate_environment(env=None):
    """Check explicit operator-approved identities BEFORE importing DB/app code.

    Matching names does not prove isolation. The operator must first verify the
    new database's identity in Render and acknowledge it with DB_CONFIRMED=1.
    """
    env = os.environ if env is None else env
    if (env.get('RENDER') != 'true'
            or env.get('RENDER_SERVICE_NAME') != 'fleetai-security-staging'
            or not env.get('FLEETAI_STAGING_SERVICE_ID', '').startswith('srv-')
            or env.get('RENDER_SERVICE_ID') != env.get('FLEETAI_STAGING_SERVICE_ID')):
        raise StagingConfigurationError('Explicit staging service identity required')
    if (env.get('FLEETAI_PUBLIC_BASE_URL') != PUBLIC_ORIGIN
            or env.get('PUBLIC_BASE_URL', PUBLIC_ORIGIN) != PUBLIC_ORIGIN):
        raise StagingConfigurationError('Exact staging HTTPS origin required')
    host = env.get('FLEETAI_STAGING_DB_HOST', '')
    database = env.get('FLEETAI_STAGING_DB_NAME', '')
    if (env.get('FLEETAI_STAGING_DB_CONFIRMED') != '1'
            or not (re.fullmatch(r'dpg-[a-z0-9]+-[a-z](?:\.[a-z0-9.-]+\.render\.com)?', host)
                    or re.fullmatch(r'ep-[a-z0-9-]+(?:-pooler)?\.c-[0-9]+\.[a-z0-9-]+\.aws\.neon\.tech', host))
            or not re.fullmatch(r'[a-z][a-z0-9_]{0,62}', database)):
        raise StagingConfigurationError('Operator-confirmed isolated staging database required')
    raw = env.get('DATABASE_URL', '')
    writer = _database_identity(raw, host, database)
    readonly = env.get('FINANCE_READONLY_DATABASE_URL')
    if readonly and _database_identity(readonly, host, database) == writer:
        raise StagingConfigurationError('Finance reader must not use the application writer')
    for key in ('FLASK_DEBUG', 'FLASK_TESTING', 'TESTING'):
        if env.get(key, '').lower() not in {'', '0', 'false', 'no', 'off'}:
            raise StagingConfigurationError('Debug/testing modes forbidden on staging')
    if env.get('FLASK_ENV', 'production') != 'production':
        raise StagingConfigurationError('Development mode forbidden on staging')
    if any(value and (key.startswith('PG') or key == 'GUNICORN_CMD_ARGS')
           for key, value in env.items()):
        raise StagingConfigurationError('Implicit connection/server overrides forbidden on staging')
    if any(value and (key.startswith(('TBANK_', 'TELEGRAM_', 'SMSRU_', 'WIALON_'))
                      or key == 'CRON_SECRET') for key, value in env.items()):
        raise StagingConfigurationError('External integration credentials forbidden on staging')
    enabled = env.get(BOOTSTRAP_KEYS[0], '')
    password = env.get(BOOTSTRAP_KEYS[1], '')
    if enabled not in {'', '0', '1'}:
        raise StagingConfigurationError('Bootstrap flag must be absent, 0 or 1')
    if enabled == '1':
        if not 12 <= len(password) <= 1024:
            raise StagingConfigurationError('Bootstrap password must have 12 to 1024 characters')
    elif BOOTSTRAP_KEYS[1] in env:
        raise StagingConfigurationError('Remove bootstrap password when bootstrap is disabled')
    port = env.get('PORT', '10000')
    if not re.fullmatch(r'[0-9]{1,5}', port) or not 1 <= int(port) <= 65535:
        raise StagingConfigurationError('Invalid service port')
    return StagingConfig(raw, PUBLIC_ORIGIN, int(port))


def bootstrap_owner_from_environment(env=None):
    """Opt-in creation in an already prepared, approved staging DB; no HTTP API.

    Render's persistent settings MUST be removed separately after success.
    Removing these keys here only protects the subsequent worker environment.
    """
    env = os.environ if env is None else env
    try:
        validate_environment(env)
        if env.get(BOOTSTRAP_KEYS[0]) != '1':
            return 'disabled'
        from sqlalchemy import select
        from sqlalchemy.exc import IntegrityError
        from . import db
        from .auth import OwnerAlreadyExists, create_owner
        from .auth_models import Owner
        with db.Session() as session:
            owner = session.scalar(select(Owner))
            if owner is not None:
                if owner.username != 'admin':
                    raise StagingConfigurationError('Existing owner is not admin; refusing replacement')
                return 'already-exists'
            try:
                create_owner(session, 'admin', env[BOOTSTRAP_KEYS[1]])
                session.commit()
            except (IntegrityError, OwnerAlreadyExists):
                session.rollback()
                # A concurrent startup may have won the singleton insert.
                owner = session.scalar(select(Owner))
                if owner is None or owner.username != 'admin':
                    raise StagingConfigurationError('Owner creation refused') from None
                return 'already-exists'
        return 'created'
    finally:
        for key in BOOTSTRAP_KEYS:
            env.pop(key, None)


def _create_application(config):
    from . import create_app
    return create_app({'DATABASE_URL': config.database_url,
                       'PUBLIC_BASE_URL': config.public_base_url,
                       'SEED_LEGACY_CARS': False})


def create_staging_app():
    """Gunicorn factory after the launcher has consumed temporary variables."""
    config = validate_environment()
    if any(key in os.environ for key in BOOTSTRAP_KEYS):
        raise StagingConfigurationError('Use staging launcher to consume bootstrap variables')
    return _create_application(config)


def main():
    """Only an explicitly approved Render Start Command may call this launcher."""
    import sys
    try:
        config = validate_environment()
        _create_application(config)
        result = bootstrap_owner_from_environment()
        from . import db
        db.engine.dispose()
        print('Staging bootstrap: ' + result, flush=True)
        os.execv(sys.executable, [sys.executable, '-m', 'gunicorn',
                 'fleetai.staging_start:create_staging_app()',
                 '--bind', '0.0.0.0:' + str(config.port), '--workers', '1'])
        return 0  # Only reached by an intercepted exec in isolated tests.
    except StagingConfigurationError as error:
        for key in BOOTSTRAP_KEYS:
            os.environ.pop(key, None)
        # These diagnostics are fixed literals from this module, never inputs.
        print('Staging startup refused: ' + str(error), file=sys.stderr)
        return 1
    except Exception:
        for key in BOOTSTRAP_KEYS:
            os.environ.pop(key, None)
        # Never render an exception/traceback: DB errors may contain credentials.
        print('Staging startup refused; check approved configuration and database.', file=sys.stderr)
        return 1


if __name__ == '__main__':
    raise SystemExit(main())
