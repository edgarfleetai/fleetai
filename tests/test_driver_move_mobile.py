import unittest
from fleetai.driver_move_mobile import mobile_move_summary


class DriverMoveMobileTests(unittest.TestCase):
    def test_summary_is_never_confirmation(self):
        result = mobile_move_summary({'ok': True,
            'changes': [{'car': '636', 'before': 'Мердан', 'after': 'Мекан'}],
            'closeout_plan': {'steps': [{'car_code': '636', 'wallet_balance_rub': -3000,
                'existing_debt_rub': 1000, 'deposit_to_reconcile_rub': 5000,
                'rent_per_day_rub': 1857}]}})
        self.assertIn('Мердан', result['message'])
        self.assertIn('-3000', result['message'])
        self.assertFalse(result['confirmation_enabled'])
        self.assertFalse(result['writes_performed'])

    def test_rejected_preview_has_no_confirmation(self):
        self.assertFalse(mobile_move_summary({'ok': False})['ready'])
