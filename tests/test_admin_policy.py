import unittest
from unittest.mock import patch
from fleetai.admin_policy import requires_owner


class AdminPolicyTests(unittest.TestCase):
    def test_sensitive_writes_require_owner(self):
        for rule in (
            "/api/driver-wallet/fine",
            "/api/driver-debt-payment",
            "/api/driver-contract/create",
            "/api/delete-operation/<int:operation_id>",
            "/api/driver-mvp/<code>/test-topup",
            "/api/wialon/665/command",
        ):
            with self.subTest(rule=rule):
                self.assertTrue(requires_owner(rule, "POST"))

    def test_public_driver_and_cron_not_covered(self):
        self.assertFalse(requires_owner("/api/driver-contract/<token>/sign", "POST"))
        self.assertFalse(requires_owner("/api/cron/daily-driver-rent", "GET"))
        self.assertFalse(requires_owner("/api/driver-mvp/<code>/bank-payment", "POST"))

    def test_dynamic_route_guard(self):
        from fleetai import create_app
        with patch("fleetai.init_db"):
            app = create_app()
        client = app.test_client()
        result = client.post("/api/delete-operation/12345", json={})
        self.assertEqual(result.status_code, 401)

    def test_remote_block_always_disabled(self):
        from fleetai import create_app
        with patch("fleetai.init_db"):
            app = create_app()
        client = app.test_client()
        with client.session_transaction() as sess:
            sess["fleetai_admin"] = True
        result = client.post(
            "/api/wialon/665/command",
            json={"action": "block", "safety_confirmation": "PARKED_ENGINE_OFF_665"},
            headers={"Origin": "https://localhost"},
        )
        self.assertEqual(result.status_code, 403)


if __name__ == "__main__":
    unittest.main()
