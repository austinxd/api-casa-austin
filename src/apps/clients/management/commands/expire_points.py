
from django.core.management.base import BaseCommand
from django.utils import timezone
from apps.clients.models import Clients


class Command(BaseCommand):
    help = 'Expira los puntos de clientes que han pasado la fecha de expiración'

    def handle(self, *args, **options):
        expired_clients = Clients.objects.filter(
            points_balance__gt=0,
            points_expires_at__lt=timezone.now(),
            deleted=False
        )
        
        expired_count = 0
        total_expired_points = 0
        
        for client in expired_clients:
            expired_points = float(client.points_balance)
            client.expire_points()
            expired_count += 1
            total_expired_points += expired_points
            
            self.stdout.write(
                self.style.WARNING(
                    f'Puntos expirados para {client.first_name} {client.last_name}: {expired_points} puntos'
                )
            )
        
        self.stdout.write(
            self.style.SUCCESS(
                f'Proceso completado: {expired_count} clientes afectados, {total_expired_points} puntos expirados en total'
            )
        )
