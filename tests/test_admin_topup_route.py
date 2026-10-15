import os
import unittest
from unittest.mock import patch


class WalletTopupGateTests(unittest.TestCase):
    def setUp(self):
        from fleetai import create_app
        with patch('fleetai.init_db'):
            self.app = create_app()
        self.client = self.app.test_client()

    def test_missing_key_denied_without_database_write(self):
        with patch.dict(os.environ, {'FLEETAI_ADMIN_API_KEY': 'test-secret'}):
            response = self.client.post('/api/driver-wallet/topup', json={'car_code': '665', 'amount': 1000})
        self.assertEqual(response.status_code, 403)

    def test_wrong_key_denied(self):
        with patch.dict(os.environ, {'FLEETAI_ADMIN_API_KEY': 'test-secret'}):
            response = self.client.post('/api/driver-wallet/topup', headers={'X-FleetAI-Admin-Key': 'wrong'}, json={'car_code': '665', 'amount': 1000})
        self.assertEqual(response.status_code, 403)

    def test_no_configuration_denied(self):
        with patch.dict(os.environ, {}, clear=True):
            response = self.client.post('/api/driver-wallet/topup', headers={'X-FleetAI-Admin-Key': 'anything'}, json={'car_code': '665', 'amount': 1000})
        self.assertEqual(response.status_code, 403)


if __name__ == '__main__':
    unittest.main()
