import re
import logging
from django.utils import timezone

from .models import ChatSession, ChatMessage, ChatbotConfiguration
from .channel_sender import get_sender

logger = logging.getLogger(__name__)


class WebhookProcessor:
    """
    Procesa los payloads del webhook unificado de Meta.
    Soporta WhatsApp Business API, Instagram Messaging, y Facebook Messenger.

    Estructura de payloads:
    - WhatsApp: object="whatsapp_business_account", entry[].changes[].value.messages[]
    - Instagram: object="instagram", entry[].messaging[]
    - Messenger: object="page", entry[].messaging[]
    """

    # Mapeo de object type a canal
    CHANNEL_MAP = {
        'whatsapp_business_account': 'whatsapp',
        'instagram': 'instagram',
        'page': 'messenger',
    }

    def process(self, payload):
        """Punto de entrada principal para procesar un payload de webhook"""
        if not payload:
            return

        object_type = payload.get('object', '')
        channel = self.CHANNEL_MAP.get(object_type)

        if not channel:
            logger.warning(f"Tipo de objeto desconocido en webhook: {object_type}")
            return

        entries = payload.get('entry', [])

        if channel == 'whatsapp':
            self._process_whatsapp_entries(entries)
        else:
            # Instagram y Messenger usan la misma estructura (messaging[])
            self._process_messaging_entries(entries, channel)

    # =============================================
    # WhatsApp processing (estructura changes[])
    # =============================================

    def _process_whatsapp_entries(self, entries):
        """Procesa entries de WhatsApp Business API"""
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
                    self._process_whatsapp_message(message, contact_map)

    def _process_whatsapp_message(self, message, contact_map):
        """Procesa un mensaje entrante de WhatsApp"""
        wa_id = message.get('from')
        wa_message_id = message.get('id')
        msg_type = message.get('type', 'text')

        if not wa_id or not wa_message_id:
            return

        # Idempotencia
        if ChatMessage.objects.filter(wa_message_id=wa_message_id).exists():
            logger.info(f"Mensaje duplicado ignorado: {wa_message_id}")
            return

        content = self._extract_whatsapp_content(message, msg_type)
        if not content:
            logger.info(f"Mensaje sin contenido procesable: {msg_type}")
            return

        profile_name = contact_map.get(wa_id)
        session = self._get_or_create_session(wa_id, 'whatsapp', profile_name)

        message_type_map = {
            'text': 'text', 'image': 'image', 'audio': 'audio',
            'document': 'document', 'location': 'location',
            'interactive': 'interactive', 'button': 'interactive',
        }
        chat_msg_type = message_type_map.get(msg_type, 'text')

        chat_message = ChatMessage.objects.create(
            session=session,
            direction=ChatMessage.DirectionChoices.INBOUND,
            message_type=chat_msg_type,
            content=content,
            wa_message_id=wa_message_id,
            media_url=self._extract_whatsapp_media_url(message, msg_type),
        )

        self._update_session_on_message(session)

        # Marcar como leído en WhatsApp
        sender = get_sender('whatsapp')
        sender.mark_as_read(wa_message_id)

        self._dispatch(session, chat_message)

    # =============================================
    # Instagram / Messenger processing (estructura messaging[])
    # =============================================

    def _process_messaging_entries(self, entries, channel):
        """Procesa entries de Instagram o Messenger (misma estructura)"""
        for entry in entries:
            messaging_events = entry.get('messaging', [])
            for event in messaging_events:
                # Verificar si es un mensaje (no un delivery/read receipt)
                if 'message' in event:
                    self._process_messaging_message(event, channel)
                elif 'delivery' in event or 'read' in event:
                    self._process_messaging_status(event, channel)

    def _process_messaging_message(self, event, channel):
        """Procesa un mensaje de Instagram DM o Facebook Messenger"""
        sender_id = event.get('sender', {}).get('id')
        recipient_id = event.get('recipient', {}).get('id')
        message_data = event.get('message', {})
        message_id = message_data.get('mid')

        if not sender_id or not message_id:
            return

        # Ignorar mensajes enviados por nosotros (echo)
        if message_data.get('is_echo'):
            return

        # Idempotencia
        if ChatMessage.objects.filter(wa_message_id=message_id).exists():
            logger.info(f"Mensaje {channel} duplicado ignorado: {message_id}")
            return

        # Extraer contenido
        content = self._extract_messaging_content(message_data, channel)
        if not content:
            logger.info(f"Mensaje {channel} sin contenido procesable")
            return

        # Obtener o crear sesión
        session = self._get_or_create_session(sender_id, channel)

        # Determinar tipo de mensaje
        msg_type = 'text'
        attachments = message_data.get('attachments', [])
        media_url = None
        if attachments:
            att_type = attachments[0].get('type', 'text')
            media_url = attachments[0].get('payload', {}).get('url')
            type_map = {'image': 'image', 'audio': 'audio', 'video': 'image', 'file': 'document'}
            msg_type = type_map.get(att_type, 'text')

        chat_message = ChatMessage.objects.create(
            session=session,
            direction=ChatMessage.DirectionChoices.INBOUND,
            message_type=msg_type,
            content=content,
            wa_message_id=message_id,
            media_url=media_url,
        )

        self._update_session_on_message(session)

        # Mark as seen (Messenger soporta, Instagram no)
        if channel == 'messenger':
            sender = get_sender('messenger')
            sender.mark_as_read(sender_id)

        self._dispatch(session, chat_message)

    def _process_messaging_status(self, event, channel):
        """Procesa delivery/read receipts de Instagram/Messenger"""
        # Por ahora solo log, no actualizamos estado individual
        pass

    # =============================================
    # Content extraction
    # =============================================

    def _extract_whatsapp_content(self, message, msg_type):
        """Extrae el contenido textual de un mensaje de WhatsApp"""
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

    def _extract_messaging_content(self, message_data, channel):
        """Extrae contenido de un mensaje de Instagram/Messenger"""
        # Texto directo
        text = message_data.get('text')
        if text:
            return text

        # Attachments (imagen, audio, video, sticker)
        attachments = message_data.get('attachments', [])
        if attachments:
            att = attachments[0]
            att_type = att.get('type', '')
            if att_type == 'image':
                return '[Imagen]'
            elif att_type == 'audio':
                return '[Audio]'
            elif att_type == 'video':
                return '[Video]'
            elif att_type == 'file':
                return '[Archivo]'
            elif att_type in ('sticker', 'like_heart'):
                return '[Sticker]'
            elif att_type == 'share':
                # Publicación compartida
                payload = att.get('payload', {})
                return f"[Compartido: {payload.get('url', '')}]"
            return f'[{att_type}]'

        # Story reply (Instagram)
        if message_data.get('reply_to', {}).get('story'):
            return '[Respuesta a historia]'

        return None

    def _extract_whatsapp_media_url(self, message, msg_type):
        """Extrae URL de medios de WhatsApp"""
        media_fields = {'image': 'image', 'audio': 'audio', 'document': 'document'}
        if msg_type in media_fields:
            media = message.get(media_fields[msg_type], {})
            return media.get('link') or media.get('url')
        return None

    # =============================================
    # Session management
    # =============================================

    def _get_or_create_session(self, contact_id, channel, profile_name=None):
        """Obtiene o crea una sesión de chat para un contacto.
        Un contacto + canal = una sesión."""
        from django.db import transaction

        with transaction.atomic():
            session = ChatSession.objects.select_for_update().filter(
                wa_id=contact_id, channel=channel, deleted=False
            ).order_by('-last_message_at').first()

            if session:
                update_fields = []
                if profile_name and not session.wa_profile_name:
                    session.wa_profile_name = profile_name
                    update_fields.append('wa_profile_name')
                if session.status == ChatSession.StatusChoices.CLOSED:
                    session.status = ChatSession.StatusChoices.ACTIVE
                    session.ai_enabled = True
                    update_fields.extend(['status', 'ai_enabled'])
                if update_fields:
                    session.save(update_fields=update_fields)
                return session

            session = ChatSession.objects.create(
                wa_id=contact_id,
                channel=channel,
                wa_profile_name=profile_name,
                status=ChatSession.StatusChoices.ACTIVE,
            )

        # Intentar vincular con cliente existente (solo WhatsApp tiene teléfono)
        if channel == 'whatsapp':
            self._try_link_client(session)

        return session

    def _update_session_on_message(self, session):
        """Actualiza contadores de sesión al recibir mensaje"""
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

    def _try_link_client(self, session):
        """Intenta vincular la sesión con un cliente existente por teléfono"""
        from apps.clients.models import Clients

        wa_id = session.wa_id
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
        """Genera variantes de búsqueda para un número WhatsApp."""
        digits = re.sub(r'\D', '', wa_id)
        variants = [digits]

        if digits.startswith('51') and len(digits) > 9:
            local = digits[2:]
            variants.append(local)
            variants.append(f'+51{local}')
            variants.append(f'51{local}')

        return variants

    # =============================================
    # Dispatch
    # =============================================

    def _dispatch(self, session, chat_message):
        """Despacha al AI o notifica admins"""
        if session.ai_enabled:
            self._dispatch_to_ai(session, chat_message)
        else:
            self._notify_admins(session, chat_message)

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

            channel_label = {
                'whatsapp': 'WhatsApp',
                'instagram': 'Instagram',
                'messenger': 'Messenger',
            }.get(session.channel, session.channel)

            name = session.wa_profile_name or session.wa_id
            preview = chat_message.content[:100]

            ExpoPushService.send_to_admins(
                title=f"💬 {channel_label} — {name}",
                body=preview,
                data={
                    'type': 'chatbot_message',
                    'session_id': str(session.id),
                    'channel': session.channel,
                    'screen': 'ChatBot',
                }
            )
        except Exception as e:
            logger.error(f"Error notificando admins: {e}")

    def _process_status_update(self, status_update):
        """Actualiza el estado de entrega de un mensaje saliente (WhatsApp)"""
        wa_message_id = status_update.get('id')
        new_status = status_update.get('status')

        if not wa_message_id or not new_status:
            return

        try:
            msg = ChatMessage.objects.filter(wa_message_id=wa_message_id).first()
            if msg:
                msg.wa_status = new_status
                msg.save(update_fields=['wa_status'])
        except Exception as e:
            logger.error(f"Error actualizando status de {wa_message_id}: {e}")
