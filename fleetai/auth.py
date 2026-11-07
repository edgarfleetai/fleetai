"""Opaque server-side auth. Public Principal: kind, car_code, csrf_token,
scopes (frozenset), has_scope(name). Helpers accept a caller-owned SQLAlchemy
Session; caller commits/rolls back. No helper sends messages or calls a network.
"""
from dataclasses import dataclass, field
from hashlib import sha256
import secrets
import time
from urllib.parse import quote, urlsplit
import os

import click
from flask import Blueprint, current_app, g, jsonify, redirect, request
from sqlalchemy import select, text, update, event, case, delete, inspect, func
from .models import Car
from werkzeug.security import check_password_hash, generate_password_hash
from . import db
from .auth_models import AuthSession, Owner, HermesCredential, DriverEpoch, DriverTicket, LoginAttempt

COOKIE = '__Host-fleetai_session'


@dataclass(frozen=True)
class Principal:
    kind: str
    car_code: str | None = None
    csrf_token: str | None = None
    scopes: frozenset = field(default_factory=frozenset)
    session_hash: str | None = None

    def has_scope(self, name):
        return name in self.scopes


def _hash(value):
    return sha256(value.encode('utf-8')).hexdigest()


def _new_session(session, kind, **kwargs):
    raw = secrets.token_urlsafe(32)
    ttl = min(28800, max(1, int(current_app.config.get('AUTH_SESSION_TTL', 28800))))
    row = AuthSession(token_hash=_hash(raw), kind=kind,
                      csrf_token=secrets.token_urlsafe(32), expires_at=time.time() + ttl, **kwargs)
    session.add(row)
    return raw


def _cookie(response, raw):
    response.set_cookie(COOKIE, raw, secure=True, httponly=True, samesite='Lax', path='/', max_age=28800)
    return response


def issue_hermes_credential(session, label, *, scopes=frozenset({'finance:read'}), expires_at=None):
    """Return (raw credential, persisted/flushed record); caller must commit.

    The only accepted scope is finance:read. Local administration must protect
    this helper; there is deliberately no public credential-management route.
    """
    if frozenset(scopes) != frozenset({'finance:read'}):
        raise ValueError('Only finance:read is allowed')
    if not label or len(label) > 128:
        raise ValueError('Invalid credential label')
    if expires_at is not None and expires_at <= time.time():
        raise ValueError('Expiry must be in the future')
    raw = 'fh_' + secrets.token_urlsafe(32)
    record = HermesCredential(label=label, token_hash=_hash(raw), scope='finance:read',
                              created_at=time.time(), expires_at=expires_at)
    session.add(record)
    session.flush()
    return raw, record


def revoke_hermes_credential(session, credential_id):
    record = session.get(HermesCredential, credential_id)
    if not record:
        return False
    record.revoked_at = time.time()
    return True


def _upsert(session, model, values, updates):
    dialect = session.get_bind().dialect.name
    if dialect == 'sqlite':
        from sqlalchemy.dialects.sqlite import insert
    elif dialect == 'postgresql':
        from sqlalchemy.dialects.postgresql import insert
    else:
        raise RuntimeError('Authentication supports SQLite/PostgreSQL only')
    return session.execute(insert(model).values(**values).on_conflict_do_update(
        index_elements=list(model.__table__.primary_key.columns), set_=updates))


def lock_driver_assignment(session, car_code):
    """Shared serialization point for assignment, binding and session issuance.

    PostgreSQL uses the persisted car row. SQLite test databases reserve their
    writer transaction before any subsequent reads; no production lock is used.
    """
    if session.get_bind().dialect.name == 'sqlite':
        connection = session.connection()
        if not connection.connection.driver_connection.in_transaction:
            connection.exec_driver_sql('BEGIN IMMEDIATE')
    table = Car.__table__
    return session.execute(select(table.c.code, table.c.driver).where(
        table.c.code == car_code).with_for_update()).first()


def revoke_driver_access(session, car_code, *, keep_link_id=None):
    """Increment assignment epoch and revoke all sessions/tickets atomically.

    No commit: part of caller transaction. Deletes Telegram bindings and pending
    legacy link tokens: reassignment always requires a new verified binding.
    DB triggers do this automatically for persisted cars.driver changes,
    including raw SQL/bulk updates and ABA.
    """
    lock_driver_assignment(session, car_code)
    _upsert(session, DriverEpoch, {'car_code': car_code, 'epoch': 1},
            {'epoch': DriverEpoch.epoch + 1})
    now = time.time()
    session.execute(update(AuthSession).where(AuthSession.kind == 'driver', AuthSession.car_code == car_code).values(revoked_at=now))
    session.execute(update(DriverTicket).where(DriverTicket.car_code == car_code).values(revoked_at=now))
    session.execute(text('DELETE FROM driver_telegram_bindings WHERE car_code=:code'), {'code': car_code})
    if keep_link_id is None:
        session.execute(text('DELETE FROM driver_telegram_links WHERE car_code=:code'), {'code': car_code})
    else:
        # A verified, atomically claimed enrollment link is retained as used.
        session.execute(text('DELETE FROM driver_telegram_links WHERE car_code=:code AND id<>:keep'),
                        {'code': car_code, 'keep': keep_link_id})


@event.listens_for(Car.driver, 'set', active_history=True)
def _observe_driver_assignment(car, value, oldvalue, initiator):
    state = inspect(car)
    if state.persistent and value != oldvalue:
        state.info['auth_driver_changed'] = True


@event.listens_for(db.Session.class_, 'before_flush')
def _invalidate_unflushed_assignment_roundtrip(session, flush_context, instances):
    # A->B->A before flush produces no SQL UPDATE, so DB triggers cannot see it.
    for car in list(session.dirty):
        if isinstance(car, Car):
            state = inspect(car)
            changed = state.info.pop('auth_driver_changed', False)
            if changed and not state.attrs.driver.history.has_changes():
                revoke_driver_access(session, car.code)


@event.listens_for(db.Session.class_, 'after_soft_rollback')
def _clear_rolled_back_assignments(session, previous_transaction):
    for obj in session.identity_map.values():
        if isinstance(obj, Car):
            inspect(obj).info.pop('auth_driver_changed', None)


def _install_assignment_triggers(metadata, connection, **kwargs):
    """DB-level invalidation protects ORM and legacy SQL assignment writers."""
    dialect = connection.dialect.name
    if dialect in {'sqlite', 'postgresql'}:
        # Legacy finance/document lookups trim car keys. Exact-key uniqueness
        # alone permits aliases and a concurrent second identity for one ledger.
        # Reject duplicates atomically; never normalize or rewrite existing data.
        connection.exec_driver_sql('CREATE UNIQUE INDEX IF NOT EXISTS auth_car_code_trim_unique ON cars (trim(code))')
    if dialect == 'sqlite':
        body = '''
          INSERT INTO auth_driver_epochs(car_code, epoch) VALUES (OLD.code, 1)
          ON CONFLICT(car_code) DO UPDATE SET epoch=epoch+1;
          UPDATE auth_sessions SET revoked_at=CAST(strftime('%s','now') AS REAL)
            WHERE kind='driver' AND car_code=OLD.code;
          UPDATE auth_driver_tickets SET revoked_at=CAST(strftime('%s','now') AS REAL)
            WHERE car_code=OLD.code;
          DELETE FROM driver_telegram_bindings WHERE car_code=OLD.code;
          DELETE FROM driver_telegram_links WHERE car_code=OLD.code;
        '''
        connection.exec_driver_sql('CREATE TRIGGER IF NOT EXISTS auth_driver_assignment_update '
            'AFTER UPDATE OF driver ON cars WHEN OLD.driver IS NOT NEW.driver BEGIN ' + body + ' END')
        connection.exec_driver_sql('CREATE TRIGGER IF NOT EXISTS auth_driver_assignment_delete '
            'AFTER DELETE ON cars BEGIN ' + body + ' END')
    elif dialect == 'postgresql':
        connection.exec_driver_sql('''CREATE OR REPLACE FUNCTION fleetai_auth_revoke_driver()
          RETURNS trigger LANGUAGE plpgsql AS $$ BEGIN
          IF TG_OP = 'DELETE' OR OLD.driver IS DISTINCT FROM NEW.driver THEN
            INSERT INTO auth_driver_epochs(car_code, epoch) VALUES (OLD.code, 1)
              ON CONFLICT(car_code) DO UPDATE SET epoch=auth_driver_epochs.epoch+1;
            UPDATE auth_sessions SET revoked_at=EXTRACT(EPOCH FROM clock_timestamp())
              WHERE kind='driver' AND car_code=OLD.code;
            UPDATE auth_driver_tickets SET revoked_at=EXTRACT(EPOCH FROM clock_timestamp())
              WHERE car_code=OLD.code;
            DELETE FROM driver_telegram_bindings WHERE car_code=OLD.code;
            DELETE FROM driver_telegram_links WHERE car_code=OLD.code;
          END IF;
          RETURN OLD; END $$''')
        connection.exec_driver_sql('DROP TRIGGER IF EXISTS auth_driver_assignment ON cars')
        connection.exec_driver_sql('CREATE TRIGGER auth_driver_assignment AFTER UPDATE OF driver OR DELETE '
                                   'ON cars FOR EACH ROW EXECUTE FUNCTION fleetai_auth_revoke_driver()')
    else:
        raise RuntimeError('Authentication supports SQLite/PostgreSQL only')


def _epoch(session, car_code):
    return session.scalar(select(DriverEpoch.epoch).where(DriverEpoch.car_code == car_code)) or 0


def _binding_valid(session, car_code, driver_name, chat_id):
    return bool(driver_name and session.execute(text(
        'SELECT 1 FROM driver_telegram_bindings WHERE car_code=:car '
        'AND driver_name=:driver AND telegram_chat_id=:chat LIMIT 1'),
        {'car': car_code, 'driver': driver_name, 'chat': str(chat_id)}).first())


def _driver_code_unambiguous(session, car_code):
    """Deny ambiguous legacy trim aliases; never rewrite vehicles or ledgers."""
    if not isinstance(car_code, str) or not car_code or car_code != car_code.strip():
        return False
    table = Car.__table__
    alias = session.execute(select(table.c.code).where(
        func.trim(table.c.code) == car_code, table.c.code != car_code).limit(1)).first()
    return alias is None


def lock_driver_financial_car(session, principal, car_code):
    """Revalidate the admitted driver while holding the assignment's row lock.

    The caller owns this transaction and MUST retain it through materializing
    the complete response. In particular, legacy rent sync must flush, not
    commit. Assignment, explicit revocation and binding changes use this same
    persisted-car lock, so they cannot overtake the authorized snapshot.
    """
    if (not principal or principal.kind != 'driver' or not principal.session_hash
            or principal.car_code != car_code):
        return None
    current = lock_driver_assignment(session, car_code)
    if current is None or not _driver_code_unambiguous(session, car_code):
        return None
    # Read table values afresh: a cached ORM auth row is not a revalidation.
    table = AuthSession.__table__
    row = session.execute(select(table).where(
        table.c.token_hash == principal.session_hash)).mappings().first()
    if (not row or row['kind'] != 'driver' or row['revoked_at'] is not None
            or row['expires_at'] <= time.time() or row['car_code'] != current.code
            or not current.driver or row['driver_name'] != current.driver
            or row['epoch'] != _epoch(session, current.code)
            or not _binding_valid(session, current.code, current.driver, row['chat_id'])):
        return None
    # Never switch back to the legacy trimmed-key lookup after locking an exact key.
    return session.scalar(select(Car).where(Car.code == current.code)
                          .execution_options(populate_existing=True))


def issue_driver_login(session, car, chat_id):
    """Issue <=5-minute ticket only for a persisted current car/chat binding.

    Caller commits and sends raw ticket ONLY as /auth/driver#token=<ticket>.
    No raw ticket is persisted, and GET never redeems it.
    """
    if not car or not car.code or not chat_id:
        raise ValueError('Verified binding required')
    # Read persisted assignment, not arbitrary caller-supplied object fields.
    current = lock_driver_assignment(session, car.code)
    if (not current or not _driver_code_unambiguous(session, car.code)
            or current.driver != car.driver or not _binding_valid(session, current.code, current.driver, chat_id)):
        raise ValueError('Verified current Telegram binding required')
    raw = secrets.token_urlsafe(32)
    session.add(DriverTicket(token_hash=_hash(raw), car_code=current.code,
                            driver_name=current.driver, chat_id=str(chat_id),
                            epoch=_epoch(session, current.code), expires_at=time.time() + 300))
    return raw


def authenticate_request():
    g.principal = None
    authorization = request.headers.get('Authorization')
    if authorization is not None:
        parts = authorization.split()
        if len(parts) != 2 or parts[0].lower() != 'bearer' or len(parts[1]) > 256:
            return None
        with db.Session() as session:
            record = session.scalar(select(HermesCredential).where(HermesCredential.token_hash == _hash(parts[1])))
            if (not record or record.revoked_at is not None or record.scope != 'finance:read'
                    or (record.expires_at is not None and record.expires_at <= time.time())):
                return None
        g.principal = Principal('hermes', scopes=frozenset({'finance:read'}))
        return g.principal
    raw = request.cookies.get(COOKIE, '')
    if not raw or len(raw) > 256:
        return None
    with db.Session() as session:
        row = session.get(AuthSession, _hash(raw))
        if not row or row.revoked_at is not None or row.expires_at <= time.time():
            return None
        if row.kind == 'driver':
            if not _driver_code_unambiguous(session, row.car_code):
                return None
            driver = session.scalar(select(Car.driver).where(Car.code == row.car_code))
            if (not driver or driver != row.driver_name or _epoch(session, row.car_code) != row.epoch
                    or not _binding_valid(session, row.car_code, row.driver_name, row.chat_id)):
                return None
        elif row.kind != 'owner' or not session.get(Owner, row.owner_id):
            return None
        principal = Principal(row.kind, row.car_code, row.csrf_token, session_hash=row.token_hash)
    g.principal = principal
    return principal


def _same_origin(require_proof=False):
    # TLS can terminate at Render: never trust arbitrary forwarded headers.
    # An explicitly configured public HTTPS origin is authoritative instead.
    configured = current_app.config.get('PUBLIC_BASE_URL') or os.getenv('FLEETAI_PUBLIC_BASE_URL')
    if configured:
        expected = str(configured).rstrip('/')
        parsed = urlsplit(expected)
        if (parsed.scheme != 'https' or not parsed.netloc or parsed.username or
                parsed.password or parsed.path or parsed.query or parsed.fragment):
            return False
    else:
        if not current_app.testing:
            return False
        expected = request.host_url.rstrip('/')
    origin = request.headers.get('Origin')
    fetch_site = request.headers.get('Sec-Fetch-Site')
    if fetch_site == 'cross-site' or (origin is not None and origin != expected):
        return False
    if origin is not None:
        return True
    if not require_proof:
        return True
    if fetch_site == 'same-origin':
        return True
    # Some browsers omit Fetch Metadata on ordinary HTML form posts.
    # Accept an exact same-origin HTTPS Referer as alternate browser proof.
    referer = request.headers.get('Referer', '')
    if not referer:
        return False
    parsed_referer = urlsplit(referer)
    return (parsed_referer.scheme == 'https' and
            parsed_referer.netloc == urlsplit(expected).netloc and
            not parsed_referer.username and not parsed_referer.password)


def require_csrf(principal):
    supplied = request.headers.get('X-CSRF-Token') or request.form.get('csrf_token', '')
    return bool(principal and principal.kind in ('owner', 'driver') and principal.csrf_token
                and supplied.isascii() and _same_origin()
                and secrets.compare_digest(principal.csrf_token, supplied))


def _login_allowed(username):
    """Persisted atomic 15-minute limits: IP 20, account 5, account/IP 5.

    Uses REMOTE_ADDR only; never trusts client-controlled forwarding headers.
    Check IP first to avoid unbounded account buckets from a blocked address.
    """
    now = time.time()
    remote = request.remote_addr or '<unknown>'
    with db.Session() as session:
        session.execute(delete(LoginAttempt).where(LoginAttempt.window_start < now - 1800))
        for key, limit in ((f'ip:{remote}', 20), (f'account:{username}', 5),
                           (f'pair:{username}:{remote}', 5)):
            key = _hash(key)
            expired = LoginAttempt.window_start <= now - 900
            _upsert(session, LoginAttempt, {'key': key, 'window_start': now, 'attempts': 1},
                    {'window_start': case((expired, now), else_=LoginAttempt.window_start),
                     'attempts': case((expired, 1), else_=LoginAttempt.attempts + 1)})
            attempts = session.scalar(select(LoginAttempt.attempts).where(LoginAttempt.key == key))
            if attempts > limit:
                session.commit()
                return False
        session.commit()
    return True


class OwnerAlreadyExists(ValueError):
    """Singleton owner creation refused; existing credentials are never reset."""


def create_owner(session, username, password, *, password_method='scrypt'):
    """Create the singleton owner; caller owns commit/rollback and authorization.

    This is not an HTTP endpoint. A concurrent insert is rejected by the existing
    singleton constraint; callers must roll back on IntegrityError.
    """
    username = username.strip().casefold()
    if not username or len(username) > 128:
        raise ValueError('Invalid username')
    if session.scalar(select(Owner.id).limit(1)) is not None:
        raise OwnerAlreadyExists('Owner already exists')
    if not isinstance(password, str) or not 12 <= len(password) <= 1024:
        raise ValueError('Password must have 12 to 1024 characters')
    session.execute(delete(AuthSession).where(AuthSession.kind == 'owner'))
    session.add(Owner(id=1, username=username, password_hash=generate_password_hash(
        password, method=password_method)))
    session.flush()


def init_auth(app):
    """Register metadata, routes, CLI; performs no DB connections itself."""
    if 'fleetai_auth' in app.extensions:
        return
    app.extensions['fleetai_auth'] = {'authenticate_request': authenticate_request,
                                     'require_csrf': require_csrf}
    password_method = app.config.get('AUTH_PASSWORD_METHOD', 'scrypt') if app.testing else 'scrypt'
    dummy_hash = generate_password_hash(secrets.token_urlsafe(32), method=password_method)
    bp = Blueprint('auth', __name__, url_prefix='/auth')

    @bp.after_request
    def protect(response):
        response.headers['Cache-Control'] = 'no-store'
        response.headers['Referrer-Policy'] = 'no-referrer'
        response.headers['X-Content-Type-Options'] = 'nosniff'
        return response

    @bp.route('/login', methods=['GET', 'POST'])
    def login():
        if request.method == 'GET':
            proof = secrets.token_urlsafe(32)
            response = current_app.make_response('<!doctype html><title>Owner login</title><form method="post"><input name="username" autocomplete="username" required><input name="password" type="password" autocomplete="current-password" required><input type="hidden" name="login_proof" value="' + proof + '"><button>Sign in</button></form>')
            response.set_cookie('__Host-fleetai_login_proof', proof, secure=True, httponly=True, samesite='Strict', path='/', max_age=600)
            return response
        cookie_proof = request.cookies.get('__Host-fleetai_login_proof', '')
        form_proof = request.form.get('login_proof', '')
        if (not cookie_proof or len(cookie_proof) > 256 or
                not secrets.compare_digest(cookie_proof, form_proof) or
                not _same_origin()):
            return jsonify(error='forbidden'), 403
        username = request.form.get('username', '').strip().casefold()
        password = request.form.get('password', '')
        if len(username) > 128 or len(password) > 1024:
            return jsonify(error='invalid credentials'), 401
        if not _login_allowed(username):
            response = jsonify(error='too many attempts')
            response.headers['Retry-After'] = '900'
            return response, 429
        with db.Session() as session:
            owner = session.scalar(select(Owner).where(Owner.username == username))
            valid = check_password_hash(owner.password_hash if owner else dummy_hash, password)
            if not owner or not password or not valid:
                return jsonify(error='invalid credentials'), 401
            raw = _new_session(session, 'owner', owner_id=owner.id)
            session.commit()
        return _cookie(redirect('/', code=303), raw)

    @bp.get('/driver')
    def driver_landing():
        if request.query_string:
            return jsonify(error='Tickets must use URL fragments, never query strings'), 400
        return '''<!doctype html><title>Driver login</title>
<button id="confirm" type="button">Confirm driver login</button><p id="status"></p>
<script>
const fragment = location.hash.slice(1);
const ticket = new URLSearchParams(fragment).get('token') || fragment;
history.replaceState(null, '', '/auth/driver');
document.getElementById('confirm').onclick = async () => {
  const r = await fetch('/auth/driver/consume', {method:'POST',
    headers:{'Content-Type':'application/json'}, body:JSON.stringify({ticket}),
    credentials:'same-origin', redirect:'follow'});
  if (r.redirected) location.assign(r.url);
  else document.getElementById('status').textContent='Login link is invalid or expired';
};
</script>'''

    @bp.post('/driver/consume')
    def driver_consume():
        if request.query_string or not _same_origin(require_proof=True):
            return jsonify(error='forbidden'), 403
        payload = request.get_json(silent=True) if request.is_json else request.form
        if not hasattr(payload, 'get'):
            return jsonify(error='invalid ticket'), 401
        raw = payload.get('ticket', '')
        if not isinstance(raw, str) or not raw or len(raw) > 256:
            return jsonify(error='invalid ticket'), 401
        now = time.time()
        with db.Session() as session:
            ticket = session.get(DriverTicket, _hash(raw))
            if not ticket or ticket.consumed_at is not None or ticket.revoked_at is not None or ticket.expires_at <= now:
                return jsonify(error='invalid ticket'), 401
            current = lock_driver_assignment(session, ticket.car_code)
            # Assignment locking may have waited past the link's expiry.
            now = time.time()
            if ticket.expires_at <= now:
                return jsonify(error='invalid ticket'), 401
            if (not current or not _driver_code_unambiguous(session, ticket.car_code)
                    or current.driver != ticket.driver_name or _epoch(session, ticket.car_code) != ticket.epoch
                    or not _binding_valid(session, ticket.car_code, ticket.driver_name, ticket.chat_id)):
                return jsonify(error='invalid ticket'), 401
            used = session.execute(update(DriverTicket).where(
                DriverTicket.token_hash == ticket.token_hash, DriverTicket.consumed_at.is_(None),
                DriverTicket.revoked_at.is_(None), DriverTicket.expires_at > now
            ).values(consumed_at=now))
            if used.rowcount != 1:
                return jsonify(error='invalid ticket'), 401
            session_raw = _new_session(session, 'driver', car_code=ticket.car_code,
                                       driver_name=ticket.driver_name, chat_id=ticket.chat_id, epoch=ticket.epoch)
            target = '/driver?code=' + quote(ticket.car_code, safe='')
            session.commit()
        return _cookie(redirect(target, code=303), session_raw)

    @bp.get('/session')
    def whoami():
        principal = authenticate_request()
        if not principal:
            return jsonify(error='unauthorized'), 401
        return jsonify(kind=principal.kind, car_code=principal.car_code,
                       csrf_token=principal.csrf_token, scopes=sorted(principal.scopes))

    @bp.post('/logout')
    def logout():
        principal = authenticate_request()
        if not require_csrf(principal):
            return jsonify(error='forbidden'), 403
        with db.Session() as session:
            row = session.get(AuthSession, principal.session_hash)
            row.revoked_at = time.time()
            session.commit()
        response = redirect('/auth/login', code=303)
        response.delete_cookie(COOKIE, secure=True, httponly=True, samesite='Lax', path='/')
        return response

    app.register_blueprint(bp)

    @app.cli.group('auth')
    def auth_cli():
        """Local owner-only authentication administration."""

    @auth_cli.command('bootstrap-owner')
    @click.option('--username', prompt=True)
    def bootstrap_owner(username):
        username = username.strip().casefold()
        if not username or len(username) > 128:
            raise click.ClickException('Invalid username')
        with db.Session() as session:
            if session.scalar(select(Owner.id).limit(1)) is not None:
                raise click.ClickException('Owner already exists')
            password = click.prompt('Password', hide_input=True, confirmation_prompt=True)
            from sqlalchemy.exc import IntegrityError
            try:
                create_owner(session, username, password, password_method=password_method)
                session.commit()
            except IntegrityError:
                session.rollback()
                raise click.ClickException('Owner already exists') from None
            except ValueError as exc:
                session.rollback()
                raise click.ClickException(str(exc)) from None
        click.echo('Owner created')

    @auth_cli.command('create-hermes-credential')
    @click.option('--label', prompt=True)
    def create_credential(label):
        """Create finance:read bearer; prints the secret once, locally only."""
        with db.Session() as session:
            if session.scalar(select(Owner.id).limit(1)) is None:
                raise click.ClickException('Bootstrap an owner first')
            click.confirm('Local owner administrator: create finance:read credential?', abort=True)
            try:
                raw, record = issue_hermes_credential(session, label)
            except ValueError as exc:
                raise click.ClickException(str(exc)) from exc
            record_id = record.id
            session.commit()
        click.echo(f'Credential ID: {record_id}; scope: finance:read. Save secret now; shown once:')
        click.echo(raw)

    @auth_cli.command('revoke-hermes-credential')
    @click.option('--credential-id', type=int, required=True)
    def revoke_credential(credential_id):
        with db.Session() as session:
            if session.scalar(select(Owner.id).limit(1)) is None:
                raise click.ClickException('Bootstrap an owner first')
            click.confirm('Local owner administrator: revoke this credential?', abort=True)
            if not revoke_hermes_credential(session, credential_id):
                raise click.ClickException('Credential not found')
            session.commit()
        click.echo('Credential revoked')
