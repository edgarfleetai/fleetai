import unittest
from unittest.mock import patch

from fleetai import create_app


class AdminFetchMetadataTests(unittest.TestCase):
    def setUp(self):
        with patch("fleetai.init_db"):
            app = create_app()
        app.config["SESSION_COOKIE_SECURE"] = False
        self.client = app.test_client()
        with self.client.session_transaction() as session:
            session["fleetai_admin"] = True

    def test_cross_site_fetch_metadata_denied_even_with_forged_origin(self):
        response = self.client.post(
            "/api/driver-wallet/topup", json={},
            headers={"Origin": "http://localhost", "Sec-Fetch-Site": "cross-site"},
        )
        self.assertEqual(response.status_code, 403)

    def test_same_origin_metadata_not_rejected_by_metadata_gate(self):
        response = self.client.post(
            "/api/driver-wallet/topup", json={},
            headers={"Origin": "http://localhost", "Sec-Fetch-Site": "same-origin"},
        )
        self.assertNotEqual(response.status_code, 403)


if __name__ == "__main__":
    unittest.main()
