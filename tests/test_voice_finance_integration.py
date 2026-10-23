import os
import unittest
from unittest.mock import patch
from sqlalchemy import create_engine, select
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool
from fleetai import create_app
from fleetai.db import Base
from fleetai.models import Car, Income, Expense


class VoiceFinanceIntegrationTests(unittest.TestCase):
    def setUp(self):
        self.engine = create_engine('sqlite://', connect_args={'check_same_thread': False}, poolclass=StaticPool)
        Base.metadata.create_all(self.engine)
        self.session_factory = sessionmaker(bind=self.engine)
        with self.session_factory.begin() as db:
            db.add(Car(code='218'))
        self.secret_patch = patch.dict(os.environ, {'FLEETAI_VOICE_CONFIRM_SECRET': 'integration-voice-finance-secret-123456789'})
        self.secret_patch.start()
        self.app = create_app()
        self.app.testing = True
        self.client = self.app.test_client()
        with self.client.session_transaction() as sess:
            sess['fleetai_admin'] = True
            sess['fleetai_csrf_token'] = 'test-token'
        self.db_patch = patch('fleetai.voice_finance_api.Session', self.session_factory)
        self.db_patch.start()
        self.headers = {'Origin': 'http://localhost', 'X-FleetAI-CSRF-Token': 'test-token'}

    def tearDown(self):
        self.db_patch.stop()
        self.secret_patch.stop()
        self.engine.dispose()

    def test_preview_then_confirm_once(self):
        with patch.dict(os.environ, {'FLEETAI_REQUIRE_CSRF_TOKEN': '1'}):
            preview = self.client.post('/api/assistant/finance/preview',
                json={'text': 'Ремонт 218 3500 рублей'}, headers=self.headers)
            self.assertEqual(preview.status_code, 200, preview.get_json())
            token = preview.get_json()['confirmation_token']
            body = {'approved': True, 'confirmation_token': token,
                    'request_key': 'integration-repair-0001'}
            response = self.client.post('/api/assistant/finance/confirm', json=body, headers=self.headers)
            self.assertEqual(response.status_code, 200, response.get_json())
            again = self.client.post('/api/assistant/finance/confirm', json=body, headers=self.headers)
            self.assertEqual(again.status_code, 422)
            with self.session_factory() as db:
                self.assertEqual(len(db.scalars(select(Expense)).all()), 1)

    def test_no_approval_does_not_write(self):
        preview = self.client.post('/api/assistant/finance/preview',
            json={'text': 'Получил 15000 рублей за 218'}, headers=self.headers)
        self.assertEqual(preview.status_code, 200, preview.get_json())
        response = self.client.post('/api/assistant/finance/confirm',
            json={'approved': False, 'confirmation_token': preview.get_json()['confirmation_token'],
                  'request_key': 'integration-income-0001'}, headers=self.headers)
        self.assertEqual(response.status_code, 400)
        with self.session_factory() as db:
            self.assertEqual(len(db.scalars(select(Income)).all()), 0)
