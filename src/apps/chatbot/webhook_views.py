import logging

from django.conf import settings
from rest_framework.views import APIView
from rest_framework.response import Response
from rest_framework.permissions import AllowAny
from rest_framework import status

from .webhook_processor import WebhookProcessor

logger = logging.getLogger(__name__)


class MetaWebhookView(APIView):
    """
    Webhook unificado para recibir mensajes de WhatsApp, Instagram y Messenger.
    Todos usan la misma plataforma Meta y el mismo endpoint de webhook.

    GET: Verificación del webhook por Meta.
    POST: Recepción de mensajes/status updates. Retorna 200 inmediato.
    """
    permission_classes = [AllowAny]
    authentication_classes = []

    def get(self, request):
        """Verificación del webhook de Meta (compartido por WA, IG, Messenger)"""
        mode = request.query_params.get('hub.mode')
        token = request.query_params.get('hub.verify_token')
        challenge = request.query_params.get('hub.challenge')

        verify_token = getattr(
            settings, 'WHATSAPP_WEBHOOK_VERIFY_TOKEN',
            'casa_austin_webhook_2024'
        )

        if mode == 'subscribe' and token == verify_token:
            logger.info("Webhook Meta verificado exitosamente")
            return Response(int(challenge), status=status.HTTP_200_OK)

        logger.warning(f"Verificación de webhook fallida: mode={mode}, token={token}")
        return Response(
            {'error': 'Verification failed'},
            status=status.HTTP_403_FORBIDDEN
        )

    def post(self, request):
        """
        Recepción de mensajes y actualizaciones de estado.
        Detecta automáticamente el canal (WhatsApp, Instagram, Messenger)
        basándose en el campo 'object' del payload.
        Retorna 200 inmediato para evitar reintentos de Meta.
        """
        try:
            payload = request.data
            processor = WebhookProcessor()
            processor.process(payload)
        except Exception as e:
            logger.error(f"Error procesando webhook: {e}", exc_info=True)

        # Siempre retornar 200 para evitar reintentos de Meta
        return Response({'status': 'ok'}, status=status.HTTP_200_OK)


# Alias para compatibilidad con urls.py existente
WhatsAppWebhookView = MetaWebhookView
