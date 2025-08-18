
from django.core.management.base import BaseCommand
from apps.clients.models import Clients, Achievement, ClientAchievement


class Command(BaseCommand):
    help = 'Verifica y otorga logros a todos los clientes que los merezcan'

    def add_arguments(self, parser):
        parser.add_argument(
            '--achievement-id',
            type=int,
            help='ID específico de logro a verificar',
        )

    def handle(self, *args, **options):
        achievement_id = options.get('achievement_id')
        
        if achievement_id:
            try:
                achievements = [Achievement.objects.get(id=achievement_id, is_active=True)]
                self.stdout.write(f'Verificando logro específico: {achievements[0].name}')
            except Achievement.DoesNotExist:
                self.stdout.write(
                    self.style.ERROR(f'Logro con ID {achievement_id} no encontrado o inactivo')
                )
                return
        else:
            achievements = Achievement.objects.filter(is_active=True, deleted=False)
            self.stdout.write(f'Verificando {achievements.count()} logros activos...')

        clients = Clients.objects.filter(deleted=False)
        total_awarded = 0

        for achievement in achievements:
            self.stdout.write(f'\nVerificando logro: {achievement.name}')
            achievement_awarded = 0
            
            for client in clients:
                if achievement.check_client_qualifies(client):
                    # Verificar si ya tiene el logro
                    if not ClientAchievement.objects.filter(
                        client=client, 
                        achievement=achievement
                    ).exists():
                        ClientAchievement.objects.create(
                            client=client, 
                            achievement=achievement
                        )
                        achievement_awarded += 1
                        total_awarded += 1
                        self.stdout.write(
                            f'  ✓ Logro otorgado a: {client.first_name} {client.last_name}'
                        )
            
            if achievement_awarded == 0:
                self.stdout.write(f'  - No se otorgaron nuevos logros para: {achievement.name}')
            else:
                self.stdout.write(
                    self.style.SUCCESS(
                        f'  ✓ {achievement_awarded} logros otorgados para: {achievement.name}'
                    )
                )

        self.stdout.write(
            self.style.SUCCESS(f'\n¡Completado! Total de logros otorgados: {total_awarded}')
        )
