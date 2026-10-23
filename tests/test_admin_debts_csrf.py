import unittest
from fleetai.routes import driver_debts_admin
from flask import Flask


class DriverDebtsCsrfWiringTests(unittest.TestCase):
    def test_debt_mutations_attach_csrf_token(self):
        with Flask(__name__).app_context():
            html = driver_debts_admin()
        self.assertIn("X-FleetAI-CSRF-Token", html)
        self.assertIn("/api/admin/csrf-token", html)
        self.assertIn("await debtFetch('/api/driver-debt-from-car'", html)
        self.assertIn("await debtFetch('/api/driver-debt-payment'", html)


if __name__ == "__main__":
    unittest.main()
