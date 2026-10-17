import unittest
from fleetai.views import HTML


class AdminDashboardCsrfWiringTests(unittest.TestCase):
    def test_dashboard_wraps_fetch_for_mutating_requests(self):
        self.assertIn("window.fetch = async", HTML)
        self.assertIn("X-FleetAI-CSRF-Token", HTML)
        self.assertIn("/api/admin/csrf-token", HTML)
        self.assertIn("url.origin !== location.origin", HTML)
        self.assertIn("nativeFetch(input, {...init, headers})", HTML)


if __name__ == "__main__":
    unittest.main()
