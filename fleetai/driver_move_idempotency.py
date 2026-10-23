"""Durable request identities for future confirmed driver moves."""
from datetime import datetime
from sqlalchemy import Column, DateTime, Integer, String, Text, UniqueConstraint
from .db import Base


class DriverMoveRequest(Base):
    __tablename__ = 'driver_move_requests'
    id = Column(Integer, primary_key=True)
    request_key = Column(String(80), nullable=False, unique=True)
    source_car = Column(String(16), nullable=False)
    target_car = Column(String(16), nullable=False)
    expected_fingerprint = Column(String(64), nullable=False)
    action = Column(String(16), nullable=False)
    status = Column(String(16), nullable=False, default='pending')
    result_json = Column(Text, nullable=False, default='')
    created_at = Column(DateTime, default=datetime.now, nullable=False)
    completed_at = Column(DateTime)


def validate_request_key(key):
    import re
    return isinstance(key, str) and bool(re.fullmatch(r'[A-Za-z0-9_-]{16,80}', key))
