from types import SimpleNamespace

from fleetai.driver_voice import parse_driver_lookup, current_driver_response


def test_current_driver_lookup():
    assert parse_driver_lookup("Кто сейчас ездит на 636?") == {
        "kind": "current_driver", "car_code": "636", "read_only": True
    }


def test_unrelated_text_not_interpreted_as_driver_lookup():
    assert parse_driver_lookup("Потратил на 636 500 рублей") is None


def test_current_driver_response():
    car = SimpleNamespace(code="636", driver="Мердан")
    assert current_driver_response(car)["driver"] == "Мердан"
    assert current_driver_response(None)["ok"] is False


def test_empty_driver():
    car = SimpleNamespace(code="404", driver="")
    assert "не назначен" in current_driver_response(car)["message"]
