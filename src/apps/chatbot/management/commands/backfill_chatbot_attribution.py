"""Backfill retroactivo de atribución chatbot a reservas históricas.

Recorre Reservation con chatbot_session=NULL en un rango de días y, si
encuentra una ChatSession del mismo cliente con `quoted_at` dentro de
las 72h previas a la creación de la reserva, atribuye.

Uso:
    python manage.py backfill_chatbot_attribution
    python manage.py backfill_chatbot_attribution --days 30 --dry-run
    python manage.py backfill_chatbot_attribution --days 60
"""
from datetime import timedelta
from django.core.management.base import BaseCommand
from django.utils import timezone

from apps.chatbot.models import ChatSession
from apps.reservation.models import Reservation
from apps.chatbot.attribution import ATTRIBUTION_WINDOW_HOURS


class Command(BaseCommand):
    help = "Atribuye reservas históricas sin chatbot_session a la ChatSession más reciente del cliente que haya cotizado en las 72h previas."

    def add_arguments(self, parser):
        parser.add_argument('--days', type=int, default=30, help='Cuántos días atrás recorrer (default 30)')
        parser.add_argument('--dry-run', action='store_true', help='Solo muestra qué atribuiría, no guarda nada')

    def handle(self, *args, **opts):
        days_back = opts['days']
        dry_run = opts['dry_run']
        since = timezone.now() - timedelta(days=days_back)

        qs = Reservation.objects.filter(
            deleted=False,
            chatbot_session__isnull=True,
            client__isnull=False,
            created__gte=since,
        ).order_by('created')

        total = qs.count()
        self.stdout.write(f"\n=== Backfill chatbot attribution ===")
        self.stdout.write(f"Período: últimos {days_back} días (desde {since.date()})")
        self.stdout.write(f"Reservas candidatas: {total:,}\n")

        attributed = 0
        skipped_no_session = 0
        for res in qs:
            # Buscar ChatSession del cliente con quoted_at dentro de las 72h
            # ANTES de la creación de la reserva
            window_start = res.created - timedelta(hours=ATTRIBUTION_WINDOW_HOURS)
            session = (
                ChatSession.objects.filter(
                    client_id=res.client_id,
                    deleted=False,
                    quoted_at__gte=window_start,
                    quoted_at__lte=res.created,  # cotización ANTES de la reserva
                )
                .order_by('-quoted_at')
                .first()
            )
            if not session:
                skipped_no_session += 1
                continue

            name = (res.client.first_name or '') + ' ' + (res.client.last_name or '')
            msg = (
                f"  ✓ Reserva {str(res.id)[:8]}... ({res.check_in_date}, "
                f"{name.strip() or 'sin nombre'}) → ChatSession {str(session.id)[:8]}... "
                f"(quoted_at {session.quoted_at.strftime('%Y-%m-%d %H:%M')})"
            )
            self.stdout.write(msg)

            if not dry_run:
                res.chatbot_session = session
                res.save(update_fields=['chatbot_session', 'updated'])
            attributed += 1

        self.stdout.write('')
        if dry_run:
            self.stdout.write(self.style.WARNING(
                f"--dry-run: {attributed} reservas SE ATRIBUIRÍAN, "
                f"{skipped_no_session} sin sesión candidata."
            ))
            self.stdout.write(self.style.WARNING("No se guardó nada. Corre sin --dry-run para aplicar."))
        else:
            self.stdout.write(self.style.SUCCESS(
                f"✓ Atribuidas {attributed} reservas. "
                f"{skipped_no_session} sin sesión candidata (probablemente reservas no del bot)."
            ))
