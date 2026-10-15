"""HTTPS origin validation behind a deliberately configured reverse proxy."""
import os
import unittest
from unittest.mock import patch
from fleetai import create_app


class AdminProxyOriginTests(unittest.TestCase):
    def make_client(self, trust_proxy):
        with patch.dict(os.environ, {"FLEETAI_TRUST_PROXY": "1" if trust_proxy else "0"}):
            with patch("fleetai.init_db"):
                app = create_app()
        app.config["SESSION_COOKIE_SECURE"] = False  # test client uses HTTP transport
        client = app.test_client()
        with client.session_transaction() as session:
            session["fleetai_admin"] = True
        return client

    def test_https_forwarded_origin_allowed_only_with_trusted_proxy(self):
        client = self.make_client(True)
        response = client.post(
            "/api/driver-wallet/topup",
            json={},
            headers={"Origin": "https://fleetai-1.onrender.com",
                     "X-Forwarded-Proto": "https"},
            environ_overrides={"HTTP_HOST": "fleetai-1.onrender.com"},
        )
        self.assertNotIn(response.status_code, (401, 403))

    def test_untrusted_forwarded_proto_cannot_override_scheme(self):
        client = self.make_client(False)
        response = client.post(
            "/api/driver-wallet/topup",
            json={},
            headers={"Origin": "https://fleetai-1.onrender.com",
                     "X-Forwarded-Proto": "https"},
            environ_overrides={"HTTP_HOST": "fleetai-1.onrender.com"},
        )
        self.assertEqual(response.status_code, 403)

    def test_cross_origin_rejected_with_proxy(self):
        client = self.make_client(True)
        response = client.post(
            "/api/driver-wallet/fine",
            json={},
            headers={"Origin": "https://evil.example",
                     "X-Forwarded-Proto": "https"},
            environ_overrides={"HTTP_HOST": "fleetai-1.onrender.com"},
        )
        self.assertEqual(response.status_code, 403)


if __name__ == "__main__":
    unittest.main()
