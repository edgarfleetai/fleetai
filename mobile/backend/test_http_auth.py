import os
import tempfile
import unittest
from pathlib import Path
import sqlite3
from datetime import datetime, timezone
from app import create_app
from identity import initialize, create_account_after_verified_otp, issue_session

class AuthHttpTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory()
        self.path=str(Path(self.tmp.name)/"accounts.sqlite")
        self.db=sqlite3.connect(self.path,isolation_level=None)
        initialize(self.db)
        create_account_after_verified_otp(self.db,"driver-1","+79990001122")
        self.token=issue_session(self.db,"driver-1")
        self.client=create_app({"TESTING":True,"DRIVER_APP_DB_PATH":self.path}).test_client()
    def tearDown(self):
        self.db.close()
        self.tmp.cleanup()
    def test_profile_requires_bearer(self):
        self.assertEqual(self.client.get("/v1/me").status_code,401)
        self.assertEqual(self.client.get("/v1/me",headers={"Authorization":"Bearer bad"}).status_code,401)
    def test_profile_exposes_minimum(self):
        r=self.client.get("/v1/me",headers={"Authorization":"Bearer "+self.token})
        self.assertEqual(r.status_code,200)
        self.assertEqual(r.json,{"account_id":"driver-1","verification_status":"pending_review"})
        self.assertNotIn("phone_e164",r.json)
    def test_logout_revokes_token(self):
        h={"Authorization":"Bearer "+self.token}
        self.assertEqual(self.client.post("/v1/auth/logout",headers=h).status_code,204)
        self.assertEqual(self.client.get("/v1/me",headers=h).status_code,401)
        self.assertEqual(self.client.post("/v1/auth/logout",headers=h).status_code,401)
    def test_unconfigured_identity_fails_closed(self):
        client=create_app({"TESTING":True}).test_client()
        self.assertEqual(client.get("/v1/me",headers={"Authorization":"Bearer "+self.token}).status_code,503)
        self.assertEqual(client.post("/v1/auth/logout",headers={"Authorization":"Bearer "+self.token}).status_code,503)

if __name__=="__main__":
    unittest.main()
