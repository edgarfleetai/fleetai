import unittest
from unittest.mock import patch
from fleetai.admin_policy import (
    ADMIN_READ_RULES, ADMIN_WRITE_RULES, requires_owner,
    DANGEROUS_WIALON_COMMAND,
)


class AdminPolicyCoverageTests(unittest.TestCase):
    def test_every_policy_rule_is_registered(self):
        from fleetai import create_app
        with patch("fleetai.init_db"):
            app = create_app()
        routes = {rule.rule for rule in app.url_map.iter_rules()}
        missing = (ADMIN_READ_RULES | ADMIN_WRITE_RULES) - routes
        self.assertEqual(missing, set(), f"Stale admin policy rules: {missing}")

    def test_write_routes_use_write_methods(self):
        from fleetai import create_app
        with patch("fleetai.init_db"):
            app = create_app()
        methods = {rule.rule: rule.methods for rule in app.url_map.iter_rules()}
        for rule in ADMIN_WRITE_RULES:
            with self.subTest(rule=rule):
                self.assertTrue(
                    methods[rule] & {"POST", "PUT", "PATCH", "DELETE"}
                )
                self.assertTrue(requires_owner(rule, "POST"))

    def test_block_command_is_admin_only(self):
        self.assertIn(DANGEROUS_WIALON_COMMAND, ADMIN_WRITE_RULES)


if __name__ == "__main__":
    unittest.main()
