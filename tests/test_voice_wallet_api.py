import os
import unittest
from unittest.mock import patch
from sqlalchemy import create_engine, select
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool
from fleetai import create_app
from fleetai.db import Base
from fleetai.models import Car, Income, DriverWalletTransaction


class VoiceWalletApiTests(unittest.TestCase):
    def setUp(self):
        self.engine = create_engine('sqlite://', connect_args={'check_same_thread': False}, poolclass=StaticPool)
        Base.metadata.create_all(self.engine)
        self.factory = sessionmaker(bind=self.engine)
        with self.factory.begin() as db:
            db.add(Car(code='636', driver='Мердан'))
        self.secret_patch = patch.dict(os.environ, {'FLEETAI_VOICE_CONFIRM_SECRET': 'test-wallet-secret-12345678901234567890'})
        self.secret_patch.start()
        self.app = create_app()
        self.app.testing = True
        self.client = self.app.test_client()
        with self.client.session_transaction() as sess:
            sess['fleetai_admin'] = True
        self.session_patch = patch('fleetai.voice_wallet_api.Session', self.factory)
        self.session_patch.start()
        self.headers = {'Origin': 'http://localhost'}

    def tearDown(self):
        self.session_patch.stop()
        self.secret_patch.stop()
        self.engine.dispose()

    def test_preview_confirm_and_replay(self):
        preview = self.client.post('/api/assistant/wallet/preview', json={
            'car_code': '636', 'amount_rub': 5000, 'payment_method': 'cash'}, headers=self.headers)
        self.assertEqual(preview.status_code, 200, preview.get_json())
        body = {'approved': True, 'confirmation_token': preview.get_json()['confirmation_token'],
                'request_key': 'wallet-api-00000001'}
        response = self.client.post('/api/assistant/wallet/confirm', json=body, headers=self.headers)
        self.assertEqual(response.status_code, 200, response.get_json())
        replay = self.client.post('/api/assistant/wallet/confirm', json=body, headers=self.headers)
        self.assertEqual(replay.status_code, 422)
        with self.factory() as db:
            self.assertEqual(len(db.scalars(select(Income)).all()), 1)
            self.assertEqual(sum(x.amount for x in db.scalars(select(DriverWalletTransaction)).all()), 5000)

    def test_changed_driver_blocks_payment(self):
        preview = self.client.post('/api/assistant/wallet/preview', json={
            'car_code': '636', 'amount_rub': 5000}, headers=self.headers)
        self.assertEqual(preview.status_code, 200, preview.get_json())
        with self.factory.begin() as db:
            db.execute(__import__('sqlalchemy').update(Car).where(Car.code == '636').values(driver='Другой'))
        response = self.client.post('/api/assistant/wallet/confirm', json={
            'approved': True, 'confirmation_token': preview.get_json()['confirmation_token'],
            'request_key': 'wallet-api-00000002'}, headers=self.headers)
        self.assertEqual(response.status_code, 422)

    def test_unauthorized(self):
        with self.app.test_client() as client:
            response = client.post('/api/assistant/wallet/preview', json={'car_code': '636', 'amount_rub': 5000})
            self.assertIn(response.status_code, (302, 401, 403))
