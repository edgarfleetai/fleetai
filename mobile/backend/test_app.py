import unittest
from app import create_app

class ApiSafetyTests(unittest.TestCase):
    def setUp(self):
        self.client = create_app().test_client()
    def test_health(self):
        self.assertEqual(self.client.get("/health").status_code, 200)
    def test_no_fake_vehicles(self):
        self.assertEqual(self.client.get("/v1/public/vehicles").json, [])
    def test_sensitive_features_fail_closed(self):
        for path in ["/v1/auth/otp/request", "/v1/auth/otp/verify", "/v1/bookings", "/v1/verification"]:
            with self.subTest(path=path):
                self.assertEqual(self.client.post(path, json={}).status_code, 503)

if __name__ == "__main__":
    unittest.main()
