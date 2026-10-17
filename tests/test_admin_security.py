import os
import unittest
from unittest.mock import patch
from fleetai.admin_security import verify_admin_key


class AdminKeyTests(unittest.TestCase):
    def test_missing_configuration_fails_closed(self):
        with patch.dict(os.environ, {}, clear=True):
            self.assertFalse(verify_admin_key('anything'))

    def test_missing_or_wrong_key(self):
        with patch.dict(os.environ, {'FLEETAI_ADMIN_API_KEY': 'secret-example'}):
            self.assertFalse(verify_admin_key(None))
            self.assertFalse(verify_admin_key('incorrect'))
            self.assertTrue(verify_admin_key('secret-example'))


if __name__ == '__main__':
    unittest.main()
