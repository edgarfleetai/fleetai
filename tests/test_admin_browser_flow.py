import os
import unittest
from unittest.mock import patch
from fleetai import create_app


class AdminBrowserFlowTests(unittest.TestCase):
    def setUp(self):
        with patch("fleetai.init_db"):
            self.app = create_app()
        self.client = self.app.test_client()
        with self.client.session_transaction() as sess:
            sess["fleetai_admin"] = True

    def test_same_origin_topup_reaches_route_validation(self):
        # Invalid payload must reach the actual route, not be rejected by CSRF gate.
        response = self.client.post(
            "/api/driver-wallet/topup",
            json={},
            headers={"Referer": "http://localhost/driver-topup"},
        )
        self.assertNotIn(response.status_code, (401, 403))

    def test_cross_origin_fine_rejected_before_db(self):
        response = self.client.post(
            "/api/driver-wallet/fine",
            json={},
            headers={"Origin": "https://other.example"},
        )
        self.assertEqual(response.status_code, 403)

    def test_private_wialon_page_requires_login(self):
        self.client.post("/admin/logout")
        response = self.client.get("/wialon-settings")
        self.assertEqual(response.status_code, 302)
        self.assertIn("/admin/login", response.headers["Location"])

    def test_admin_logout_clears_session(self):
        response = self.client.post("/admin/logout")
        self.assertEqual(response.status_code, 302)
        response = self.client.get("/api/operations")
        self.assertEqual(response.status_code, 401)


if __name__ == "__main__":
    unittest.main()
