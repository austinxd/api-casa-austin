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
    "aún no ha reservado. Escribe UN SOLO mensaje corto para incentivar la conversión.\n\n"
    "ANALIZA EL HISTORIAL para personalizar tu follow-up:\n"
    "- ¿Qué casa le interesó? ¿Para cuántas personas? ¿Qué fechas?\n"
    "- ¿Hubo alguna duda sin resolver? (precio, servicios, ubicación)\n"
    "- ¿Mencionó alguna ocasión especial? (cumpleaños, fiesta, viaje familiar)\n"
    "- ¿Mostró objeción de precio o pidió pensarlo?\n\n"
    "SEGÚN EL CONTEXTO, elige UN enfoque (NO los combines todos):\n"
    "1. DUDA PENDIENTE → Retoma la duda: '¿Pudiste aclarar lo de [tema]?'\n"
    "2. OCASIÓN ESPECIAL → Referencia la ocasión: 'Para tu [cumpleaños/evento], todo listo en Casa Austin'\n"
    "3. VALOR → Calcula precio por persona si aplica: 'Dividido entre X personas sale a S/Y cada uno'\n"
    "4. FACILIDAD → Enfoca en lo fácil: 'Solo necesitas el 50% de adelanto para separar tu fecha'\n"
    "5. PREGUNTA ABIERTA → Si no hay contexto claro: '¿Tienes alguna duda sobre la cotización?'\n\n"
    "Reglas:\n"
    "- Máximo 3-4 líneas\n"
    "- VARÍA tu enfoque. NO siempre digas 'las fechas se llenan rápido'\n"
    "- Menciona algo ESPECÍFICO del historial (la casa, las fechas, el motivo)\n"
    "- Si el cliente ya dijo que va a pensarlo, NO insistas. Solo deja la puerta abierta.\n"
    "- NO uses herramientas, solo responde con texto\n"
    "- NO repitas la cotización completa\n"
    "- NO uses frases genéricas como 'solo quería recordarte' sin agregar valor específico\n"
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
        skipped = 0

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

            # Saltar si un admin ya intervino o si el cliente tiene reserva activa
            skip_reason = self._should_skip(session)
            if skip_reason:
                skipped += 1
                if dry_run:
                    self.stdout.write(f'[SKIP] {name}: {skip_reason}')
                continue

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

            # Saltar si un admin ya intervino o si el cliente tiene reserva activa
            skip_reason = self._should_skip(session)
            if skip_reason:
                skipped += 1
                if dry_run:
                    self.stdout.write(f'[SKIP] {name}: {skip_reason}')
                continue

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
            f'{sent_quoted} follow-ups post-cotización. '
            f'Saltados: {skipped}.'
        ))

    def _should_skip(self, session):
        """Verifica si la sesión debe ser excluida del follow-up.

        Returns:
            str con la razón si debe saltarse, None si está ok.
        """
        from apps.reservation.models import Reservation
        from datetime import date as date_type

        # 1. Saltar si un admin ya respondió en esta sesión
        has_admin_msg = ChatMessage.objects.filter(
            session=session,
            deleted=False,
            direction=ChatMessage.DirectionChoices.OUTBOUND_HUMAN,
        ).exists()
        if has_admin_msg:
            return 'admin ya intervino en la conversación'

        # 2. Saltar si el cliente tiene reserva activa (aprobada/pendiente)
        if session.client:
            has_active_reservation = Reservation.objects.filter(
                client=session.client,
                deleted=False,
                status__in=['approved', 'pending', 'incomplete'],
                check_out_date__gte=date_type.today(),
            ).exists()
            if has_active_reservation:
                return 'cliente tiene reserva activa'

        return None

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
