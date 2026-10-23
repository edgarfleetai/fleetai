import unittest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session
from fleetai.db import Base
from fleetai.models import Car, DriverWalletTransaction
from fleetai.voice_wallet_preview import preview_wallet_topup


class VoiceWalletPreviewTests(unittest.TestCase):
    def setUp(self):
        self.engine = create_engine('sqlite:///:memory:')
        Base.metadata.create_all(self.engine)
        self.db = Session(self.engine)
        self.db.add(Car(code='636', driver='Мердан'))
        self.db.add(DriverWalletTransaction(car_code='636', driver_name='Мердан', amount=-2000))
        self.db.commit()

    def tearDown(self):
        self.db.close()
        self.engine.dispose()

    def test_wallet_preview(self):
        result = preview_wallet_topup(self.db, car_code='636', amount_rub=5000)
        self.assertTrue(result['ok'])
        self.assertEqual(result['driver_name'], 'Мердан')
        self.assertEqual(result['current_wallet_balance'], -2000)
        self.assertEqual(result['projected_balance_before_rent_sync'], 3000)
        self.assertTrue(result['requires_rent_sync'])
        self.assertEqual(self.db.query(DriverWalletTransaction).count(), 1)

    def test_no_driver(self):
        self.db.add(Car(code='218', driver=''))
        self.db.commit()
        self.assertFalse(preview_wallet_topup(self.db, car_code='218', amount_rub=5000)['ok'])
