
from django.core.management.base import BaseCommand
from django.utils import timezone
from apps.reservation.models import Reservation
from apps.core.telegram_notifier import send_telegram_message
from django.conf import settings
import logging
from datetime import date, timedelta

logger = logging.getLogger(__name__)


class Command(BaseCommand):
    help = 'Elimina reservas de clientes que no subieron voucher en tiempo'

    def add_arguments(self, parser):
        parser.add_argument(
            '--dry-run',
            action='store_true',
            help='Solo muestra las reservas que serían eliminadas sin eliminarlas',
        )

    def handle(self, *args, **options):
        now = timezone.now()
        dry_run = options['dry_run']
        
        # Buscar reservas expiradas (incompletas o pendientes sin voucher)
        expired_reservations = Reservation.objects.filter(
            origin='client',
            status__in=['incomplete', 'pending'],
            payment_voucher_uploaded=False,
            payment_voucher_deadline__lt=now,
            deleted=False
        )
        
        self.stdout.write(f'Encontradas {expired_reservations.count()} reservas expiradas')
        
        count = 0
        today = date.today()
        tomorrow = today + timedelta(days=1)
        
        for reservation in expired_reservations:
            self.stdout.write(
                f"Reserva ID: {reservation.id} - Cliente: {reservation.client.first_name if reservation.client else 'N/A'} "
                f"- Propiedad: {reservation.property.name if reservation.property else 'N/A'} "
                f"- Deadline: {reservation.payment_voucher_deadline}"
            )
            
            if not dry_run:
                # Verificar si la reserva es para hoy o mañana antes de eliminar
                should_notify = reservation.check_in_date in [today, tomorrow]
                
                if should_notify:
                    self._send_expiration_notification(reservation)
                
                logger.info(f"Eliminando reserva expirada ID: {reservation.id}")
                reservation.delete()
                count += 1
            else:
                count += 1
        
        if dry_run:
            self.stdout.write(
                self.style.WARNING(f'DRY RUN: Se eliminarían {count} reservas expiradas')
            )
        else:
            self.stdout.write(
                self.style.SUCCESS(f'Se eliminaron {count} reservas expiradas')
            )

    def _send_expiration_notification(self, reservation):
        """Envía notificación por Telegram cuando se elimina una reserva para hoy o mañana"""
        try:
            from apps.reservation.signals import format_date_es
            
            client_name = f"{reservation.client.first_name} {reservation.client.last_name}" if reservation.client else "Cliente desconocido"
            check_in_date = format_date_es(reservation.check_in_date)
            check_out_date = format_date_es(reservation.check_out_date)
            
            message = (
                f"⚠️ **RESERVA ELIMINADA POR EXPIRACIÓN** ⚠️\n"
                f"Cliente: {client_name}\n"
                f"Propiedad: {reservation.property.name}\n"
                f"Check-in: {check_in_date}\n"
                f"Check-out: {check_out_date}\n"
                f"💰 Total: S/{reservation.price_sol:.2f}\n"
                f"📱 Teléfono: +{reservation.client.tel_number if reservation.client else 'N/A'}\n"
                f"❌ Motivo: No subió voucher a tiempo\n"
                f"🆔 Reserva ID: {reservation.id}\n"
                f"⏰ Eliminada automáticamente por expiración"
            )
            
            # Enviar al canal de clientes
            send_telegram_message(message, settings.CLIENTS_CHAT_ID)
            logger.info(f"Notificación de eliminación enviada para reserva {reservation.id}")
            
        except Exception as e:
            logger.error(f"Error enviando notificación de eliminación para reserva {reservation.id}: {str(e)}")
