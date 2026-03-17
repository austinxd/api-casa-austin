import os
import re
import logging
import threading
import requests
from django.utils import timezone

from .models import ChatSession, ChatMessage, ChatbotConfiguration, ReviewRequest
from .channel_sender import get_sender

logger = logging.getLogger(__name__)

# Debounce: agrupa mensajes rápidos antes de enviar a IA
_debounce_timers = {}
_debounce_lock = threading.Lock()
DEBOUNCE_SECONDS = 5

# Session-level lock: previene llamadas AI concurrentes por sesión
_session_processing = {}  # session_id -> True cuando AI está procesando


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
        from django.db import IntegrityError, transaction

        wa_id = message.get('from')
        wa_message_id = message.get('id')
        msg_type = message.get('type', 'text')

        if not wa_id or not wa_message_id:
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

        # Idempotencia atómica: crear o fallar por unique constraint
        try:
            with transaction.atomic():
                chat_message = ChatMessage.objects.create(
                    session=session,
                    direction=ChatMessage.DirectionChoices.INBOUND,
                    message_type=chat_msg_type,
                    content=content,
                    wa_message_id=wa_message_id,
                    media_url=self._extract_whatsapp_media_url(message, msg_type),
                )
        except IntegrityError:
            logger.info(f"Mensaje duplicado ignorado (constraint): {wa_message_id}")
            return

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
        from django.db import IntegrityError, transaction

        sender_id = event.get('sender', {}).get('id')
        recipient_id = event.get('recipient', {}).get('id')
        message_data = event.get('message', {})
        message_id = message_data.get('mid')

        if not sender_id or not message_id:
            return

        # Ignorar mensajes enviados por nosotros (echo)
        if message_data.get('is_echo'):
            return

        # Extraer contenido
        content = self._extract_messaging_content(message_data, channel)
        if not content:
            logger.info(f"Mensaje {channel} sin contenido procesable")
            return

        # Obtener nombre del perfil (Messenger requiere llamada extra a la API)
        profile_name = None
        if channel == 'messenger':
            profile_name = self._fetch_messenger_profile(sender_id)

        # Obtener o crear sesión
        session = self._get_or_create_session(sender_id, channel, profile_name)

        # Determinar tipo de mensaje
        msg_type = 'text'
        attachments = message_data.get('attachments', [])
        media_url = None
        if attachments:
            att_type = attachments[0].get('type', 'text')
            media_url = attachments[0].get('payload', {}).get('url')
            type_map = {'image': 'image', 'audio': 'audio', 'video': 'image', 'file': 'document'}
            msg_type = type_map.get(att_type, 'text')

        # Idempotencia atómica: crear o fallar por unique constraint
        try:
            with transaction.atomic():
                chat_message = ChatMessage.objects.create(
                    session=session,
                    direction=ChatMessage.DirectionChoices.INBOUND,
                    message_type=msg_type,
                    content=content,
                    wa_message_id=message_id,
                    media_url=media_url,
                )
        except IntegrityError:
            logger.info(f"Mensaje {channel} duplicado ignorado (constraint): {message_id}")
            return

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
        """Descarga medios de WhatsApp y los guarda localmente.

        WhatsApp Cloud API envía un media ID. Se hace:
        1. GET /media_id → obtener URL temporal de descarga
        2. GET url → descargar el archivo con Authorization header
        3. Guardar en MEDIA_ROOT/chatbot/ y devolver URL pública
        """
        media_fields = {'image': 'image', 'audio': 'audio', 'document': 'document'}
        if msg_type not in media_fields:
            return None

        media = message.get(media_fields[msg_type], {})
        media_id = media.get('id')
        if not media_id:
            return None

        access_token = os.getenv('WHATSAPP_ACCESS_TOKEN')
        if not access_token:
            logger.warning("WHATSAPP_ACCESS_TOKEN no configurado, no se puede obtener media")
            return None

        auth_header = {'Authorization': f'Bearer {access_token}'}

        try:
            # Paso 1: obtener URL temporal
            resp = requests.get(
                f"https://graph.facebook.com/v22.0/{media_id}",
                headers=auth_header,
                timeout=10,
            )
            resp.raise_for_status()
            download_url = resp.json().get('url')
            mime_type = resp.json().get('mime_type', '')
            if not download_url:
                return None

            # Paso 2: descargar el archivo
            media_resp = requests.get(
                download_url,
                headers=auth_header,
                timeout=30,
            )
            media_resp.raise_for_status()

            # Paso 3: guardar localmente
            from django.conf import settings as dj_settings
            ext_map = {
                'image/jpeg': '.jpg', 'image/png': '.png', 'image/webp': '.webp',
                'audio/ogg': '.ogg', 'audio/mpeg': '.mp3',
                'application/pdf': '.pdf',
            }
            ext = ext_map.get(mime_type, '.bin')
            filename = f"{media_id}{ext}"

            media_dir = os.path.join(dj_settings.MEDIA_ROOT, 'chatbot')
            os.makedirs(media_dir, exist_ok=True)
            filepath = os.path.join(media_dir, filename)

            with open(filepath, 'wb') as f:
                f.write(media_resp.content)

            local_url = f"{dj_settings.MEDIA_URL}chatbot/{filename}"
            logger.info(f"Media guardado: {media_id} → {local_url}")
            return local_url

        except requests.exceptions.RequestException as e:
            logger.error(f"Error descargando media {media_id}: {e}")
            return None

    # =============================================
    # Session management
    # =============================================

    def _fetch_messenger_profile(self, psid):
        """Obtiene el nombre del usuario de Messenger via Graph API."""
        token = os.getenv('MESSENGER_PAGE_ACCESS_TOKEN')
        if not token:
            return None
        try:
            resp = requests.get(
                f"https://graph.facebook.com/v22.0/{psid}",
                params={'fields': 'name', 'access_token': token},
                timeout=5,
            )
            if resp.status_code == 200:
                name = resp.json().get('name')
                if name:
                    logger.info(f"Messenger profile: {psid} → {name}")
                    return name
        except requests.exceptions.RequestException as e:
            logger.warning(f"Error obteniendo perfil Messenger {psid}: {e}")
        return None

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
                session.client_was_new = client.created >= session.created
                session.save(update_fields=['client', 'client_was_new'])
                logger.info(
                    f"Cliente vinculado: {client.first_name} → sesión {session.id} "
                    f"(was_new={session.client_was_new})"
                )
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

    # =============================================
    # Review flow constants
    # =============================================

    EXIT_KEYWORDS = [
        "no gracias", "después", "despues", "no me interesa",
        "luego", "ahora no",
    ]
    MAX_REVIEW_RETRIES = 2

    def _dispatch(self, session, chat_message):
        """Despacha al AI o notifica admins.
        - IA activa: el bot responde solo, NO se notifica (el bot usa notify_team cuando necesita).
        - IA pausada: el admin gestiona, se le notifica cada mensaje del cliente."""
        # Interceptar review flow
        ctx = session.conversation_context or {}
        review_state = ctx.get('review_flow')
        if review_state:
            handled = self._handle_review_flow(session, chat_message, review_state)
            if handled:
                return

        if session.ai_enabled:
            self._dispatch_to_ai_debounced(session, chat_message)
        else:
            self._notify_admins(session, chat_message)

    def _dispatch_to_ai_debounced(self, session, chat_message):
        """Despacha a IA con debounce: espera 5s agrupando mensajes rápidos.
        Si la IA ya está procesando para esta sesión, NO dispara otra llamada
        concurrente — encola el mensaje para que se procese al terminar."""
        session_id = str(session.id)

        def _do_dispatch():
            with _debounce_lock:
                _debounce_timers.pop(session_id, None)

                # Si ya hay una llamada AI en curso para esta sesión, no lanzar otra
                if _session_processing.get(session_id):
                    logger.info(
                        f"AI busy for session {session_id}, "
                        f"msg {chat_message.id} will be picked up after current call"
                    )
                    return

                _session_processing[session_id] = True

            try:
                from django.db import connection
                connection.ensure_connection()

                # Procesar en loop: si llegan mensajes mientras AI trabaja,
                # al terminar re-chequea si hay mensajes nuevos sin responder
                while True:
                    latest = ChatMessage.objects.filter(
                        session_id=session.id,
                        direction=ChatMessage.DirectionChoices.INBOUND,
                        deleted=False,
                    ).order_by('-created').first()

                    if not latest:
                        break

                    # Verificar que el último mensaje inbound no tenga respuesta AI posterior
                    has_ai_reply = ChatMessage.objects.filter(
                        session_id=session.id,
                        direction=ChatMessage.DirectionChoices.OUTBOUND_AI,
                        created__gt=latest.created,
                        deleted=False,
                    ).exists()

                    if has_ai_reply:
                        logger.info(
                            f"Session {session_id}: latest inbound msg {latest.id} "
                            f"already has AI reply, done."
                        )
                        break

                    logger.info(
                        f"Processing msg {latest.id} for session {session_id}"
                    )
                    self._dispatch_to_ai(session, latest)

                    # Pequeña pausa para que mensajes en vuelo se guarden en BD
                    import time
                    time.sleep(0.5)

            except Exception as e:
                logger.error(f"Error in debounced dispatch: {e}", exc_info=True)
            finally:
                with _debounce_lock:
                    _session_processing.pop(session_id, None)

        with _debounce_lock:
            old_timer = _debounce_timers.get(session_id)
            if old_timer:
                old_timer.cancel()
            timer = threading.Timer(DEBOUNCE_SECONDS, _do_dispatch)
            timer.daemon = True
            _debounce_timers[session_id] = timer
            timer.start()

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

            # Después de AI responder, re-enviar botones de review si aplica
            self._post_ai_review_retry(session)

        except Exception as e:
            logger.error(f"Error en AI dispatch: {e}", exc_info=True)

    def _notify_admins(self, session, chat_message):
        """Notifica a admins vía push cuando la IA está pausada.
        Throttle: máximo 1 cada 30 minutos por sesión."""
        try:
            from django.utils import timezone
            from datetime import timedelta
            from apps.clients.expo_push_service import ExpoPushService

            now = timezone.now()
            if session.last_notify_at:
                elapsed = now - session.last_notify_at
                if elapsed < timedelta(minutes=30):
                    return

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

            session.last_notify_at = now
            session.save(update_fields=['last_notify_at'])
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

    # =============================================
    # Review flow handling
    # =============================================

    def _clear_review_flow(self, session):
        """Limpia el review flow del contexto de la sesión."""
        ctx = session.conversation_context or {}
        ctx.pop('review_flow', None)
        ctx.pop('review_request_id', None)
        session.conversation_context = ctx
        session.save(update_fields=['conversation_context'])

    def _get_review_request(self, session):
        """Obtiene el ReviewRequest activo para esta sesión."""
        ctx = session.conversation_context or {}
        rr_id = ctx.get('review_request_id')
        if not rr_id:
            return None
        try:
            return ReviewRequest.objects.get(id=rr_id, deleted=False)
        except ReviewRequest.DoesNotExist:
            return None

    def _handle_review_flow(self, session, chat_message, state):
        """
        Intercepta mensajes durante el review flow.
        Returns True si el mensaje fue manejado completamente (no pasa a AI).
        Returns False si el AI debe procesar el mensaje.
        """
        text = (chat_message.content or '').strip().lower()

        # Verificar exit keywords (aplica en todos los estados)
        for kw in self.EXIT_KEYWORDS:
            if kw in text:
                logger.info(f"Review flow: exit keyword '{kw}' detected, clearing flow")
                self._clear_review_flow(session)
                return False  # AI retoma limpio

        if state == 'awaiting_benefits_click':
            return self._handle_awaiting_benefits(session, chat_message, text)
        elif state == 'awaiting_rating':
            return self._handle_awaiting_rating(session, chat_message, text)
        elif state == 'awaiting_feedback':
            return self._handle_awaiting_feedback(session, chat_message, text)

        return False

    def _handle_awaiting_benefits(self, session, chat_message, text):
        """Maneja estado awaiting_benefits_click."""
        # Detectar botón "VER MIS BENEFICIOS" (button reply o texto exacto)
        benefits_triggers = ['ver mis beneficios', 'ver beneficios', 'mis beneficios']
        is_benefits_click = any(t in text for t in benefits_triggers)

        if is_benefits_click:
            review_req = self._get_review_request(session)
            if not review_req:
                self._clear_review_flow(session)
                return False

            self._send_benefits_and_rating(session, review_req)
            return True

        # Texto libre: verificar retries
        review_req = self._get_review_request(session)
        if review_req and review_req.review_retries >= self.MAX_REVIEW_RETRIES:
            logger.info("Review flow: max retries reached in awaiting_benefits, clearing")
            self._clear_review_flow(session)
            return False  # AI retoma limpio

        # AI procesará, luego _post_ai_review_retry re-envía botones
        return False

    def _handle_awaiting_rating(self, session, chat_message, text):
        """Maneja estado awaiting_rating."""
        review_req = self._get_review_request(session)
        if not review_req:
            self._clear_review_flow(session)
            return False

        # Detectar botones de rating
        if 'excelente' in text:
            self._process_positive_rating(session, review_req, rating=5)
            return True
        elif 'muy buena' in text:
            self._process_positive_rating(session, review_req, rating=4)
            return True
        elif 'mejorar' in text:
            self._process_negative_rating(session, review_req)
            return True

        # Texto libre: verificar retries
        if review_req.review_retries >= self.MAX_REVIEW_RETRIES:
            logger.info("Review flow: max retries reached in awaiting_rating, clearing")
            self._clear_review_flow(session)
            return False

        # AI procesará, luego _post_ai_review_retry re-envía botones
        return False

    def _handle_awaiting_feedback(self, session, chat_message, text):
        """Maneja estado awaiting_feedback: cualquier texto es feedback."""
        review_req = self._get_review_request(session)
        if not review_req:
            self._clear_review_flow(session)
            return False

        # Guardar feedback
        review_req.feedback_text = chat_message.content
        review_req.status = 'feedback_received'
        review_req.save(update_fields=['feedback_text', 'status'])

        # Notificar al equipo por Telegram
        try:
            from apps.core.telegram_notifier import send_telegram_message, CHAT_ID
            client_name = f"{review_req.client.first_name} {review_req.client.last_name or ''}".strip()
            telegram_msg = (
                f"⚠️ Review negativa de {client_name} "
                f"({review_req.client.tel_number}):\n\n"
                f"{chat_message.content}"
            )
            if CHAT_ID:
                send_telegram_message(telegram_msg, CHAT_ID)
        except Exception as e:
            logger.error(f"Error notificando feedback por Telegram: {e}")

        # Responder al cliente
        from .whatsapp_sender import WhatsAppSender
        sender = WhatsAppSender()
        wa_msg_id = sender.send_text_message(
            to=session.wa_id,
            text="Gracias por tu feedback, lo tomaremos muy en cuenta para mejorar 🙏"
        )

        # Registrar mensaje
        ChatMessage.objects.create(
            session=session,
            direction='outbound_ai',
            message_type='text',
            content="Gracias por tu feedback, lo tomaremos muy en cuenta para mejorar 🙏",
            wa_message_id=wa_msg_id,
            intent_detected='review_feedback',
        )
        session.total_messages += 1
        session.last_message_at = timezone.now()
        session.save(update_fields=['total_messages', 'last_message_at'])

        # Limpiar review flow
        self._clear_review_flow(session)
        return True

    def _send_benefits_and_rating(self, session, review_req):
        """Envía detalles de beneficios y botones de rating."""
        from apps.chatbot.management.commands.send_promo_birthday import get_client_level_info
        from apps.chatbot.models import PromoBirthdayConfig
        from .whatsapp_sender import WhatsAppSender

        client = review_req.client
        nivel, discount_perm, siguiente_nivel, que_falta = get_client_level_info(client)
        puntos = client.get_available_points()
        referral_code = client.get_referral_code()

        # Obtener descuento de cumpleaños
        try:
            bday_config = PromoBirthdayConfig.get_config()
            bday_discount = bday_config.birthday_discount_percentage if bday_config.is_active else 0
        except Exception:
            bday_discount = 0

        # Obtener descuento del siguiente nivel
        next_level_discount = 0
        if siguiente_nivel != "Máximo alcanzado":
            try:
                from apps.clients.models import Achievement
                next_ach = Achievement.objects.filter(
                    name=siguiente_nivel, is_active=True, deleted=False
                ).first()
                if next_ach:
                    next_level_discount = int(next_ach.discount_percentage)
            except Exception:
                pass

        # Construir mensaje de beneficios
        benefits_text = f"🏆 *Tu perfil Casa Austin*\n\n"
        benefits_text += f"📊 Nivel: *{nivel}*\n\n"

        # Beneficios activos
        benefits_text += "✅ *Tus beneficios activos:*\n\n"

        # Descuento permanente
        if int(discount_perm) > 0:
            benefits_text += f"🏷️ *{int(discount_perm)}%* de descuento en todas tus reservas\n"
        else:
            benefits_text += "🏷️ Descuento permanente: _disponible desde el siguiente nivel_\n"

        # Descuento de cumpleaños
        if bday_discount > 0:
            benefits_text += f"🎂 *{bday_discount}%* de descuento en tu mes de cumpleaños\n"

        # Puntos
        if int(puntos) > 0:
            benefits_text += f"💰 *{int(puntos)} puntos* acumulados (canjeables por S/{int(puntos)} en tu próxima reserva)\n"
        else:
            benefits_text += "💰 Acumulas *5% en puntos* con cada reserva\n"

        # Código de referido
        benefits_text += f"👥 Tu código: *{referral_code}* — compártelo y gana puntos por cada amigo que reserve\n"

        # Siguiente nivel
        if siguiente_nivel != "Máximo alcanzado":
            benefits_text += f"\n🚀 *Siguiente nivel: {siguiente_nivel}*\n"
            benefits_text += f"Te falta: {que_falta}\n"
            if next_level_discount > 0:
                benefits_text += f"🔓 Desbloqueas: *{next_level_discount}% de descuento permanente*\n"
        else:
            benefits_text += f"\n🚀 *¡Felicidades! Ya eres del nivel más alto* 🎉\n"

        sender = WhatsAppSender()

        # Enviar texto de beneficios
        wa_msg_id = sender.send_text_message(to=session.wa_id, text=benefits_text)
        ChatMessage.objects.create(
            session=session,
            direction='outbound_ai',
            message_type='text',
            content=benefits_text,
            wa_message_id=wa_msg_id,
            intent_detected='review_benefits',
        )

        # Enviar botones de rating
        rating_body = "¿Cómo calificarías tu experiencia en Casa Austin?"
        rating_buttons = [
            {'id': 'rating_excellent', 'title': '⭐⭐⭐⭐⭐ Excelente'},
            {'id': 'rating_good', 'title': '⭐⭐⭐⭐ Muy buena'},
            {'id': 'rating_improve', 'title': 'Podría mejorar'},
        ]
        wa_btn_id = sender.send_interactive_buttons(
            to=session.wa_id, body=rating_body, buttons=rating_buttons
        )
        ChatMessage.objects.create(
            session=session,
            direction='outbound_ai',
            message_type='interactive',
            content=rating_body,
            wa_message_id=wa_btn_id,
            intent_detected='review_rating_ask',
        )

        session.total_messages += 2
        session.last_message_at = timezone.now()
        session.save(update_fields=['total_messages', 'last_message_at'])

        # Actualizar review request
        review_req.status = 'benefits_viewed'
        review_req.review_retries = 0
        review_req.save(update_fields=['status', 'review_retries'])

        # Cambiar estado del flow
        ctx = session.conversation_context or {}
        ctx['review_flow'] = 'awaiting_rating'
        session.conversation_context = ctx
        session.save(update_fields=['conversation_context'])

    def _process_positive_rating(self, session, review_req, rating):
        """Procesa rating positivo (4-5): envía link de Google Review."""
        from .models import ReviewRequestConfig
        from .whatsapp_sender import WhatsAppSender

        config = ReviewRequestConfig.get_config()

        review_req.rating = rating
        review_req.status = 'review_link_sent'
        review_req.save(update_fields=['rating', 'status'])

        sender = WhatsAppSender()
        rating_label = "⭐⭐⭐⭐⭐" if rating == 5 else "⭐⭐⭐⭐"
        text = (
            f"¡Muchas gracias por tu calificación {rating_label}! 🎉\n\n"
            f"Nos encantaría que compartieras tu experiencia con otros viajeros. "
            f"¿Podrías dejarnos una reseña en Google? Solo toma 1 minuto:\n\n"
            f"👉 {config.google_review_url}\n\n"
            f"¡Tu opinión nos ayuda muchísimo! 🙏"
        )

        wa_msg_id = sender.send_text_message(to=session.wa_id, text=text)
        ChatMessage.objects.create(
            session=session,
            direction='outbound_ai',
            message_type='text',
            content=text,
            wa_message_id=wa_msg_id,
            intent_detected='review_google_link',
        )

        session.total_messages += 1
        session.last_message_at = timezone.now()
        session.save(update_fields=['total_messages', 'last_message_at'])

        # Limpiar review flow
        self._clear_review_flow(session)

    def _process_negative_rating(self, session, review_req):
        """Procesa rating negativo: pide feedback."""
        from .whatsapp_sender import WhatsAppSender

        review_req.rating = 3
        review_req.status = 'rating_negative'
        review_req.save(update_fields=['rating', 'status'])

        sender = WhatsAppSender()
        text = (
            "Lamentamos que tu experiencia no haya sido la mejor 😔\n\n"
            "Tu opinión es muy importante para nosotros. "
            "¿Podrías contarnos qué podríamos mejorar?"
        )

        wa_msg_id = sender.send_text_message(to=session.wa_id, text=text)
        ChatMessage.objects.create(
            session=session,
            direction='outbound_ai',
            message_type='text',
            content=text,
            wa_message_id=wa_msg_id,
            intent_detected='review_feedback_ask',
        )

        session.total_messages += 1
        session.last_message_at = timezone.now()
        session.save(update_fields=['total_messages', 'last_message_at'])

        # Cambiar estado a awaiting_feedback
        ctx = session.conversation_context or {}
        ctx['review_flow'] = 'awaiting_feedback'
        session.conversation_context = ctx
        session.save(update_fields=['conversation_context'])

    def _post_ai_review_retry(self, session):
        """
        Después de que el AI responde, re-envía botones del review flow si aplica.
        Incrementa review_retries.
        """
        try:
            # Refrescar sesión desde BD
            session.refresh_from_db()
            ctx = session.conversation_context or {}
            review_state = ctx.get('review_flow')

            if not review_state or review_state == 'awaiting_feedback':
                return

            review_req = self._get_review_request(session)
            if not review_req:
                return

            # Incrementar retries
            review_req.review_retries += 1
            review_req.save(update_fields=['review_retries'])

            from .whatsapp_sender import WhatsAppSender
            sender = WhatsAppSender()

            if review_state == 'awaiting_benefits_click':
                body = "Por cierto, ¿quieres ver tus beneficios de cliente frecuente? 👇"
                buttons = [
                    {'id': 'view_benefits', 'title': 'VER MIS BENEFICIOS'},
                ]
                wa_btn_id = sender.send_interactive_buttons(
                    to=session.wa_id, body=body, buttons=buttons
                )
                ChatMessage.objects.create(
                    session=session,
                    direction='outbound_ai',
                    message_type='interactive',
                    content=body,
                    wa_message_id=wa_btn_id,
                    intent_detected='review_benefits_retry',
                )

            elif review_state == 'awaiting_rating':
                body = "¿Cómo calificarías tu experiencia en Casa Austin? 👇"
                buttons = [
                    {'id': 'rating_excellent', 'title': '⭐⭐⭐⭐⭐ Excelente'},
                    {'id': 'rating_good', 'title': '⭐⭐⭐⭐ Muy buena'},
                    {'id': 'rating_improve', 'title': 'Podría mejorar'},
                ]
                wa_btn_id = sender.send_interactive_buttons(
                    to=session.wa_id, body=body, buttons=buttons
                )
                ChatMessage.objects.create(
                    session=session,
                    direction='outbound_ai',
                    message_type='interactive',
                    content=body,
                    wa_message_id=wa_btn_id,
                    intent_detected='review_rating_retry',
                )

            session.total_messages += 1
            session.last_message_at = timezone.now()
            session.save(update_fields=['total_messages', 'last_message_at'])

        except Exception as e:
            logger.error(f"Error en _post_ai_review_retry: {e}", exc_info=True)
