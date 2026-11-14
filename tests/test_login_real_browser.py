"""Owner login as a real browser sends it (regression: production login answered 403).

With Referrer-Policy: no-referrer a browser submits the login form with
`Origin: null`, which the origin check rejected even with a valid proof.
"""
import re

PASSWORD = 'Synthetic owner password 123!'


def bootstrap(app):
    result = app.test_cli_runner().invoke(args=['auth', 'bootstrap-owner', '--username', 'owner'],
                                          input=PASSWORD + '\n' + PASSWORD + '\n')
    assert result.exit_code == 0


def form(client):
    page = client.get('/auth/login', base_url='https://localhost')
    proof = re.search(r'name="login_proof" value="([^"]+)"', page.get_data(as_text=True)).group(1)
    return page, proof


def post(client, proof, origin, site):
    environ = {'HTTP_SEC_FETCH_SITE': site}
    if origin is not None:
        environ['HTTP_ORIGIN'] = origin
    return client.post('/auth/login', base_url='https://localhost', environ_overrides=environ,
                       data={'username': 'owner', 'password': PASSWORD, 'login_proof': proof})


def test_login_page_lets_browser_send_its_origin(secure_app):
    page, _ = form(secure_app.test_client())
    assert page.headers['Referrer-Policy'] == 'same-origin'


def test_browser_login_with_null_origin_same_origin_fetch_metadata(secure_app):
    bootstrap(secure_app)
    client = secure_app.test_client()
    _, proof = form(client)
    assert post(client, proof, 'null', 'same-origin').status_code == 303


def test_null_origin_without_same_origin_attestation_is_rejected(secure_app):
    bootstrap(secure_app)
    client = secure_app.test_client()
    _, proof = form(client)
    assert post(client, proof, 'null', 'cross-site').status_code == 403
    _, proof = form(client)
    assert post(client, proof, 'null', 'same-site').status_code == 403


def test_owner_ui_post_with_null_origin_and_csrf_token_works(secure_app):
    bootstrap(secure_app)
    client = secure_app.test_client()
    _, proof = form(client)
    assert post(client, proof, 'https://localhost', 'same-origin').status_code == 303
    token = client.get('/auth/session', base_url='https://localhost').get_json()['csrf_token']
    response = client.post('/auth/logout', base_url='https://localhost',
                           headers={'X-CSRF-Token': token},
                           environ_overrides={'HTTP_ORIGIN': 'null', 'HTTP_SEC_FETCH_SITE': 'same-origin'})
    assert response.status_code in (200, 204, 303)
