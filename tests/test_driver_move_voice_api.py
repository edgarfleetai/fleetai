import unittest
from fleetai import create_app


class VoicePreviewApiTests(unittest.TestCase):
    def test_unauthorized_voice_preview(self):
        app = create_app()
        app.testing = True
        response = app.test_client().post('/api/assistant/driver-move/preview',
            json={'text': 'Поменяй водителей 404 и 636 местами'})
        self.assertEqual(response.status_code, 401)

    def test_ambiguous_voice_command_rejected(self):
        app = create_app()
        app.testing = True
        with app.test_client() as client:
            with client.session_transaction() as session:
                session['fleetai_admin'] = True
            response = client.post('/api/assistant/driver-move/preview',
                json={'text': 'Поменяй водителя на 404'},
                headers={'Origin': 'http://localhost'}, base_url='http://localhost')
            self.assertEqual(response.status_code, 422)
