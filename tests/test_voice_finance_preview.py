import unittest
from types import SimpleNamespace
from fleetai.voice_finance_preview import preview_finance_voice


class VoiceFinancePreviewTests(unittest.TestCase):
    def test_known_car_preview(self):
        result = preview_finance_voice('Получил 15000 рублей за 897',
            lambda code: SimpleNamespace(code=code) if code == '897' else None)
        self.assertTrue(result['ok'])
        self.assertTrue(result['requires_confirmation'])
        self.assertFalse(result['writes_performed'])

    def test_unknown_car_rejected(self):
        result = preview_finance_voice('Ремонт 218 3500 рублей', lambda code: None)
        self.assertFalse(result['ok'])
