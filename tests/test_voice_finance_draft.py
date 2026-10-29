import unittest
from fleetai.voice_finance_draft import parse_finance_voice


class VoiceFinanceDraftTests(unittest.TestCase):
    def test_repair(self):
        draft = parse_finance_voice('Запиши ремонт 218, замена масла, 3500 рублей')
        self.assertTrue(draft['ok'])
        self.assertEqual(draft['draft']['kind'], 'repair_expense')
        self.assertEqual(draft['draft']['amount_rub'], 3500)

    def test_income(self):
        draft = parse_finance_voice('Получил 15 тысяч за продажу деталей 897')
        self.assertTrue(draft['ok'])
        self.assertEqual(draft['draft']['amount_rub'], 15000)
        self.assertEqual(draft['draft']['kind'], 'income')

    def test_ambiguous(self):
        self.assertFalse(parse_finance_voice('Получил и потратил 500 рублей на 218')['ok'])

    def test_multiple_cars(self):
        self.assertFalse(parse_finance_voice('Получил 500 рублей с 218 и 404')['ok'])
