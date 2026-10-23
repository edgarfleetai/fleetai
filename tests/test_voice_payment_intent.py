import unittest
from fleetai.voice_payment_intent import classify_voice_payment
from fleetai.voice_finance_draft import parse_finance_voice


class VoicePaymentIntentTests(unittest.TestCase):
    def test_wallet_requires_separate_flow(self):
        self.assertEqual(classify_voice_payment('Пополнение кошелька 897')['kind'], 'driver_wallet_topup')
        self.assertFalse(parse_finance_voice('Получил пополнение кошелька 897 15000 рублей')['ok'])

    def test_debt_requires_separate_flow(self):
        self.assertEqual(classify_voice_payment('Погасил долг 897')['kind'], 'driver_debt_payment')
        self.assertFalse(parse_finance_voice('Получил погашение долга 897 15000 рублей')['ok'])

    def test_rent_income_requires_wallet_review(self):
        self.assertEqual(classify_voice_payment('Получил 15000 рублей за аренду 897')['kind'], 'driver_wallet_topup')
        self.assertFalse(parse_finance_voice('Получил 15000 рублей за аренду 897')['ok'])

    def test_regular_income(self):
        self.assertEqual(classify_voice_payment('Получил 15000 рублей за продажу деталей 897')['kind'], 'generic_income')
