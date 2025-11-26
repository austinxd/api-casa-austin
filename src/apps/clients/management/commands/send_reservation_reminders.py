"""
Comando para enviar recordatorios de check-in y check-out a través de notificaciones push
Se ejecuta diariamente para notificar a clientes sobre sus reservas próximas

Uso:
    python manage.py send_reservation_reminders
"""
from django.core.management.base import BaseCommand
from django.utils import timezone
from datetime import timedelta
from apps.reservation.models import Reservation
from apps.clients.expo_push_service import ExpoPushService, NotificationTypes
import logging

logger = logging.getLogger(__name__)


class Command(BaseCommand):
    help = 'Envía recordatorios push de check-in y check-out para reservas próximas'

    def add_arguments(self, parser):
        parser.add_argument(
            '--dry-run',
            action='store_true',
            help='Simula el envío de notificaciones sin enviarlas realmente'
        )
        parser.add_argument(
            '--days-ahead',
            type=int,
            default=1,
            help='Días de anticipación para recordatorios (default: 1 día antes)'
        )

    def handle(self, *args, **options):
        dry_run = options['dry_run']
        days_ahead = options['days_ahead']
        
        self.stdout.write(self.style.SUCCESS(
            f"{'[DRY RUN] ' if dry_run else ''}Iniciando envío de recordatorios de reservas..."
        ))
        
        # Calcular fechas objetivo (mañana para recordatorios de 1 día antes)
        today = timezone.now().date()
        target_date = today + timedelta(days=days_ahead)
        
        # Estadísticas
        stats = {
            'checkin_reminders_sent': 0,
            'checkout_reminders_sent': 0,
            'total_devices': 0,
            'failed': 0
        }
        
        # 1. RECORDATORIOS DE CHECK-IN (mañana hay check-in)
        self.stdout.write(f"\n🔔 Buscando check-ins para {target_date}...")
        
        checkin_reservations = Reservation.objects.filter(
            check_in_date=target_date,
            status__in=['approved', 'pago_confirmado', 'pagado', 'confirmed'],
            client__isnull=False,
            deleted=False
        ).select_related('client', 'property')
        
        for reservation in checkin_reservations:
            try:
                if dry_run:
                    self.stdout.write(
                        f"  [DRY RUN] Check-in reminder para {reservation.client.first_name} "
                        f"- {reservation.property.name}"
                    )
                else:
                    notification = NotificationTypes.checkin_reminder(reservation)
                    result = ExpoPushService.send_to_client(
                        client=reservation.client,
                        title=notification['title'],
                        body=notification['body'],
                        data=notification['data']
                    )
                    
                    if result.get('success'):
                        devices_sent = result.get('sent', 0)
                        stats['checkin_reminders_sent'] += 1
                        stats['total_devices'] += devices_sent
                        
                        self.stdout.write(
                            self.style.SUCCESS(
                                f"  ✅ Check-in reminder enviado a {reservation.client.first_name} "
                                f"({devices_sent} dispositivo(s)) - {reservation.property.name}"
                            )
                        )
                        logger.info(
                            f"Recordatorio de check-in enviado: Reserva {reservation.id}, "
                            f"Cliente {reservation.client.id}, {devices_sent} dispositivos"
                        )
                    else:
                        stats['failed'] += 1
                        self.stdout.write(
                            self.style.WARNING(
                                f"  ⚠️ No se pudo enviar a {reservation.client.first_name}: "
                                f"{result.get('message', 'Sin dispositivos')}"
                            )
                        )
                        
            except Exception as e:
                stats['failed'] += 1
                self.stdout.write(
                    self.style.ERROR(
                        f"  ❌ Error enviando recordatorio de check-in para reserva {reservation.id}: {str(e)}"
                    )
                )
                logger.error(f"Error enviando recordatorio de check-in: {str(e)}", exc_info=True)
        
        # 2. RECORDATORIOS DE CHECK-OUT (mañana hay check-out)
        self.stdout.write(f"\n🔔 Buscando check-outs para {target_date}...")
        
        checkout_reservations = Reservation.objects.filter(
            check_out_date=target_date,
            status__in=['approved', 'pago_confirmado', 'pagado', 'confirmed'],
            client__isnull=False,
            deleted=False
        ).select_related('client', 'property')
        
        for reservation in checkout_reservations:
            try:
                if dry_run:
                    self.stdout.write(
                        f"  [DRY RUN] Check-out reminder para {reservation.client.first_name} "
                        f"- {reservation.property.name}"
                    )
                else:
                    notification = NotificationTypes.checkout_reminder(reservation)
                    result = ExpoPushService.send_to_client(
                        client=reservation.client,
                        title=notification['title'],
                        body=notification['body'],
                        data=notification['data']
                    )
                    
                    if result.get('success'):
                        devices_sent = result.get('sent', 0)
                        stats['checkout_reminders_sent'] += 1
                        stats['total_devices'] += devices_sent
                        
                        self.stdout.write(
                            self.style.SUCCESS(
                                f"  ✅ Check-out reminder enviado a {reservation.client.first_name} "
                                f"({devices_sent} dispositivo(s)) - {reservation.property.name}"
                            )
                        )
                        logger.info(
                            f"Recordatorio de check-out enviado: Reserva {reservation.id}, "
                            f"Cliente {reservation.client.id}, {devices_sent} dispositivos"
                        )
                    else:
                        stats['failed'] += 1
                        self.stdout.write(
                            self.style.WARNING(
                                f"  ⚠️ No se pudo enviar a {reservation.client.first_name}: "
                                f"{result.get('message', 'Sin dispositivos')}"
                            )
                        )
                        
            except Exception as e:
                stats['failed'] += 1
                self.stdout.write(
                    self.style.ERROR(
                        f"  ❌ Error enviando recordatorio de check-out para reserva {reservation.id}: {str(e)}"
                    )
                )
                logger.error(f"Error enviando recordatorio de check-out: {str(e)}", exc_info=True)
        
        # Resumen final
        self.stdout.write("\n" + "="*60)
        self.stdout.write(self.style.SUCCESS(
            f"{'[DRY RUN] ' if dry_run else ''}Resumen de recordatorios:"
        ))
        self.stdout.write(f"  📅 Fecha objetivo: {target_date}")
        self.stdout.write(f"  📱 Check-in reminders: {stats['checkin_reminders_sent']}")
        self.stdout.write(f"  📱 Check-out reminders: {stats['checkout_reminders_sent']}")
        self.stdout.write(f"  📲 Total dispositivos: {stats['total_devices']}")
        
        if stats['failed'] > 0:
            self.stdout.write(
                self.style.WARNING(f"  ⚠️ Fallos: {stats['failed']}")
            )
        
        self.stdout.write("="*60 + "\n")
        
        if dry_run:
            self.stdout.write(
                self.style.WARNING(
                    "Este fue un dry-run. Ejecuta sin --dry-run para enviar notificaciones reales."
                )
            )
