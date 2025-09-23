"""
Management command para notificar ganadores de eventos cuando llega la fecha de anuncio
Ejecutar con: python manage.py notify_event_winners
"""

from django.core.management.base import BaseCommand
from django.utils import timezone
from apps.events.models import EventRegistration


class Command(BaseCommand):
    help = 'Notifica a ganadores de eventos cuando llega su fecha de anuncio'

    def handle(self, *args, **options):
        now = timezone.now().date()
        
        # Buscar ganadores que necesitan ser notificados
        pending_notifications = EventRegistration.objects.filter(
            winner_status=EventRegistration.WinnerStatus.WINNER,
            winner_notified=False,
            winner_announcement_date__lte=now  # Fecha de anuncio ya pasó o es hoy
        )
        
        notifications_sent = 0
        errors = 0
        
        for registration in pending_notifications:
            try:
                self.stdout.write(f"Notificando a {registration.client.first_name} del evento '{registration.event.title}'...")
                
                # Enviar notificación
                registration._notify_winner()
                notifications_sent += 1
                
                self.stdout.write(
                    self.style.SUCCESS(f"✅ Notificado: {registration.client.first_name}")
                )
                
            except Exception as e:
                errors += 1
                self.stdout.write(
                    self.style.ERROR(f"❌ Error notificando a {registration.client.first_name}: {e}")
                )
        
        # Resumen final
        if notifications_sent > 0 or errors > 0:
            self.stdout.write(f"\n📊 Resumen:")
            self.stdout.write(f"   ✅ Notificaciones enviadas: {notifications_sent}")
            if errors > 0:
                self.stdout.write(f"   ❌ Errores: {errors}")
        else:
            self.stdout.write("📭 No hay ganadores pendientes de notificar hoy.")