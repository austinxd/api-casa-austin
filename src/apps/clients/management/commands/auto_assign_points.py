
from django.core.management.base import BaseCommand
from django.utils import timezone
from apps.clients.models import Clients, ClientPoints
from apps.reservation.models import Reservation


class Command(BaseCommand):
    help = 'Asigna puntos automáticamente a reservas que ya pasaron checkout'

    def handle(self, *args, **options):
        today = timezone.now().date()
        
        # Buscar reservas que ya pasaron checkout pero no tienen puntos asignados
        pending_reservations = Reservation.objects.filter(
            origin='aus',
            check_out_date__lt=today,  # Ya pasó el checkout
            client__isnull=False,
            price_sol__gt=0,
            deleted=False
        ).exclude(
            client__first_name__in=['Mantenimiento', 'AirBnB']
        )

        points_assigned = 0
        reservations_processed = 0

        for reservation in pending_reservations:
            # Verificar si ya tiene puntos asignados
            existing_points = ClientPoints.objects.filter(
                client=reservation.client,
                reservation=reservation,
                transaction_type=ClientPoints.TransactionType.EARNED,
                deleted=False
            ).exists()

            if existing_points:
                continue

            # Asignar puntos
            points_to_add = reservation.client.calculate_points_from_reservation(reservation.price_sol)
            
            if points_to_add > 0:
                reservation.client.add_points(
                    points=points_to_add,
                    reservation=reservation,
                    description=f"Puntos ganados por reserva #{reservation.id} - {reservation.property.name}"
                )
                
                points_assigned += points_to_add
                reservations_processed += 1

                self.stdout.write(
                    self.style.SUCCESS(
                        f"✅ {points_to_add:.2f} puntos asignados a {reservation.client.first_name} {reservation.client.last_name} "
                        f"(Reserva #{reservation.id})"
                    )
                )

        self.stdout.write(
            self.style.SUCCESS(
                f"\n🎯 Proceso completado:\n"
                f"Reservas procesadas: {reservations_processed}\n"
                f"Total puntos asignados: {points_assigned:.2f}"
            )
        )
