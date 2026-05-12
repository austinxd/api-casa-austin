"""Reporte de activaciones de guards determinísticos (R1.0 + R2).

Cada guard persiste un ChatMessage con ai_model='guard' y tool_calls que
incluye el nombre del guard, subtype, topic. Este comando consulta esa
data para medir cuántas respuestas salieron por guard vs IA.

Uso:
    python manage.py chatbot_guards_report
    python manage.py chatbot_guards_report --days 30
    python manage.py chatbot_guards_report --days 7 --verbose
"""
from collections import Counter
from datetime import timedelta

from django.core.management.base import BaseCommand
from django.db.models import Count
from django.utils import timezone

from apps.chatbot.models import ChatMessage


# Estimación conservadora de tokens promedio por respuesta de IA
# (basado en cotizaciones + replies típicas). Ajustar si tienes datos reales.
AVG_TOKENS_PER_AI_RESPONSE = 600


class Command(BaseCommand):
    help = "Reporte de activaciones de guards (G1, G_REQUOTE, G3, G_FAQ, G4)."

    def add_arguments(self, parser):
        parser.add_argument(
            '--days', type=int, default=30,
            help='Ventana hacia atrás en días (default 30).',
        )
        parser.add_argument(
            '--verbose', action='store_true',
            help='Mostrar todas las sesiones afectadas.',
        )

    def handle(self, *args, **opts):
        days = opts['days']
        since = timezone.now() - timedelta(days=days)

        guard_msgs = ChatMessage.objects.filter(
            deleted=False,
            direction=ChatMessage.DirectionChoices.OUTBOUND_AI,
            ai_model='guard',
            created__gte=since,
        )
        total_guard = guard_msgs.count()

        ai_msgs = ChatMessage.objects.filter(
            deleted=False,
            direction=ChatMessage.DirectionChoices.OUTBOUND_AI,
            created__gte=since,
        ).exclude(ai_model='guard').exclude(ai_model='error')
        total_ai = ai_msgs.count()

        grand_total = total_guard + total_ai

        self.stdout.write(self.style.SUCCESS(
            f"\n=== Guards report · últimos {days} días ==="
        ))
        if grand_total == 0:
            self.stdout.write("Sin mensajes en la ventana.")
            return

        self.stdout.write(
            f"Total respuestas bot: {grand_total}"
        )
        self.stdout.write(
            f"  - Por guard (0 tokens): {total_guard} ({total_guard/grand_total:.0%})"
        )
        self.stdout.write(
            f"  - Por IA (con tokens):  {total_ai} ({total_ai/grand_total:.0%})"
        )

        # Conteo por guard
        guard_counter = Counter()
        subtype_counter = Counter()  # G_REQUOTE
        topic_counter = Counter()    # G_FAQ
        sessions_affected = set()

        for msg in guard_msgs.only('id', 'session_id', 'tool_calls'):
            sessions_affected.add(msg.session_id)
            for tc in (msg.tool_calls or []):
                if tc.get('name') != 'guard':
                    continue
                guard = tc.get('guard', 'unknown')
                guard_counter[guard] += 1
                if guard == 'requote':
                    subtype_counter[tc.get('subtype', '?')] += 1
                if guard == 'faq':
                    topic_counter[tc.get('topic', '?')] += 1

        self.stdout.write(self.style.SUCCESS(
            f"\n--- Activaciones por guard ---"
        ))
        for guard, count in sorted(
            guard_counter.items(), key=lambda x: -x[1]
        ):
            pct = count / total_guard * 100 if total_guard else 0
            self.stdout.write(
                f"  {guard:25s} {count:>5} ({pct:>5.1f}%)"
            )

        if subtype_counter:
            self.stdout.write(self.style.SUCCESS(
                f"\n--- G_REQUOTE por subtype ---"
            ))
            for sub, count in sorted(
                subtype_counter.items(), key=lambda x: -x[1]
            ):
                self.stdout.write(f"  {sub:20s} {count:>5}")

        if topic_counter:
            self.stdout.write(self.style.SUCCESS(
                f"\n--- G_FAQ por topic ---"
            ))
            for topic, count in sorted(
                topic_counter.items(), key=lambda x: -x[1]
            ):
                self.stdout.write(f"  {topic:25s} {count:>5}")

        # Ahorro estimado
        saved_tokens = total_guard * AVG_TOKENS_PER_AI_RESPONSE
        self.stdout.write(self.style.SUCCESS(
            f"\n--- Estimación de ahorro ---"
        ))
        self.stdout.write(
            f"  Sesiones con al menos 1 guard: {len(sessions_affected)}"
        )
        self.stdout.write(
            f"  Tokens evitados (≈{AVG_TOKENS_PER_AI_RESPONSE}/respuesta): "
            f"~{saved_tokens:,}"
        )

        # log_unanswered_question count para comparar
        unanswered_msgs = ChatMessage.objects.filter(
            deleted=False,
            direction=ChatMessage.DirectionChoices.OUTBOUND_AI,
            tool_calls__contains=[{'name': 'log_unanswered_question'}],
            created__gte=since,
        )
        unanswered_count = unanswered_msgs.count()
        self.stdout.write(self.style.SUCCESS(
            f"\n--- log_unanswered_question ---"
        ))
        self.stdout.write(
            f"  Llamadas a log_unanswered_question: {unanswered_count}"
        )
        if total_guard > 0:
            ratio = unanswered_count / total_guard
            self.stdout.write(
                f"  Ratio unanswered/guard: {ratio:.2f} "
                f"(menor = G_FAQ está cubriendo más)"
            )

        if opts['verbose']:
            self.stdout.write(self.style.SUCCESS(
                f"\n--- Sesiones afectadas ({len(sessions_affected)}) ---"
            ))
            for sid in sorted(str(s) for s in sessions_affected):
                self.stdout.write(f"  {sid}")
