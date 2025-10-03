from django.core.management.base import BaseCommand
from django.db import transaction
from decimal import Decimal
from datetime import datetime

from apps.reservation.models import Reservation
from apps.clients.models import Clients, ClientPoints, Achievement, ClientAchievement
from apps.clients.signals import check_and_assign_achievements
import logging

logger = logging.getLogger(__name__)


class Command(BaseCommand):
    help = 'Recalcula puntos y asigna logros para reservas existentes'

    def add_arguments(self, parser):
        parser.add_argument(
            '--from-date',
            type=str,
            help='Fecha desde la cual procesar reservas (formato: YYYY-MM-DD)'
        )
        parser.add_argument(
            '--to-date',
            type=str,
            help='Fecha hasta la cual procesar reservas (formato: YYYY-MM-DD)'
        )
        parser.add_argument(
            '--client-id',
            type=str,
            help='ID del cliente específico para procesar'
        )
        parser.add_argument(
            '--dry-run',
            action='store_true',
            help='Solo mostrar lo que se haría sin ejecutar cambios'
        )

    def handle(self, *args, **options):
        from_date = options.get('from_date')
        to_date = options.get('to_date')
        client_id = options.get('client_id')
        dry_run = options.get('dry_run')

        self.stdout.write(self.style.WARNING(f'\n{"="*80}'))
        self.stdout.write(self.style.WARNING('RECÁLCULO DE PUNTOS Y LOGROS'))
        self.stdout.write(self.style.WARNING(f'{"="*80}\n'))

        if dry_run:
            self.stdout.write(self.style.WARNING('⚠️  MODO DRY-RUN: No se realizarán cambios\n'))

        # Filtrar reservas
        reservations = Reservation.objects.filter(
            status='approved',
            deleted=False
        ).select_related('client', 'property')

        if from_date:
            from_date_obj = datetime.strptime(from_date, '%Y-%m-%d').date()
            reservations = reservations.filter(check_in_date__gte=from_date_obj)
            self.stdout.write(f'Desde: {from_date}')

        if to_date:
            to_date_obj = datetime.strptime(to_date, '%Y-%m-%d').date()
            reservations = reservations.filter(check_in_date__lte=to_date_obj)
            self.stdout.write(f'Hasta: {to_date}')

        if client_id:
            reservations = reservations.filter(client__id=client_id)
            self.stdout.write(f'Cliente: {client_id}')

        reservations = reservations.order_by('check_in_date')

        self.stdout.write(f'\nReservas encontradas: {reservations.count()}\n')

        if reservations.count() == 0:
            self.stdout.write(self.style.WARNING('No hay reservas para procesar'))
            return

        # Agrupar por cliente
        clients_data = {}
        for reservation in reservations:
            if not reservation.client:
                continue

            client_id = reservation.client.id
            if client_id not in clients_data:
                clients_data[client_id] = {
                    'client': reservation.client,
                    'reservations': [],
                    'total_points': Decimal('0')
                }

            # Calcular puntos (5% del precio efectivo en soles)
            precio_efectivo = reservation.price_sol or Decimal('0')
            points = (precio_efectivo * Decimal('0.05')).quantize(Decimal('0.01'))
            
            clients_data[client_id]['reservations'].append({
                'reservation': reservation,
                'points': points
            })
            clients_data[client_id]['total_points'] += points

        self.stdout.write(self.style.WARNING(f'\n{"="*80}'))
        self.stdout.write(self.style.WARNING(f'CLIENTES A PROCESAR: {len(clients_data)}'))
        self.stdout.write(self.style.WARNING(f'{"="*80}\n'))

        points_created = 0
        achievements_assigned = 0
        errors = 0

        for client_id, data in clients_data.items():
            client = data['client']
            client_name = f"{client.first_name} {client.last_name}"
            
            self.stdout.write(f'\n📊 {client_name}')
            self.stdout.write(f'   Reservas: {len(data["reservations"])}')
            self.stdout.write(f'   Puntos totales: {data["total_points"]}')

            if not dry_run:
                try:
                    with transaction.atomic():
                        # Asignar puntos por cada reserva
                        for res_data in data['reservations']:
                            reservation = res_data['reservation']
                            points = res_data['points']

                            # Verificar si ya existen puntos para esta reserva
                            existing = ClientPoints.objects.filter(
                                client=client,
                                reservation=reservation,
                                deleted=False
                            ).exists()

                            if not existing and points > 0:
                                ClientPoints.objects.create(
                                    client=client,
                                    reservation=reservation,
                                    points=points,
                                    description=f"Puntos por reserva en {reservation.property.name}"
                                )
                                points_created += 1

                        # Verificar y asignar logros
                        initial_achievements = ClientAchievement.objects.filter(
                            client=client,
                            deleted=False
                        ).count()

                        check_and_assign_achievements(client)

                        final_achievements = ClientAchievement.objects.filter(
                            client=client,
                            deleted=False
                        ).count()

                        new_achievements = final_achievements - initial_achievements
                        if new_achievements > 0:
                            achievements_assigned += new_achievements
                            self.stdout.write(self.style.SUCCESS(f'   ✓ {new_achievements} logros asignados'))

                except Exception as e:
                    errors += 1
                    self.stdout.write(self.style.ERROR(f'   ✗ Error: {str(e)}'))

        self.stdout.write(self.style.WARNING(f'\n{"="*80}'))
        self.stdout.write(self.style.WARNING('RESUMEN'))
        self.stdout.write(self.style.WARNING(f'{"="*80}\n'))

        if dry_run:
            self.stdout.write(self.style.WARNING('MODO DRY-RUN - Sin cambios realizados'))
            self.stdout.write(f'Se procesarían: {len(clients_data)} clientes')
            self.stdout.write(f'Puntos estimados a crear: {sum(len(d["reservations"]) for d in clients_data.values())}')
        else:
            self.stdout.write(self.style.SUCCESS(f'✓ Clientes procesados: {len(clients_data)}'))
            self.stdout.write(self.style.SUCCESS(f'✓ Puntos creados: {points_created}'))
            self.stdout.write(self.style.SUCCESS(f'✓ Logros asignados: {achievements_assigned}'))
            if errors > 0:
                self.stdout.write(self.style.ERROR(f'✗ Errores: {errors}'))

        self.stdout.write('')
