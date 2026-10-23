import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session
from fleetai.db import Base
from fleetai.models import Car
from fleetai.driver_move_guard import assignment_fingerprint
from fleetai.driver_move_transaction import execute_driver_move
from fleetai.driver_move_idempotency import DriverMoveRequest
from fleetai.driver_move_audit import DriverMoveAudit


def test_rejects_rent_before_changing_drivers():
    engine = create_engine('sqlite:///:memory:')
    Base.metadata.create_all(engine)
    with Session(engine) as db:
        first = Car(code='636', driver='Мердан', daily_rent=1857)
        second = Car(code='404', driver='Мекан', daily_rent=1857)
        db.add_all([first, second])
        db.flush()
        fingerprint = assignment_fingerprint([first, second])
        with pytest.raises(ValueError, match='Финансовые данные'):
            execute_driver_move(db, source='636', target='404', swap=True,
                fingerprint=fingerprint, approved=True, request_key='voice_request_12345678')
        assert first.driver == 'Мердан'
        assert second.driver == 'Мекан'
        db.rollback()
    engine.dispose()


def test_rejects_missing_approval():
    engine = create_engine('sqlite:///:memory:')
    Base.metadata.create_all(engine)
    with Session(engine) as db:
        with pytest.raises(ValueError, match='подтверждение'):
            execute_driver_move(db, source='636', target='404', swap=True,
                fingerprint='a' * 64, approved=False, request_key='voice_request_12345678')
    engine.dispose()
