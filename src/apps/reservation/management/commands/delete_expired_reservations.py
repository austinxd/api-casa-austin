
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
                # Registrar actividad en el feed ANTES de eliminar la reserva
                self._register_activity_feed(reservation)
                
                # Enviar WhatsApp al cliente SIEMPRE que se cancele una reserva
                self._send_whatsapp_notification(reservation)
                
                # Enviar Telegram interno solo si la reserva es para hoy o mañana
                should_notify_telegram = reservation.check_in_date in [today, tomorrow]
                if should_notify_telegram:
                    self._send_telegram_notification(reservation)
                
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

    def _send_telegram_notification(self, reservation):
        """Envía notificación interna por Telegram cuando se elimina una reserva para hoy o mañana"""
        from apps.reservation.signals import format_date_es
        
        try:
            client_name = f"{reservation.client.first_name} {reservation.client.last_name}" if reservation.client else "Cliente desconocido"
            check_in_date = format_date_es(reservation.check_in_date)
            check_out_date = format_date_es(reservation.check_out_date)
            property_name = reservation.property.name if reservation.property else "Propiedad no disponible"
            
            telegram_message = (
                f"⚠️ **RESERVA ELIMINADA POR EXPIRACIÓN** ⚠️\n"
                f"Cliente: {client_name}\n"
                f"Propiedad: {property_name}\n"
                f"Check-in: {check_in_date}\n"
                f"Check-out: {check_out_date}\n"
                f"❌ Motivo: No subió voucher a tiempo\n"
                f"🆔 Reserva ID: {reservation.id}\n"
                f"⏰ Eliminada automáticamente por expiración"
            )
            
            send_telegram_message(telegram_message, settings.CLIENTS_CHAT_ID)
            logger.info(f"Notificación de eliminación enviada por Telegram para reserva {reservation.id}")
            
        except Exception as e:
            logger.error(f"Error enviando notificación por Telegram para reserva {reservation.id}: {str(e)}")

    def _send_whatsapp_notification(self, reservation):
        """Envía WhatsApp al cliente cuando se elimina cualquier reserva por expiración"""
        from apps.clients.whatsapp_service import send_whatsapp_reservation_cancelled
        
        # Enviar WhatsApp al cliente si tiene teléfono
        if reservation.client and reservation.client.tel_number:
            try:
                # Preparar nombre del cliente para WhatsApp template {{1}}
                first_name = reservation.client.first_name.split()[0] if reservation.client.first_name else ""
                first_last_name = ""
                if reservation.client.last_name:
                    first_last_name = reservation.client.last_name.split()[0]
                whatsapp_client_name = f"{first_name} {first_last_name}".strip()
                
                logger.info(f"Enviando WhatsApp de cancelación a {reservation.client.tel_number} para reserva {reservation.id}")
                whatsapp_success = send_whatsapp_reservation_cancelled(
                    phone_number=reservation.client.tel_number,
                    client_name=whatsapp_client_name
                )
                
                if whatsapp_success:
                    logger.info(f"WhatsApp de cancelación enviado exitosamente para reserva {reservation.id}")
                else:
                    logger.error(f"Error al enviar WhatsApp de cancelación para reserva {reservation.id}")
                    
            except Exception as e:
                logger.error(f"Error enviando WhatsApp de cancelación para reserva {reservation.id}: {str(e)}")
        else:
            logger.warning(f"No se puede enviar WhatsApp para reserva {reservation.id}: cliente sin teléfono")

    def _register_activity_feed(self, reservation):
        """Registra la eliminación de la reserva en el Activity Feed"""
        try:
            # Importación local para evitar problemas de dependencias circulares
            from apps.events.models import ActivityFeed, ActivityFeedConfig
            from apps.reservation.signals import format_date_es
            
            # Verificar si el tipo de actividad está habilitado
            if not ActivityFeedConfig.is_type_enabled(ActivityFeed.ActivityType.RESERVATION_AUTO_DELETED_CRON):
                logger.info(f"⚠️ ActivityFeed deshabilitado para tipo RESERVATION_AUTO_DELETED_CRON - no se registra actividad para reserva {reservation.id}")
                return
            
            # Preparar datos de la actividad  
            from apps.reservation.signals import format_date_range_es
            dates = format_date_range_es(reservation.check_in_date, reservation.check_out_date)
            property_name = reservation.property.name if reservation.property else "Propiedad no disponible"
            
            activity_data = {
                'property_name': property_name,
                'dates': dates,
                'check_in': reservation.check_in_date.isoformat() if reservation.check_in_date else None,
                'check_out': reservation.check_out_date.isoformat() if reservation.check_out_date else None,
                'reason': 'depósito no confirmado en el plazo indicado',
                'deadline_expired': reservation.payment_voucher_deadline.isoformat() if reservation.payment_voucher_deadline else None,
                'origin': 'cron_delete_expired'
            }
            
            # Importar configuración para respetar configuración global
            from apps.events.models import ActivityFeedConfig
            
            # Usar configuración por defecto para visibilidad e importancia
            is_public = ActivityFeedConfig.should_be_public(ActivityFeed.ActivityType.RESERVATION_AUTO_DELETED_CRON)
            importance = ActivityFeedConfig.get_default_importance(ActivityFeed.ActivityType.RESERVATION_AUTO_DELETED_CRON)
            
            # Crear actividad usando get_or_create para evitar duplicados
            activity, created = ActivityFeed.objects.get_or_create(
                activity_type=ActivityFeed.ActivityType.RESERVATION_AUTO_DELETED_CRON,
                client=reservation.client,
                property_location=reservation.property,
                activity_data__property_name=property_name,  # Deduplicación por propiedad y fechas
                activity_data__dates=dates,
                defaults={
                    'title': 'Reserva Liberada por Sistema',
                    'description': 'La reserva fue liberada automáticamente debido a que no se confirmó el depósito en el plazo indicado',
                    'activity_data': activity_data,
                    'is_public': is_public,
                    'importance_level': importance
                }
            )
            
            if created:
                logger.info(f"✅ Actividad registrada en feed para eliminación de reserva {reservation.id}")
            else:
                logger.info(f"⚠️ Actividad ya existía en feed para reserva {reservation.id}")
                
        except Exception as e:
            logger.error(f"❌ Error registrando actividad en feed para reserva {reservation.id}: {str(e)}")
