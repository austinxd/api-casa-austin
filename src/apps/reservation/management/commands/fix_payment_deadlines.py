
from django.core.management.base import BaseCommand
from django.utils import timezone
from datetime import timedelta
from apps.reservation.models import Reservation
import logging

logger = logging.getLogger(__name__)


class Command(BaseCommand):
    help = 'Configura payment_voucher_deadline para reservas de clientes existentes'

    def add_arguments(self, parser):
        parser.add_argument(
            '--dry-run',
            action='store_true',
            help='Solo muestra las reservas que serían actualizadas sin actualizarlas',
        )

    def handle(self, *args, **options):
        dry_run = options['dry_run']
        
        # Buscar reservas de clientes sin deadline configurado
        reservations_without_deadline = Reservation.objects.filter(
            origin='client',
            status='pending',
            payment_voucher_deadline__isnull=True,
            deleted=False
        )
        
        self.stdout.write(f'Encontradas {reservations_without_deadline.count()} reservas sin deadline')
        
        count = 0
        for reservation in reservations_without_deadline:
            # Calcular deadline basado en la fecha de creación + 1 hora
            # Si ya pasó más de 1 hora desde la creación, marcar como expirada inmediatamente
            created_plus_hour = reservation.created + timedelta(hours=1)
            
            self.stdout.write(
                f"Reserva ID: {reservation.id} - Cliente: {reservation.client.first_name if reservation.client else 'N/A'} "
                f"- Creada: {reservation.created} - Deadline calculado: {created_plus_hour}"
            )
            
            if not dry_run:
                reservation.payment_voucher_deadline = created_plus_hour
                reservation.save()
                logger.info(f"Actualizada reserva ID: {reservation.id} con deadline: {created_plus_hour}")
                count += 1
            else:
                count += 1
        
        if dry_run:
            self.stdout.write(
                self.style.WARNING(f'DRY RUN: Se actualizarían {count} reservas')
            )
        else:
            self.stdout.write(
                self.style.SUCCESS(f'Se actualizaron {count} reservas con deadline')
            )
