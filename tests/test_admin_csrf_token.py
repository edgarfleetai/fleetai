import os
import unittest
from unittest.mock import patch
from fleetai import create_app


class AdminCsrfTokenTests(unittest.TestCase):
    def setUp(self):
        with patch("fleetai.init_db"):
            app = create_app()
        app.config["SESSION_COOKIE_SECURE"] = False
        self.client = app.test_client()

    def test_anonymous_cannot_read_token(self):
        self.assertEqual(self.client.get("/api/admin/csrf-token").status_code, 401)

    def test_token_required_for_admin_write_when_enabled(self):
        with self.client.session_transaction() as session:
            session["fleetai_admin"] = True
        token_response = self.client.get("/api/admin/csrf-token")
        self.assertEqual(token_response.status_code, 200)
        token = token_response.json["csrf_token"]
        self.assertEqual(token_response.headers.get("Cache-Control"), "no-store")
        with patch.dict(os.environ, {"FLEETAI_REQUIRE_CSRF_TOKEN": "1"}):
            denied = self.client.post(
                "/api/driver-wallet/topup", json={},
                headers={"Origin": "http://localhost"},
            )
            self.assertEqual(denied.status_code, 403)
            self.assertIn("CSRF", denied.json["message"])
            allowed = self.client.post(
                "/api/driver-wallet/topup", json={},
                headers={"Origin": "http://localhost", "X-FleetAI-CSRF-Token": token},
            )
            self.assertNotIn(allowed.status_code, (401, 403))

    def test_token_cannot_be_reused_after_logout(self):
        with self.client.session_transaction() as session:
            session["fleetai_admin"] = True
        token = self.client.get("/api/admin/csrf-token").json["csrf_token"]
        self.client.post("/admin/logout")
        with self.client.session_transaction() as session:
            session["fleetai_admin"] = True
        with patch.dict(os.environ, {"FLEETAI_REQUIRE_CSRF_TOKEN": "1"}):
            response = self.client.post(
                "/api/driver-wallet/topup", json={},
                headers={"Origin": "http://localhost", "X-FleetAI-CSRF-Token": token},
            )
        self.assertEqual(response.status_code, 403)


if __name__ == "__main__":
    unittest.main()
