import unittest
from fleetai.driver_move_voice import parse_driver_move_voice


class DriverMoveVoiceTests(unittest.TestCase):
    def test_swap(self):
        result = parse_driver_move_voice('Поменяй водителей 404 и 636 местами')
        self.assertEqual(result['kind'], 'driver_swap')
        self.assertTrue(result['requires_confirmation'])

    def test_move(self):
        result = parse_driver_move_voice('Переведи водителя с 636 на 404')
        self.assertEqual(result['source'], '636')
        self.assertFalse(result['swap'])

    def test_single_car_rejected(self):
        self.assertIsNone(parse_driver_move_voice('Поменяй водителя на 404'))

    def test_ambiguous_intent_rejected(self):
        self.assertIsNone(parse_driver_move_voice('Переведи и поменяй 636 404'))
