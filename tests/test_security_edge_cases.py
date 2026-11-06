"""Regression cases identified during integration review, isolated only."""
import pytest


def test_explicit_public_origin_survives_https_termination_at_proxy(secure_app):
    secure_app.config['PUBLIC_BASE_URL'] = 'https://staging.fleetai.test'
    secure_app.config['SERVER_NAME'] = None
    runner = secure_app.test_cli_runner()
    result = runner.invoke(args=['auth','bootstrap-owner','--username','owner'], input='Synthetic owner password 123!\nSynthetic owner password 123!\n')
    assert result.exit_code == 0
    response = secure_app.test_client().post('/auth/login', base_url='http://internal-render:10000',
        data={'username':'owner','password':'Synthetic owner password 123!'},
        headers={'Host':'staging.fleetai.test','Origin':'https://staging.fleetai.test','X-Forwarded-Proto':'https'})
    assert response.status_code == 303
    wrong = secure_app.test_client().post('/auth/login', base_url='http://internal-render:10000',
        data={'username':'owner','password':'Synthetic owner password 123!'},
        headers={'Host':'staging.fleetai.test','Origin':'https://outside.invalid','X-Forwarded-Proto':'https'})
    assert wrong.status_code == 403


@pytest.mark.parametrize('path,header,config_key', [
    ('/api/telegram/webhook','X-Telegram-Bot-Api-Secret-Token','TELEGRAM_WEBHOOK_SECRET'),
    ('/api/cron/daily-rent-and-alerts','X-Admin-Secret','CRON_SECRET'),
])
def test_non_ascii_service_header_is_denied_not_a_server_error(secure_app, path, header, config_key):
    secure_app.config[config_key] = 'synthetic-ascii-secret'
    response = secure_app.test_client().post(path, base_url='https://localhost', headers={header:'é'}, json={})
    assert response.status_code == 403


def test_database_enforces_single_owner_even_if_bootstrap_races(secure_app):
    from fleetai import db
    from fleetai.auth_models import Owner
    from sqlalchemy.exc import IntegrityError
    runner = secure_app.test_cli_runner()
    result = runner.invoke(args=['auth','bootstrap-owner','--username','owner'], input='Synthetic owner password 123!\nSynthetic owner password 123!\n')
    assert result.exit_code == 0
    with db.Session() as session:
        session.add(Owner(username='second-owner', password_hash='synthetic-hash-not-a-password'))
        with pytest.raises(IntegrityError):
            session.commit()
        session.rollback()
        assert session.query(Owner).count() == 1

