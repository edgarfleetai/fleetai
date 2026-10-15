import unittest
from unittest.mock import patch
from fleetai.admin_policy import requires_owner


class AdminReadPolicyTests(unittest.TestCase):
    def test_sensitive_reads_require_owner(self):
        for rule in (
            "/api/driver-debts",
            "/api/operations",
            "/api/cars-monthly-finance",
            "/api/investors",
            "/api/driver-assignment/<code>",
            "/api/wialon/665/state",
            "/api/wialon/settings/<car_code>",
        ):
            with self.subTest(rule=rule):
                self.assertTrue(requires_owner(rule, "GET"))

    def test_driver_and_cron_exemptions(self):
        self.assertFalse(requires_owner("/driver", "GET"))
        self.assertFalse(requires_owner("/api/cron/daily-driver-rent", "GET"))
        self.assertFalse(requires_owner("/api/driver-contract/<token>", "GET"))

    def test_financial_read_denied_to_guest(self):
        from fleetai import create_app
        with patch("fleetai.init_db"):
            app = create_app()
        response = app.test_client().get("/api/operations")
        self.assertEqual(response.status_code, 401)


if __name__ == "__main__":
    unittest.main()
