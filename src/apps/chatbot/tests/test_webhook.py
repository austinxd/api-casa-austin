import json
from django.test import TestCase, RequestFactory
from django.test.utils import override_settings
from rest_framework.test import APIClient

from apps.chatbot.models import ChatSession, ChatMessage, ChatbotConfiguration
from apps.chatbot.webhook_processor import WebhookProcessor


class WebhookVerificationTest(TestCase):
    """Tests para la verificación del webhook de Meta"""

    def setUp(self):
        self.client = APIClient()

    @override_settings(WHATSAPP_WEBHOOK_VERIFY_TOKEN='test_token_123')
    def test_webhook_verification_success(self):
        response = self.client.get('/api/v1/chatbot/webhook/', {
            'hub.mode': 'subscribe',
            'hub.verify_token': 'test_token_123',
            'hub.challenge': '12345',
        })
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data, 12345)

    @override_settings(WHATSAPP_WEBHOOK_VERIFY_TOKEN='test_token_123')
    def test_webhook_verification_failure(self):
        response = self.client.get('/api/v1/chatbot/webhook/', {
            'hub.mode': 'subscribe',
            'hub.verify_token': 'wrong_token',
            'hub.challenge': '12345',
        })
        self.assertEqual(response.status_code, 403)

    def test_webhook_post_returns_200(self):
        """Siempre retorna 200 para evitar reintentos de Meta"""
        # Crear config para evitar error en AI dispatch
        ChatbotConfiguration.objects.create(is_active=False)

        response = self.client.post(
            '/api/v1/chatbot/webhook/',
            data={'entry': []},
            format='json'
        )
        self.assertEqual(response.status_code, 200)


class WebhookProcessorTest(TestCase):
    """Tests para el procesador de webhooks"""

    def setUp(self):
        self.processor = WebhookProcessor()
        ChatbotConfiguration.objects.create(is_active=False)

    def test_process_empty_payload(self):
        """No falla con payload vacío"""
        self.processor.process({})
        self.processor.process(None)

    def test_process_text_message_creates_session_and_message(self):
        """Crea sesión y mensaje al recibir un mensaje de texto"""
        payload = {
            'entry': [{
                'changes': [{
                    'value': {
                        'contacts': [{
                            'wa_id': '51999888777',
                            'profile': {'name': 'Juan Test'}
                        }],
                        'messages': [{
                            'from': '51999888777',
                            'id': 'wamid.test123',
                            'type': 'text',
                            'text': {'body': 'Hola, quiero reservar'},
                            'timestamp': '1234567890',
                        }]
                    }
                }]
            }]
        }

        self.processor.process(payload)

        # Verificar sesión creada
        session = ChatSession.objects.filter(wa_id='51999888777').first()
        self.assertIsNotNone(session)
        self.assertEqual(session.wa_profile_name, 'Juan Test')
        self.assertEqual(session.status, 'active')

        # Verificar mensaje creado
        msg = ChatMessage.objects.filter(wa_message_id='wamid.test123').first()
        self.assertIsNotNone(msg)
        self.assertEqual(msg.content, 'Hola, quiero reservar')
        self.assertEqual(msg.direction, 'inbound')

    def test_idempotency_prevents_duplicate(self):
        """No procesa el mismo mensaje dos veces"""
        payload = {
            'entry': [{
                'changes': [{
                    'value': {
                        'contacts': [{'wa_id': '51111222333', 'profile': {'name': 'Test'}}],
                        'messages': [{
                            'from': '51111222333',
                            'id': 'wamid.duplicate_test',
                            'type': 'text',
                            'text': {'body': 'Mensaje duplicado'},
                            'timestamp': '1234567890',
                        }]
                    }
                }]
            }]
        }

        self.processor.process(payload)
        self.processor.process(payload)  # Segunda vez

        count = ChatMessage.objects.filter(wa_message_id='wamid.duplicate_test').count()
        self.assertEqual(count, 1)

    def test_process_status_update(self):
        """Actualiza estado de entrega de mensajes"""
        # Crear mensaje previo
        session = ChatSession.objects.create(wa_id='51999000111')
        ChatMessage.objects.create(
            session=session,
            direction='outbound_ai',
            content='Respuesta test',
            wa_message_id='wamid.status_test',
            wa_status='sent',
        )

        payload = {
            'entry': [{
                'changes': [{
                    'value': {
                        'statuses': [{
                            'id': 'wamid.status_test',
                            'status': 'delivered',
                        }]
                    }
                }]
            }]
        }

        self.processor.process(payload)

        msg = ChatMessage.objects.get(wa_message_id='wamid.status_test')
        self.assertEqual(msg.wa_status, 'delivered')
