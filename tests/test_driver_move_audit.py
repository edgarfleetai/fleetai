from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session
from fleetai.driver_move_audit import DriverMoveAudit


def test_driver_move_audit_retains_history():
    engine = create_engine('sqlite:///:memory:')
    DriverMoveAudit.__table__.create(engine)
    with Session(engine) as db:
        db.add(DriverMoveAudit(request_key='voice_test_12345678', car_code='636',
            previous_driver='Мердан', new_driver='Мекан', financial_snapshot_json='{}'))
        db.commit()
        row = db.execute(select(DriverMoveAudit)).scalar_one()
        assert row.previous_driver == 'Мердан'
        assert row.new_driver == 'Мекан'
    engine.dispose()
