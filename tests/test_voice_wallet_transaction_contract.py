"""Guardrail tests for the future wallet top-up executor.

The existing routes._sync_daily_rent() commits internally. Do not call it from
an atomic voice transaction until the shared implementation is refactored.
"""
import inspect
import unittest
from fleetai import routes
from fleetai.voice_wallet_guard import validate_wallet_confirmation


class VoiceWalletTransactionContractTests(unittest.TestCase):
    def test_legacy_rent_sync_commits_internally(self):
        source = inspect.getsource(routes._sync_daily_rent)
        self.assertIn('session.commit()', source)

    def test_driver_change_blocks_confirmation_before_rent_sync(self):
        preview = {'ok': True, 'car_code': '636', 'driver_name': 'Мердан',
                   'writes_performed': False, 'requires_confirmation': True}
        result = validate_wallet_confirmation(preview, current_driver='Новый водитель',
                                               current_car_code='636', approved=True)
        self.assertFalse(result['ok'])
