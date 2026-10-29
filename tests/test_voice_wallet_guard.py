import unittest
from fleetai.voice_wallet_guard import validate_wallet_confirmation


class VoiceWalletGuardTests(unittest.TestCase):
    def setUp(self):
        self.preview = {'ok': True, 'car_code': '636', 'driver_name': 'Мердан',
                        'writes_performed': False, 'requires_confirmation': True}

    def test_same_driver_approved(self):
        result = validate_wallet_confirmation(self.preview, current_driver='Мердан',
                                               current_car_code='636', approved=True)
        self.assertTrue(result['ok'])
        self.assertTrue(result['requires_rent_sync'])

    def test_reassignment_rejected(self):
        self.assertFalse(validate_wallet_confirmation(self.preview, current_driver='Сулейман',
                                                      current_car_code='636', approved=True)['ok'])

    def test_approval_required(self):
        self.assertFalse(validate_wallet_confirmation(self.preview, current_driver='Мердан',
                                                      current_car_code='636', approved=False)['ok'])
