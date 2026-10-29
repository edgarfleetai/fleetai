from fleetai.driver_move_preview import preview_driver_move


def test_move_to_empty_car():
    result = preview_driver_move({'636': 'Мердан', '404': ''}, '636', '404')
    assert result['ok'] is True
    assert result['writes_performed'] is False
    assert result['requires_confirmation'] is True
    assert result['changes'][0]['after'] == ''
    assert result['changes'][1]['after'] == 'Мердан'


def test_occupied_target_rejected():
    result = preview_driver_move({'636': 'Мердан', '404': 'Мекан'}, '636', '404')
    assert result['ok'] is False


def test_explicit_swap():
    result = preview_driver_move({'636': 'Мердан', '404': 'Мекан'}, '636', '404', swap=True)
    assert result['ok'] is True
    assert result['changes'][0]['after'] == 'Мекан'
    assert result['changes'][1]['after'] == 'Мердан'


def test_same_car_rejected():
    assert preview_driver_move({'636': 'Мердан'}, '636', '636')['ok'] is False


def test_missing_source_driver_rejected():
    assert preview_driver_move({'636': '', '404': ''}, '636', '404')['ok'] is False
