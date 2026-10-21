import sqlite3
import unittest
from datetime import datetime,timedelta,timezone
from identity import (initialize,create_account_after_verified_otp,issue_session,
                      account_for_session,revoke_session,link_existing_driver)
NOW=datetime(2026,10,21,12,tzinfo=timezone.utc)

class IdentityTests(unittest.TestCase):
    def setUp(self):
        self.db=sqlite3.connect(":memory:",isolation_level=None)
        initialize(self.db)
        create_account_after_verified_otp(self.db,"u1","+79990001122",NOW)
    def tearDown(self):
        self.db.close()
    def test_phone_validation(self):
        with self.assertRaises(ValueError):
            create_account_after_verified_otp(self.db,"bad","89990001122",NOW)
    def test_unique_phone(self):
        with self.assertRaises(sqlite3.IntegrityError):
            create_account_after_verified_otp(self.db,"u2","+79990001122",NOW)
    def test_session_lifecycle(self):
        token=issue_session(self.db,"u1",NOW)
        self.assertEqual(account_for_session(self.db,token,NOW)["id"],"u1")
        self.assertIsNone(account_for_session(self.db,token,NOW+timedelta(days=8)))
        self.assertTrue(revoke_session(self.db,token,NOW))
        self.assertIsNone(account_for_session(self.db,token,NOW))
    def test_unknown_session_and_user(self):
        self.assertIsNone(account_for_session(self.db,"x"))
        with self.assertRaises(ValueError):
            issue_session(self.db,"missing",NOW)
    def test_explicit_driver_link(self):
        link_existing_driver(self.db,"u1","fleet-driver-123","admin-1",NOW)
        row=self.db.execute("SELECT fleetai_driver_id FROM fleetai_links WHERE account_id='u1'").fetchone()
        self.assertEqual(row[0],"fleet-driver-123")
        with self.assertRaises(sqlite3.IntegrityError):
            link_existing_driver(self.db,"u1","another-driver","admin-1",NOW)
    def test_unapproved_by_default(self):
        token=issue_session(self.db,"u1",NOW)
        self.assertEqual(account_for_session(self.db,token,NOW)["verification_status"],"pending_review")

if __name__=="__main__":
    unittest.main()
