"""Real legacy handlers behind policy; SQLite and synthetic identities only.

Bank signatures are calculated independently, never by the production signer.
Only Telegram delivery is mocked; authorization, handlers and SQL stay real.
"""
import hashlib
from unittest.mock import Mock

import pytest


@pytest.fixture
def bank(monkeypatch):
    from fleetai import tbank
    password = 'synthetic-terminal-password-for-regression'
    monkeypatch.setattr(tbank, 'TBANK_TERMINAL_PASSWORD', password)

    def notification(**overrides):
        payload = {
            'TerminalKey': 'synthetic-terminal', 'Success': True,
            'Status': 'CONFIRMED', 'PaymentId': 'synthetic-payment-001',
            'OrderId': 'fleetai-991-syntheticorder', 'Amount': 100000,
            'Data': {'source': 'SBP'}, 'IgnoredNull': None,
        }
        payload.update(overrides)
        scalar = {key: ('true' if value is True else 'false' if value is False else str(value))
                  for key, value in payload.items()
                  if key != 'Token' and value is not None and not isinstance(value, (dict, list))}
        scalar['Password'] = password
        payload['Token'] = hashlib.sha256(''.join(scalar[key] for key in sorted(scalar)).encode()).hexdigest()
        return payload

    return tbank, notification


@pytest.fixture
def synthetic_payment(secure_app):
    from fleetai.db import Session
    from fleetai.models import Car, DriverBankPayment
    with Session() as session:
        session.add(Car(code='991', driver='Synthetic Driver', daily_rent=0))
        session.add(DriverBankPayment(payment_id='synthetic-payment-001', car_code='991',
                                      driver_name='Synthetic Driver', amount=1000,
                                      provider='tbank', status='pending'))
        session.commit()


def assert_no_posting():
    from fleetai.db import Session
    from fleetai.models import Operation, Income, DriverWalletTransaction
    with Session() as session:
        for model in (Operation, Income, DriverWalletTransaction):
            assert session.query(model).count() == 0


def test_real_bank_verifier_accepts_independent_signature_and_rejects_tampering(bank):
    tbank, notification = bank
    payload = notification()
    assert tbank.verify_notification(payload) is True
    payload['Amount'] += 100
    assert tbank.verify_notification(payload) is False
    assert tbank.verify_notification({}) is False


@pytest.mark.parametrize('token_kind', ['absent', 'invalid', 'tampered'])
def test_unsigned_or_invalid_bank_notification_cannot_post(secure_app, synthetic_payment, bank, token_kind):
    _, notification = bank
    payload = notification()
    if token_kind == 'absent':
        payload.pop('Token')
    elif token_kind == 'invalid':
        payload['Token'] = 'synthetic-invalid-signature'
    else:
        payload['Amount'] += 100
    response = secure_app.test_client().post('/api/tbank/webhook', json=payload)
    assert response.status_code == 403
    assert response.get_data(as_text=True) == 'INVALID TOKEN'
    assert_no_posting()


@pytest.mark.parametrize(('source', 'wallet_credit'), [('SBP', 980), ('CARD', 960)])
def test_confirmed_bank_payment_posts_original_rows_exactly_once(secure_app, synthetic_payment, bank, source, wallet_credit):
    from fleetai.db import Session
    from fleetai.models import Operation, Income, DriverWalletTransaction, DriverBankPayment
    _, notification = bank
    payload = notification(Data={'source': source})
    client = secure_app.test_client()
    for _ in range(2):
        response = client.post('/api/tbank/webhook', json=payload)
        assert response.status_code == 200
        assert response.get_data(as_text=True) == 'OK'
        with Session() as session:
            operation = session.query(Operation).one()
            assert (operation.car_code, operation.type, operation.category, operation.amount) == ('991', 'income', 'Аренда', 1000)
            assert '[TBANK_PAYMENT:synthetic-payment-001]' in operation.raw_message
            income = session.query(Income).one()
            assert (income.operation_id, income.car_code, income.amount) == (operation.id, '991', 1000)
            wallet = session.query(DriverWalletTransaction).one()
            assert (wallet.car_code, wallet.driver_name, wallet.amount, wallet.transaction_type, wallet.source) == ('991', 'Synthetic Driver', wallet_credit, 'topup', 'tbank')
            payment = session.query(DriverBankPayment).one()
            assert payment.status == 'paid'
            assert payment.paid_at is not None


@pytest.mark.parametrize('overrides', [
    {'Success': False}, {'Status': 'AUTHORIZED'}, {'Status': 'NEW'},
])
def test_signed_unconfirmed_notification_acknowledges_without_posting(secure_app, synthetic_payment, bank, overrides):
    from fleetai.db import Session
    from fleetai.models import DriverBankPayment
    _, notification = bank
    response = secure_app.test_client().post('/api/tbank/webhook', json=notification(**overrides))
    assert response.status_code == 200
    assert response.get_data(as_text=True) == 'OK'
    assert_no_posting()
    with Session() as session:
        payment = session.query(DriverBankPayment).one()
        assert payment.status == 'pending'
        assert payment.paid_at is None


@pytest.fixture
def telegram(secure_app, monkeypatch):
    from fleetai import routes
    secret = 'synthetic-telegram-webhook-secret'
    secure_app.config['TELEGRAM_WEBHOOK_SECRET'] = secret
    monkeypatch.setenv('TELEGRAM_WEBHOOK_SECRET', secret)
    send = Mock(return_value=True)
    issue = Mock(side_effect=AssertionError('Unexpected credential issuance'))
    monkeypatch.setattr(routes, 'send_telegram_to_chat', send)
    monkeypatch.setattr(routes, 'driver_login_url', issue)
    return {'X-Telegram-Bot-Api-Secret-Token': secret}, send, issue


def telegram_update(command='/login', chat_type='private', sender=991001):
    return {'update_id': 1, 'message': {'text': command,
            'chat': {'id': 991001, 'type': chat_type}, 'from': {'id': sender}}}


@pytest.mark.parametrize('mode', ['unconfigured', 'missing', 'mismatch'])
def test_telegram_rejected_before_send_or_credentials(secure_app, telegram, monkeypatch, mode):
    headers, send, issue = telegram
    if mode == 'unconfigured':
        secure_app.config.pop('TELEGRAM_WEBHOOK_SECRET')
        monkeypatch.delenv('TELEGRAM_WEBHOOK_SECRET')
    elif mode == 'missing':
        headers = {}
    else:
        headers = {'X-Telegram-Bot-Api-Secret-Token': 'synthetic-wrong-secret'}
    response = secure_app.test_client().post('/api/telegram/webhook', headers=headers, json=telegram_update())
    assert response.status_code == (503 if mode == 'unconfigured' else 403)
    send.assert_not_called()
    issue.assert_not_called()


def test_authenticated_telegram_ignored_command_needs_no_owner(secure_app, telegram):
    headers, send, issue = telegram
    response = secure_app.test_client().post('/api/telegram/webhook', headers=headers,
                                            json=telegram_update('/synthetic_unknown'))
    assert response.status_code == 200
    assert response.json['ok'] is True
    send.assert_not_called()
    issue.assert_not_called()


@pytest.mark.parametrize(('chat_type', 'sender', 'expected_messages'), [
    ('private', 991001, 1), ('group', 991001, 0),
    ('supergroup', 991001, 0), ('private', 991002, 0),
])
def test_telegram_login_without_verified_private_binding_never_issues_credentials(secure_app, telegram, chat_type, sender, expected_messages):
    from fleetai.db import Session
    from fleetai.auth_models import DriverTicket
    headers, send, issue = telegram
    response = secure_app.test_client().post('/api/telegram/webhook', headers=headers,
                                            json=telegram_update(chat_type=chat_type, sender=sender))
    assert response.status_code == 200
    assert response.json['ok'] is True
    assert send.call_count == expected_messages
    issue.assert_not_called()
    with Session() as session:
        assert session.query(DriverTicket).count() == 0


@pytest.mark.parametrize(('method', 'path'), [
    ('GET', '/api/driver-contract/synthetic-invalid-capability'),
    ('POST', '/api/driver-contract/synthetic-invalid-capability/save'),
    ('POST', '/api/driver-contract/synthetic-invalid-capability/send-code'),
    ('POST', '/api/driver-contract/synthetic-invalid-capability/sign'),
    ('GET', '/driver-contract/synthetic-invalid-capability/preview.pdf'),
    ('GET', '/driver-contract/synthetic-invalid-capability/pdf'),
])
def test_invalid_contract_capability_reaches_original_404_without_owner(secure_app, method, path):
    # Real contract DDL (including BYTEA) is accepted by isolated SQLite.
    # No contract lookup or authorization mocks are needed.
    response = secure_app.test_client().open(path, method=method, json={} if method == 'POST' else None)
    assert response.status_code == 404


SERVICE_CASES = [
    ('GET', '/api/cron/daily-rent-and-alerts'),
    ('POST', '/api/cron/daily-rent-and-alerts'),
    ('GET', '/api/cron/driver-balance-alerts'),
    ('POST', '/api/cron/driver-balance-alerts'),
    ('GET', '/api/cron/daily-driver-rent'),
    ('GET', '/api/check-driver-payments'),
]


@pytest.mark.parametrize(('method', 'path'), SERVICE_CASES)
@pytest.mark.parametrize('mode', ['unconfigured', 'missing', 'mismatch'])
def test_service_routes_fail_closed_without_exact_secret(secure_app, monkeypatch, method, path, mode):
    secure_app.config.pop('CRON_SECRET', None)
    monkeypatch.delenv('CRON_SECRET', raising=False)
    headers = {}
    if mode != 'unconfigured':
        monkeypatch.setenv('CRON_SECRET', 'synthetic-cron-secret')
    if mode == 'mismatch':
        headers['X-Admin-Secret'] = 'synthetic-wrong-secret'
    response = secure_app.test_client().open(path, method=method, headers=headers)
    assert response.status_code == 403
    assert_no_posting()


@pytest.mark.parametrize(('method', 'path'), SERVICE_CASES)
def test_verified_cron_runs_real_empty_fleet_handler_without_owner(secure_app, monkeypatch, method, path):
    from fleetai.db import Session
    from fleetai.models import Car
    secret = 'synthetic-cron-secret'
    monkeypatch.setenv('CRON_SECRET', secret)
    with Session() as session:
        assert session.query(Car).count() == 0
    # All original handlers support query authentication, including GET aliases.
    response = secure_app.test_client().open(path, method=method, query_string={'secret': secret})
    assert response.status_code == 200
    assert response.json['ok'] is True
    for field in ('processed', 'alerts_sent', 'checked', 'sent', 'cars_processed', 'rent_charges_created'):
        if field in response.json:
            assert response.json[field] == 0
    assert_no_posting()


@pytest.mark.parametrize('method', ['GET', 'POST'])
@pytest.mark.parametrize('path', ['/api/cron/daily-rent-and-alerts', '/api/cron/driver-balance-alerts'])
def test_original_cron_header_auth_methods_preserved(secure_app, monkeypatch, method, path):
    secret = 'synthetic-cron-secret'
    monkeypatch.setenv('CRON_SECRET', secret)
    response = secure_app.test_client().open(path, method=method, headers={'X-Admin-Secret': secret})
    assert response.status_code == 200
    assert response.json['ok'] is True
    assert_no_posting()
