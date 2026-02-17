"""
Envía promos automáticas por WhatsApp a clientes que buscaron fechas que siguen disponibles.

Lógica:
1. Lee PromoDateConfig (singleton) — si no activo, sale
2. Calcula fecha objetivo: hoy + days_before_checkin
3. Busca en SearchTracking clientes que buscaron esa check_in_date
4. Excluye clientes con reserva activa/futura y clientes que ya recibieron promo
5. Para cada cliente elegible: verifica disponibilidad, genera código, envía template WA

Uso: python manage.py send_promo_dates [--dry-run]
Cron recomendado: diario 9am
"""
import logging
from datetime import date, timedelta

from django.core.management.base import BaseCommand
from django.db.models import Q
from django.utils import timezone

from apps.chatbot.models import (
    ChatSession, ChatMessage, PromoDateConfig, PromoDateSent,
)
from apps.chatbot.whatsapp_sender import WhatsAppSender
from apps.clients.models import SearchTracking

logger = logging.getLogger(__name__)


def select_best_search(searches):
    """De varias búsquedas del mismo cliente para la misma fecha,
    elige la mejor combinación de personas y check_out.

    Lógica de personas: tomar la menor cantidad > 1 (más probable real),
    o 1 si todos buscaron con 1. Del subset, tomar la búsqueda más reciente.
    """
    guest_counts = set(s.guests for s in searches)

    counts_gt1 = sorted(g for g in guest_counts if g > 1)
    selected_guests = counts_gt1[0] if counts_gt1 else 1

    matching = [s for s in searches if s.guests == selected_guests]
    best = max(matching, key=lambda s: s.search_timestamp)

    return best.check_out_date, selected_guests


class Command(BaseCommand):
    help = 'Envía promos automáticas por fechas buscadas que siguen disponibles'

    def add_arguments(self, parser):
        parser.add_argument(
            '--dry-run', action='store_true',
            help='Solo muestra qué haría, sin enviar mensajes ni generar códigos'
        )

    def handle(self, *args, **options):
        dry_run = options['dry_run']

        config = PromoDateConfig.get_config()
        if not config.is_active:
            self.stdout.write('PromoDateConfig inactivo, saltando.')
            return

        if not config.discount_config:
            self.stdout.write(self.style.ERROR(
                'No hay DynamicDiscountConfig asignado en PromoDateConfig.'
            ))
            return

        today = date.today()
        target_date = today + timedelta(days=config.days_before_checkin)

        self.stdout.write(f'Fecha objetivo check-in: {target_date} (hoy + {config.days_before_checkin}d)')

        # Buscar en SearchTracking: clientes que buscaron esa check_in_date
        searches = SearchTracking.objects.filter(
            check_in_date=target_date,
            client__isnull=False,
        ).select_related('client')

        if not searches.exists():
            self.stdout.write('No hay búsquedas de clientes para esa fecha.')
            return

        # Agrupar por cliente
        client_searches = {}
        for s in searches:
            client_id = s.client_id
            if client_id not in client_searches:
                client_searches[client_id] = []
            client_searches[client_id].append(s)

        self.stdout.write(f'Clientes únicos que buscaron {target_date}: {len(client_searches)}')

        # Filtrar clientes que ya tienen reserva activa/futura
        from apps.reservation.models import Reservation
        clients_with_reservation = set(
            Reservation.objects.filter(
                deleted=False,
                status__in=['approved', 'pending', 'incomplete', 'under_review'],
                check_in_date__lte=target_date,
                check_out_date__gt=target_date,
            ).values_list('client_id', flat=True)
        )

        # Filtrar clientes que ya recibieron promo para esta fecha
        clients_already_promo = set(
            PromoDateSent.objects.filter(
                check_in_date=target_date,
                deleted=False,
            ).values_list('client_id', flat=True)
        )

        # Opcionalmente excluir clientes con chat activo < 24h
        clients_recent_chat = set()
        if config.exclude_recent_chatters:
            cutoff = timezone.now() - timedelta(hours=24)
            clients_recent_chat = set(
                ChatSession.objects.filter(
                    deleted=False,
                    client__isnull=False,
                    last_customer_message_at__gte=cutoff,
                ).values_list('client_id', flat=True)
            )

        sent_count = 0
        skipped_count = 0

        for client_id, client_search_list in client_searches.items():
            client = client_search_list[0].client
            client_name = f"{client.first_name} {client.last_name or ''}".strip()

            # Exclusiones
            if client_id in clients_with_reservation:
                self.stdout.write(f'  SKIP {client_name}: tiene reserva activa')
                skipped_count += 1
                continue

            if client_id in clients_already_promo:
                self.stdout.write(f'  SKIP {client_name}: ya recibió promo')
                skipped_count += 1
                continue

            if client_id in clients_recent_chat:
                self.stdout.write(f'  SKIP {client_name}: chat activo < 24h')
                skipped_count += 1
                continue

            # Verificar min_search_count
            if len(client_search_list) < config.min_search_count:
                self.stdout.write(f'  SKIP {client_name}: solo {len(client_search_list)} búsqueda(s)')
                skipped_count += 1
                continue

            # Verificar que el cliente tiene teléfono
            phone = client.tel_number
            if not phone:
                self.stdout.write(f'  SKIP {client_name}: sin teléfono')
                skipped_count += 1
                continue

            # Seleccionar mejor búsqueda (personas y check_out)
            check_out_date, guests = select_best_search(client_search_list)

            # Verificar disponibilidad y calcular pricing
            try:
                from apps.property.pricing_service import PricingCalculationService
                pricing_service = PricingCalculationService()
                pricing_result = pricing_service.calculate_pricing(
                    check_in_date=target_date,
                    check_out_date=check_out_date,
                    guests=guests,
                    client_id=str(client.id),
                )
            except Exception as e:
                self.stdout.write(self.style.ERROR(
                    f'  ERROR {client_name}: pricing falló: {e}'
                ))
                continue

            # Verificar que hay propiedades disponibles
            available_properties = [
                p for p in pricing_result.get('properties', [])
                if p.get('available')
            ]

            if not available_properties:
                self.stdout.write(f'  SKIP {client_name}: sin disponibilidad')
                skipped_count += 1
                continue

            if dry_run:
                casas = ', '.join(p['property_name'] for p in available_properties)
                self.stdout.write(
                    f'  [DRY] {client_name} ({phone}): '
                    f'{target_date} → {check_out_date}, {guests}p, '
                    f'casas: {casas}'
                )
                sent_count += 1
                continue

            # Generar código de descuento
            try:
                discount_code = config.discount_config.generate_code()
            except Exception as e:
                self.stdout.write(self.style.ERROR(
                    f'  ERROR {client_name}: no se pudo generar código: {e}'
                ))
                continue

            # Recalcular pricing con descuento
            try:
                pricing_with_discount = pricing_service.calculate_pricing(
                    check_in_date=target_date,
                    check_out_date=check_out_date,
                    guests=guests,
                    client_id=str(client.id),
                    discount_code=discount_code.code,
                )
                available_with_discount = [
                    p for p in pricing_with_discount.get('properties', [])
                    if p.get('available')
                ]
            except Exception:
                available_with_discount = available_properties

            # Construir detalle de casas para el template
            casas_detalle = []
            for p in available_with_discount:
                original = float(p.get('subtotal_sol', p.get('final_price_sol', 0)))
                final = float(p.get('final_price_sol', 0))
                if original > final:
                    casas_detalle.append(
                        f"{p['property_name']}: S/{original:.0f} → S/{final:.0f}"
                    )
                else:
                    casas_detalle.append(
                        f"{p['property_name']}: S/{final:.0f}"
                    )
            casas_text = '\n'.join(casas_detalle)

            # Formatear fechas
            from apps.property.pricing_service import PricingCalculationService as PCS
            try:
                svc = PCS()
                mes_in = svc._get_month_name_spanish(target_date.month)
                mes_out = svc._get_month_name_spanish(check_out_date.month)
            except Exception:
                mes_in = str(target_date.month)
                mes_out = str(check_out_date.month)

            if target_date.month == check_out_date.month:
                fechas_str = f"{target_date.day}-{check_out_date.day} de {mes_in}"
            else:
                fechas_str = f"{target_date.day} de {mes_in} al {check_out_date.day} de {mes_out}"

            discount_pct = int(config.discount_config.discount_percentage)

            # Construir componentes del template
            components = [
                {
                    'type': 'body',
                    'parameters': [
                        {'type': 'text', 'text': client.first_name},
                        {'type': 'text', 'text': fechas_str},
                        {'type': 'text', 'text': str(guests)},
                        {'type': 'text', 'text': casas_text},
                        {'type': 'text', 'text': discount_code.code},
                        {'type': 'text', 'text': str(discount_pct)},
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
                # No borrar el código generado, pero marcar como fallido
                PromoDateSent.objects.create(
                    client=client,
                    check_in_date=target_date,
                    check_out_date=check_out_date,
                    guests=guests,
                    discount_code=discount_code,
                    wa_message_id=None,
                    message_content=casas_text,
                    pricing_snapshot={
                        'properties': [
                            {
                                'name': p['property_name'],
                                'final_price_sol': float(p.get('final_price_sol', 0)),
                            }
                            for p in available_with_discount
                        ],
                        'discount_percentage': discount_pct,
                    },
                    status='failed',
                )
                continue

            # Registrar en PromoDateSent
            session = ChatSession.objects.filter(
                client=client, deleted=False
            ).order_by('-last_message_at').first()

            promo_sent = PromoDateSent.objects.create(
                client=client,
                check_in_date=target_date,
                check_out_date=check_out_date,
                guests=guests,
                discount_code=discount_code,
                wa_message_id=wa_message_id,
                session=session,
                message_content=casas_text,
                pricing_snapshot={
                    'properties': [
                        {
                            'name': p['property_name'],
                            'final_price_sol': float(p.get('final_price_sol', 0)),
                        }
                        for p in available_with_discount
                    ],
                    'discount_percentage': discount_pct,
                    'discount_code': discount_code.code,
                },
                status='sent',
            )

            # Crear/actualizar ChatSession y ChatMessage para visibilidad en Austin Assistant
            if not session:
                session = ChatSession.objects.create(
                    channel='whatsapp',
                    wa_id=phone,
                    wa_profile_name=client_name,
                    client=client,
                    status='active',
                    ai_enabled=True,
                )

            ChatMessage.objects.create(
                session=session,
                direction='system',
                message_type='text',
                content=(
                    f"[Promo automática] Se envió promo por fecha {fechas_str} "
                    f"({guests}p). Código: {discount_code.code} ({discount_pct}% desc). "
                    f"Casas: {casas_text}"
                ),
                wa_message_id=wa_message_id,
                intent_detected='promo_date',
            )

            # Actualizar contadores de sesión
            session.total_messages += 1
            session.last_message_at = timezone.now()
            session.save(update_fields=['total_messages', 'last_message_at'])

            sent_count += 1
            self.stdout.write(
                f'  ENVIADO {client_name}: {discount_code.code} '
                f'({discount_pct}%) - {casas_text[:60]}'
            )

        action = 'Enviaría' if dry_run else 'Enviados'
        self.stdout.write(self.style.SUCCESS(
            f'\n{action}: {sent_count} promos. Omitidos: {skipped_count}.'
        ))
