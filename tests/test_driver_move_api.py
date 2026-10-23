from fleetai import create_app


def test_driver_move_preview_requires_owner(monkeypatch):
    monkeypatch.setenv('DATABASE_URL', 'sqlite:///:memory:')
    app = create_app()
    app.testing = True
    response = app.test_client().post('/api/assistant/driver-move/preview', json={'source': '636', 'target': '404'})
    assert response.status_code == 401


def test_driver_move_preview_rejects_bad_input(monkeypatch):
    monkeypatch.setenv('DATABASE_URL', 'sqlite:///:memory:')
    app = create_app()
    app.testing = True
    with app.test_client() as client:
        with client.session_transaction() as sess:
            sess['fleetai_admin'] = True
        response = client.post('/api/assistant/driver-move/preview', json={'source': '', 'target': '404'}, headers={'Origin': 'http://localhost'}, base_url='http://localhost')
        assert response.status_code == 400
