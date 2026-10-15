import unittest
from unittest.mock import patch

class WalletAccessTests(unittest.TestCase):
    def setUp(self):
        from fleetai import create_app
        with patch("fleetai.init_db"):
            self.app = create_app()
        self.client = self.app.test_client()

    def test_page_redirects_without_login(self):
        result = self.client.get("/driver-topup")
        self.assertEqual(result.status_code, 302)
        self.assertIn("/admin/login", result.headers["Location"])

    def test_cars_list_denied_without_login(self):
        result = self.client.get("/api/driver-wallet/cars")
        self.assertEqual(result.status_code, 401)

    def test_cross_site_post_denied_after_login(self):
        with self.client.session_transaction() as sess:
            sess["fleetai_admin"] = True
        response = self.client.post(
            "/api/driver-wallet/topup",
            json={"car_code": "665", "amount": 1000},
            headers={"Origin": "https://untrusted.example"},
        )
        self.assertEqual(response.status_code, 403)

    def test_missing_origin_denied_after_login(self):
        with self.client.session_transaction() as sess:
            sess["fleetai_admin"] = True
        response = self.client.post("/api/driver-wallet/topup", json={"car_code": "665", "amount": 1000})
        self.assertEqual(response.status_code, 403)

if __name__ == "__main__":
    unittest.main()
