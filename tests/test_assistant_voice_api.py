from fleetai import create_app


def test_voice_lookup_requires_owner(monkeypatch):
    monkeypatch.setenv('DATABASE_URL', 'sqlite:///:memory:')
    app = create_app()
    app.testing = True
    response = app.test_client().post('/api/assistant/voice/lookup', json={'text': 'Кто на машине 636?'})
    assert response.status_code == 401


def test_voice_lookup_rejects_unrecognized_command(monkeypatch):
    monkeypatch.setenv('DATABASE_URL', 'sqlite:///:memory:')
    app = create_app()
    app.testing = True
    with app.test_client() as client:
        with client.session_transaction() as sess:
            sess['fleetai_admin'] = True
            sess['fleetai_csrf_token'] = 'test-token'
        response = client.post('/api/assistant/voice/lookup', json={'text': 'привет'}, headers={'Origin': 'http://localhost', 'X-FleetAI-CSRF-Token': 'test-token'}, base_url='http://localhost')
        assert response.status_code == 422
