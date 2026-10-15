"""PostgreSQL-only CI smoke tests; never run against production credentials."""
import os
import unittest

from sqlalchemy import text
from sqlalchemy.engine import make_url

from fleetai.db import engine


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


if __name__ == "__main__":
    unittest.main()
