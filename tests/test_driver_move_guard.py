from types import SimpleNamespace
from fleetai.driver_move_guard import assignment_fingerprint, is_preview_current


def car(code, driver):
    return SimpleNamespace(code=code, driver=driver, daily_rent=1857, driver_deposit=5000)


def test_same_assignment_matches():
    cars = [car('636', 'Мердан'), car('404', 'Мекан')]
    fingerprint = assignment_fingerprint(cars)
    assert is_preview_current(list(reversed(cars)), fingerprint)


def test_changed_driver_invalidates_preview():
    cars = [car('636', 'Мердан'), car('404', 'Мекан')]
    fingerprint = assignment_fingerprint(cars)
    cars[0].driver = 'Другой водитель'
    assert not is_preview_current(cars, fingerprint)


def test_changed_rent_invalidates_preview():
    cars = [car('636', 'Мердан'), car('404', 'Мекан')]
    fingerprint = assignment_fingerprint(cars)
    cars[1].daily_rent = 2000
    assert not is_preview_current(cars, fingerprint)
