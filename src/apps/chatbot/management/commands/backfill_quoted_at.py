"""Backfill quoted_at para sesiones que ya recibieron cotización.

Detecta cotizaciones por múltiples vías:
  1. ChatMessage con intent_detected que incluya 'availability_check'.
  2. ChatMessage con tool_calls que incluyan 'check_availability'.
  3. Patrón de texto en el contenido (varios copys históricos del bot).
  4. Existencia de un ReservationMagicLink asociado a la sesión.

Para cada sesión sin quoted_at, busca el evento de cotización más
antiguo entre estos métodos y lo usa como timestamp.

Uso: python manage.py backfill_quoted_at [--dry-run]
"""
from django.core.management.base import BaseCommand
from django.db.models import Q

from apps.chatbot.models import ChatSession, ChatMessage


# Patrones de texto que indican que el bot mostró una cotización
QUOTE_CONTENT_PATTERNS = [
    'Precio total por toda la estadía',     # copy actual (2026+)
    'COTIZACIÓN CASA AUSTIN',                # copy legacy
    'PRECIO PARA',                           # copy intermedio
    'Reservar y pagar ahora',                # copy nuevo del magic link
    'Te dejo tu link de reserva',            # copy legacy del magic link
    'Tu link para reservar y pagar',         # copy actual del magic link
    'casaaustin.pe/r/',                      # cualquier mensaje con magic link URL
]


class Command(BaseCommand):
    help = 'Backfill quoted_at para sesiones existentes con cotización'

    def add_arguments(self, parser):
        parser.add_argument('--dry-run', action='store_true', help='Solo muestra sin guardar.')

    def handle(self, *args, **opts):
        sessions = ChatSession.objects.filter(deleted=False, quoted_at__isnull=True)
        total = sessions.count()
        self.stdout.write(f"Sesiones sin quoted_at: {total}")
        self.stdout.write('')

        updated = 0
        for session in sessions:
            quote_at = self._find_quote_timestamp(session)
            if not quote_at:
                continue

            name = session.wa_profile_name or session.wa_id
            self.stdout.write(f'  Marcada: {name} — quoted_at = {quote_at}')

            if not opts['dry_run']:
                session.quoted_at = quote_at
                session.save(update_fields=['quoted_at'])
            updated += 1

        self.stdout.write('')
        if opts['dry_run']:
            self.stdout.write(self.style.WARNING(f'--dry-run: {updated} sesiones se actualizarían.'))
        else:
            self.stdout.write(self.style.SUCCESS(f'Backfill completado: {updated} sesiones actualizadas.'))

    def _find_quote_timestamp(self, session):
        """Devuelve el datetime de la cotización más antigua, o None."""
        # 1. Por intent_detected (más confiable)
        msg = ChatMessage.objects.filter(
            session=session, deleted=False,
            direction='outbound_ai',
            intent_detected__icontains='availability_check',
        ).order_by('created').first()
        if msg:
            return msg.created

        # 2. Por tool_calls (cuando el bot llamó check_availability)
        msg = ChatMessage.objects.filter(
            session=session, deleted=False, direction='outbound_ai',
            tool_calls__contains=[{'name': 'check_availability'}],
        ).order_by('created').first()
        if msg:
            return msg.created

        # 3. Por contenido del mensaje (cualquier patrón conocido)
        q = Q()
        for pattern in QUOTE_CONTENT_PATTERNS:
            q |= Q(content__icontains=pattern)
        msg = ChatMessage.objects.filter(
            session=session, deleted=False, direction='outbound_ai',
        ).filter(q).order_by('created').first()
        if msg:
            return msg.created

        # 4. Si existe un ReservationMagicLink para la sesión, usar su `created`
        try:
            from apps.clients.magic_link_models import ReservationMagicLink
            ml = ReservationMagicLink.objects.filter(
                chat_session=session, deleted=False,
            ).order_by('created').first()
            if ml:
                return ml.created
        except Exception:
            pass

        return None
