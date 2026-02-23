"""
Envía promos automáticas de cumpleaños por WhatsApp.

Lógica:
1. Lee PromoBirthdayConfig (singleton) — si no activo, sale
2. Calcula fecha objetivo: hoy + days_before_birthday
3. Busca clientes con cumpleaños en esa fecha (date__month, date__day)
4. Filtra: tiene teléfono, no existe PromoBirthdaySent para ese año
5. Para cada cliente: construye 7 params de plantilla y envía via WhatsApp

Uso: python manage.py send_promo_birthday [--dry-run]
Cron recomendado: diario 9am
"""
import logging
from datetime import date, timedelta

from django.core.management.base import BaseCommand

from apps.chatbot.models import (
    ChatSession, PromoBirthdayConfig, PromoBirthdaySent,
)
from apps.chatbot.whatsapp_sender import WhatsAppSender
from apps.clients.models import Clients, Achievement, ClientAchievement

logger = logging.getLogger(__name__)


def get_client_level_info(client):
    """
    Obtiene info del nivel actual del cliente y qué le falta para el siguiente.

    Returns:
        tuple: (nivel_actual, discount_perm, siguiente_nivel, que_falta)
    """
    from apps.reservation.models import Reservation

    # Último logro obtenido por el cliente
    last_ca = ClientAchievement.objects.filter(
        client=client, deleted=False,
    ).select_related('achievement').order_by('-earned_at').first()

    if last_ca:
        current_achievement = last_ca.achievement
        nivel_actual = current_achievement.name
        discount_perm = current_achievement.discount_percentage
    else:
        current_achievement = None
        nivel_actual = "Sin nivel"
        discount_perm = 0

    # Buscar siguiente nivel en orden
    if current_achievement:
        next_achievement = Achievement.objects.filter(
            is_active=True, deleted=False,
            order__gt=current_achievement.order,
        ).order_by('order').first()
    else:
        next_achievement = Achievement.objects.filter(
            is_active=True, deleted=False,
        ).order_by('order').first()

    if not next_achievement:
        return nivel_actual, discount_perm, "Máximo alcanzado", "¡Ya eres del nivel más alto!"

    # Calcular qué falta
    client_reservations = Reservation.objects.filter(
        client=client, deleted=False, status='approved',
    ).count()
    client_referrals = Clients.objects.filter(
        referred_by=client, deleted=False,
    ).count()
    referral_reservations = Reservation.objects.filter(
        client__referred_by=client, deleted=False, status='approved',
    ).count()

    faltas = []
    if next_achievement.required_reservations > client_reservations:
        diff = next_achievement.required_reservations - client_reservations
        faltas.append(f"{diff} reserva{'s' if diff > 1 else ''}")
    if next_achievement.required_referrals > client_referrals:
        diff = next_achievement.required_referrals - client_referrals
        faltas.append(f"{diff} referido{'s' if diff > 1 else ''}")
    if next_achievement.required_referral_reservations > referral_reservations:
        diff = next_achievement.required_referral_reservations - referral_reservations
        faltas.append(f"{diff} reserva{'s' if diff > 1 else ''} de referidos")

    que_falta = " y ".join(faltas) if faltas else "¡Ya cumples los requisitos!"

    return nivel_actual, discount_perm, next_achievement.name, que_falta


class Command(BaseCommand):
    help = 'Envía promos automáticas de cumpleaños por WhatsApp'

    def add_arguments(self, parser):
        parser.add_argument(
            '--dry-run', action='store_true',
            help='Solo muestra qué haría, sin enviar mensajes'
        )

    def handle(self, *args, **options):
        dry_run = options['dry_run']

        config = PromoBirthdayConfig.get_config()
        if not config.is_active:
            self.stdout.write('PromoBirthdayConfig inactivo, saltando.')
            return

        today = date.today()
        target_date = today + timedelta(days=config.days_before_birthday)

        self.stdout.write(
            f'Fecha objetivo cumpleaños: {target_date.day}/{target_date.month} '
            f'(hoy + {config.days_before_birthday}d)'
        )

        # Buscar clientes con cumpleaños en la fecha objetivo
        clients = Clients.objects.filter(
            date__month=target_date.month,
            date__day=target_date.day,
            deleted=False,
        )

        if not clients.exists():
            self.stdout.write('No hay clientes con cumpleaños en esa fecha.')
            return

        self.stdout.write(f'Clientes con cumpleaños el {target_date.day}/{target_date.month}: {clients.count()}')

        # Clientes que ya recibieron promo este año
        already_sent = set(
            PromoBirthdaySent.objects.filter(
                year=target_date.year,
                deleted=False,
            ).values_list('client_id', flat=True)
        )

        sent_count = 0
        skipped_count = 0

        for client in clients:
            client_name = f"{client.first_name} {client.last_name or ''}".strip()

            # Verificar que no se haya enviado ya
            if client.id in already_sent:
                self.stdout.write(f'  SKIP {client_name}: ya recibió promo este año')
                skipped_count += 1
                continue

            # Verificar que tiene teléfono
            phone = client.tel_number
            if not phone:
                self.stdout.write(f'  SKIP {client_name}: sin teléfono')
                skipped_count += 1
                continue

            # Obtener info de nivel
            nivel_actual, discount_perm, siguiente_nivel, que_falta = get_client_level_info(client)

            # Puntos disponibles (= S/)
            puntos = client.get_available_points()

            # Primer nombre
            primer_nombre = client.first_name.split()[0] if client.first_name else "Cliente"

            if dry_run:
                self.stdout.write(
                    f'  [DRY] {client_name} ({phone}):\n'
                    f'    {{1}} nombre: {primer_nombre}\n'
                    f'    {{2}} nivel: {nivel_actual}\n'
                    f'    {{3}} puntos: {puntos}\n'
                    f'    {{4}} sig nivel: {siguiente_nivel}\n'
                    f'    {{5}} falta: {que_falta}\n'
                    f'    {{6}} desc cumple: {config.birthday_discount_percentage}%\n'
                    f'    {{7}} desc perm: {discount_perm}%'
                )
                sent_count += 1
                continue

            # Construir componentes del template (7 parámetros body)
            components = [
                {
                    'type': 'body',
                    'parameters': [
                        {'type': 'text', 'text': primer_nombre},
                        {'type': 'text', 'text': str(nivel_actual)},
                        {'type': 'text', 'text': str(int(puntos))},
                        {'type': 'text', 'text': str(siguiente_nivel)},
                        {'type': 'text', 'text': str(que_falta)},
                        {'type': 'text', 'text': str(config.birthday_discount_percentage)},
                        {'type': 'text', 'text': str(int(discount_perm))},
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

            if not wa_message_id:
                self.stdout.write(self.style.ERROR(
                    f'  ERROR {client_name}: envío WA falló'
                ))
                PromoBirthdaySent.objects.create(
                    client=client,
                    year=target_date.year,
                    wa_message_id=None,
                    status='failed',
                )
                skipped_count += 1
                continue

            # Registrar envío exitoso
            PromoBirthdaySent.objects.create(
                client=client,
                year=target_date.year,
                wa_message_id=wa_message_id,
                status='sent',
            )

            # Registrar en chat
            content = (
                f"[Promo cumpleaños] Se envió promo de cumpleaños a {client_name}. "
                f"Nivel: {nivel_actual}, Puntos: {int(puntos)}, "
                f"Desc cumple: {config.birthday_discount_percentage}%, "
                f"Desc permanente: {int(discount_perm)}%"
            )
            ChatSession.register_outbound_template(
                phone_number=phone,
                content=content,
                intent='promo_birthday',
                client=client,
            )

            sent_count += 1
            self.stdout.write(
                f'  ENVIADO {client_name}: nivel={nivel_actual}, '
                f'puntos={int(puntos)}, desc={config.birthday_discount_percentage}%'
            )

        action = 'Enviaría' if dry_run else 'Enviados'
        self.stdout.write(self.style.SUCCESS(
            f'\n{action}: {sent_count} promos de cumpleaños. Omitidos: {skipped_count}.'
        ))
