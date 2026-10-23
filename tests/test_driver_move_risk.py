from fleetai.driver_move_risk import financial_closeout_requirements


def test_financial_closeout_identifies_all_risks():
    result = financial_closeout_requirements({'cars': [{'car_code': '636',
        'wallet_balance_rub': -3000, 'open_driver_debt_rub': 1000,
        'deposit_rub': 5000, 'daily_rent_rub': 1857}]})
    assert result['automatic_execution_allowed'] is False
    assert {item['item'] for item in result['manual_review_items']} == {
        'wallet', 'debt', 'deposit', 'rent_schedule'}


def test_empty_financial_review_has_no_flags():
    result = financial_closeout_requirements({'cars': [{'car_code': '404',
        'wallet_balance_rub': 0, 'open_driver_debt_rub': 0,
        'deposit_rub': 0, 'daily_rent_rub': 0}]})
    assert result['automatic_execution_allowed'] is True
