"""
Envía follow-ups automáticos a conversaciones sin conversión.

Dos tipos de follow-up:
1. SIN COTIZACIÓN: Cliente escribió hace 2-22h pero nunca recibió cotización.
   → Enviar nudge para que dé sus fechas.
2. CON COTIZACIÓN: Cliente recibió cotización hace 4-22h pero no reservó.
   → Enviar mensaje de cierre/oferta para convertir.

La ventana de WhatsApp es 24h desde el último mensaje del cliente.
Se respeta un máximo de 1 follow-up por sesión.

Uso: python manage.py send_followups
Cron recomendado: cada 2 horas (8am-10pm)
"""
import logging
from datetime import timedelta

from django.core.management.base import BaseCommand
from django.utils import timezone

from apps.chatbot.models import ChatSession, ChatMessage, ChatbotConfiguration
from apps.chatbot.channel_sender import get_sender
from apps.chatbot.ai_orchestrator import AIOrchestrator

logger = logging.getLogger(__name__)


FOLLOWUP_NO_QUOTE_PROMPT = (
    "Eres Austin Bot. Este cliente escribió hace unas horas pero no se concretó "
    "una cotización. Analiza el historial para entender POR QUÉ:\n\n"
    "ESCENARIO A — El cliente NO dio fechas (conversación se cortó o fue genérica):\n"
    "→ Retoma pidiendo fechas amigablemente.\n"
    "→ Ejemplo: '¡Hola de nuevo! 😊 ¿Ya tienes fechas en mente? Te cotizo al instante 🏖️'\n\n"
    "ESCENARIO B — El cliente SÍ dio fechas pero NO había disponibilidad:\n"
    "→ NO pidas fechas de nuevo (ya las dio).\n"
    "→ Reconoce que las fechas que buscó estaban ocupadas.\n"
    "→ Sugiere alternativas: otros fines de semana, fechas entre semana, o que te diga otras fechas.\n"
    "→ Ejemplo: '¡Hola [nombre]! 😊 Vi que las fechas que buscabas estaban ocupadas. "
    "¿Te gustaría que revise otros fines de semana cercanos? Tenemos buena disponibilidad "
    "para [sugerir fechas genéricas] 🏖️'\n\n"
    "ESCENARIO C — El cliente dio fechas y personas, pero la conversación se cortó "
    "antes de poder cotizar:\n"
    "→ NO repitas preguntas ya respondidas.\n"
    "→ Retoma desde donde se quedó.\n"
    "→ Ejemplo: '¡Hola! 😊 Me quedé con ganas de enviarte la cotización. "
    "¿Sigues interesado para esas fechas?'\n\n"
    "Reglas GENERALES:\n"
    "- Máximo 2-3 líneas\n"
    "- Tono cálido, no insistente ni spam\n"
    "- NUNCA pidas información que el cliente YA proporcionó en el historial\n"
    "- Referencia algo específico del historial (fechas, personas, ocasión)\n"
    "- NO uses herramientas, solo responde con texto\n"
)

FOLLOWUP_QUOTED_PROMPT = (
    "Eres Austin Bot. Este cliente recibió una cotización hace unas horas pero "
    "aún no ha reservado. Escribe UN SOLO mensaje corto para incentivarlo a reservar.\n\n"
    "Reglas:\n"
    "- Máximo 3-4 líneas\n"
    "- Tono amigable, genera urgencia suave (sin presionar)\n"
    "- Menciona que las fechas se agotan rápido si aplica\n"
    "- Recuerda que reservar es fácil (web + 50% adelanto)\n"
    "- Ofrece resolver dudas\n"
    "- NO uses herramientas, solo responde con texto\n"
    "- NO repitas la cotización completa\n\n"
    "Ejemplos:\n"
    "- '¡Hola! 😊 ¿Pudiste revisar la cotización? Las fechas en Playa Los Pulpos "
    "se van rápido ⚡ Si tienes alguna duda, aquí estoy. Reservar es súper fácil en "
    "casaaustin.pe 🏖️'\n"
    "- 'Hey! Solo quería recordarte que tu cotización sigue vigente 😊 "
    "¿Necesitas que aclare algo? Puedes separar tu fecha con solo el 50% de adelanto.'"
)


class Command(BaseCommand):
    help = 'Envía follow-ups automáticos a conversaciones sin conversión'

    def add_arguments(self, parser):
        parser.add_argument(
            '--dry-run', action='store_true',
            help='Solo muestra qué haría, sin enviar mensajes'
        )

    def handle(self, *args, **options):
        dry_run = options['dry_run']
        config = ChatbotConfiguration.get_config()

        if not config.is_active:
            self.stdout.write('Chatbot inactivo, saltando follow-ups.')
            return

        now = timezone.now()
        # Ventana: mensajes del cliente entre 2h y 22h atrás
        # (2h mínimo para no ser invasivo, 22h para respetar ventana 24h de WA)
        min_age = now - timedelta(hours=22)
        max_age_no_quote = now - timedelta(hours=2)
        max_age_quoted = now - timedelta(hours=4)

        sent_no_quote = 0
        sent_quoted = 0

        # === 1. Sesiones SIN cotización ===
        no_quote_sessions = ChatSession.objects.filter(
            deleted=False,
            status__in=['active', 'ai_paused'],
            ai_enabled=True,
            quoted_at__isnull=True,
            followup_count=0,
            last_customer_message_at__isnull=False,
            last_customer_message_at__gte=min_age,
            last_customer_message_at__lte=max_age_no_quote,
            total_messages__gte=2,  # Al menos 1 ida y vuelta
        )

        for session in no_quote_sessions:
            name = session.wa_profile_name or session.wa_id
            if dry_run:
                self.stdout.write(f'[DRY] Sin cotización: {name} — último msg cliente: {session.last_customer_message_at}')
                sent_no_quote += 1
                continue

            try:
                self._send_followup(session, config, 'no_quote')
                sent_no_quote += 1
                self.stdout.write(f'  Enviado a {name}')
            except Exception as e:
                logger.error(f"Error enviando follow-up sin cotización a {session.wa_id}: {e}")
                self.stdout.write(self.style.ERROR(f'  Error con {name}: {e}'))

        # === 2. Sesiones CON cotización pero sin conversión ===
        quoted_sessions = ChatSession.objects.filter(
            deleted=False,
            status__in=['active', 'ai_paused'],
            ai_enabled=True,
            quoted_at__isnull=False,
            followup_count=0,
            last_customer_message_at__isnull=False,
            last_customer_message_at__gte=min_age,
            quoted_at__lte=max_age_quoted,
        )

        for session in quoted_sessions:
            name = session.wa_profile_name or session.wa_id
            if dry_run:
                self.stdout.write(f'[DRY] Cotizada sin conversión: {name} — cotizada: {session.quoted_at}')
                sent_quoted += 1
                continue

            try:
                self._send_followup(session, config, 'quoted')
                sent_quoted += 1
                self.stdout.write(f'  Enviado a {name}')
            except Exception as e:
                logger.error(f"Error enviando follow-up cotizado a {session.wa_id}: {e}")
                self.stdout.write(self.style.ERROR(f'  Error con {name}: {e}'))

        action = 'Enviaría' if dry_run else 'Enviados'
        self.stdout.write(self.style.SUCCESS(
            f'{action}: {sent_no_quote} follow-ups sin cotización, '
            f'{sent_quoted} follow-ups post-cotización.'
        ))

    def _send_followup(self, session, config, followup_type):
        """Genera y envía un mensaje de follow-up usando IA"""
        import openai
        from django.conf import settings

        client = openai.OpenAI(api_key=settings.OPENAI_API_KEY)

        # Obtener últimos mensajes para contexto
        recent_msgs = ChatMessage.objects.filter(
            session=session, deleted=False
        ).order_by('-created')[:10]

        messages = []
        if followup_type == 'no_quote':
            messages.append({"role": "system", "content": FOLLOWUP_NO_QUOTE_PROMPT})
        else:
            messages.append({"role": "system", "content": FOLLOWUP_QUOTED_PROMPT})

        # Agregar historial como contexto
        history = ""
        for msg in reversed(list(recent_msgs)):
            direction = {
                'inbound': 'Cliente',
                'outbound_ai': 'IA',
                'outbound_human': 'Admin',
            }.get(msg.direction, 'Sistema')
            history += f"[{direction}]: {msg.content[:200]}\n"

        name = session.wa_profile_name or session.wa_id
        messages.append({
            "role": "user",
            "content": f"Contacto: {name}\nHistorial:\n{history}\n\nGenera el mensaje de follow-up."
        })

        response = client.chat.completions.create(
            model=config.primary_model,
            messages=messages,
            temperature=0.8,
            max_tokens=200,
        )

        followup_text = response.choices[0].message.content or ""
        if not followup_text.strip():
            return

        # Enviar por el canal correspondiente
        sender = get_sender(session.channel)
        wa_message_id = sender.send_text_message(session.wa_id, followup_text)

        # Guardar mensaje
        ChatMessage.objects.create(
            session=session,
            direction=ChatMessage.DirectionChoices.OUTBOUND_AI,
            message_type=ChatMessage.MessageTypeChoices.TEXT,
            content=followup_text,
            wa_message_id=wa_message_id,
            ai_model=config.primary_model,
            intent_detected=f'followup_{followup_type}',
        )

        # Actualizar sesión
        now = timezone.now()
        session.followup_sent_at = now
        session.followup_count += 1
        session.total_messages += 1
        session.ai_messages += 1
        session.last_message_at = now
        session.save(update_fields=[
            'followup_sent_at', 'followup_count',
            'total_messages', 'ai_messages', 'last_message_at',
        ])

        logger.info(
            f"Follow-up ({followup_type}) enviado a {session.wa_id}: "
            f"{followup_text[:80]}..."
        )
