import unittest
from fleetai.routes import _owner_csrf_html, driver_topup_page
from flask import Flask


class OwnerCsrfPageTests(unittest.TestCase):
    def test_script_inserted_in_head(self):
        html = _owner_csrf_html("<html><head></head><body></body></html>")
        self.assertIn("X-FleetAI-CSRF-Token", html)
        self.assertIn("/api/admin/csrf-token", html)
        self.assertLess(html.index("X-FleetAI-CSRF-Token"), html.index("</head>"))

    def test_wallet_topup_page_has_csrf_shim(self):
        with Flask(__name__).app_context():
            html = driver_topup_page()
        self.assertIn("X-FleetAI-CSRF-Token", html)
        self.assertIn("/api/admin/csrf-token", html)

    def test_only_same_origin_mutations_are_wrapped(self):
        html = _owner_csrf_html("<head></head>")
        self.assertIn("url.origin !== location.origin", html)
        self.assertIn("'POST', 'PUT', 'PATCH', 'DELETE'", html)


if __name__ == "__main__":
    unittest.main()
