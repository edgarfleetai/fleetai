"""Audit trail for future confirmed driver move transactions."""
from datetime import datetime
from sqlalchemy import Column, DateTime, Integer, String, Text
from .db import Base


class DriverMoveAudit(Base):
    __tablename__ = 'driver_move_audit'
    id = Column(Integer, primary_key=True)
    request_key = Column(String(80), nullable=False, index=True)
    car_code = Column(String(16), nullable=False)
    previous_driver = Column(String(255), nullable=False, default='')
    new_driver = Column(String(255), nullable=False, default='')
    financial_snapshot_json = Column(Text, nullable=False, default='{}')
    created_at = Column(DateTime, default=datetime.now, nullable=False)
