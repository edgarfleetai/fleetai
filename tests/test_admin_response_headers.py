import unittest
from unittest.mock import patch

from fleetai import create_app


class AdminResponseHeaderTests(unittest.TestCase):
    def setUp(self):
        with patch("fleetai.init_db"):
            self.client = create_app().test_client()

    def assert_private_headers(self, response):
        self.assertEqual(response.headers.get("Cache-Control"), "no-store")
        self.assertEqual(response.headers.get("X-Frame-Options"), "DENY")
        self.assertEqual(response.headers.get("X-Content-Type-Options"), "nosniff")
        self.assertEqual(response.headers.get("Referrer-Policy"), "same-origin")

    def test_login_page_is_not_cached_or_embedded(self):
        self.assert_private_headers(self.client.get("/admin/login"))

    def test_private_api_denial_is_not_cached(self):
        response = self.client.get("/api/operations")
        self.assertEqual(response.status_code, 401)
        self.assert_private_headers(response)

    def test_private_page_redirect_is_not_cached(self):
        response = self.client.get("/wialon-settings")
        self.assertEqual(response.status_code, 302)
        self.assert_private_headers(response)


if __name__ == "__main__":
    unittest.main()
