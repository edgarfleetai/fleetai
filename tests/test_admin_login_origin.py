import os
import unittest
from unittest.mock import patch
from werkzeug.security import generate_password_hash

from fleetai import create_app


class AdminLoginOriginTests(unittest.TestCase):
    def setUp(self):
        with patch("fleetai.init_db"):
            self.app = create_app()
        self.client = self.app.test_client()

    def test_cross_site_login_rejected_even_with_correct_password(self):
        with patch.dict(os.environ, {
            "FLASK_SECRET_KEY": "test-secret",
            "FLEETAI_ADMIN_PASSWORD_HASH": generate_password_hash("correct-password"),
        }):
            response = self.client.post(
                "/admin/login",
                data={"password": "correct-password"},
                headers={"Origin": "https://evil.example"},
            )
        self.assertEqual(response.status_code, 403)
        with self.client.session_transaction() as session:
            self.assertFalse(session.get("fleetai_admin", False))

    def test_same_origin_login_remains_available(self):
        with patch.dict(os.environ, {
            "FLASK_SECRET_KEY": "test-secret",
            "FLEETAI_ADMIN_PASSWORD_HASH": generate_password_hash("correct-password"),
        }):
            response = self.client.post(
                "/admin/login",
                data={"password": "correct-password"},
                headers={"Origin": "http://localhost"},
            )
        self.assertEqual(response.status_code, 302)


if __name__ == "__main__":
    unittest.main()
