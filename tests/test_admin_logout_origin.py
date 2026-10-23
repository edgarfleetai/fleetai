import unittest
from unittest.mock import patch
from fleetai import create_app


class AdminLogoutOriginTests(unittest.TestCase):
    def setUp(self):
        with patch("fleetai.init_db"):
            self.client = create_app().test_client()
        with self.client.session_transaction() as session:
            session["fleetai_admin"] = True

    def test_foreign_origin_cannot_log_out_admin(self):
        response = self.client.post("/admin/logout", headers={"Origin": "https://evil.example"})
        self.assertEqual(response.status_code, 403)
        with self.client.session_transaction() as session:
            self.assertTrue(session.get("fleetai_admin"))

    def test_same_origin_can_log_out_admin(self):
        response = self.client.post("/admin/logout", headers={"Origin": "http://localhost"})
        self.assertEqual(response.status_code, 302)
        with self.client.session_transaction() as session:
            self.assertFalse(session.get("fleetai_admin", False))


if __name__ == "__main__":
    unittest.main()
