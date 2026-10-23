import os
import unittest
from unittest.mock import patch
from werkzeug.security import generate_password_hash
from flask import Flask

from fleetai.admin_auth import verify_admin_password, is_admin, admin_credentials_configured


class AdminAuthenticationTests(unittest.TestCase):
    def test_password_not_configured(self):
        with patch.dict(os.environ, {}, clear=True):
            self.assertFalse(verify_admin_password("anything"))
            self.assertFalse(admin_credentials_configured())

    def test_password_hash(self):
        hashed = generate_password_hash("example-password")
        with patch.dict(os.environ, {"FLEETAI_ADMIN_PASSWORD_HASH": hashed, "FLASK_SECRET_KEY": "test-only"}):
            self.assertTrue(verify_admin_password("example-password"))
            self.assertFalse(verify_admin_password("wrong"))
            self.assertTrue(admin_credentials_configured())

    def test_session_is_not_admin_by_default(self):
        app = Flask(__name__)
        app.secret_key = "test-only"
        with app.test_request_context("/"):
            self.assertFalse(is_admin())


if __name__ == "__main__":
    unittest.main()
