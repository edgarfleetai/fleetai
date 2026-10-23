import unittest
from fleetai.driver_move_closeout import build_closeout_plan


class CloseoutPlanTests(unittest.TestCase):
    def test_separate_balances_for_each_car(self):
        review = {'cars': [
            {'car_code': '636', 'driver': 'Мердан', 'wallet_balance_rub': -3000,
             'open_driver_debt_rub': 1000, 'deposit_rub': 5000, 'daily_rent_rub': 1857},
            {'car_code': '404', 'driver': 'Мекан', 'wallet_balance_rub': 500,
             'open_driver_debt_rub': 0, 'deposit_rub': 0, 'daily_rent_rub': 1857}]}
        changes = [{'car': '636', 'before': 'Мердан', 'after': 'Мекан'},
                   {'car': '404', 'before': 'Мекан', 'after': 'Мердан'}]
        plan = build_closeout_plan(review, changes)
        self.assertEqual(plan['steps'][0]['wallet_balance_rub'], -3000)
        self.assertEqual(plan['steps'][1]['wallet_balance_rub'], 500)
        self.assertFalse(plan['can_execute'])

    def test_stale_assignment_rejected(self):
        with self.assertRaisesRegex(ValueError, 'Назначение изменилось'):
            build_closeout_plan({'cars': [{'car_code': '636', 'driver': 'Другой'}]},
                                [{'car': '636', 'before': 'Мердан', 'after': ''}])
