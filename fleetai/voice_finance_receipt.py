"""Unique confirmation receipts for financial voice writes."""
from datetime import datetime
from sqlalchemy import Column, DateTime, Integer, String, Text
from .db import Base


class VoiceFinanceReceipt(Base):
    __tablename__ = 'voice_finance_receipts'
    id = Column(Integer, primary_key=True)
    request_key = Column(String(128), unique=True, nullable=False)
    car_code = Column(String(32), nullable=False)
    kind = Column(String(32), nullable=False)
    amount_rub = Column(Integer, nullable=False)
    operation_id = Column(Integer)
    status = Column(String(24), nullable=False, default='completed')
    created_at = Column(DateTime, nullable=False, default=datetime.now)
    raw_draft_json = Column(Text)
