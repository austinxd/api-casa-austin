"""
Envía review requests post-estadía por WhatsApp.

Lógica:
1. Lee ReviewRequestConfig (singleton) — si no activo, sale
2. Busca reservas con check_out_date=ayer, status=approved, con cliente
3. Excluye reservas que ya tienen ReviewRequest
4. Para cada reserva elegible:
   a. Obtiene nivel actual del cliente
   b. Obtiene/crea ChatSession
   c. Envía template post_stay_level_update con nombre y nivel
   d. Crea ReviewRequest con status=sent
   e. Guarda review_flow en conversation_context de la sesión

Uso: python manage.py send_review_requests [--dry-run]
Cron recomendado: diario 2pm Lima (19:00 UTC)
"""
import logging
from datetime import date, timedelta

from django.core.management.base import BaseCommand
from django.utils import timezone

from apps.chatbot.models import (
    ChatSession, ChatMessage, ReviewRequestConfig, ReviewRequest,
)
from apps.chatbot.whatsapp_sender import WhatsAppSender
from apps.clients.models import Clients, ClientAchievement
from apps.reservation.models import Reservation

logger = logging.getLogger(__name__)


def get_client_current_level(client):
    """Obtiene el nombre del nivel actual del cliente."""
    last_ca = ClientAchievement.objects.filter(
        client=client, deleted=False,
    ).select_related('achievement').order_by('-earned_at').first()

    if last_ca:
        return last_ca.achievement.name
    return "Curioso"


class Command(BaseCommand):
    help = 'Envía review requests post-estadía por WhatsApp a clientes que hicieron checkout ayer'

    def add_arguments(self, parser):
        parser.add_argument(
            '--dry-run', action='store_true',
            help='Solo muestra qué haría, sin enviar mensajes'
        )

    def handle(self, *args, **options):
        dry_run = options['dry_run']

        config = ReviewRequestConfig.get_config()
        if not config.is_active:
            self.stdout.write('ReviewRequestConfig inactivo, saltando.')
            return

        yesterday = date.today() - timedelta(days=1)
        self.stdout.write(f'Buscando reservas con checkout: {yesterday}')

        # Buscar reservas elegibles
        reservations = Reservation.objects.filter(
            check_out_date=yesterday,
            status='approved',
            client__isnull=False,
            deleted=False,
        ).select_related('client')

        if not reservations.exists():
            self.stdout.write('No hay reservas con checkout ayer.')
            return

        # Excluir las que ya tienen ReviewRequest
        already_requested = set(
            ReviewRequest.objects.filter(
                reservation__in=reservations,
                deleted=False,
            ).values_list('reservation_id', flat=True)
        )

        sent_count = 0
        skipped_count = 0

        for reservation in reservations:
            client = reservation.client
            client_name = f"{client.first_name} {client.last_name or ''}".strip()

            if reservation.id in already_requested:
                self.stdout.write(f'  SKIP {client_name}: ya tiene review request')
                skipped_count += 1
                continue

            # Verificar que tiene teléfono
            phone = client.tel_number
            if not phone:
                self.stdout.write(f'  SKIP {client_name}: sin teléfono')
                skipped_count += 1
                continue

            # Obtener nivel actual del cliente
            nivel = get_client_current_level(client)
            primer_nombre = client.first_name.split()[0] if client.first_name else "Cliente"

            if dry_run:
                self.stdout.write(
                    f'  [DRY] {client_name} ({phone}): '
                    f'nivel={nivel}, reserva={reservation.id}'
                )
                sent_count += 1
                continue

            # Construir componentes del template (2 parámetros: nombre, nivel)
            components = [
                {
                    'type': 'body',
                    'parameters': [
                        {'type': 'text', 'text': primer_nombre},
                        {'type': 'text', 'text': nivel},
                    ]
                }
            ]

            # Enviar template WA
            sender = WhatsAppSender()
            wa_message_id = sender.send_template_message(
                to=phone,
                template_name=config.wa_template_name,
                language_code=config.wa_template_language,
                components=components,
            )

            # Obtener/crear sesión de chat
            session = ChatSession.objects.filter(
                client=client, deleted=False
            ).order_by('-last_message_at').first()

            if not session:
                session = ChatSession.objects.create(
                    channel='whatsapp',
                    wa_id=phone,
                    wa_profile_name=client_name,
                    client=client,
                    status='active',
                    ai_enabled=True,
                )

            if not wa_message_id:
                self.stdout.write(self.style.ERROR(
                    f'  ERROR {client_name}: envío WA falló'
                ))
                ReviewRequest.objects.create(
                    client=client,
                    reservation=reservation,
                    session=session,
                    wa_message_id=None,
                    status='failed',
                    achievement_at_send=nivel,
                )
                skipped_count += 1
                continue

            # Crear ReviewRequest
            review_req = ReviewRequest.objects.create(
                client=client,
                reservation=reservation,
                session=session,
                wa_message_id=wa_message_id,
                status='sent',
                achievement_at_send=nivel,
            )

            # Guardar review_flow en conversation_context
            ctx = session.conversation_context or {}
            ctx['review_flow'] = 'awaiting_benefits_click'
            ctx['review_request_id'] = str(review_req.id)
            session.conversation_context = ctx
            session.save(update_fields=['conversation_context'])

            # Registrar mensaje system en la sesión
            rendered = sender.render_template(
                config.wa_template_name, config.wa_template_language, components
            )
            template_content = rendered or (
                f"Review request enviado - Nivel: {nivel}"
            )

            ChatMessage.objects.create(
                session=session,
                direction='system',
                message_type='text',
                content=f"[Review Post-Estadía - Enviado OK]\n\n{template_content}",
                wa_message_id=wa_message_id,
                intent_detected='review_request',
            )

            session.total_messages += 1
            session.last_message_at = timezone.now()
            session.save(update_fields=['total_messages', 'last_message_at'])

            sent_count += 1
            self.stdout.write(
                f'  ENVIADO {client_name}: nivel={nivel}, '
                f'review_req={review_req.id}'
            )

        action = 'Enviaría' if dry_run else 'Enviados'
        self.stdout.write(self.style.SUCCESS(
            f'\n{action}: {sent_count} review requests. Omitidos: {skipped_count}.'
        ))
