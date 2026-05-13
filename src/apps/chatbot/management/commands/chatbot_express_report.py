"""Reporte del funnel de Reserva Express (R4.2).

Mide el embudo desde que el bot pide DNI hasta que se crea la reserva,
y separa los distintos puntos de abandono / conflicto.

Uso:
    python manage.py chatbot_express_report
    python manage.py chatbot_express_report --days 7
    python manage.py chatbot_express_report --days 30 --verbose
"""
from collections import Counter
from datetime import timedelta

from django.core.management.base import BaseCommand
from django.db.models import Count, Q
from django.utils import timezone

from apps.chatbot.models import ChatMessage
from apps.clients.magic_link_models import ReservationMagicLink


class Command(BaseCommand):
    help = "Funnel de Reserva Express (R4.2): links creados/validados/consumidos."

    def add_arguments(self, parser):
        parser.add_argument(
            '--days', type=int, default=30,
            help='Ventana hacia atrás en días (default 30).',
        )
        parser.add_argument(
            '--verbose', action='store_true',
            help='Detalle por sesión y casos individuales.',
        )

    def handle(self, *args, **opts):
        days = opts['days']
        verbose = opts['verbose']
        since = timezone.now() - timedelta(days=days)

        self.stdout.write(self.style.SUCCESS(
            f"\n=== Reserva Express (R4.2) · últimos {days} días ===\n"
        ))

        # === 1. Funnel del guard del chatbot (via ChatMessage.tool_calls) ===
        # Cada fase del guard deja un ChatMessage outbound con
        # tool_calls=[{guard:'express', phase:'...'}].
        guard_msgs = ChatMessage.objects.filter(
            deleted=False,
            direction=ChatMessage.DirectionChoices.OUTBOUND_AI,
            ai_model='guard',
            created__gte=since,
        )
        phase_counter = Counter()
        express_sessions = set()
        for msg in guard_msgs.only('session_id', 'tool_calls'):
            for tc in (msg.tool_calls or []):
                if tc.get('guard') != 'express':
                    continue
                phase = tc.get('phase', '?')
                phase_counter[phase] += 1
                express_sessions.add(msg.session_id)

        if not phase_counter:
            self.stdout.write(
                "Sin activaciones del guard G_EXPRESS en la ventana.\n"
            )

        self.stdout.write(self.style.SUCCESS(
            "--- Funnel del guard G_EXPRESS ---"
        ))
        for phase, count in phase_counter.most_common():
            self.stdout.write(f"  {phase:30s} {count:>5}")
        self.stdout.write(
            f"  → Sesiones únicas con activación: {len(express_sessions)}"
        )

        # === 2. Magic links guest_express en BD ===
        ml_qs = ReservationMagicLink.objects.filter(
            link_type='guest_express',
            created__gte=since,
            deleted=False,
        )
        ml_total = ml_qs.count()
        ml_consumed = ml_qs.filter(used_at__isnull=False).count()
        now = timezone.now()
        ml_expired_unused = ml_qs.filter(
            used_at__isnull=True, expires_at__lt=now,
        ).count()
        ml_valid = ml_qs.filter(
            used_at__isnull=True, expires_at__gt=now,
        ).count()
        ml_redeemed_not_consumed = ml_qs.filter(
            used_at__isnull=True, use_count__gt=0,
        ).count()

        self.stdout.write(self.style.SUCCESS(
            "\n--- Magic Links guest_express en BD ---"
        ))
        self.stdout.write(f"  Total creados:                  {ml_total}")
        self.stdout.write(f"  Consumidos (reserva creada):    {ml_consumed}")
        self.stdout.write(f"  Vigentes (no consumidos):       {ml_valid}")
        self.stdout.write(f"  Expirados sin reserva:          {ml_expired_unused}")
        self.stdout.write(
            f"  Abiertos pero sin consumir:     {ml_redeemed_not_consumed}"
        )

        if ml_total > 0:
            conversion = (ml_consumed / ml_total) * 100
            abandono = (ml_expired_unused / ml_total) * 100
            self.stdout.write(self.style.SUCCESS(
                "\n--- Tasas ---"
            ))
            self.stdout.write(
                f"  Conversión a reserva: {conversion:.1f}%"
            )
            self.stdout.write(
                f"  Abandono (expirado):  {abandono:.1f}%"
            )

        # === 3. Casos de conflicto (vía ChatMessage tool_calls notify_team) ===
        notify_msgs = ChatMessage.objects.filter(
            deleted=False,
            direction=ChatMessage.DirectionChoices.OUTBOUND_AI,
            created__gte=since,
        )
        express_notify_counter = Counter()
        for msg in notify_msgs.only('tool_calls'):
            for tc in (msg.tool_calls or []):
                if tc.get('name') != 'notify_team':
                    continue
                reason = (tc.get('arguments') or {}).get('reason', '')
                if reason.startswith('express_'):
                    express_notify_counter[reason] += 1

        if express_notify_counter:
            self.stdout.write(self.style.SUCCESS(
                "\n--- Conflictos / notify_team express ---"
            ))
            for reason, count in express_notify_counter.most_common():
                self.stdout.write(f"  {reason:50s} {count:>5}")

        # === 4. Verbose: últimos 10 links express ===
        if verbose:
            self.stdout.write(self.style.SUCCESS(
                "\n--- Últimos 10 magic links express ---"
            ))
            for m in ml_qs.order_by('-created')[:10]:
                status = m.status_label
                dni_mask = (
                    (m.document_number[:4] + '****')
                    if m.document_number and len(m.document_number) >= 4
                    else m.document_number or '-'
                )
                self.stdout.write(
                    f"  {m.created.strftime('%Y-%m-%d %H:%M')} | "
                    f"DNI {dni_mask} | "
                    f"{m.validated_full_name or '-'} | "
                    f"{m.check_in}→{m.check_out} {m.guests}p | "
                    f"{status}"
                )

        self.stdout.write("")
