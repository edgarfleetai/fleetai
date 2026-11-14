#!/usr/bin/env python3
"""Opt-in real TLS acceptance; run in a fresh interpreter, never import into app."""
from __future__ import annotations

import argparse
from contextlib import ExitStack
import hashlib
from http import HTTPStatus
from http.client import HTTPConnection
from http.cookies import SimpleCookie
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
import os
from pathlib import Path
import secrets
import shutil
import socket
import sqlite3
import ssl
import sys
import tempfile
import threading
import traceback
from urllib.parse import urlsplit
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[2]
PREFIX = '/api/integrations/hermes/v1'
COOKIE = '__Host-fleetai_session'
SPOOF = {'Forwarded': 'for=203.0.113.99;proto=https;host=evil.invalid',
         'X-Forwarded-Proto': 'https', 'X-Forwarded-Host': 'evil.invalid',
         'X-Forwarded-For': '203.0.113.99'}


class BoundaryViolation(RuntimeError):
    pass


class Boundary:
    """Process-local guard, not a sandbox against malicious native extensions."""
    def __init__(self, directory):
        self.directory = directory.resolve()
        self.listeners = set()
        self.bind_count = 0
        self.events = []
        self.expected_denial = False
        self.main_thread = threading.get_ident()

    def deny(self, operation):
        self.events.append({'operation': operation, 'expected': self.expected_denial})
        raise BoundaryViolation('Denied boundary: ' + operation)

    def audit(self, event, args):
        if event == 'socket.connect':
            sock, address = args
            if (sock.family != socket.AF_INET or sock.type & socket.SOCK_STREAM == 0
                    or not isinstance(address, tuple) or address not in self.listeners):
                self.deny('socket.connect')
        elif event == 'socket.bind':
            sock, address = args
            if (sock.family != socket.AF_INET or sock.type & socket.SOCK_STREAM == 0
                    or address != ('127.0.0.1', 0) or self.bind_count >= 2):
                self.deny('socket.bind')
            self.bind_count += 1
        elif event in {'socket.sendto', 'socket.sendmsg', 'subprocess.Popen',
                       'os.system', 'os.posix_spawn', 'os.exec', 'os.fork'}:
            self.deny(event)
        elif event == 'sqlite3.connect':
            database = str(args[0])
            if database not in {str(self.directory / 'writer.sqlite'), str(self.directory / 'reader.sqlite')}:
                self.deny('sqlite3.connect')
        elif event == 'socket.getaddrinfo':
            if args[0] not in ('localhost', '127.0.0.1'):
                self.deny('socket.getaddrinfo')
        elif event in ('socket.gethostbyname', 'socket.gethostbyaddr'):
            if args[0] not in ('localhost', '127.0.0.1'):
                self.deny(event)

    def install(self, stack):
        sys.addaudithook(self.audit)
        original = socket.getaddrinfo

        def local_resolution(host, port, family=0, type=0, proto=0, flags=0):
            if host not in ('localhost', '127.0.0.1'):
                self.deny('DNS')
            return original('127.0.0.1', port, socket.AF_INET, type, proto, flags)

        stack.enter_context(patch.object(socket, 'getaddrinfo', local_resolution))
        # connect_ex does not emit socket.connect on every CPython release.
        original_connect = socket.socket.connect

        def connect_ex(sock, address):
            self.audit('socket.connect', (sock, address))
            try:
                original_connect(sock, address)
                return 0
            except OSError as error:
                return error.errno

        stack.enter_context(patch.object(socket.socket, 'connect_ex', connect_ex))

    def selfcheck(self):
        self.expected_denial = True
        try:
            for address in [('198.51.100.1', 443), ('127.0.0.1', 1), ('::1', 443)]:
                with socket.socket(socket.AF_INET6 if address[0] == '::1' else socket.AF_INET) as sock:
                    try:
                        sock.connect(address)
                    except BoundaryViolation:
                        pass
                    else:
                        raise AssertionError('TCP guard allowed an unlisted destination')
            try:
                socket.getaddrinfo('external.invalid', 443)
            except BoundaryViolation:
                pass
            else:
                raise AssertionError('External DNS allowed')
            with socket.socket() as sock:
                try:
                    sock.connect_ex(('127.0.0.1', 1))
                except BoundaryViolation:
                    pass
                else:
                    raise AssertionError('connect_ex bypassed guard')
        finally:
            self.expected_denial = False


def certificate(directory):
    """One-day synthetic CA/localhost leaf; OpenSSL runs BEFORE app/guards."""
    import subprocess
    openssl = shutil.which('openssl')
    if not openssl:
        raise RuntimeError('OpenSSL executable is required')
    ca_path, cert_path, key_path = [directory / p for p in ('ca.pem', 'localhost.pem', 'localhost.key')]
    ca_key, csr, config = [directory / p for p in ('ca.key', 'localhost.csr', 'openssl.cnf')]
    config.write_text('''[req]
distinguished_name=dn
prompt=no
[dn]
CN=localhost
[ca]
basicConstraints=critical,CA:TRUE,pathlen:0
keyUsage=critical,keyCertSign,cRLSign
[leaf]
basicConstraints=critical,CA:FALSE
keyUsage=critical,digitalSignature,keyEncipherment
extendedKeyUsage=serverAuth
subjectAltName=DNS:localhost
''')
    # LibreSSL may prefer prompt=no config DN over -subj; use distinct configs
    # so issuer and leaf subjects cannot accidentally both become localhost.
    ca_config = directory / 'ca.cnf'
    ca_config.write_text(config.read_text().replace('CN=localhost', 'CN=FleetAI synthetic acceptance CA'))
    def command(*arguments):
        subprocess.run([openssl, *map(str, arguments)], check=True,
                       stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=30,
                       env={'PATH': os.defpath})
    old_umask = os.umask(0o077)
    try:
        command('req', '-x509', '-newkey', 'rsa:2048', '-nodes', '-sha256', '-days', '1',
                '-config', ca_config, '-extensions', 'ca',
                '-keyout', ca_key, '-out', ca_path)
        command('req', '-new', '-newkey', 'rsa:2048', '-nodes', '-sha256', '-config', config,
                '-keyout', key_path, '-out', csr)
        command('x509', '-req', '-in', csr, '-CA', ca_path, '-CAkey', ca_key,
                '-set_serial', str(secrets.randbits(128)), '-days', '1', '-sha256',
                '-extfile', config, '-extensions', 'leaf', '-out', cert_path)
        context = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
        context.minimum_version = ssl.TLSVersion.TLSv1_2
        context.load_cert_chain(cert_path, key_path)
    finally:
        os.umask(old_umask)
        for secret in (key_path, ca_key, csr, config, ca_config):
            secret.unlink(missing_ok=True)
    return context, ca_path


class Proxy(BaseHTTPRequestHandler):
    protocol_version = 'HTTP/1.1'
    def log_message(self, *args):
        pass  # Never log credentials, tickets, cookies or bodies.

    def do_GET(self):
        self.forward()

    do_POST = do_HEAD = do_OPTIONS = do_PUT = do_DELETE = do_GET

    def forward(self):
        parsed = urlsplit(self.path)
        if parsed.scheme or parsed.netloc or not self.path.startswith('/'):
            self.send_error(HTTPStatus.BAD_REQUEST)
            return
        length = int(self.headers.get('Content-Length', '0'))
        if length > 1024 * 1024 or self.headers.get('Transfer-Encoding'):
            self.send_error(HTTPStatus.BAD_REQUEST)
            return
        body = self.rfile.read(length)
        hop = {'connection', 'proxy-connection', 'keep-alive', 'transfer-encoding',
               'te', 'trailer', 'upgrade', 'proxy-authorization', 'proxy-authenticate'}
        headers = {key: value for key, value in self.headers.items() if key.lower() not in hop}
        # Host is deliberately preserved. Injected client forwarding headers are
        # deliberately passed through for adversarial tests, never used as trust.
        headers.setdefault('X-Forwarded-Proto', 'https')
        headers.setdefault('X-Forwarded-Host', self.headers['Host'])
        headers['Connection'] = 'close'
        connection = HTTPConnection('127.0.0.1', self.server.backend_port, timeout=10)
        try:
            connection.request(self.command, self.path, body=body, headers=headers)
            response = connection.getresponse()
            data = response.read()
            self.send_response_only(response.status)
            for key, value in response.getheaders():
                if key.lower() not in hop | {'content-length', 'server', 'date'}:
                    self.send_header(key, value)
            self.send_header('Content-Length', str(len(data)))
            self.send_header('Connection', 'close')
            self.end_headers()
            if self.command != 'HEAD':
                self.wfile.write(data)
        finally:
            connection.close()


class QuietHandler:
    @staticmethod
    def make():
        from werkzeug.serving import WSGIRequestHandler
        class Handler(WSGIRequestHandler):
            def log(self, *args, **kwargs):
                pass
        return Handler


class Harness:
    def __init__(self, directory, stack):
        self.directory, self.stack = directory, stack
        self.boundary = Boundary(directory)
        # Certificate subprocesses finish before any application module import;
        # after guard installation ALL subprocess creation is forbidden.
        self.context, self.ca = certificate(directory)
        self.boundary.install(stack)
        # urllib3's import-time IPv6 bind capability probe is irrelevant to
        # this IPv4-only harness. Disable that probe, not any security policy.
        with patch.object(socket, 'has_ipv6', False):
            import requests
        # Drop every inherited credential/configuration before application imports.
        keep = {key: value for key, value in os.environ.items()
                if key in {'PATH', 'HOME', 'LANG', 'LC_ALL', 'SYSTEMROOT', 'WINDIR'}}
        stack.enter_context(patch.dict(os.environ, keep, clear=True))
        writer = directory / 'writer.sqlite'
        reader = directory / 'reader.sqlite'
        os.environ['DATABASE_URL'] = 'sqlite:///' + str(writer)
        os.environ['TMPDIR'] = str(directory)
        self.proxy = ThreadingHTTPServer(('127.0.0.1', 0), Proxy)
        stack.callback(self.proxy.server_close)
        self.boundary.listeners.add(self.proxy.server_address)
        self.origin = 'https://localhost:' + str(self.proxy.server_port)
        self.proxy.socket = self.context.wrap_socket(self.proxy.socket, server_side=True)
        from fleetai import create_app, db
        from sqlalchemy import event
        from sqlalchemy.engine import Engine

        def isolated_database(dialect, record, args, kwargs):
            if dialect.name != 'sqlite' or str(args[0]) not in {str(writer), str(reader)}:
                self.boundary.deny('SQLAlchemy.do_connect')
        event.listen(Engine, 'do_connect', isolated_database)
        stack.callback(event.remove, Engine, 'do_connect', isolated_database)
        # The only app helper patched: prevent built-in real-world fleet sample seeding.
        with patch.object(db, 'seed_cars', lambda: None):
            self.app = create_app({'TESTING': False, 'DEBUG': False,
                                   'DATABASE_URL': 'sqlite:///' + str(writer),
                                   'PUBLIC_BASE_URL': self.origin,
                                   'FINANCE_READONLY_DATABASE_URL': 'sqlite:///' + str(reader)})
        assert not self.app.testing and not self.app.debug
        stack.callback(db.engine.dispose)
        self.seed()
        # Separate persisted datasource, with distinct marker only in reader.
        with sqlite3.connect(writer) as source, sqlite3.connect(reader) as target:
            source.backup(target)
            target.execute("UPDATE cars SET driver='Reader-only synthetic marker' WHERE code='HTTPSA'")
            target.commit()
        self.observations = []
        def observed(environ, start_response):
            self.observations.append({'scheme': environ['wsgi.url_scheme'],
                                      'host': environ.get('HTTP_HOST'),
                                      'path': environ['PATH_INFO']})
            return self.app(environ, start_response)
        from werkzeug.serving import make_server
        self.backend = make_server('127.0.0.1', 0, observed, threaded=True,
                                   request_handler=QuietHandler.make())
        stack.callback(self.backend.server_close)
        self.boundary.listeners.add(self.backend.socket.getsockname())
        self.proxy.backend_port = self.backend.server_port
        self.backend_url = 'http://127.0.0.1:' + str(self.backend.server_port)
        stack.callback(self.dispose_reader)
        self.threads = []
        for server in (self.backend, self.proxy):
            thread = threading.Thread(target=server.serve_forever, kwargs={'poll_interval': 0.05}, daemon=True)
            thread.start()
            self.threads.append(thread)
            stack.callback(self.stop, server, thread)
        import requests
        self.requests = requests
        original_send = requests.Session.send
        def guarded_send(session, request, **kwargs):
            target = urlsplit(request.url)
            if threading.get_ident() != self.boundary.main_thread:
                self.boundary.deny('application.requests')
            if target.scheme != 'https' or target.netloc != urlsplit(self.origin).netloc:
                self.boundary.deny('client.noncanonical_or_plaintext_request')
            if kwargs.get('verify') != str(self.ca):
                self.boundary.deny('client.unverified_TLS')
            return original_send(session, request, **kwargs)
        stack.enter_context(patch.object(requests.Session, 'send', guarded_send))

    def dispose_reader(self):
        engine = self.app.extensions.get('fleetai_finance_readonly_engine')
        if engine is not None:
            engine.dispose()

    @staticmethod
    def stop(server, thread):
        server.shutdown()
        thread.join(timeout=5)
        if thread.is_alive():
            raise AssertionError('Server thread failed to stop')

    def seed(self):
        from fleetai import db
        from fleetai.models import Car, DriverDebt, DriverWalletTransaction, Operation
        from fleetai.auth_models import Owner, telegram_bindings
        from fleetai.auth import issue_hermes_credential
        from werkzeug.security import generate_password_hash
        self.username = 'https-synthetic-owner'
        self.password = secrets.token_urlsafe(32)
        with db.Session() as session:
            session.add(Owner(id=1, username=self.username, password_hash=generate_password_hash(self.password)))
            session.add_all([Car(code='HTTPSA', driver='Synthetic A', brand='Synthetic', model='Local', plate='LOCAL-A'),
                             Car(code='HTTPSB', driver='Synthetic B', brand='Synthetic', model='Local', plate='LOCAL-B')])
            session.flush()
            session.execute(telegram_bindings.insert().values(car_code='HTTPSA', driver_name='Synthetic A', telegram_chat_id='1000000001'))
            session.add(DriverDebt(car_code='HTTPSA', driver_name='Synthetic A', original_amount=17, paid_amount=0, balance=17, reason='local acceptance'))
            session.add(DriverWalletTransaction(car_code='HTTPSA', driver_name='Synthetic A', amount=-11, transaction_type='daily_rent', source='manual', comment='local acceptance'))
            session.add(Operation(car_code='HTTPSA', type='income', category='Аренда', amount=13, description='local acceptance'))
            self.bearer, _ = issue_hermes_credential(session, 'local-https-acceptance')
            session.commit()

    def browser(self):
        session = self.requests.Session()
        session.trust_env = False
        session.verify = str(self.ca)
        self.stack.callback(session.close)
        return session

    def request(self, browser, method, path, **kwargs):
        assert path.startswith('/') and not path.startswith('//'), 'Relative canonical target required'
        return browser.request(method, self.origin + path, timeout=10, allow_redirects=False, **kwargs)

    def owner(self, host=None):
        browser = self.browser()
        headers = {'Origin': self.origin}
        if host:
            headers['Host'] = host
        response = self.request(browser, 'POST', '/auth/login', headers=headers,
                                data={'username': self.username, 'password': self.password})
        assert response.status_code == 303, f'Owner login expected 303, got {response.status_code}'
        check_cookie(response)
        response = self.request(browser, 'GET', '/auth/session')
        assert response.status_code == 200, 'Secure owner session did not survive HTTPS round trip'
        data = response.json()
        assert data['kind'] == 'owner'
        return browser, data['csrf_token']

    def ticket(self):
        from fleetai import db
        from fleetai.models import Car
        from fleetai.routes import driver_login_url
        from sqlalchemy import select
        # Explicit hostile request context proves URL builder uses configured canonical URL.
        with self.app.test_request_context('/', base_url='http://evil.invalid', headers=SPOOF):
            with db.Session() as session:
                return driver_login_url(session, session.scalar(select(Car).where(Car.code == 'HTTPSA')), '1000000001')

    def snapshot(self):
        result = {}
        for name in ('writer.sqlite', 'reader.sqlite'):
            with sqlite3.connect(self.directory / name) as connection:
                result[name] = hashlib.sha256('\n'.join(connection.iterdump()).encode()).hexdigest()
        return result


def check_cookie(response):
    headers = response.raw.headers.getlist('Set-Cookie')
    cookies = SimpleCookie()
    for value in headers:
        cookies.load(value)
    assert COOKIE in cookies, 'Missing __Host session cookie'
    cookie = cookies[COOKIE]
    assert cookie['secure'] and cookie['httponly'], 'Session cookie needs Secure and HttpOnly'
    assert cookie['samesite'].lower() == 'lax', 'Session cookie SameSite must be Lax'
    assert cookie['path'] == '/' and not cookie['domain'], '__Host cookie must be host-only, Path=/'


def check_headers(response):
    assert 'no-store' in response.headers.get('Cache-Control', ''), 'Sensitive response must be no-store'
    assert response.headers.get('X-Content-Type-Options') == 'nosniff'
    assert response.headers.get('Referrer-Policy') == 'no-referrer'
    assert response.headers.get('X-Frame-Options') == 'SAMEORIGIN'
    assert response.headers.get('Strict-Transport-Security') == 'max-age=31536000', 'Configured HTTPS origin must emit HSTS even behind HTTP termination'


def scenarios(h):
    def guard():
        h.boundary.selfcheck()
        assert len(h.boundary.listeners) == 2 and h.boundary.bind_count == 2
        assert all(host == '127.0.0.1' for host, _ in h.boundary.listeners)
        assert not list(h.directory.glob('*.key'))
        browser = h.browser()
        h.boundary.expected_denial = True
        try:
            for url, options in [(h.backend_url + '/auth/login', {'data': {'password': 'synthetic-never-sent'}}),
                                 ('https://external.invalid/', {}),
                                 (h.origin + '/auth/session', {'verify': False})]:
                try:
                    browser.post(url, timeout=1, **options)
                except BoundaryViolation:
                    pass
                else:
                    raise AssertionError('Request guard allowed external/plaintext/unverified request')
        finally:
            h.boundary.expected_denial = False
    yield 'transport_guard_selfcheck', guard

    def transport():
        browser = h.browser()
        for path, status in [('/auth/login', 200), ('/auth/session', 401), ('/auth/driver', 200)]:
            response = h.request(browser, 'GET', path)
            assert response.status_code == status, f'{path}: expected {status}, got {response.status_code}'
            check_headers(response)
        assert h.observations and all(row['scheme'] == 'http' for row in h.observations), 'Proxy did not terminate TLS to actual backend HTTP'
        assert h.observations[-1]['host'] == urlsplit(h.origin).netloc, 'Proxy did not preserve original Host'
        # Default trust MUST fail; a successful CA-verified call alone could mask verify=False.
        context = ssl.create_default_context()
        try:
            with socket.create_connection(('127.0.0.1', h.proxy.server_port), timeout=5) as raw:
                with context.wrap_socket(raw, server_hostname='localhost'):
                    pass
        except ssl.SSLCertVerificationError:
            pass
        else:
            raise AssertionError('Synthetic CA unexpectedly trusted by default')
        # Wrong hostname must fail with the explicitly trusted CA as well.
        context = ssl.create_default_context(cafile=str(h.ca))
        try:
            with socket.create_connection(('127.0.0.1', h.proxy.server_port), timeout=5) as raw:
                with context.wrap_socket(raw, server_hostname='wrong.invalid'):
                    pass
        except ssl.SSLCertVerificationError:
            pass
        else:
            raise AssertionError('TLS hostname validation was bypassed')
        # A browser cookie jar never emits Secure cookies on plaintext HTTP.
        from requests import Request
        browser.cookies.set(COOKIE, 'synthetic-cookie-probe', domain='localhost.local', path='/', secure=True)
        prepared = browser.prepare_request(Request('GET', 'http://localhost:' + str(h.proxy.server_port) + '/auth/session'))
        assert 'Cookie' not in prepared.headers, 'Secure cookie leaked to plaintext'
        # TLS listener does not expose a plaintext HTTP login page. No secrets sent.
        with socket.create_connection(('127.0.0.1', h.proxy.server_port), timeout=5) as raw:
            raw.sendall(b'GET /auth/login HTTP/1.1\r\nHost: localhost\r\nConnection: close\r\n\r\n')
            try:
                data = raw.recv(4096)
            except ConnectionResetError:
                data = b''
            assert b'<form' not in data and b'200 OK' not in data, 'Plaintext login page exposed by TLS listener'
    yield 'verified_tls_real_http_backend_and_headers', transport

    def prelogin():
        browser = h.browser()
        for headers in [{}, {'Origin': 'https://evil.invalid', **SPOOF},
                        {'Origin': h.origin, 'Sec-Fetch-Site': 'cross-site', **SPOOF},
                        {'Forwarded': 'proto=https;host=localhost', 'X-Forwarded-Proto': 'https',
                         'X-Forwarded-Host': urlsplit(h.origin).netloc}]:
            response = h.request(browser, 'POST', '/auth/login', headers=headers,
                                 data={'username': h.username, 'password': h.password})
            assert response.status_code == 403, f'Pre-login origin proof: expected 403, got {response.status_code}'
            assert COOKIE not in browser.cookies
            check_headers(response)
    yield 'prelogin_origin_proof_and_forwarding_spoof_denied', prelogin

    def owner():
        browser, csrf = h.owner()
        for headers in [{'Origin': h.origin}, {'Origin': h.origin, 'X-CSRF-Token': 'wrong'},
                        {'Origin': 'https://evil.invalid', 'X-CSRF-Token': csrf, **SPOOF},
                        {'Origin': 'http://' + urlsplit(h.origin).netloc, 'X-CSRF-Token': csrf, **SPOOF}]:
            response = h.request(browser, 'POST', '/auth/logout', headers=headers)
            assert response.status_code == 403, f'CSRF negative expected 403, got {response.status_code}'
            assert h.request(browser, 'GET', '/auth/session').status_code == 200
            check_headers(response)
        response = h.request(browser, 'POST', '/auth/logout', headers={'Origin': h.origin, 'X-CSRF-Token': csrf})
        assert response.status_code == 303, f'Canonical origin CSRF expected 303, got {response.status_code}'
        assert h.request(browser, 'GET', '/auth/session').status_code == 401
    yield 'owner_cookie_https_session_csrf_and_logout', owner

    def canonical():
        # Host/forwarding hints must not replace PUBLIC_BASE_URL in origin matching.
        browser = h.browser()
        hostile_host = 'hostile.invalid'
        response = h.request(browser, 'POST', '/auth/login', headers={'Host': hostile_host, 'Origin': 'https://' + hostile_host, **SPOOF},
                             data={'username': h.username, 'password': h.password})
        assert response.status_code == 403, 'Client Host replaced configured canonical Origin'
        response = h.request(browser, 'POST', '/auth/login', headers={'Host': hostile_host, 'Origin': h.origin, **SPOOF},
                             data={'username': h.username, 'password': h.password})
        assert response.status_code == 303, f'Configured canonical Origin rejected behind HTTP proxy: {response.status_code}'
        assert h.observations[-1]['host'] == hostile_host
        assert h.observations[-1]['scheme'] == 'http'
        check_cookie(response)
        assert response.headers['Location'] == '/', 'Login redirect reflected attacker Host'
    yield 'explicit_public_base_url_authoritative_behind_proxy', canonical

    def driver():
        url = h.ticket()
        parts = urlsplit(url)
        assert parts.scheme + '://' + parts.netloc == h.origin
        assert parts.path == '/auth/driver' and not parts.query and parts.fragment.startswith('token=')
        token = parts.fragment.removeprefix('token=')
        browser = h.browser()
        response = h.request(browser, 'GET', parts.path + '#' + parts.fragment)
        assert response.status_code == 200
        assert token not in response.text and token not in h.observations[-1]['path']
        assert "history.replaceState" in response.text and "onclick" in response.text, 'Fragment must clear before explicit redemption'
        assert h.request(browser, 'GET', '/auth/session').status_code == 401, 'Landing GET redeemed ticket'
        assert h.request(browser, 'GET', '/auth/driver?token=' + token).status_code == 400
        for headers in [{}, {'Origin': 'https://evil.invalid', **SPOOF}]:
            response = h.request(browser, 'POST', '/auth/driver/consume', headers=headers, json={'ticket': token})
            assert response.status_code == 403
        response = h.request(browser, 'POST', '/auth/driver/consume', headers={'Origin': h.origin}, json={'ticket': token})
        assert response.status_code == 303, f'Driver consume expected 303, got {response.status_code}'
        assert response.headers['Location'] == '/driver?code=HTTPSA'
        check_cookie(response)
        data = h.request(browser, 'GET', '/auth/session').json()
        assert data['kind'] == 'driver' and data['car_code'] == 'HTTPSA'
        assert h.request(h.browser(), 'POST', '/auth/driver/consume', headers={'Origin': h.origin}, json={'ticket': token}).status_code == 401
        response = h.request(browser, 'GET', '/driver?code=HTTPSA')
        assert response.status_code == 200
        check_headers(response)
        response = h.request(browser, 'GET', '/api/driver-mvp/HTTPSA',
                             headers={'Origin': h.origin, 'X-CSRF-Token': data['csrf_token']})
        assert response.status_code == 200, f'Own-car financial read failed: {response.status_code}'
        assert response.json()['car']['code'] == 'HTTPSA'
        check_headers(response)
        for path in ['/driver?code=HTTPSB', '/api/driver-mvp/HTTPSB', '/api/driver-debts', '/']:
            assert h.request(browser, 'GET', path, headers={'Origin': h.origin, 'X-CSRF-Token': data['csrf_token'], **SPOOF}).status_code == 403, 'Driver escaped own-car scope: ' + path
        pending = urlsplit(h.ticket()).fragment.removeprefix('token=')
        from fleetai import db
        from fleetai.auth import revoke_driver_access
        with db.Session() as session:
            revoke_driver_access(session, 'HTTPSA')
            session.commit()
        assert h.request(browser, 'GET', '/auth/session').status_code == 401
        assert h.request(browser, 'GET', '/driver?code=HTTPSA').status_code == 302
        assert h.request(h.browser(), 'POST', '/auth/driver/consume', headers={'Origin': h.origin}, json={'ticket': pending}).status_code == 401
    yield 'driver_fragment_single_use_scope_and_revocation', driver

    def hermes():
        owner, csrf = h.owner()
        browser = h.browser()
        bearer = {'Authorization': 'Bearer ' + h.bearer}
        before = h.snapshot()
        try:
            for endpoint in ('debts', 'balances', 'rent-accruals', 'payments'):
                path = PREFIX + '/' + endpoint
                response = h.request(browser, 'GET', path, headers=bearer)
                assert response.status_code == 200, f'{endpoint}: expected 200, got {response.status_code}'
                check_headers(response)
                data = response.json()['data']
                assert data and data[0]['car_code'] == 'HTTPSA', endpoint + ': missing synthetic ledger'
                if endpoint == 'balances':
                    assert data[0]['current_driver_name'] == 'Reader-only synthetic marker', 'Read API used writer datasource'
                assert h.request(browser, 'POST', path, headers=bearer, json={'amount': 1}).status_code in (403, 405)
                assert h.request(owner, 'GET', path).status_code == 403, 'Owner cookie replaced required bearer'
                assert h.request(owner, 'GET', path, headers={'Authorization': 'Bearer invalid'}).status_code == 401, 'Invalid bearer fell back to owner cookie'
                assert h.request(browser, 'GET', path).status_code == 401
            for path in ['/api/summary', '/api/cars', '/api/driver-mvp/HTTPSA', '/api/driver-debts', '/auth/session', '/']:
                response = h.request(owner, 'GET', path, headers={**bearer, 'Origin': h.origin, 'X-CSRF-Token': csrf})
                assert response.status_code == 403, 'Hermes entered legacy/owner route: ' + path
            assert h.request(owner, 'POST', '/auth/logout', headers={**bearer, 'Origin': h.origin, 'X-CSRF-Token': csrf}).status_code == 403
        finally:
            assert h.snapshot() == before, 'Hermes reads/denials mutated a database'
    yield 'hermes_four_reads_dedicated_datasource_denials_no_mutations', hermes


def source_inventory():
    return {str(path.relative_to(ROOT)): hashlib.sha256(path.read_bytes()).hexdigest()
            for path in sorted((ROOT / 'fleetai').glob('*.py'))}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--artifacts-dir', required=True, type=Path,
                        help='Existing/new directory OUTSIDE repository; per-run child is created')
    parser.add_argument('--smoke', action='store_true', help='PRELIMINARY guard/TLS/read-only public endpoints only; not acceptance')
    args = parser.parse_args()
    if not __debug__:
        parser.error('Assertions must be enabled: do not use python -O or PYTHONOPTIMIZE')
    root = args.artifacts_dir.expanduser().resolve()
    if root == ROOT or root.is_relative_to(ROOT):
        parser.error('--artifacts-dir must be outside repository (certificates/secrets must never enter Git)')
    root.mkdir(parents=True, exist_ok=True)
    directory = Path(tempfile.mkdtemp(prefix='fleetai-https-', dir=root))
    directory.chmod(0o700)
    sys.path.insert(0, str(ROOT))
    sys.dont_write_bytecode = True
    report = {'mode': 'PRELIMINARY_SMOKE' if args.smoke else 'ACCEPTANCE', 'cases': [],
              'source_before': source_inventory(), 'scope': 'local synthetic HTTPS only',
              'python': sys.version, 'command': sys.argv,
              'harness_sha256': hashlib.sha256(Path(__file__).read_bytes()).hexdigest()}
    harness = None
    try:
        with ExitStack() as stack:
            harness = Harness(directory, stack)
            selected = list(scenarios(harness))
            if args.smoke:
                selected = selected[:2]
            report['expected_cases'] = [name for name, _ in selected] + ['zero_unexpected_boundary_attempts']
            for name, case in selected:
                try:
                    case()
                except Exception as error:
                    # Record only fixed assertion messages; exception strings may contain secrets/URLs.
                    detail = str(error) if isinstance(error, AssertionError) or args.smoke else type(error).__name__
                    frames = [{'file': frame.filename, 'line': frame.lineno, 'function': frame.name}
                              for frame in traceback.extract_tb(error.__traceback__)]
                    report['cases'].append({'name': name, 'outcome': 'RED', 'detail': detail, 'frames': frames})
                    print('RED ' + name + ': ' + detail)
                else:
                    report['cases'].append({'name': name, 'outcome': 'PASS'})
                    print('PASS ' + name)
            report['listeners'] = sorted([list(value) for value in harness.boundary.listeners])
            report['backend_observations'] = harness.observations
            report['boundary_events'] = harness.boundary.events
            unexpected = [event for event in harness.boundary.events if not event['expected']]
            if unexpected:
                report['cases'].append({'name': 'zero_unexpected_boundary_attempts', 'outcome': 'RED', 'detail': 'Blocked integration/network attempt occurred'})
            else:
                report['cases'].append({'name': 'zero_unexpected_boundary_attempts', 'outcome': 'PASS'})
    except Exception as error:
        report['setup_or_cleanup_error'] = type(error).__name__
        report['error_frames'] = [{'file': frame.filename, 'line': frame.lineno, 'function': frame.name}
                                  for frame in traceback.extract_tb(error.__traceback__)]
        print('HARNESS ERROR: ' + type(error).__name__, file=sys.stderr)
    finally:
        report['source_after'] = source_inventory()
        report['source_unchanged'] = report['source_before'] == report['source_after']
        report['servers_stopped'] = harness is not None and all(not thread.is_alive() for thread in harness.threads)
        # No databases, passwords, keys, certificates, tickets or bearer secrets retained.
        for item in directory.iterdir():
            if item.is_file():
                item.unlink()
            elif item.is_dir():
                shutil.rmtree(item)
        report['private_keys_removed'] = not list(directory.glob('*.key'))
        report['passed'] = sum(case['outcome'] == 'PASS' for case in report['cases'])
        report['red'] = sum(case['outcome'] == 'RED' for case in report['cases'])
        report['complete'] = ([case['name'] for case in report['cases']] == report.get('expected_cases')
                              and bool(report.get('expected_cases')))
        report['success'] = (not report['red'] and not report.get('setup_or_cleanup_error')
                             and report['source_unchanged'] and report['servers_stopped'] and report['complete'])
        (directory / 'report.json').write_text(json.dumps(report, indent=2) + '\n')
        print('Report: ' + str(directory / 'report.json'))
    return 0 if report['success'] else 1


if __name__ == '__main__':
    raise SystemExit(main())
