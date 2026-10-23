import unittest
from fleetai import create_app


class VoiceFinanceApiTests(unittest.TestCase):
    def test_unauthorized_finance_preview(self):
        app = create_app()
        app.testing = True
        response = app.test_client().post('/api/assistant/finance/preview',
            json={'text': 'Ремонт 218 3500 рублей'})
        self.assertEqual(response.status_code, 401)

    def test_unauthorized_finance_confirm(self):
        app = create_app()
        app.testing = True
        response = app.test_client().post('/api/assistant/finance/confirm',
            json={'text': 'Получил 15000 рублей за 897',
                  'approved': True, 'request_key': 'test-finance-0000001'})
        self.assertEqual(response.status_code, 401)
