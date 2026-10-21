"""Isolated transactional booking domain. No production FleetAI integration."""
import sqlite3
from datetime import datetime, timedelta, timezone
from uuid import uuid4

SCHEMA = """
CREATE TABLE IF NOT EXISTS drivers (
 id TEXT PRIMARY KEY,
 verification_status TEXT NOT NULL DEFAULT 'pending_review'
 CHECK (verification_status IN ('pending_review','approved','rejected'))
);
CREATE TABLE IF NOT EXISTS vehicles (
 id TEXT PRIMARY KEY,
 daily_rent INTEGER NOT NULL CHECK (daily_rent > 0),
 deposit INTEGER NOT NULL CHECK (deposit >= 0),
 enabled INTEGER NOT NULL DEFAULT 0 CHECK (enabled IN (0,1))
);
CREATE TABLE IF NOT EXISTS bookings (
 id TEXT PRIMARY KEY,
 driver_id TEXT NOT NULL REFERENCES drivers(id),
 vehicle_id TEXT NOT NULL REFERENCES vehicles(id),
 status TEXT NOT NULL CHECK (status IN ('reserved','cancelled','expired','completed')),
 created_at TEXT NOT NULL,
 expires_at TEXT NOT NULL
);
CREATE UNIQUE INDEX IF NOT EXISTS one_active_booking_per_car
ON bookings(vehicle_id) WHERE status='reserved';
"""

class BookingError(Exception):
    pass

def initialize(conn):
    conn.execute("PRAGMA foreign_keys=ON")
    conn.executescript(SCHEMA)

def reserve(conn, driver_id, vehicle_id, now=None):
    """Atomically reserve one enabled vehicle for one verified driver."""
    now = now or datetime.now(timezone.utc)
    if now.tzinfo is None:
        raise ValueError("now must be timezone aware")
    now_s = now.isoformat()
    expiry = (now + timedelta(minutes=20)).isoformat()
    conn.execute("BEGIN IMMEDIATE")
    try:
        conn.execute(
            "UPDATE bookings SET status='expired' WHERE status='reserved' AND expires_at <= ?",
            (now_s,),
        )
        driver = conn.execute(
            "SELECT verification_status FROM drivers WHERE id=?", (driver_id,)
        ).fetchone()
        if not driver or driver[0] != "approved":
            raise BookingError("Driver verification is not approved")
        vehicle = conn.execute(
            "SELECT enabled FROM vehicles WHERE id=?", (vehicle_id,)
        ).fetchone()
        if not vehicle or vehicle[0] != 1:
            raise BookingError("Vehicle is unavailable")
        existing = conn.execute(
            "SELECT 1 FROM bookings WHERE vehicle_id=? AND status='reserved'",
            (vehicle_id,),
        ).fetchone()
        if existing:
            raise BookingError("Vehicle is already reserved")
        booking_id = str(uuid4())
        conn.execute(
            "INSERT INTO bookings(id,driver_id,vehicle_id,status,created_at,expires_at) "
            "VALUES(?,?,?,'reserved',?,?)",
            (booking_id, driver_id, vehicle_id, now_s, expiry),
        )
        conn.commit()
        return {"id": booking_id, "vehicle_id": vehicle_id, "expires_at": expiry}
    except Exception:
        conn.rollback()
        raise

def cancel(conn, booking_id, driver_id):
    conn.execute("BEGIN IMMEDIATE")
    try:
        updated = conn.execute(
            "UPDATE bookings SET status='cancelled' "
            "WHERE id=? AND driver_id=? AND status='reserved'",
            (booking_id, driver_id),
        ).rowcount
        conn.commit()
        return updated == 1
    except Exception:
        conn.rollback()
        raise
