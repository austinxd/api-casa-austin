
from django.core.management.base import BaseCommand
from django.utils import timezone
from apps.reservation.models import Reservation
import logging

logger = logging.getLogger(__name__)


class Command(BaseCommand):
    help = 'Elimina payment_voucher_deadline de reservas que ya tienen voucher subido'

    def add_arguments(self, parser):
        parser.add_argument(
            '--dry-run',
            action='store_true',
            help='Solo muestra las reservas que serían actualizadas sin actualizarlas',
        )

    def handle(self, *args, **options):
        dry_run = options['dry_run']
        
        # Buscar reservas de clientes que tienen voucher subido pero aún tienen deadline
        reservations_with_voucher_and_deadline = Reservation.objects.filter(
            origin='client',
            payment_voucher_uploaded=True,
            payment_voucher_deadline__isnull=False,
            deleted=False
        )
        
        self.stdout.write(f'Encontradas {reservations_with_voucher_and_deadline.count()} reservas con voucher subido que aún tienen deadline')
        
        count = 0
        for reservation in reservations_with_voucher_and_deadline:
            client_name = f"{reservation.client.first_name} {reservation.client.last_name}" if reservation.client else "Cliente desconocido"
            
            self.stdout.write(
                f"Reserva ID: {reservation.id} - Cliente: {client_name} "
                f"- Propiedad: {reservation.property.name if reservation.property else 'N/A'} "
                f"- Status: {reservation.status} - Deadline actual: {reservation.payment_voucher_deadline}"
            )
            
            if not dry_run:
                reservation.payment_voucher_deadline = None
                reservation.save(update_fields=['payment_voucher_deadline'])
                logger.info(f"Eliminado deadline de reserva ID: {reservation.id}")
                count += 1
            else:
                count += 1
        
        if dry_run:
            self.stdout.write(
                self.style.WARNING(f'DRY RUN: Se eliminarían deadlines de {count} reservas')
            )
        else:
            self.stdout.write(
                self.style.SUCCESS(f'Se eliminaron deadlines de {count} reservas')
            )
