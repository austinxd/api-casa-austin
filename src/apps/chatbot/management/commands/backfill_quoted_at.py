"""
Backfill quoted_at para sesiones que ya recibieron cotización.
Busca mensajes con check_availability en tool_calls y marca la sesión.

Uso: python manage.py backfill_quoted_at
"""
from django.core.management.base import BaseCommand
from django.db.models import Q

from apps.chatbot.models import ChatSession, ChatMessage


class Command(BaseCommand):
    help = 'Backfill quoted_at para sesiones existentes con cotización'

    def handle(self, *args, **options):
        # Sesiones sin quoted_at
        sessions = ChatSession.objects.filter(
            deleted=False, quoted_at__isnull=True
        )

        updated = 0
        for session in sessions:
            # Buscar mensajes outbound_ai que tengan check_availability en tool_calls
            quote_msg = ChatMessage.objects.filter(
                session=session,
                deleted=False,
                direction='outbound_ai',
                tool_calls__contains=[{'name': 'check_availability'}],
            ).order_by('created').first()

            if not quote_msg:
                # Fallback: buscar en el contenido del mensaje por patrones de cotización
                quote_msg = ChatMessage.objects.filter(
                    session=session,
                    deleted=False,
                    direction='outbound_ai',
                    content__contains='COTIZACIÓN CASA AUSTIN',
                ).order_by('created').first()

            if quote_msg:
                session.quoted_at = quote_msg.created
                session.save(update_fields=['quoted_at'])
                name = session.wa_profile_name or session.wa_id
                self.stdout.write(f'  Marcada: {name} — quoted_at = {quote_msg.created}')
                updated += 1

        self.stdout.write(self.style.SUCCESS(f'Backfill completado: {updated} sesiones actualizadas.'))
