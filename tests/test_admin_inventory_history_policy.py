import unittest
from unittest.mock import patch
from fleetai import create_app


class SensitiveInventoryHistoryTests(unittest.TestCase):
    def setUp(self):
        with patch("fleetai.init_db"):
            app = create_app()
        self.client = app.test_client()

    def test_unauthenticated_inventory_is_private(self):
        self.assertEqual(self.client.get("/api/warehouse").status_code, 401)

    def test_unauthenticated_warehouse_match_is_private(self):
        self.assertEqual(
            self.client.post("/api/warehouse/check-match", json={"part_name": "oil"}).status_code,
            401,
        )

    def test_unauthenticated_repair_history_is_private(self):
        self.assertEqual(
            self.client.post("/api/ask-history", json={"message": "repair"}).status_code,
            401,
        )


if __name__ == "__main__":
    unittest.main()
