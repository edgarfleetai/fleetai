import unittest
from fleetai.login_limiter import login_blocked, record_login_failure, clear_login_failures


class LoginLimiterTests(unittest.TestCase):
    def tearDown(self):
        clear_login_failures("test-ip")

    def test_blocks_after_five_failures(self):
        clear_login_failures("test-ip")
        for i in range(5):
            self.assertFalse(login_blocked("test-ip", now=100+i))
            record_login_failure("test-ip", now=100+i)
        self.assertTrue(login_blocked("test-ip", now=110))

    def test_expiration(self):
        clear_login_failures("test-ip")
        for i in range(5):
            record_login_failure("test-ip", now=100+i)
        self.assertFalse(login_blocked("test-ip", now=100+901))

    def test_clear(self):
        clear_login_failures("test-ip")
        for i in range(5):
            record_login_failure("test-ip", now=100+i)
        clear_login_failures("test-ip")
        self.assertFalse(login_blocked("test-ip", now=110))


if __name__ == "__main__":
    unittest.main()
