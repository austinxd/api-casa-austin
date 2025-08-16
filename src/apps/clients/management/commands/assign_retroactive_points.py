
from django.core.management.base import BaseCommand
from django.utils import timezone
from apps.clients.models import Clients, ClientPoints
from apps.reservation.models import Reservation
from datetime import datetime, timedelta


class Command(BaseCommand):
    help = 'Asigna puntos retroactivamente a clientes con reservas pasadas completadas'

    def add_arguments(self, parser):
        parser.add_argument(
            '--dry-run',
            action='store_true',
            help='Muestra qué se haría sin ejecutar los cambios',
        )
        parser.add_argument(
            '--confirm',
            action='store_true',
            help='Confirma que quieres ejecutar la asignación masiva de puntos',
        )

    def handle(self, *args, **options):
        dry_run = options['dry_run']
        confirm = options['confirm']
        
        if not dry_run and not confirm:
            self.stdout.write(
                self.style.WARNING(
                    'ADVERTENCIA: Este comando asignará puntos masivamente.\n'
                    'Usa --dry-run para ver qué se haría sin ejecutar cambios.\n'
                    'Usa --confirm para ejecutar los cambios reales.'
                )
            )
            return

        # Obtener todas las reservas de Austin completadas (checkout pasado)
        today = timezone.now().date()
        
        completed_reservations = Reservation.objects.filter(
            origin__in=['aus', 'client'],  # Reservas de Austin y Cliente Web
            check_out_date__lt=today,  # Ya pasó el checkout
            client__isnull=False,  # Tiene cliente
            price_sol__gt=0,  # Tiene precio válido
            deleted=False  # No eliminadas
        ).exclude(
            client__first_name__in=['Mantenimiento', 'AirBnB']  # Excluir clientes especiales
        ).select_related('client', 'property')

        self.stdout.write(f"Reservas completadas encontradas: {completed_reservations.count()}")

        total_points_assigned = 0
        clients_affected = 0
        reservations_processed = 0
        reservations_skipped = 0

        for reservation in completed_reservations:
            # Verificar si ya se asignaron puntos para esta reserva
            existing_points = ClientPoints.objects.filter(
                client=reservation.client,
                reservation=reservation,
                transaction_type=ClientPoints.TransactionType.EARNED,
                deleted=False
            ).exists()

            if existing_points:
                reservations_skipped += 1
                if dry_run:
                    self.stdout.write(
                        f"  SKIP: Reserva {reservation.id} ya tiene puntos asignados"
                    )
                continue

            # Calcular puntos (5% del precio en soles)
            points_to_add = reservation.client.calculate_points_from_reservation(reservation.price_sol)
            
            if points_to_add <= 0:
                reservations_skipped += 1
                continue

            reservations_processed += 1
            total_points_assigned += points_to_add

            if dry_run:
                self.stdout.write(
                    f"  WOULD ADD: {points_to_add:.2f} puntos para {reservation.client.first_name} {reservation.client.last_name} "
                    f"(Reserva #{reservation.id} - {reservation.property.name} - S/{reservation.price_sol})"
                )
            else:
                # Asignar puntos realmente
                old_balance = float(reservation.client.points_balance)
                
                reservation.client.add_points(
                    points=points_to_add,
                    reservation=reservation,
                    description=f"Puntos retroactivos por reserva #{reservation.id} - {reservation.property.name}"
                )
                
                new_balance = float(reservation.client.points_balance)
                
                self.stdout.write(
                    self.style.SUCCESS(
                        f"  ✅ ASIGNADO: {points_to_add:.2f} puntos para {reservation.client.first_name} {reservation.client.last_name} "
                        f"(Balance: {old_balance:.2f} → {new_balance:.2f}) - Reserva #{reservation.id}"
                    )
                )

        # Contar clientes únicos afectados
        if not dry_run:
            clients_affected = completed_reservations.filter(
                id__in=[r.id for r in completed_reservations if not ClientPoints.objects.filter(
                    client=r.client,
                    reservation=r,
                    transaction_type=ClientPoints.TransactionType.EARNED,
                    deleted=False
                ).exists()]
            ).values('client').distinct().count()
        else:
            clients_affected = completed_reservations.values('client').distinct().count()

        # Resumen final
        self.stdout.write("\n" + "="*60)
        if dry_run:
            self.stdout.write(
                self.style.WARNING(
                    f"🔍 SIMULACIÓN COMPLETADA (DRY RUN)\n"
                    f"Reservas que recibirían puntos: {reservations_processed}\n"
                    f"Reservas omitidas (ya tienen puntos): {reservations_skipped}\n"
                    f"Total de puntos que se asignarían: {total_points_assigned:.2f}\n"
                    f"Clientes únicos afectados: {clients_affected}\n\n"
                    f"Para ejecutar realmente: python manage.py assign_retroactive_points --confirm"
                )
            )
        else:
            self.stdout.write(
                self.style.SUCCESS(
                    f"✅ ASIGNACIÓN COMPLETADA\n"
                    f"Reservas procesadas: {reservations_processed}\n"
                    f"Reservas omitidas: {reservations_skipped}\n"
                    f"Total de puntos asignados: {total_points_assigned:.2f}\n"
                    f"Clientes beneficiados: {clients_affected}"
                )
            )
