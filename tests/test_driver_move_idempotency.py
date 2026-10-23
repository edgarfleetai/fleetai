import pytest
from sqlalchemy import create_engine
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session
from fleetai.driver_move_idempotency import DriverMoveRequest, validate_request_key


def test_request_key_validation():
    assert validate_request_key('voice_20261023_abcd1234')
    assert not validate_request_key('short')
    assert not validate_request_key('unsafe key!')


def test_duplicate_request_key_rejected():
    engine = create_engine('sqlite:///:memory:')
    DriverMoveRequest.__table__.create(engine)
    with Session(engine) as db:
        for source in ('636', '404'):
            db.add(DriverMoveRequest(request_key='request_unique_123456', source_car=source,
                target_car='218', expected_fingerprint='a' * 64, action='swap', status='pending'))
        with pytest.raises(IntegrityError):
            db.commit()
        db.rollback()
    engine.dispose()
