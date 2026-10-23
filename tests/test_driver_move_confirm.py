from types import SimpleNamespace
from fleetai.driver_move_guard import assignment_fingerprint
from fleetai.driver_move_confirm import validate_driver_move_confirmation


def cars():
    return [SimpleNamespace(code='636', driver='Мердан', daily_rent=1857, driver_deposit=0),
            SimpleNamespace(code='404', driver='Мекан', daily_rent=1857, driver_deposit=0)]


def test_explicit_approval_required():
    current = cars()
    result = validate_driver_move_confirmation(current, '636', '404', True, assignment_fingerprint(current), False)
    assert not result['ok']


def test_stale_preview_rejected():
    current = cars()
    old = assignment_fingerprint(current)
    current[0].driver = 'Другой'
    result = validate_driver_move_confirmation(current, '636', '404', True, old, True)
    assert not result['ok']


def test_valid_confirmation_still_does_not_write():
    current = cars()
    result = validate_driver_move_confirmation(current, '636', '404', True, assignment_fingerprint(current), True)
    assert result['ok']
    assert result['ready_for_transaction']
    assert result['writes_performed'] is False
    assert current[0].driver == 'Мердан'
