import re
import logging
from django.utils import timezone

from .models import ChatSession, ChatMessage, ChatbotConfiguration
from .whatsapp_sender import WhatsAppSender

logger = logging.getLogger(__name__)


class WebhookProcessor:
    """
    Procesa los payloads del webhook de WhatsApp Business API.
    - Parsea mensajes entrantes y actualizaciones de estado
    - Crea/obtiene sesiones de chat
    - Verifica idempotencia
    - Vincula con clientes existentes
    - Despacha al AI Orchestrator o notifica admins
    """

    def process(self, payload):
        """Punto de entrada principal para procesar un payload de webhook"""
        if not payload:
            return

        entries = payload.get('entry', [])
        for entry in entries:
            changes = entry.get('changes', [])
            for change in changes:
                value = change.get('value', {})

                # Procesar actualizaciones de estado
                statuses = value.get('statuses', [])
                for status_update in statuses:
                    self._process_status_update(status_update)

                # Procesar mensajes entrantes
                messages = value.get('messages', [])
                contacts = value.get('contacts', [])
                contact_map = {}
                for contact in contacts:
                    wa_id = contact.get('wa_id')
                    profile_name = contact.get('profile', {}).get('name')
                    if wa_id:
                        contact_map[wa_id] = profile_name

                for message in messages:
                    self._process_message(message, contact_map)

    def _process_status_update(self, status_update):
        """Actualiza el estado de entrega de un mensaje saliente"""
        wa_message_id = status_update.get('id')
        new_status = status_update.get('status')  # sent/delivered/read/failed

        if not wa_message_id or not new_status:
            return

        try:
            msg = ChatMessage.objects.filter(wa_message_id=wa_message_id).first()
            if msg:
                msg.wa_status = new_status
                msg.save(update_fields=['wa_status'])
        except Exception as e:
            logger.error(f"Error actualizando status de {wa_message_id}: {e}")

    def _process_message(self, message, contact_map):
        """Procesa un mensaje entrante de WhatsApp"""
        wa_id = message.get('from')
        wa_message_id = message.get('id')
        msg_type = message.get('type', 'text')
        timestamp = message.get('timestamp')

        if not wa_id or not wa_message_id:
            return

        # Idempotencia: verificar si el mensaje ya fue procesado
        if ChatMessage.objects.filter(wa_message_id=wa_message_id).exists():
            logger.info(f"Mensaje duplicado ignorado: {wa_message_id}")
            return

        # Extraer contenido según tipo de mensaje
        content = self._extract_content(message, msg_type)
        if not content:
            logger.info(f"Mensaje sin contenido procesable: {msg_type}")
            return

        # Obtener o crear sesión
        profile_name = contact_map.get(wa_id)
        session = self._get_or_create_session(wa_id, profile_name)

        # Mapear tipo de mensaje
        message_type_map = {
            'text': 'text', 'image': 'image', 'audio': 'audio',
            'document': 'document', 'location': 'location',
            'interactive': 'interactive', 'button': 'interactive',
        }
        chat_msg_type = message_type_map.get(msg_type, 'text')

        # Crear mensaje entrante
        chat_message = ChatMessage.objects.create(
            session=session,
            direction=ChatMessage.DirectionChoices.INBOUND,
            message_type=chat_msg_type,
            content=content,
            wa_message_id=wa_message_id,
            media_url=self._extract_media_url(message, msg_type),
        )

        # Actualizar contadores de sesión
        now = timezone.now()
        session.total_messages += 1
        session.last_message_at = now
        session.last_customer_message_at = now
        if session.status == ChatSession.StatusChoices.CLOSED:
            session.status = ChatSession.StatusChoices.ACTIVE
            session.ai_enabled = True
        session.save(update_fields=[
            'total_messages', 'last_message_at',
            'last_customer_message_at', 'status', 'ai_enabled',
        ])

        # Marcar como leído
        sender = WhatsAppSender()
        sender.mark_as_read(wa_message_id)

        # Despachar al AI o notificar admins
        if session.ai_enabled:
            self._dispatch_to_ai(session, chat_message)
        else:
            self._notify_admins(session, chat_message)

    def _extract_content(self, message, msg_type):
        """Extrae el contenido textual de un mensaje según su tipo"""
        if msg_type == 'text':
            return message.get('text', {}).get('body', '')
        elif msg_type == 'interactive':
            interactive = message.get('interactive', {})
            if interactive.get('type') == 'button_reply':
                return interactive.get('button_reply', {}).get('title', '')
            elif interactive.get('type') == 'list_reply':
                return interactive.get('list_reply', {}).get('title', '')
        elif msg_type == 'button':
            return message.get('button', {}).get('text', '')
        elif msg_type == 'image':
            return message.get('image', {}).get('caption', '[Imagen]')
        elif msg_type == 'audio':
            return '[Audio]'
        elif msg_type == 'document':
            return message.get('document', {}).get('caption', '[Documento]')
        elif msg_type == 'location':
            loc = message.get('location', {})
            return f"[Ubicación: {loc.get('latitude')}, {loc.get('longitude')}]"
        return None

    def _extract_media_url(self, message, msg_type):
        """Extrae URL de medios si existe"""
        media_fields = {'image': 'image', 'audio': 'audio', 'document': 'document'}
        if msg_type in media_fields:
            media = message.get(media_fields[msg_type], {})
            return media.get('link') or media.get('url')
        return None

    def _get_or_create_session(self, wa_id, profile_name=None):
        """Obtiene o crea una sesión de chat para un wa_id.
        Usa select_for_update para evitar sesiones duplicadas por race condition."""
        from django.db import transaction

        with transaction.atomic():
            session = ChatSession.objects.select_for_update().filter(
                wa_id=wa_id, deleted=False
            ).exclude(
                status=ChatSession.StatusChoices.CLOSED
            ).first()

            if session:
                if profile_name and not session.wa_profile_name:
                    session.wa_profile_name = profile_name
                    session.save(update_fields=['wa_profile_name'])
                return session

            # Crear nueva sesión
            session = ChatSession.objects.create(
                wa_id=wa_id,
                wa_profile_name=profile_name,
                status=ChatSession.StatusChoices.ACTIVE,
            )

        # Intentar vincular con cliente existente (fuera del lock)
        self._try_link_client(session)

        return session

    def _try_link_client(self, session):
        """Intenta vincular la sesión con un cliente existente por teléfono"""
        from apps.clients.models import Clients

        wa_id = session.wa_id
        # Generar variantes del número para búsqueda
        phone_variants = self._normalize_phone_variants(wa_id)

        for variant in phone_variants:
            client = Clients.objects.filter(
                tel_number__icontains=variant, deleted=False
            ).first()
            if client:
                session.client = client
                session.save(update_fields=['client'])
                logger.info(f"Cliente vinculado: {client.first_name} → sesión {session.id}")
                return

    def _normalize_phone_variants(self, wa_id):
        """
        Genera variantes de búsqueda para un número WhatsApp.
        wa_id viene como 51XXXXXXXXX (sin +)
        """
        digits = re.sub(r'\D', '', wa_id)
        variants = [digits]

        # Sin código de país (51)
        if digits.startswith('51') and len(digits) > 9:
            local = digits[2:]
            variants.append(local)
            variants.append(f'+51{local}')
            variants.append(f'51{local}')

        return variants

    def _dispatch_to_ai(self, session, chat_message):
        """Envía el mensaje al orquestador de IA para respuesta"""
        try:
            config = ChatbotConfiguration.get_config()
            if not config.is_active:
                logger.info("Chatbot IA desactivado globalmente")
                return

            from .ai_orchestrator import AIOrchestrator
            orchestrator = AIOrchestrator(config)
            orchestrator.process_message(session, chat_message)

        except Exception as e:
            logger.error(f"Error en AI dispatch: {e}", exc_info=True)

    def _notify_admins(self, session, chat_message):
        """Notifica a admins vía push cuando la IA está pausada"""
        try:
            from apps.clients.expo_push_service import ExpoPushService

            name = session.wa_profile_name or session.wa_id
            preview = chat_message.content[:100]

            ExpoPushService.send_to_admins(
                title=f"💬 Mensaje de {name}",
                body=preview,
                data={
                    'type': 'chatbot_message',
                    'session_id': str(session.id),
                    'screen': 'ChatBot',
                }
            )
        except Exception as e:
            logger.error(f"Error notificando admins: {e}")
