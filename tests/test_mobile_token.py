import unittest
from fleetai.mobile_token import issue_mobile_token, verify_mobile_token


class MobileTokenTests(unittest.TestCase):
    secret = 'development-test-secret-not-for-production-12345'

    def test_valid_scoped_token(self):
        token = issue_mobile_token(self.secret, 'driver-move:preview', now=1000)
        self.assertTrue(verify_mobile_token(self.secret, token, 'driver-move:preview', now=1001))
        self.assertFalse(verify_mobile_token(self.secret, token, 'driver:lookup', now=1001))

    def test_expired_token(self):
        token = issue_mobile_token(self.secret, 'driver:lookup', ttl_seconds=5, now=1000)
        self.assertFalse(verify_mobile_token(self.secret, token, 'driver:lookup', now=1005))

    def test_tampering_rejected(self):
        token = issue_mobile_token(self.secret, 'driver:lookup', now=1000)
        self.assertFalse(verify_mobile_token(self.secret, token + 'x', 'driver:lookup', now=1001))

    def test_short_secret_rejected(self):
        with self.assertRaises(ValueError):
            issue_mobile_token('weak', 'driver:lookup')
