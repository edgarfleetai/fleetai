"""Regression tests for the expense-query optimization.

Run with: python -m unittest discover -s tests -p 'test_finance_expense_query.py'
"""
import unittest
from datetime import datetime
from sqlalchemy import create_engine
from sqlalchemy.orm import Session
from fleetai.models import Base, Expense, Operation
from fleetai.finance import _split_expenses


class ExpenseQueryTests(unittest.TestCase):
    def setUp(self):
        self.engine = create_engine("sqlite:///:memory:")
        Base.metadata.create_all(self.engine)
        self.session = Session(self.engine)

    def tearDown(self):
        self.session.close()
        self.engine.dispose()

    def test_car_and_date_filter_with_legacy_split(self):
        self.session.add_all([
            Operation(id=1, type="investor_expense_split"),
            Expense(car_code=" 404 ", date=datetime(2026, 10, 16), amount=100,
                    share_type="shared", operation_id=1),
            Expense(car_code="404", date=datetime(2026, 10, 17), amount=50,
                    share_type="park_only"),
            Expense(car_code="404", date=datetime(2026, 10, 18), amount=75,
                    share_type="shared"),
            Expense(car_code="404", date=datetime(2026, 10, 15), amount=999,
                    share_type="shared"),
            Expense(car_code="218", date=datetime(2026, 10, 17), amount=888,
                    share_type="shared"),
        ])
        self.session.commit()
        self.assertEqual(
            _split_expenses(self.session, "404",
                            datetime(2026, 10, 16),
                            datetime(2026, 10, 19)),
            (75, 100, 50),
        )
        self.assertEqual(_split_expenses(self.session, "404"), (1074, 100, 50))


if __name__ == "__main__":
    unittest.main()
