"""Backfill retroactivo de atribución de canal.

Recorre reservas y clientes históricos y aplica la lógica de inferencia
de canal (mismo `infer_touch_channel` que el signal en vivo).

Fases:
  1. Para cada Reservation sin `touch_channel`: infiere y persiste.
  2. Para cada Cliente sin `acquisition_channel`: busca su primera
     reserva aprobada, toma su touch_channel, y lo persiste como
     acquisition_channel del cliente.

Uso:
    python manage.py backfill_channel_attribution --dry-run
    python manage.py backfill_channel_attribution
    python manage.py backfill_channel_attribution --days 90 --dry-run
"""
from collections import Counter
from datetime import timedelta

from django.core.management.base import BaseCommand
from django.utils import timezone

from apps.clients.models import Clients
from apps.reservation.models import Reservation
from apps.chatbot.channel_attribution import (
    infer_touch_channel,
    ACQUISITION_TRIGGER_STATUS,
)
from apps.core.channel_choices import ChannelChoice


class Command(BaseCommand):
    help = (
        "Backfill: infiere touch_channel para reservas históricas sin él, "
        "y setea acquisition_channel para clientes según su primera reserva "
        "aprobada."
    )

    def add_arguments(self, parser):
        parser.add_argument(
            '--days', type=int, default=0,
            help='Limitar a reservas/clientes creados en los últimos N días '
                 '(0 = sin límite, default 0).'
        )
        parser.add_argument(
            '--dry-run', action='store_true',
            help='No persiste cambios, solo muestra estadísticas.'
        )

    def handle(self, *args, **opts):
        days = opts['days']
        dry_run = opts['dry_run']

        cutoff = None
        if days > 0:
            cutoff = timezone.now() - timedelta(days=days)

        self.stdout.write(self.style.HTTP_INFO('\n=== Backfill channel attribution ===\n'))
        self.stdout.write(
            f"Período: {'últimos ' + str(days) + ' días' if cutoff else 'TODO el histórico'}"
        )
        self.stdout.write(f"Modo: {'DRY RUN (no guarda)' if dry_run else 'APLICAR'}\n")

        # FASE 1: touch_channel por reservation
        self.stdout.write(self.style.HTTP_INFO('Fase 1 — touch_channel por reservation'))
        rqs = Reservation.objects.filter(deleted=False, touch_channel__isnull=True)
        if cutoff:
            rqs = rqs.filter(created__gte=cutoff)
        total_r = rqs.count()
        self.stdout.write(f"  Candidatos: {total_r:,} reservas sin touch_channel")

        channel_counter = Counter()
        for res in rqs.select_related('chatbot_session', 'client').iterator():
            channel, data = infer_touch_channel(res)
            # Backfill convention: lo que la inferencia marca como
            # 'unknown' (no signals) lo guardamos como 'legacy_unknown'.
            # Así desde el live, 'unknown' = bug o edge case a investigar,
            # y 'legacy_unknown' = histórico sin captura — ignorable.
            if channel == ChannelChoice.UNKNOWN:
                channel = ChannelChoice.LEGACY_UNKNOWN
            channel_counter[channel] += 1
            if not dry_run:
                res.touch_channel = channel
                res.touch_data = data
                res.save(update_fields=['touch_channel', 'touch_data', 'updated'])

        self.stdout.write("  Breakdown:")
        for ch, n in sorted(channel_counter.items(), key=lambda x: -x[1]):
            label = dict(ChannelChoice.choices).get(ch, ch)
            self.stdout.write(f"    {ch:20s} ({label:35s}) → {n:,}")

        # FASE 2: acquisition_channel por cliente
        self.stdout.write(self.style.HTTP_INFO('\nFase 2 — acquisition_channel por cliente'))
        cqs = Clients.objects.filter(deleted=False, acquisition_channel__isnull=True)
        if cutoff:
            cqs = cqs.filter(created__gte=cutoff)
        total_c = cqs.count()
        self.stdout.write(f"  Candidatos: {total_c:,} clientes sin acquisition_channel")

        acq_counter = Counter()
        no_paid_count = 0
        for client in cqs.iterator():
            # Buscar primera reserva aprobada del cliente
            first_approved = Reservation.objects.filter(
                client_id=client.id,
                deleted=False,
                status=ACQUISITION_TRIGGER_STATUS,
            ).order_by('created').first()

            if not first_approved:
                no_paid_count += 1
                continue

            # Usar touch_channel de la primera reserva aprobada como
            # canal de adquisición. Si no estaba seteado, inferirlo.
            channel = first_approved.touch_channel
            data = first_approved.touch_data
            if not channel:
                channel, data = infer_touch_channel(first_approved)
                # Misma convención que Fase 1: unknown → legacy_unknown
                # cuando es backfill (no live).
                if channel == ChannelChoice.UNKNOWN:
                    channel = ChannelChoice.LEGACY_UNKNOWN
                if not dry_run:
                    first_approved.touch_channel = channel
                    first_approved.touch_data = data
                    first_approved.save(update_fields=[
                        'touch_channel', 'touch_data', 'updated',
                    ])
            elif channel == ChannelChoice.UNKNOWN:
                # Si la reserva ya tenía 'unknown' (raro — vino del live
                # sin signals) lo dejamos así para no enmascarar bugs.
                pass

            acq_counter[channel] += 1
            if not dry_run:
                client.acquisition_channel = channel
                client.acquisition_data = dict(data or {})
                client.acquired_at = first_approved.created
                client.save(update_fields=[
                    'acquisition_channel', 'acquisition_data',
                    'acquired_at', 'updated',
                ])

        self.stdout.write(f"  Sin reserva aprobada (no se atribuye): {no_paid_count:,}")
        self.stdout.write("  Breakdown (clientes adquiridos):")
        for ch, n in sorted(acq_counter.items(), key=lambda x: -x[1]):
            label = dict(ChannelChoice.choices).get(ch, ch)
            self.stdout.write(f"    {ch:20s} ({label:35s}) → {n:,}")

        self.stdout.write('')
        if dry_run:
            self.stdout.write(self.style.WARNING(
                f'DRY RUN: {total_r:,} reservas + {sum(acq_counter.values()):,} '
                f'clientes se actualizarían.'
            ))
            self.stdout.write(self.style.WARNING(
                'No se guardó nada. Corre sin --dry-run para aplicar.'
            ))
        else:
            self.stdout.write(self.style.SUCCESS(
                f'✓ Aplicado: {total_r:,} reservas + {sum(acq_counter.values()):,} '
                f'clientes actualizados.'
            ))
