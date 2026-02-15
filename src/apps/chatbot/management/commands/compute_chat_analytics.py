"""
Cron diario: agrega métricas del día anterior (o fecha indicada).

Uso: python manage.py compute_chat_analytics
     python manage.py compute_chat_analytics --date 2024-12-15
"""
from datetime import date, timedelta
from decimal import Decimal

from django.core.management.base import BaseCommand
from django.db.models import Count, Q, Sum

from apps.chatbot.models import ChatSession, ChatMessage, ChatAnalytics


# Costos por modelo (por 1M tokens)
MODEL_COSTS = {
    'gpt-4.1-nano': {'input': Decimal('0.10'), 'output': Decimal('0.40')},
    'gpt-4o-mini': {'input': Decimal('0.15'), 'output': Decimal('0.60')},
}


class Command(BaseCommand):
    help = 'Computa analíticas diarias del chatbot'

    def add_arguments(self, parser):
        parser.add_argument(
            '--date', type=str, default=None,
            help='Fecha a computar (YYYY-MM-DD). Por defecto: ayer.'
        )

    def handle(self, *args, **options):
        if options['date']:
            target_date = date.fromisoformat(options['date'])
        else:
            target_date = date.today() - timedelta(days=1)

        self.stdout.write(f'Computando analíticas para {target_date}...')

        # Mensajes del día
        messages = ChatMessage.objects.filter(
            created__date=target_date, deleted=False
        )

        messages_in = messages.filter(direction='inbound').count()
        messages_out_ai = messages.filter(direction='outbound_ai').count()
        messages_out_human = messages.filter(direction='outbound_human').count()

        # Sesiones activas del día
        session_ids = messages.values_list('session_id', flat=True).distinct()
        total_sessions = len(set(session_ids))

        # Nuevas sesiones del día
        new_sessions = ChatSession.objects.filter(
            created__date=target_date, deleted=False
        ).count()

        # Escalaciones
        escalations = ChatSession.objects.filter(
            status='escalated',
            updated__date=target_date,
            deleted=False,
        ).count()

        # Tokens y costos
        ai_messages = messages.filter(direction='outbound_ai')
        tokens_data = ai_messages.aggregate(
            total_tokens=Sum('tokens_used')
        )
        total_tokens = tokens_data['total_tokens'] or 0

        # Estimar input/output (60/40 split aprox)
        tokens_input = int(total_tokens * 0.6)
        tokens_output = int(total_tokens * 0.4)

        # Calcular costo estimado
        estimated_cost = Decimal('0')
        for model_name, costs in MODEL_COSTS.items():
            model_msgs = ai_messages.filter(ai_model=model_name)
            model_tokens = model_msgs.aggregate(total=Sum('tokens_used'))['total'] or 0
            if model_tokens > 0:
                input_cost = (Decimal(str(int(model_tokens * 0.6))) / Decimal('1000000')) * costs['input']
                output_cost = (Decimal(str(int(model_tokens * 0.4))) / Decimal('1000000')) * costs['output']
                estimated_cost += input_cost + output_cost

        # Intents breakdown
        intents = {}
        for msg in ai_messages.exclude(intent_detected__isnull=True).exclude(intent_detected=''):
            intent = msg.intent_detected
            intents[intent] = intents.get(intent, 0) + 1

        # Reservas creadas vía chatbot (buscar en tool_calls)
        reservations_created = 0
        clients_identified = 0
        for msg in ai_messages:
            if isinstance(msg.tool_calls, list):
                for tc in msg.tool_calls:
                    if isinstance(tc, dict):
                        if tc.get('name') == 'create_reservation':
                            reservations_created += 1
                        elif tc.get('name') == 'identify_client':
                            clients_identified += 1

        # Guardar o actualizar
        analytics, created = ChatAnalytics.objects.update_or_create(
            date=target_date,
            defaults={
                'total_sessions': total_sessions,
                'new_sessions': new_sessions,
                'total_messages_in': messages_in,
                'total_messages_out_ai': messages_out_ai,
                'total_messages_out_human': messages_out_human,
                'escalations': escalations,
                'intents_breakdown': intents,
                'total_tokens_input': tokens_input,
                'total_tokens_output': tokens_output,
                'estimated_cost_usd': estimated_cost,
                'reservations_created': reservations_created,
                'clients_identified': clients_identified,
            }
        )

        action = 'Creada' if created else 'Actualizada'
        self.stdout.write(self.style.SUCCESS(
            f'{action} analítica para {target_date}: '
            f'{total_sessions} sesiones, {messages_in} msgs in, '
            f'{messages_out_ai} msgs IA, ${estimated_cost:.4f} costo'
        ))
