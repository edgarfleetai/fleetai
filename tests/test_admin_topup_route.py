import os
import unittest
from unittest.mock import patch
from werkzeug.security import generate_password_hash


class WalletTopupGateTests(unittest.TestCase):
    def setUp(self):
        from fleetai import create_app
        with patch('fleetai.init_db'):
            self.app = create_app()
        self.client = self.app.test_client()

    def test_missing_session_denied(self):
        response = self.client.post('/api/driver-wallet/topup', json={'car_code': '665', 'amount': 1000})
        self.assertEqual(response.status_code, 401)

    def test_password_login_and_session(self):
        with patch.dict(os.environ, {'FLASK_SECRET_KEY': 'test-secret', 'FLEETAI_ADMIN_PASSWORD_HASH': generate_password_hash('password') }):
            wrong = self.client.post('/admin/login', data={'password': 'wrong'})
            self.assertEqual(wrong.status_code, 401)
            ok = self.client.post('/admin/login', data={'password': 'password'})
            self.assertEqual(ok.status_code, 302)
            with self.client.session_transaction() as sess:
                self.assertTrue(sess.get('fleetai_admin'))
            self.client.post('/admin/logout')
            response = self.client.post('/api/driver-wallet/topup', json={'car_code': '665', 'amount': 1000})
            self.assertEqual(response.status_code, 401)

    def test_login_without_configuration_fails(self):
        with patch.dict(os.environ, {}, clear=True):
            response = self.client.post('/admin/login', data={'password': 'anything'})
        self.assertEqual(response.status_code, 503)


if __name__ == '__main__':
    unittest.main()
