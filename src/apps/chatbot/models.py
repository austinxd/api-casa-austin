import re
import logging

from django.db import models
from django.conf import settings
from django.utils import timezone

from apps.core.models import BaseModel

logger = logging.getLogger('apps')


class ChatSession(BaseModel):
    """Sesión de chat por contacto (WhatsApp, Instagram, Messenger)"""

    class StatusChoices(models.TextChoices):
        ACTIVE = 'active', 'Activa'
        AI_PAUSED = 'ai_paused', 'IA Pausada'
        CLOSED = 'closed', 'Cerrada'
        ESCALATED = 'escalated', 'Escalada'

    class ChannelChoices(models.TextChoices):
        WHATSAPP = 'whatsapp', 'WhatsApp'
        INSTAGRAM = 'instagram', 'Instagram'
        MESSENGER = 'messenger', 'Messenger'

    channel = models.CharField(
        max_length=15, choices=ChannelChoices.choices,
        default=ChannelChoices.WHATSAPP, db_index=True,
        help_text="Canal de comunicación"
    )
    wa_id = models.CharField(
        max_length=50, db_index=True,
        help_text="ID del contacto: número WA (51XXX), IGSID (Instagram), o PSID (Messenger)"
    )
    wa_profile_name = models.CharField(max_length=150, null=True, blank=True)
    client = models.ForeignKey(
        'clients.Clients', on_delete=models.SET_NULL,
        null=True, blank=True, related_name='chat_sessions',
        help_text="Vinculación automática con cliente"
    )
    status = models.CharField(
        max_length=15, choices=StatusChoices.choices,
        default=StatusChoices.ACTIVE
    )
    ai_enabled = models.BooleanField(default=True)
    ai_paused_at = models.DateTimeField(null=True, blank=True)
    ai_paused_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.SET_NULL,
        null=True, blank=True, related_name='paused_sessions'
    )
    ai_resume_at = models.DateTimeField(null=True, blank=True)
    current_intent = models.CharField(max_length=100, null=True, blank=True)
    conversation_context = models.JSONField(default=dict, blank=True)
    total_messages = models.PositiveIntegerField(default=0)
    ai_messages = models.PositiveIntegerField(default=0)
    human_messages = models.PositiveIntegerField(default=0)
    last_message_at = models.DateTimeField(null=True, blank=True)
    last_customer_message_at = models.DateTimeField(null=True, blank=True)
    last_read_at = models.DateTimeField(
        null=True, blank=True,
        help_text="Última vez que un admin leyó esta conversación"
    )
    quoted_at = models.DateTimeField(
        null=True, blank=True,
        help_text="Cuándo se envió la primera cotización"
    )
    followup_sent_at = models.DateTimeField(
        null=True, blank=True,
        help_text="Cuándo se envió el último follow-up automático"
    )
    followup_count = models.PositiveIntegerField(
        default=0,
        help_text="Cantidad de follow-ups enviados"
    )
    client_was_new = models.BooleanField(
        null=True, blank=True, default=None,
        help_text="True si el cliente no existía cuando inició el chat"
    )
    last_notify_at = models.DateTimeField(
        null=True, blank=True,
        help_text="Última vez que se envió notify_team para esta sesión"
    )

    class Meta:
        verbose_name = '💬 Sesión de Chat'
        verbose_name_plural = '💬 Sesiones de Chat'
        ordering = ['-last_message_at']

    def __str__(self):
        name = self.wa_profile_name or self.wa_id
        return f"Chat con {name} ({self.get_status_display()})"


    @staticmethod
    def register_outbound_template(phone_number, content, intent, client=None):
        """Registra un mensaje de plantilla saliente en el historial de chat."""
        try:
            digits = re.sub(r'\D', '', phone_number)
            variants = {digits}
            if digits.startswith('51') and len(digits) > 9:
                variants.add(digits[2:])
            elif len(digits) == 9:
                variants.add(f'51{digits}')

            session = ChatSession.objects.filter(
                wa_id__in=list(variants),
                channel='whatsapp',
                deleted=False,
            ).order_by('-last_message_at').first()

            if not session and client:
                session = ChatSession.objects.create(
                    channel='whatsapp',
                    wa_id=digits,
                    wa_profile_name=client.first_name or '',
                    client=client,
                    status='active',
                    ai_enabled=True,
                )

            if not session:
                logger.warning(
                    f"register_outbound_template: no se encontró sesión para {digits} y no hay client para crearla"
                )
                return None

            # Vincular client si la sesión no lo tiene
            if client and not session.client:
                session.client = client
                session.save(update_fields=['client'])

            msg = ChatMessage.objects.create(
                session=session,
                direction='system',
                message_type='text',
                content=content,
                intent_detected=intent,
            )

            session.total_messages += 1
            session.last_message_at = timezone.now()
            session.save(update_fields=['total_messages', 'last_message_at'])

            return msg
        except Exception as e:
            logger.error(f"register_outbound_template error: {e}")
            return None


class ChatMessage(BaseModel):
    """Mensaje individual de una sesión de chat"""

    class DirectionChoices(models.TextChoices):
        INBOUND = 'inbound', 'Entrante (Cliente)'
        OUTBOUND_AI = 'outbound_ai', 'Saliente (IA)'
        OUTBOUND_HUMAN = 'outbound_human', 'Saliente (Humano)'
        SYSTEM = 'system', 'Sistema'

    class MessageTypeChoices(models.TextChoices):
        TEXT = 'text', 'Texto'
        IMAGE = 'image', 'Imagen'
        AUDIO = 'audio', 'Audio'
        DOCUMENT = 'document', 'Documento'
        LOCATION = 'location', 'Ubicación'
        INTERACTIVE = 'interactive', 'Interactivo'

    session = models.ForeignKey(
        ChatSession, on_delete=models.CASCADE,
        related_name='messages'
    )
    direction = models.CharField(
        max_length=15, choices=DirectionChoices.choices
    )
    message_type = models.CharField(
        max_length=15, choices=MessageTypeChoices.choices,
        default=MessageTypeChoices.TEXT
    )
    content = models.TextField()
    media_url = models.URLField(null=True, blank=True)
    wa_message_id = models.CharField(
        max_length=500, unique=True, null=True, blank=True,
        help_text="ID del mensaje (WhatsApp/Instagram/Messenger) para idempotencia"
    )
    wa_status = models.CharField(
        max_length=15, null=True, blank=True,
        help_text="sent/delivered/read/failed"
    )
    intent_detected = models.CharField(max_length=100, null=True, blank=True)
    confidence_score = models.FloatField(null=True, blank=True)
    ai_model = models.CharField(max_length=50, null=True, blank=True)
    tokens_used = models.PositiveIntegerField(default=0)
    tool_calls = models.JSONField(
        default=list, blank=True,
        help_text="Herramientas usadas por la IA"
    )
    sent_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.SET_NULL,
        null=True, blank=True, related_name='sent_chat_messages',
        help_text="Admin que envió mensaje manual"
    )

    class Meta:
        verbose_name = '📝 Mensaje de Chat'
        verbose_name_plural = '📝 Mensajes de Chat'
        ordering = ['created']

    def __str__(self):
        preview = self.content[:50] + '...' if len(self.content) > 50 else self.content
        return f"[{self.get_direction_display()}] {preview}"


class ChatbotConfiguration(BaseModel):
    """Configuración global del chatbot (singleton)"""

    is_active = models.BooleanField(default=True)
    system_prompt = models.TextField(
        default="Eres un asistente virtual de Casa Austin, un servicio de alquiler de casas vacacionales en Lima, Perú.",
        help_text="Prompt de sistema para la IA"
    )
    primary_model = models.CharField(
        max_length=50, default='gpt-4.1-nano'
    )
    fallback_model = models.CharField(
        max_length=50, default='gpt-4o-mini'
    )
    temperature = models.FloatField(default=0.7)
    max_tokens_per_response = models.PositiveIntegerField(default=700)
    ai_auto_resume_minutes = models.PositiveIntegerField(
        default=30,
        help_text="Minutos para reactivar IA automáticamente tras pausa"
    )
    business_hours_start = models.TimeField(
        null=True, blank=True, help_text="Inicio horario de atención"
    )
    business_hours_end = models.TimeField(
        null=True, blank=True, help_text="Fin horario de atención"
    )
    out_of_hours_message = models.TextField(
        default="Gracias por contactarnos. Nuestro horario de atención es de 8am a 10pm. Te responderemos pronto.",
        blank=True
    )
    escalation_keywords = models.JSONField(
        default=list, blank=True,
        help_text=(
            "Palabras clave que PAUSAN la IA y escalan a humano "
            "(usar para reclamos/quejas/emergencias). Lista de strings. "
            "Match es case-insensitive por substring."
        )
    )
    callback_keywords = models.JSONField(
        default=list, blank=True,
        help_text=(
            "Palabras clave que NOTIFICAN al equipo pero la IA sigue respondiendo "
            "(usar para pedidos de llamada). Lista de strings. "
            "Match es case-insensitive por substring."
        )
    )
    max_consecutive_ai_messages = models.PositiveIntegerField(
        default=10,
        help_text="Máximo de respuestas IA consecutivas antes de escalar"
    )

    class Meta:
        verbose_name = '⚙️ Configuración del Chatbot'
        verbose_name_plural = '⚙️ Configuración del Chatbot'

    def __str__(self):
        status = "Activo" if self.is_active else "Inactivo"
        return f"Chatbot Config ({status}) - {self.primary_model}"

    def save(self, *args, **kwargs):
        # Singleton: solo puede haber un registro
        if not self.pk and ChatbotConfiguration.objects.exists():
            existing = ChatbotConfiguration.objects.first()
            self.pk = existing.pk
        super().save(*args, **kwargs)

    @classmethod
    def get_config(cls):
        config, _ = cls.objects.get_or_create(
            defaults={'is_active': True}
        )
        return config


class PropertyVisit(BaseModel):
    """Visita programada a una propiedad vía chatbot"""

    class StatusChoices(models.TextChoices):
        SCHEDULED = 'scheduled', 'Programada'
        COMPLETED = 'completed', 'Realizada'
        CANCELLED = 'cancelled', 'Cancelada'
        NO_SHOW = 'no_show', 'No asistió'

    session = models.ForeignKey(
        ChatSession, on_delete=models.CASCADE,
        related_name='visits',
        help_text="Sesión de chat donde se agendó"
    )
    property = models.ForeignKey(
        'property.Property', on_delete=models.CASCADE,
        related_name='chat_visits'
    )
    client = models.ForeignKey(
        'clients.Clients', on_delete=models.SET_NULL,
        null=True, blank=True, related_name='chat_visits',
        help_text="Cliente vinculado (si fue identificado)"
    )
    visit_date = models.DateField(help_text="Fecha de la visita")
    visit_time = models.TimeField(
        null=True, blank=True,
        help_text="Hora preferida de la visita"
    )
    visitor_name = models.CharField(
        max_length=150,
        help_text="Nombre del visitante (del perfil WA o proporcionado)"
    )
    visitor_phone = models.CharField(
        max_length=20,
        help_text="Teléfono del visitante"
    )
    guests_count = models.PositiveIntegerField(
        default=1,
        help_text="Cantidad de personas que asistirán a la visita"
    )
    notes = models.TextField(
        blank=True, default='',
        help_text="Notas adicionales del cliente"
    )
    status = models.CharField(
        max_length=15, choices=StatusChoices.choices,
        default=StatusChoices.SCHEDULED
    )

    class Meta:
        verbose_name = '🏠 Visita Programada'
        verbose_name_plural = '🏠 Visitas Programadas'
        ordering = ['-visit_date', '-visit_time']

    def __str__(self):
        return f"Visita a {self.property} - {self.visit_date} - {self.visitor_name}"


class PromoDateConfig(BaseModel):
    """Configuración para promos automáticas por fechas buscadas (singleton)"""

    is_active = models.BooleanField(default=False, help_text="Activar/desactivar envío automático de promos")
    days_before_checkin = models.PositiveIntegerField(
        default=3,
        help_text="Días antes del check-in para enviar la promo"
    )
    discount_config = models.ForeignKey(
        'property.DynamicDiscountConfig', on_delete=models.SET_NULL,
        null=True, blank=True, related_name='promo_date_configs',
        help_text="Configuración de descuento dinámico a usar para generar códigos"
    )
    wa_template_name = models.CharField(
        max_length=100, default='promo_fecha_disponible',
        help_text="Nombre de la plantilla aprobada en Meta"
    )
    wa_template_language = models.CharField(
        max_length=10, default='es',
        help_text="Código de idioma de la plantilla"
    )
    max_promos_per_client = models.PositiveIntegerField(
        default=1,
        help_text="Máximo de promos por cliente para una misma fecha"
    )
    min_search_count = models.PositiveIntegerField(
        default=1,
        help_text="Mínimo de búsquedas para calificar"
    )
    send_hour = models.TimeField(
        default='09:00',
        help_text="Hora del día para envío de promos"
    )
    exclude_recent_chatters = models.BooleanField(
        default=True,
        help_text="Excluir clientes con chat activo en las últimas 24h"
    )

    class Meta:
        verbose_name = '🎯 Config Promo por Fechas'
        verbose_name_plural = '🎯 Config Promo por Fechas'

    def __str__(self):
        status = "Activo" if self.is_active else "Inactivo"
        return f"Promo Fechas ({status}) - {self.days_before_checkin} días antes"

    def save(self, *args, **kwargs):
        if not self.pk and PromoDateConfig.objects.exists():
            existing = PromoDateConfig.objects.first()
            self.pk = existing.pk
        super().save(*args, **kwargs)

    @classmethod
    def get_config(cls):
        config, _ = cls.objects.get_or_create(
            defaults={'is_active': False}
        )
        return config


class PromoDateSent(BaseModel):
    """Registro de promos enviadas para evitar duplicados"""

    class StatusChoices(models.TextChoices):
        SENT = 'sent', 'Enviado'
        DELIVERED = 'delivered', 'Entregado'
        READ = 'read', 'Leído'
        CONVERTED = 'converted', 'Convertido'
        FAILED = 'failed', 'Fallido'

    client = models.ForeignKey(
        'clients.Clients', on_delete=models.CASCADE,
        null=True, blank=True,
        related_name='promo_dates_sent'
    )
    check_in_date = models.DateField()
    check_out_date = models.DateField()
    guests = models.PositiveIntegerField()
    discount_code = models.ForeignKey(
        'property.DiscountCode', on_delete=models.SET_NULL,
        null=True, blank=True, related_name='promo_dates'
    )
    wa_message_id = models.CharField(max_length=500, null=True, blank=True)
    session = models.ForeignKey(
        ChatSession, on_delete=models.SET_NULL,
        null=True, blank=True, related_name='promo_dates'
    )
    message_content = models.TextField(
        blank=True, default='',
        help_text="Contenido/parámetros enviados"
    )
    pricing_snapshot = models.JSONField(
        default=dict, blank=True,
        help_text="Precios al momento del envío"
    )
    status = models.CharField(
        max_length=15, choices=StatusChoices.choices,
        default=StatusChoices.SENT
    )

    class Meta:
        verbose_name = '📨 Promo Enviada'
        verbose_name_plural = '📨 Promos Enviadas'
        ordering = ['-created']

    def __str__(self):
        return f"Promo a {self.client} - {self.check_in_date} ({self.status})"


class PromoBirthdayConfig(BaseModel):
    """Configuración para promos automáticas de cumpleaños (singleton)"""

    is_active = models.BooleanField(default=False, help_text="Activar/desactivar envío automático de promos de cumpleaños")
    days_before_birthday = models.PositiveIntegerField(
        default=15,
        help_text="Días antes del cumpleaños para enviar la promo"
    )
    birthday_discount_percentage = models.PositiveIntegerField(
        default=10,
        help_text="% de descuento de cumpleaños que se envía en la plantilla"
    )
    wa_template_name = models.CharField(
        max_length=100, default='cumpleanos_cliente',
        help_text="Nombre de la plantilla aprobada en Meta"
    )
    wa_template_language = models.CharField(
        max_length=10, default='es',
        help_text="Código de idioma de la plantilla"
    )
    send_hour = models.TimeField(
        default='09:00',
        help_text="Hora del día para envío de promos"
    )

    class Meta:
        verbose_name = '🎂 Config Promo Cumpleaños'
        verbose_name_plural = '🎂 Config Promo Cumpleaños'

    def __str__(self):
        status = "Activo" if self.is_active else "Inactivo"
        return f"Promo Cumpleaños ({status}) - {self.days_before_birthday} días antes, {self.birthday_discount_percentage}% desc"

    def save(self, *args, **kwargs):
        if not self.pk and PromoBirthdayConfig.objects.exists():
            existing = PromoBirthdayConfig.objects.first()
            self.pk = existing.pk
        super().save(*args, **kwargs)

    @classmethod
    def get_config(cls):
        config, _ = cls.objects.get_or_create(
            defaults={'is_active': False}
        )
        return config


class PromoBirthdaySent(BaseModel):
    """Registro de promos de cumpleaños enviadas para evitar duplicados"""

    class StatusChoices(models.TextChoices):
        SENT = 'sent', 'Enviado'
        FAILED = 'failed', 'Fallido'

    client = models.ForeignKey(
        'clients.Clients', on_delete=models.CASCADE,
        related_name='promo_birthdays_sent'
    )
    year = models.PositiveIntegerField(help_text="Año del cumpleaños para el que se envió")
    wa_message_id = models.CharField(max_length=500, null=True, blank=True)
    status = models.CharField(
        max_length=10, choices=StatusChoices.choices,
        default=StatusChoices.SENT
    )

    class Meta:
        verbose_name = '🎂 Promo Cumpleaños Enviada'
        verbose_name_plural = '🎂 Promos Cumpleaños Enviadas'
        ordering = ['-created']
        unique_together = ('client', 'year')

    def __str__(self):
        return f"Promo cumpleaños a {self.client} - {self.year} ({self.status})"


class ChatAnalysisCheckpoint(BaseModel):
    """Checkpoint (watermark) para análisis incremental de conversaciones.
    Guarda hasta dónde se revisó en el último análisis."""

    last_analyzed_message_id = models.PositiveIntegerField(
        help_text="ID numérico del último mensaje analizado"
    )
    last_analyzed_session_id = models.PositiveIntegerField(
        help_text="ID numérico de la última sesión analizada"
    )
    last_analyzed_at = models.DateTimeField(
        help_text="Timestamp del análisis"
    )
    total_sessions_analyzed = models.PositiveIntegerField(default=0)
    total_messages_analyzed = models.PositiveIntegerField(default=0)
    notes = models.TextField(blank=True, default='')

    class Meta:
        verbose_name = '📌 Checkpoint de Análisis'
        verbose_name_plural = '📌 Checkpoints de Análisis'
        ordering = ['-last_analyzed_at']

    def __str__(self):
        return f"Checkpoint {self.last_analyzed_at:%Y-%m-%d %H:%M} — {self.total_sessions_analyzed} sesiones"


class ChatAnalytics(BaseModel):
    """Métricas diarias del chatbot"""

    date = models.DateField(unique=True)
    total_sessions = models.PositiveIntegerField(default=0)
    new_sessions = models.PositiveIntegerField(default=0)
    total_messages_in = models.PositiveIntegerField(default=0)
    total_messages_out_ai = models.PositiveIntegerField(default=0)
    total_messages_out_human = models.PositiveIntegerField(default=0)
    escalations = models.PositiveIntegerField(default=0)
    intents_breakdown = models.JSONField(default=dict, blank=True)
    total_tokens_input = models.PositiveIntegerField(default=0)
    total_tokens_output = models.PositiveIntegerField(default=0)
    estimated_cost_usd = models.DecimalField(
        max_digits=10, decimal_places=4, default=0
    )
    reservations_created = models.PositiveIntegerField(default=0)
    clients_identified = models.PositiveIntegerField(default=0)
    bot_leads = models.PositiveIntegerField(
        default=0,
        help_text="Clientes nuevos generados por el bot"
    )
    bot_conversions = models.PositiveIntegerField(
        default=0,
        help_text="Reservas de clientes nuevos del bot"
    )
    returning_client_reservations = models.PositiveIntegerField(
        default=0,
        help_text="Reservas de clientes existentes que chatearon"
    )

    class Meta:
        verbose_name = '📊 Analítica del Chat'
        verbose_name_plural = '📊 Analíticas del Chat'
        ordering = ['-date']

    def __str__(self):
        return f"Analytics {self.date} - {self.total_messages_in + self.total_messages_out_ai} msgs"


class UnresolvedQuestion(BaseModel):
    """Preguntas que el bot no pudo responder, para revisar y alimentar el prompt."""

    class StatusChoices(models.TextChoices):
        PENDING = 'pending', 'Pendiente'
        RESOLVED = 'resolved', 'Resuelta'
        IGNORED = 'ignored', 'Ignorada'

    session = models.ForeignKey(
        ChatSession, on_delete=models.CASCADE,
        related_name='unresolved_questions',
    )
    question = models.TextField(
        help_text="La pregunta o consulta que el bot no pudo resolver"
    )
    context = models.TextField(
        blank=True, default='',
        help_text="Contexto de la conversación al momento de la pregunta"
    )
    category = models.CharField(
        max_length=50, blank=True, default='',
        help_text="Categoría: pricing, policy, property_info, service, other"
    )
    status = models.CharField(
        max_length=15, choices=StatusChoices.choices,
        default=StatusChoices.PENDING,
    )
    resolution = models.TextField(
        blank=True, default='',
        help_text="Respuesta correcta para alimentar al bot"
    )

    class Meta:
        verbose_name = '❓ Pregunta sin resolver'
        verbose_name_plural = '❓ Preguntas sin resolver'
        ordering = ['-created']

    def __str__(self):
        return f"{self.question[:60]}... ({self.status})"


class ReviewRequestConfig(BaseModel):
    """Configuración para review requests post-estadía (singleton)"""

    is_active = models.BooleanField(
        default=False,
        help_text="Activar/desactivar envío automático de review requests"
    )
    google_review_url = models.URLField(
        default='https://g.page/r/CcNlH9Rd7qyqEBM/review',
        help_text="URL de Google Reviews"
    )
    wa_template_name = models.CharField(
        max_length=100, default='post_stay_level_update',
        help_text="Nombre de la plantilla aprobada en Meta"
    )
    wa_template_language = models.CharField(
        max_length=10, default='es',
        help_text="Código de idioma de la plantilla"
    )

    class Meta:
        verbose_name = '⭐ Config Review Post-Estadía'
        verbose_name_plural = '⭐ Config Review Post-Estadía'

    def __str__(self):
        status = "Activo" if self.is_active else "Inactivo"
        return f"Review Request Config ({status})"

    def save(self, *args, **kwargs):
        if not self.pk and ReviewRequestConfig.objects.exists():
            existing = ReviewRequestConfig.objects.first()
            self.pk = existing.pk
        super().save(*args, **kwargs)

    @classmethod
    def get_config(cls):
        config, _ = cls.objects.get_or_create(
            defaults={'is_active': False}
        )
        return config


class ReviewRequest(BaseModel):
    """Tracking de review request por reserva"""

    class StatusChoices(models.TextChoices):
        SENT = 'sent', 'Template enviado'
        BENEFITS_VIEWED = 'benefits_viewed', 'Vio beneficios'
        RATING_POSITIVE = 'rating_positive', 'Rating positivo (4-5)'
        RATING_NEGATIVE = 'rating_negative', 'Rating negativo'
        FEEDBACK_RECEIVED = 'feedback_received', 'Feedback recibido'
        REVIEW_LINK_SENT = 'review_link_sent', 'Link Google enviado'
        FAILED = 'failed', 'Error al enviar'

    client = models.ForeignKey(
        'clients.Clients', on_delete=models.CASCADE,
        related_name='review_requests'
    )
    reservation = models.OneToOneField(
        'reservation.Reservation', on_delete=models.CASCADE,
        related_name='review_request',
        help_text="Una review request por reserva"
    )
    session = models.ForeignKey(
        ChatSession, on_delete=models.SET_NULL,
        null=True, blank=True, related_name='review_requests'
    )
    wa_message_id = models.CharField(
        max_length=500, null=True, blank=True,
        help_text="ID del template enviado"
    )
    status = models.CharField(
        max_length=20, choices=StatusChoices.choices,
        default=StatusChoices.SENT
    )
    rating = models.PositiveSmallIntegerField(
        null=True, blank=True,
        help_text="Rating del cliente (1-5)"
    )
    feedback_text = models.TextField(
        blank=True, default='',
        help_text="Feedback del cliente si calificó negativo"
    )
    achievement_at_send = models.CharField(
        max_length=100, blank=True, default='',
        help_text="Nivel del cliente al momento del envío"
    )
    review_retries = models.PositiveSmallIntegerField(
        default=0,
        help_text="Reintentos de botones tras texto libre (máx 2)"
    )

    class Meta:
        verbose_name = '⭐ Review Request'
        verbose_name_plural = '⭐ Review Requests'
        ordering = ['-created']

    def __str__(self):
        return f"Review {self.client} - {self.reservation} ({self.get_status_display()})"
