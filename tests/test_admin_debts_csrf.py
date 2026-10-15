import unittest
from fleetai.routes import driver_debts_admin


class DriverDebtsCsrfWiringTests(unittest.TestCase):
    def test_debt_mutations_attach_csrf_token(self):
        html = driver_debts_admin()
        self.assertIn("X-FleetAI-CSRF-Token", html)
        self.assertIn("/api/admin/csrf-token", html)
        self.assertIn("await debtFetch('/api/driver-debt-from-car'", html)
        self.assertIn("await debtFetch('/api/driver-debt-payment'", html)


if __name__ == "__main__":
    unittest.main()
