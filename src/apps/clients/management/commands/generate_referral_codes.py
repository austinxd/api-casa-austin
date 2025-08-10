
from django.core.management.base import BaseCommand
from apps.clients.models import Clients

class Command(BaseCommand):
    help = 'Genera códigos de referido para clientes existentes que no los tienen'

    def handle(self, *args, **options):
        clients_without_code = Clients.objects.filter(
            referral_code__isnull=True,
            deleted=False
        )
        
        generated_count = 0
        
        for client in clients_without_code:
            try:
                code = client.generate_referral_code()
                self.stdout.write(
                    self.style.SUCCESS(
                        f'Código generado para {client.first_name}: {code}'
                    )
                )
                generated_count += 1
            except Exception as e:
                self.stdout.write(
                    self.style.ERROR(
                        f'Error generando código para {client.first_name}: {str(e)}'
                    )
                )
        
        self.stdout.write(
            self.style.SUCCESS(
                f'Total de códigos generados: {generated_count}'
            )
        )
