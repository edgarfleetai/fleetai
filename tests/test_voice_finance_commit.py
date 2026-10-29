import unittest
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session
from fleetai.db import Base
from fleetai.models import Car, Operation, Income, Expense
from fleetai.voice_finance_receipt import VoiceFinanceReceipt
from fleetai.voice_finance_commit import commit_finance_draft


class VoiceFinanceCommitTests(unittest.TestCase):
    def setUp(self):
        self.engine = create_engine('sqlite:///:memory:')
        Base.metadata.create_all(self.engine)
        self.db = Session(self.engine)
        self.db.add(Car(code='218'))
        self.db.commit()

    def tearDown(self):
        self.db.close()
        self.engine.dispose()

    def test_confirmed_repair_and_duplicate_rejected(self):
        draft = {'kind': 'repair_expense', 'car_code': '218',
                 'amount_rub': 3500, 'description': 'Замена масла'}
        result = commit_finance_draft(self.db, draft, approved=True,
                                      request_key='test-repair-unique-0001')
        self.db.commit()
        self.assertEqual(self.db.scalar(select(Expense.amount)), 3500)
        self.assertEqual(result['amount_rub'], 3500)
        with self.assertRaisesRegex(ValueError, 'уже была'):
            commit_finance_draft(self.db, draft, approved=True,
                                 request_key='test-repair-unique-0001')
        self.assertEqual(len(self.db.scalars(select(Operation)).all()), 1)

    def test_no_approval_no_write(self):
        draft = {'kind': 'income', 'car_code': '218',
                 'amount_rub': 15000, 'description': 'Аренда'}
        with self.assertRaisesRegex(ValueError, 'подтверждение'):
            commit_finance_draft(self.db, draft, approved=False,
                                 request_key='test-income-unique-0001')
        self.assertIsNone(self.db.scalar(select(Income.id)))

    def test_confirmed_income(self):
        draft = {'kind': 'income', 'car_code': '218',
                 'amount_rub': 15000, 'description': 'Аренда'}
        commit_finance_draft(self.db, draft, approved=True,
                             request_key='test-income-unique-0002')
        self.db.commit()
        self.assertEqual(self.db.scalar(select(Income.amount)), 15000)
        self.assertEqual(self.db.scalar(select(VoiceFinanceReceipt.amount_rub)), 15000)
