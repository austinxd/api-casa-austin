"""
Rescate rápido a conversaciones frías 25-90 min después de la cotización.

Detecta el patrón:
- Sesión recibió cotización hace 25-90 minutos
- El cliente NO ha respondido después de la cotización
- No se le envió rescate aún (se trackea vía conversation_context)

Envía UN mensaje de intervención rápida, ANTES del follow-up de 4h, para
recuperar al cliente mientras aún recuerda la conversación.

Análisis de 179 conversaciones recientes mostró que 56% quedan frías
post-cotización. El follow-up de 4h es demasiado tarde (ya se enfriaron).

Uso: python manage.py send_quick_rescue
Cron recomendado: cada 15 minutos (8am-21pm Lima)
"""
import logging
from datetime import timedelta

from django.core.management.base import BaseCommand
from django.utils import timezone

from apps.chatbot.models import ChatSession, ChatMessage, ChatbotConfiguration
from apps.chatbot.channel_sender import get_sender

logger = logging.getLogger(__name__)


QUICK_RESCUE_PROMPT = (
    "Eres Austin Bot. Este cliente recibió una cotización de casa de playa hace "
    "aproximadamente 30-60 minutos pero aún no ha respondido. Es un rescate "
    "RÁPIDO — todavía tiene la conversación en mente.\n\n"
    "Objetivo: recuperar la conversación de forma AMIGABLE y NO invasiva, "
    "preguntando qué lo detiene o qué necesita para decidir.\n\n"
    "ANALIZA EL HISTORIAL para personalizar:\n"
    "- ¿Qué casa(s) se cotizó? ¿Cuántas personas? ¿Qué fechas?\n"
    "- ¿Mencionó alguna ocasión (cumpleaños, fiesta, descanso familiar)?\n"
    "- ¿Quedó alguna pregunta sin responder?\n"
    "- ¿Dio señales de estar comparando?\n\n"
    "ELIGE UNO de estos enfoques (NO los combines):\n\n"
    "A. PREGUNTA DIRECTA sobre bloqueo (mi favorito, úsalo 50% del tiempo):\n"
    "   '¿Hay algo específico que te detiene para reservar? Te ayudo a resolverlo.'\n"
    "   '¿Te quedó alguna duda con la cotización? Te ayudo a cerrar la decisión.'\n\n"
    "B. OFRECER AYUDA HUMANA:\n"
    "   '¿Prefieres que mi equipo te llame en 2 minutos para resolver dudas?'\n"
    "   'Si quieres, te puedo conectar con alguien del equipo que resuelva cualquier duda en vivo.'\n\n"
    "C. PROPONER SIGUIENTE PASO CONCRETO:\n"
    "   'Si te animas, te paso el link de reserva y aseguramos la fecha ahora con 50%.'\n"
    "   'Para que no se vaya la fecha, ¿te genero el link de reserva y decides más tranquilo?'\n\n"
    "D. MOSTRAR INTERÉS EN ENTENDER (si hubo múltiples cotizaciones o evaluación):\n"
    "   'Veo que estás evaluando — ¿qué te importa más: precio, espacio o comodidad? "
    "   Te oriento rápido 👍'\n\n"
    "REGLAS ESTRICTAS:\n"
    "- UN SOLO mensaje de MÁXIMO 2 líneas (es rápido, no carta).\n"
    "- Tono cálido y de ayuda, NO insistente ni vendedor agresivo.\n"
    "- NO repitas la cotización.\n"
    "- NO repitas preguntas ya respondidas en el historial (fechas, personas, ocasión).\n"
    "- NO uses 'solo quería recordarte' ni frases de relleno.\n"
    "- NO inventes urgencia falsa ('ya hay N reservas') a menos que sea fin de semana cercano.\n"
    "- Si el cliente dijo 'voy a pensarlo' o 'luego te aviso' en el último mensaje, "
    "NO envíes rescate (ya respondió — respeta su decisión).\n"
    "- NO uses herramientas, solo responde con texto.\n"
)


class Command(BaseCommand):
    help = 'Rescate rápido de conversaciones frías post-cotización (25-90 min)'

    def add_arguments(self, parser):
        parser.add_argument(
            '--dry-run', action='store_true',
            help='Solo muestra qué haría, sin enviar mensajes',
        )
        parser.add_argument(
            '--force', action='store_true',
            help='Ignora el check de horario Lima 8am-21pm (útil para pruebas)',
        )
        parser.add_argument(
            '--min-minutes', type=int, default=25,
            help='Edad mínima de la cotización en minutos (default 25)',
        )
        parser.add_argument(
            '--max-minutes', type=int, default=90,
            help='Edad máxima de la cotización en minutos (default 90)',
        )

    def handle(self, *args, **options):
        dry_run = options['dry_run']
        force = options['force']
        min_minutes = options['min_minutes']
        max_minutes = options['max_minutes']

        config = ChatbotConfiguration.get_config()
        if not config.is_active:
            self.stdout.write('Chatbot inactivo, saltando rescate rápido.')
            return

        now = timezone.now()

        # Respetar horario Lima 8am-21pm (salvo --force)
        if not force:
            import pytz
            lima_tz = pytz.timezone('America/Lima')
            lima_hour = now.astimezone(lima_tz).hour
            if lima_hour < 8 or lima_hour >= 21:
                self.stdout.write(
                    f'Fuera de horario ({lima_hour}h Lima), saltando rescate rápido. '
                    f'Usa --force para ignorar el check.'
                )
                return

        # Ventana: cotización entre `max_minutes` y `min_minutes` atrás
        quoted_before = now - timedelta(minutes=min_minutes)
        quoted_after = now - timedelta(minutes=max_minutes)

        candidates = ChatSession.objects.filter(
            deleted=False,
            status__in=['active', 'ai_paused'],
            ai_enabled=True,
            quoted_at__isnull=False,
            quoted_at__gte=quoted_after,
            quoted_at__lte=quoted_before,
        )

        sent = 0
        skipped = 0

        for session in candidates:
            name = session.wa_profile_name or session.wa_id

            skip_reason = self._should_skip(session, now)
            if skip_reason:
                skipped += 1
                if dry_run:
                    self.stdout.write(f'[SKIP] {name}: {skip_reason}')
                continue

            if dry_run:
                self.stdout.write(
                    f'[DRY] Quick rescue a {name} — cotizada: {session.quoted_at}'
                )
                sent += 1
                continue

            try:
                self._send_rescue(session, config)
                sent += 1
                self.stdout.write(f'  Enviado a {name}')
            except Exception as e:
                logger.error(
                    f"Error enviando quick rescue a {session.wa_id}: {e}",
                    exc_info=True,
                )
                self.stdout.write(self.style.ERROR(f'  Error con {name}: {e}'))

        action = 'Enviaría' if dry_run else 'Enviados'
        self.stdout.write(self.style.SUCCESS(
            f'{action}: {sent} rescates rápidos. Saltados: {skipped}.'
        ))

    def _should_skip(self, session, now):
        """Filtros para excluir sesiones del rescate rápido."""
        from apps.reservation.models import Reservation
        from datetime import date as date_type

        ctx = session.conversation_context or {}

        # 1. Ya se le envió rescate rápido
        if ctx.get('quick_rescue_sent_at'):
            return 'ya recibió rescate rápido'

        # 2. Admin ya intervino
        has_admin = ChatMessage.objects.filter(
            session=session,
            deleted=False,
            direction=ChatMessage.DirectionChoices.OUTBOUND_HUMAN,
        ).exists()
        if has_admin:
            return 'admin ya intervino'

        # 3. Cliente con reserva activa
        if session.client:
            has_res = Reservation.objects.filter(
                client=session.client,
                deleted=False,
                status__in=['approved', 'pending', 'incomplete'],
                check_out_date__gte=date_type.today(),
            ).exists()
            if has_res:
                return 'cliente ya tiene reserva activa'

        # 4. El cliente respondió DESPUÉS de la cotización
        responded = ChatMessage.objects.filter(
            session=session,
            deleted=False,
            direction=ChatMessage.DirectionChoices.INBOUND,
            created__gt=session.quoted_at,
        ).exists()
        if responded:
            return 'cliente ya respondió tras la cotización'

        # 5. Último mensaje del cliente fue una objeción de tiempo explícita
        # (respeta su decisión — no presionar)
        last_inbound = ChatMessage.objects.filter(
            session=session,
            deleted=False,
            direction=ChatMessage.DirectionChoices.INBOUND,
        ).order_by('-created').first()
        if last_inbound:
            text = (last_inbound.content or '').lower()
            time_objections = [
                'lo voy a pensar', 'voy a pensarlo', 'déjame pensarlo',
                'luego te aviso', 'después te aviso', 'después te confirmo',
                'estamos viendo', 'estamos analizando',
                'mañana te digo', 'mañana te aviso',
            ]
            if any(p in text for p in time_objections):
                return 'cliente dijo que va a pensarlo (respetar)'

        return None

    def _send_rescue(self, session, config):
        """Genera y envía el mensaje de rescate rápido usando IA."""
        import openai
        from django.conf import settings

        client = openai.OpenAI(api_key=settings.OPENAI_API_KEY)

        # Últimos 10 mensajes para contexto
        recent_msgs = ChatMessage.objects.filter(
            session=session, deleted=False
        ).order_by('-created')[:10]

        history = ""
        for msg in reversed(list(recent_msgs)):
            role = {
                'inbound': 'Cliente',
                'outbound_ai': 'IA',
                'outbound_human': 'Admin',
            }.get(msg.direction, 'Sistema')
            history += f"[{role}]: {(msg.content or '')[:250]}\n"

        name = session.wa_profile_name or session.wa_id
        messages = [
            {"role": "system", "content": QUICK_RESCUE_PROMPT},
            {
                "role": "user",
                "content": (
                    f"Contacto: {name}\n"
                    f"Cotización enviada hace ~30-60 min. Cliente aún no respondió.\n\n"
                    f"Historial:\n{history}\n\n"
                    f"Genera UN SOLO mensaje corto de rescate (max 2 líneas)."
                ),
            },
        ]

        response = client.chat.completions.create(
            model=config.primary_model,
            messages=messages,
            temperature=0.8,
            max_tokens=150,
        )

        text = (response.choices[0].message.content or "").strip()
        if not text:
            return

        sender = get_sender(session.channel)
        wa_message_id = sender.send_text_message(session.wa_id, text)

        ChatMessage.objects.create(
            session=session,
            direction=ChatMessage.DirectionChoices.OUTBOUND_AI,
            message_type=ChatMessage.MessageTypeChoices.TEXT,
            content=text,
            wa_message_id=wa_message_id,
            ai_model=config.primary_model,
            intent_detected='quick_rescue',
        )

        # Marcar en conversation_context — no incrementa followup_count para
        # que el follow-up de 4h pueda dispararse si sigue sin respuesta.
        now = timezone.now()
        ctx = session.conversation_context or {}
        ctx['quick_rescue_sent_at'] = now.isoformat()
        session.conversation_context = ctx
        session.total_messages += 1
        session.ai_messages += 1
        session.last_message_at = now
        session.save(update_fields=[
            'conversation_context', 'total_messages', 'ai_messages',
            'last_message_at',
        ])

        logger.info(
            f"Quick rescue enviado a {session.wa_id}: {text[:80]}..."
        )
