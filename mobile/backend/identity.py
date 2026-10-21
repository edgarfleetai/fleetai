"""Isolated account/session storage. No SMS provider or FleetAI production access."""
import hashlib
import hmac
import secrets
import sqlite3
from datetime import datetime, timedelta, timezone

SCHEMA = """
CREATE TABLE IF NOT EXISTS accounts (
 id TEXT PRIMARY KEY,
 phone_e164 TEXT NOT NULL UNIQUE,
 verification_status TEXT NOT NULL DEFAULT 'pending_review'
 CHECK(verification_status IN ('pending_review','approved','rejected')),
 created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS sessions (
 token_hash TEXT PRIMARY KEY,
 account_id TEXT NOT NULL REFERENCES accounts(id),
 expires_at TEXT NOT NULL,
 revoked_at TEXT,
 created_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS sessions_by_account ON sessions(account_id);
CREATE TABLE IF NOT EXISTS fleetai_links (
 account_id TEXT PRIMARY KEY REFERENCES accounts(id),
 fleetai_driver_id TEXT NOT NULL UNIQUE,
 linked_by_admin TEXT NOT NULL,
 linked_at TEXT NOT NULL
);
"""
def utcnow():
    return datetime.now(timezone.utc)

def initialize(conn):
    conn.execute("PRAGMA foreign_keys=ON")
    conn.executescript(SCHEMA)

def _hash_token(token):
    return hashlib.sha256(token.encode("ascii")).hexdigest()

def create_account_after_verified_otp(conn, account_id, phone_e164, now=None):
    """Call ONLY after a trusted SMS provider confirms the OTP server-side."""
    import re
    if not re.fullmatch(r"\+[1-9][0-9]{7,14}", phone_e164):
        raise ValueError("Phone must be E.164")
    now = now or utcnow()
    conn.execute("INSERT INTO accounts(id,phone_e164,created_at) VALUES(?,?,?)",
                 (account_id,phone_e164,now.isoformat()))

def issue_session(conn, account_id, now=None, lifetime=timedelta(days=7)):
    """Internal server-only function; never exposed before verified OTP."""
    now=now or utcnow()
    if not conn.execute("SELECT 1 FROM accounts WHERE id=?", (account_id,)).fetchone():
        raise ValueError("Unknown account")
    token=secrets.token_urlsafe(32)
    conn.execute("INSERT INTO sessions(token_hash,account_id,expires_at,created_at) VALUES(?,?,?,?)",
                 (_hash_token(token),account_id,(now+lifetime).isoformat(),now.isoformat()))
    return token

def account_for_session(conn, token, now=None):
    if not isinstance(token,str) or len(token)>256 or len(token)<32:
        return None
    now=now or utcnow()
    row=conn.execute(
        "SELECT a.id,a.verification_status FROM sessions s "
        "JOIN accounts a ON a.id=s.account_id "
        "WHERE s.token_hash=? AND s.revoked_at IS NULL AND s.expires_at>?",
        (_hash_token(token),now.isoformat())).fetchone()
    return {"id":row[0],"verification_status":row[1]} if row else None

def revoke_session(conn, token, now=None):
    now=now or utcnow()
    return conn.execute(
        "UPDATE sessions SET revoked_at=? WHERE token_hash=? AND revoked_at IS NULL",
        (now.isoformat(),_hash_token(token))).rowcount == 1

def link_existing_driver(conn, account_id, fleetai_driver_id, admin_id, now=None):
    """Administrative mapping, NOT an automatic match on name/car/phone."""
    if not admin_id or not fleetai_driver_id:
        raise ValueError("Admin and FleetAI driver IDs required")
    now=now or utcnow()
    conn.execute(
        "INSERT INTO fleetai_links(account_id,fleetai_driver_id,linked_by_admin,linked_at) "
        "VALUES(?,?,?,?)",(account_id,fleetai_driver_id,admin_id,now.isoformat()))
