import unittest
from unittest.mock import patch
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session
from fleetai.db import Base
from fleetai.models import Car, Income, Operation, DriverWalletTransaction
from fleetai.voice_wallet_preview import preview_wallet_topup
from fleetai.voice_wallet_commit import commit_wallet_topup


class VoiceWalletCommitTests(unittest.TestCase):
    def setUp(self):
        self.engine = create_engine('sqlite:///:memory:')
        Base.metadata.create_all(self.engine)
        with Session(self.engine) as db:
            db.add(Car(code='636', driver='Мердан'))
            db.commit()

    def tearDown(self):
        self.engine.dispose()

    def test_topup_writes_wallet_and_ledger(self):
        with Session(self.engine) as db:
            preview = preview_wallet_topup(db, car_code='636', amount_rub=5000)
            with patch('fleetai.voice_wallet_commit._sync_daily_rent_uncommitted', return_value={'charged': 0}):
                result = commit_wallet_topup(db, preview, approved=True, request_key='wallet-topup-00001')
            db.commit()
            self.assertEqual(result['balance'], 5000)
            self.assertEqual(db.scalar(select(Income.amount)), 5000)
            self.assertEqual(db.scalar(select(Operation.type)), 'income')
            self.assertEqual(db.scalar(select(DriverWalletTransaction.amount)), 5000)
            with self.assertRaises(ValueError):
                commit_wallet_topup(db, preview, approved=True, request_key='wallet-topup-00001')

    def test_rollback_after_rent_accrual_failure(self):
        with Session(self.engine) as db:
            preview = preview_wallet_topup(db, car_code='636', amount_rub=5000)
            db.rollback()
            def rent_then_fail(session, car):
                session.add(DriverWalletTransaction(car_code='636', driver_name='Мердан', amount=-1857))
                raise RuntimeError('simulate failure after rent accrual')
            with self.assertRaises(RuntimeError):
                with db.begin():
                    with patch('fleetai.voice_wallet_commit._sync_daily_rent_uncommitted', side_effect=rent_then_fail):
                        commit_wallet_topup(db, preview, approved=True, request_key='wallet-topup-00002')
            self.assertEqual(db.query(DriverWalletTransaction).count(), 0)
            self.assertEqual(db.query(Income).count(), 0)
