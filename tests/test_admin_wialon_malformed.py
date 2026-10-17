import unittest
from unittest.mock import patch
from fleetai import create_app


class WialonMalformedCommandTests(unittest.TestCase):
    def setUp(self):
        with patch("fleetai.init_db"):
            self.client = create_app().test_client()

    def test_block_denied_before_auth_even_for_untrusted_request(self):
        response = self.client.post("/api/wialon/665/command", json={"action": " BLOCK "})
        self.assertEqual(response.status_code, 403)

    def test_non_string_action_does_not_crash(self):
        response = self.client.post("/api/wialon/665/command", json={"action": ["block"]})
        self.assertEqual(response.status_code, 401)

    def test_json_array_does_not_crash(self):
        response = self.client.post("/api/wialon/665/command", json=["block"])
        self.assertEqual(response.status_code, 401)


if __name__ == "__main__":
    unittest.main()
