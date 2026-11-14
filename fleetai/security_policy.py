"""Explicit actor boundaries for legacy FleetAI and the separate Hermes API.

Legacy reads can write: Hermes is NEVER allowed to call them, even via GET.
Owner/driver legacy behavior remains intact behind authentication and CSRF.
"""
import hmac
import os

from urllib.parse import urlsplit
from flask import Response, current_app, g, jsonify, redirect, request, url_for

READONLY_PREFIX = '/api/integrations/hermes/v1/'
SERVICE_ENDPOINTS = frozenset({
    'api_cron_daily_rent_and_alerts', 'api_cron_driver_balance_alerts',
    'cron_daily_driver_rent', 'check_driver_payments', 'api_cron_block_preview_665',
    'api_telegram_setup_webhook', 'api_setup_897', 'api_setup_550',
})
CONTRACT_ENDPOINTS = frozenset({
    'driver_contract_page', 'api_driver_contract_get', 'api_driver_contract_save',
    'api_driver_contract_send_code', 'api_driver_contract_sign',
    'driver_contract_preview_pdf', 'driver_contract_pdf',
})
DRIVER_ENDPOINTS = {
    'driver_portal_mvp': frozenset({'GET', 'HEAD'}),
    'api_driver_mvp': frozenset({'GET', 'HEAD'}),
    'api_driver_create_bank_payment': frozenset({'POST'}),
    'api_driver_blocking_preview': frozenset({'GET', 'HEAD'}),
    'api_vehicle_license_download': frozenset({'GET', 'HEAD'}),
    'api_vehicle_license_status': frozenset({'GET', 'HEAD'}),
}
# These GET handlers have side effects (including external payments/notifications).
# Preserve existing behavior for authenticated UI, but require CSRF headers.
SIDE_EFFECT_GETS = frozenset({
    'api_summary', 'api_cars', 'api_cars_monthly_finance', 'api_car',
    'api_investor_balance', 'api_period', 'api_investors', 'api_investors_summary',
    'api_investor_report_history', 'test_investor_report', 'api_fix_investor_data',
    'api_rebuild_calculations', 'api_repair_downtime_statuses',
    'api_driver_assignment_get', 'api_driver_mvp', 'api_driver_blocking_preview',
    'test_telegram', 'api_tbank_payment_test',
    'api_wialon_odometer_check', 'api_wialon_odometer_baseline',
    'api_wialon_vehicle_mileage', 'api_wialon_vehicle_status',
    'api_wialon_vehicle_settings', 'api_wialon_665_block_preview',
})
# Unclassified legacy API GETs require CSRF too: GET is not evidence of purity.
# Navigation exceptions are explicit and limited to inspected SELECT/document reads.
SAFE_API_NAVIGATION = frozenset({
    'api_driver_debts', 'api_driver_debt_payments', 'api_operations',
    'api_driver_wallet_cars', 'api_vehicle_license_download',
    'api_vehicle_license_status', 'download_investor_report',
})
TEST_ONLY_ENDPOINTS = frozenset({
    'api_bank_simulator_webhook', 'api_driver_mvp_test_topup',
    'api_driver_mvp_test_debt', 'api_driver_mvp_clear_test_debt',
})
CLIENT_JS = r"""(() => {
'use strict';
const nativeFetch = window.fetch.bind(window);
const state = nativeFetch('/auth/session', {credentials:'same-origin',cache:'no-store'})
 .then(r => r.ok ? r.json() : null).catch(() => null);
window.fetch = async (input, options) => {
 const req = new Request(input, options);
 const target = new URL(req.url, location.href);
 if (target.origin === location.origin &&
     (target.pathname.startsWith('/api/') || target.pathname === '/auth/logout')) {
   const current = await state;
   const csrf = current && (current.csrf_token || current.csrf);
   if (csrf) req.headers.set('X-CSRF-Token', csrf);
   req.headers.set('X-Requested-With','FleetAI');
 }
 return nativeFetch(req);
};
})();"""


def fail(status, message):
    return jsonify(ok=False, message=message), status


def secrets_match(expected, supplied):
    """Reject malformed headers without raising or logging their contents."""
    return bool(expected and supplied and expected.isascii() and supplied.isascii()
                and len(supplied) <= 4096 and hmac.compare_digest(expected, supplied))


def service_authorized():
    from flask import current_app
    expected = str(current_app.config.get('CRON_SECRET') or os.getenv('CRON_SECRET') or '').strip()
    supplied = str(request.headers.get('X-Admin-Secret') or request.args.get('secret') or '').strip()
    return secrets_match(expected, supplied)


def register_policy(app):
    @app.route('/auth/client.js', methods=['GET'])
    def security_client_script():
        return Response(CLIENT_JS, mimetype='application/javascript')

    @app.before_request
    def protect_routes():
        from .auth import authenticate_request, require_csrf
        endpoint = (request.endpoint or '').rsplit('.', 1)[-1]
        if request.endpoint is None:
            return None
        # Login flows enforce their own origin checks. Service credentials do
        # not gain browser sessions or introspection access via these routes.
        if request.path.startswith('/auth/'):
            if request.headers.get('Authorization') is not None:
                principal = authenticate_request()
                return fail(403 if principal else 401, 'Credential is restricted to the Hermes read-only API')
            return None
        if endpoint in {'static', 'healthz'}:
            return None
        principal = authenticate_request()
        g.principal = principal
        has_bearer = bool(request.headers.get('Authorization'))
        if request.path.startswith(READONLY_PREFIX):
            if principal is None:
                return fail(401, 'Authentication required')
            if principal.kind != 'hermes' or 'finance:read' not in principal.scopes:
                return fail(403, 'finance:read credential required')
            if request.method not in {'GET', 'HEAD', 'OPTIONS'}:
                return fail(403, 'Read-only credential')
            return None
        # A bearer token cannot reuse owner cookies or hit any legacy handler.
        if has_bearer:
            return fail(403 if principal else 401, 'Credential is restricted to the Hermes read-only API')
        if endpoint == 'api_telegram_webhook':
            expected = str(app.config.get('TELEGRAM_WEBHOOK_SECRET') or os.getenv('TELEGRAM_WEBHOOK_SECRET') or '').strip()
            supplied = request.headers.get('X-Telegram-Bot-Api-Secret-Token', '')
            if not expected:
                return fail(503, 'Telegram webhook authentication is not configured')
            if not secrets_match(expected, supplied):
                return fail(403, 'Invalid webhook authentication')
            return None
        if endpoint == 'tbank_webhook':
            # Existing handler verifies the bank signature and confirmation state.
            return None
        if endpoint in CONTRACT_ENDPOINTS:
            # Capability tokens and call confirmation remain in existing handlers.
            return None
        if endpoint in TEST_ONLY_ENDPOINTS:
            # No public simulator or test-credit entry points in production.
            if not (app.testing and app.config.get('ENABLE_TEST_PAYMENT_ROUTES', False)):
                return fail(404, 'Not found')
        if endpoint in SERVICE_ENDPOINTS:
            # Preserve existing cron methods/query support, never fail open or
            # let a browser session substitute for service authentication.
            if service_authorized():
                return None
            return fail(403, 'Service authentication required')
        if principal is None:
            if request.path.startswith('/api/') or request.method not in {'GET', 'HEAD'}:
                return fail(401, 'Authentication required')
            if endpoint == 'driver_portal_mvp':
                return redirect('/auth/driver')
            return redirect(url_for('auth.login', next=request.path))
        if principal.kind == 'driver':
            allowed = DRIVER_ENDPOINTS.get(endpoint, frozenset())
            if request.method not in allowed:
                return fail(403, 'Driver access is restricted to the assigned vehicle')
            code = str((request.view_args or {}).get('code') or request.args.get('code') or '').strip()
            # /driver without code defaults to the authenticated assignment, never MVP_CAR.
            if not code and endpoint == 'driver_portal_mvp':
                return redirect('/driver?code=' + principal.car_code)
            if code != principal.car_code:
                return fail(403, 'Vehicle is not assigned to this session')
        elif principal.kind != 'owner':
            return fail(403, 'Owner privileges required')
        mutating = (request.method not in {'GET', 'HEAD', 'OPTIONS'} or endpoint in SIDE_EFFECT_GETS
                    or (request.path.startswith('/api/') and request.method in {'GET', 'HEAD'}
                        and endpoint not in SAFE_API_NAVIGATION))
        if mutating and not require_csrf(principal):
            return fail(403, 'CSRF token required')
        return None

    @app.after_request
    def protect_responses(response):
        response.headers.setdefault('X-Content-Type-Options', 'nosniff')
        response.headers.setdefault('Referrer-Policy', 'no-referrer')
        response.headers.setdefault('X-Frame-Options', 'SAMEORIGIN')
        configured = current_app.config.get('PUBLIC_BASE_URL') or os.getenv('FLEETAI_PUBLIC_BASE_URL')
        if configured:
            origin = urlsplit(str(configured).rstrip('/'))
            if (origin.scheme == 'https' and origin.netloc and not origin.username
                    and not origin.password and not origin.path and not origin.query and not origin.fragment):
                # Canonical configuration, not spoofable X-Forwarded-Proto.
                response.headers.setdefault('Strict-Transport-Security', 'max-age=31536000')
        if request.path.startswith(('/api/', '/auth/', '/driver')):
            response.headers['Cache-Control'] = 'no-store'
        principal = getattr(g, 'principal', None)
        if (principal and principal.kind in {'owner', 'driver'} and
                response.mimetype == 'text/html' and not request.path.startswith('/auth/')):
            text = response.get_data(as_text=True)
            script = '<script src="/auth/client.js"></script>'
            if '<head>' in text:
                text = text.replace('<head>', '<head>' + script, 1)
            else:
                text = script + text
            response.set_data(text)
        return response
