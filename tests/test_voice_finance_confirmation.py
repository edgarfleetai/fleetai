import unittest
from fleetai.voice_finance_confirmation import sign_finance_preview, verify_finance_preview


class FinanceConfirmationTests(unittest.TestCase):
    secret = 'voice-finance-test-signing-secret-1234567890'
    draft = {'kind': 'income', 'car_code': '897', 'amount_rub': 15000, 'description': 'Аренда'}

    def test_roundtrip(self):
        token = sign_finance_preview(self.secret, self.draft, now=1000)
        self.assertEqual(verify_finance_preview(self.secret, token, now=1001), self.draft)

    def test_expired(self):
        token = sign_finance_preview(self.secret, self.draft, now=1000)
        self.assertIsNone(verify_finance_preview(self.secret, token, now=1300))

    def test_tampered(self):
        token = sign_finance_preview(self.secret, self.draft, now=1000)
        self.assertIsNone(verify_finance_preview(self.secret, token + 'x', now=1001))

    def test_wrong_secret(self):
        token = sign_finance_preview(self.secret, self.draft, now=1000)
        self.assertIsNone(verify_finance_preview('other-secret-long-enough-1234567890', token, now=1001))
