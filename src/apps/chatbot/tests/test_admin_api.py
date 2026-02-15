from django.test import TestCase
from django.utils import timezone
from rest_framework.test import APIClient

from apps.accounts.models import CustomUser
from apps.chatbot.models import ChatSession, ChatMessage, ChatbotConfiguration


class AdminAPITest(TestCase):
    """Tests para la API de administración del chatbot"""

    def setUp(self):
        self.user = CustomUser.objects.create_user(
            username='admin_test',
            email='admin@test.com',
            password='testpass123',
        )
        self.client = APIClient()
        self.client.force_authenticate(user=self.user)

        ChatbotConfiguration.objects.create(is_active=True)

        # Crear sesiones de prueba
        self.session = ChatSession.objects.create(
            wa_id='51999111222',
            wa_profile_name='Test Client',
            status='active',
            last_message_at=timezone.now(),
        )

        ChatMessage.objects.create(
            session=self.session,
            direction='inbound',
            content='Hola, quiero información',
        )

    def test_list_sessions(self):
        """GET /sessions/ retorna lista de sesiones"""
        response = self.client.get('/api/v1/chatbot/sessions/')
        self.assertEqual(response.status_code, 200)
        self.assertIn('results', response.data)
        self.assertEqual(len(response.data['results']), 1)

    def test_list_sessions_filter_status(self):
        """GET /sessions/?status=active filtra por estado"""
        response = self.client.get('/api/v1/chatbot/sessions/', {'status': 'active'})
        self.assertEqual(response.status_code, 200)
        self.assertEqual(len(response.data['results']), 1)

        response = self.client.get('/api/v1/chatbot/sessions/', {'status': 'escalated'})
        self.assertEqual(response.status_code, 200)
        self.assertEqual(len(response.data['results']), 0)

    def test_list_sessions_search(self):
        """GET /sessions/?search= busca por nombre/teléfono"""
        response = self.client.get('/api/v1/chatbot/sessions/', {'search': 'Test'})
        self.assertEqual(response.status_code, 200)
        self.assertEqual(len(response.data['results']), 1)

        response = self.client.get('/api/v1/chatbot/sessions/', {'search': 'inexistente'})
        self.assertEqual(response.status_code, 200)
        self.assertEqual(len(response.data['results']), 0)

    def test_session_detail(self):
        """GET /sessions/{id}/ retorna detalle"""
        response = self.client.get(f'/api/v1/chatbot/sessions/{self.session.id}/')
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data['wa_id'], '51999111222')

    def test_get_messages(self):
        """GET /sessions/{id}/messages/ retorna mensajes"""
        response = self.client.get(
            f'/api/v1/chatbot/sessions/{self.session.id}/messages/'
        )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(len(response.data), 1)
        self.assertEqual(response.data[0]['content'], 'Hola, quiero información')

    def test_toggle_ai_pause(self):
        """POST /sessions/{id}/toggle-ai/ pausa la IA"""
        response = self.client.post(
            f'/api/v1/chatbot/sessions/{self.session.id}/toggle-ai/',
            {'ai_enabled': False},
            format='json'
        )
        self.assertEqual(response.status_code, 200)
        self.assertFalse(response.data['ai_enabled'])
        self.assertEqual(response.data['status'], 'ai_paused')

        self.session.refresh_from_db()
        self.assertFalse(self.session.ai_enabled)
        self.assertIsNotNone(self.session.ai_resume_at)

    def test_toggle_ai_resume(self):
        """POST /sessions/{id}/toggle-ai/ reactiva la IA"""
        self.session.ai_enabled = False
        self.session.status = 'ai_paused'
        self.session.save()

        response = self.client.post(
            f'/api/v1/chatbot/sessions/{self.session.id}/toggle-ai/',
            {'ai_enabled': True},
            format='json'
        )
        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.data['ai_enabled'])
        self.assertEqual(response.data['status'], 'active')

    def test_poll_sessions(self):
        """GET /sessions/poll/?since= retorna actualizaciones"""
        one_hour_ago = (timezone.now() - timezone.timedelta(hours=1)).isoformat()
        response = self.client.get('/api/v1/chatbot/sessions/poll/', {'since': one_hour_ago})
        self.assertEqual(response.status_code, 200)
        self.assertIn('sessions', response.data)
        self.assertIn('new_messages', response.data)
        self.assertIn('server_time', response.data)

    def test_poll_requires_since(self):
        """GET /sessions/poll/ sin since retorna 400"""
        response = self.client.get('/api/v1/chatbot/sessions/poll/')
        self.assertEqual(response.status_code, 400)

    def test_analytics_empty(self):
        """GET /analytics/ retorna lista vacía sin datos"""
        response = self.client.get('/api/v1/chatbot/analytics/')
        self.assertEqual(response.status_code, 200)
        self.assertEqual(len(response.data), 0)

    def test_unauthenticated_access_denied(self):
        """API requiere autenticación"""
        unauth_client = APIClient()
        response = unauth_client.get('/api/v1/chatbot/sessions/')
        self.assertIn(response.status_code, [401, 403])
