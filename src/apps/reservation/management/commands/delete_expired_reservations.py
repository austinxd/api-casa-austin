
from django.core.management.base import BaseCommand
from django.utils import timezone
from apps.reservation.models import Reservation
import logging

logger = logging.getLogger(__name__)


class Command(BaseCommand):
    help = 'Elimina reservas de clientes que no subieron voucher en tiempo'

    def handle(self, *args, **options):
        now = timezone.now()
        
        # Buscar reservas expiradas
        expired_reservations = Reservation.objects.filter(
            origin='client',
            status='pending',
            payment_voucher_uploaded=False,
            payment_voucher_deadline__lt=now,
            deleted=False
        )
        
        count = 0
        for reservation in expired_reservations:
            logger.info(f"Eliminando reserva expirada ID: {reservation.id}")
            reservation.delete()
            count += 1
        
        self.stdout.write(
            self.style.SUCCESS(f'Se eliminaron {count} reservas expiradas')
        )
