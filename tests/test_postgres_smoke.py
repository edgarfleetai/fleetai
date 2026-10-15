"""PostgreSQL-only CI smoke tests; never run against production credentials."""
import os
import unittest

from sqlalchemy import text
from sqlalchemy.engine import make_url

from fleetai.db import engine, Base
from fleetai import models  # noqa: F401 - registers all mapped tables
from sqlalchemy.orm import Session


class PostgresSmokeTests(unittest.TestCase):
    def test_database_connection_and_rollback(self):
        url = make_url(os.environ["DATABASE_URL"])
        if not url.drivername.startswith("postgresql"):
            self.skipTest("PostgreSQL connection required")
        self.assertEqual(url.database, "fleetai_test")
        with engine.connect() as conn:
            transaction = conn.begin()
            self.assertEqual(conn.execute(text("SELECT 1")).scalar_one(), 1)
            try:
                conn.execute(text("CREATE TEMP TABLE fleetai_smoke (value INTEGER) ON COMMIT DROP"))
                conn.execute(text("INSERT INTO fleetai_smoke (value) VALUES (42)"))
                self.assertEqual(conn.execute(text("SELECT value FROM fleetai_smoke")).scalar_one(), 42)
            finally:
                transaction.rollback()
        with engine.connect() as conn:
            exists = conn.execute(text(
                "SELECT to_regclass('pg_temp.fleetai_smoke')"
            )).scalar_one()
            self.assertIsNone(exists)

    def test_model_schema_can_be_created_in_isolated_postgres(self):
        url = make_url(os.environ["DATABASE_URL"])
        if url.database != "fleetai_test":
            self.skipTest("Requires isolated CI database")
        Base.metadata.create_all(engine)
        try:
            from sqlalchemy import inspect
            inspector = inspect(engine)
            self.assertIn("cars", inspector.get_table_names())
            self.assertIn("operations", inspector.get_table_names())
        finally:
            Base.metadata.drop_all(engine)

    def test_financial_records_commit_and_rollback(self):
        url = make_url(os.environ["DATABASE_URL"])
        if url.database != "fleetai_test":
            self.skipTest("Requires isolated CI database")
        Base.metadata.create_all(engine)
        try:
            with Session(engine) as session:
                session.add(models.DriverWalletTransaction(car_code="TEST", amount=1500, transaction_type="topup"))
                session.add(models.DriverDebt(driver_name="Test Driver", car_code="TEST", balance=2500))
                session.add(models.WarehouseItem(part_name="Test oil", quantity=10))
                session.add(models.InvestorPayout(investor_name="Test Investor", car_code="TEST", amount=500))
                session.commit()
            with Session(engine) as session:
                self.assertEqual(session.query(models.DriverWalletTransaction).filter_by(car_code="TEST").count(), 1)
                self.assertEqual(session.query(models.DriverDebt).filter_by(car_code="TEST").count(), 1)
                self.assertEqual(session.query(models.WarehouseItem).filter_by(part_name="Test oil").count(), 1)
                self.assertEqual(session.query(models.InvestorPayout).filter_by(car_code="TEST").count(), 1)
                session.add(models.DriverWalletTransaction(car_code="ROLLBACK", amount=999))
                session.flush()
                session.rollback()
            with Session(engine) as session:
                self.assertEqual(session.query(models.DriverWalletTransaction).filter_by(car_code="ROLLBACK").count(), 0)
        finally:
            Base.metadata.drop_all(engine)


if __name__ == "__main__":
    unittest.main()
