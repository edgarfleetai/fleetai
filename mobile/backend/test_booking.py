import sqlite3
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from booking import initialize, reserve, cancel, BookingError

NOW = datetime(2026, 10, 21, 12, 0, tzinfo=timezone.utc)

class BookingTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.path = Path(self.tmp.name) / "booking.sqlite"
        self.db = sqlite3.connect(self.path, isolation_level=None)
        initialize(self.db)
        self.db.execute("INSERT INTO drivers(id,verification_status) VALUES('verified','approved'),('pending','pending_review'),('other','approved')")
        self.db.execute("INSERT INTO vehicles(id,daily_rent,deposit,enabled) VALUES('car1',1857,5000,1),('car2',2000,0,0)")
    def tearDown(self):
        self.db.close()
        self.tmp.cleanup()
    def test_pending_driver_cannot_book(self):
        with self.assertRaises(BookingError):
            reserve(self.db,'pending','car1',NOW)
    def test_disabled_vehicle_cannot_book(self):
        with self.assertRaises(BookingError):
            reserve(self.db,'verified','car2',NOW)
    def test_prevent_double_booking(self):
        reserve(self.db,'verified','car1',NOW)
        other=sqlite3.connect(self.path,isolation_level=None)
        try:
            with self.assertRaises(BookingError):
                reserve(other,'other','car1',NOW)
        finally: other.close()
    def test_expired_booking_releases_vehicle(self):
        reserve(self.db,'verified','car1',NOW)
        result=reserve(self.db,'other','car1',NOW+timedelta(minutes=21))
        self.assertTrue(result['id'])
    def test_cancel_requires_owner(self):
        result=reserve(self.db,'verified','car1',NOW)
        self.assertFalse(cancel(self.db,result['id'],'other'))
        self.assertTrue(cancel(self.db,result['id'],'verified'))
        self.assertTrue(reserve(self.db,'other','car1',NOW)['id'])
    def test_rollback_after_failed_reservation(self):
        with self.assertRaises(BookingError):
            reserve(self.db,'pending','car1',NOW)
        self.assertTrue(reserve(self.db,'verified','car1',NOW)['id'])

if __name__ == '__main__':
    unittest.main()
