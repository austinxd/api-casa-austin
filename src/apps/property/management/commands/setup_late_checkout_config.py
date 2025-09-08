
from django.core.management.base import BaseCommand
from apps.property.pricing_models import LateCheckoutConfig
from decimal import Decimal


class Command(BaseCommand):
    help = 'Configura las configuraciones por defecto de late checkout'

    def handle(self, *args, **options):
        # Configuraciones por defecto
        configs = [
            {'weekday': 0, 'name': 'Late Checkout Lunes', 'allows_late_checkout': True, 'discount_value': Decimal('10.00')},
            {'weekday': 1, 'name': 'Late Checkout Martes', 'allows_late_checkout': True, 'discount_value': Decimal('10.00')},
            {'weekday': 2, 'name': 'Late Checkout Miércoles', 'allows_late_checkout': True, 'discount_value': Decimal('10.00')},
            {'weekday': 3, 'name': 'Late Checkout Jueves', 'allows_late_checkout': True, 'discount_value': Decimal('10.00')},
            {'weekday': 4, 'name': 'Late Checkout Viernes', 'allows_late_checkout': False, 'discount_value': Decimal('0.00')},
            {'weekday': 5, 'name': 'Late Checkout Sábado', 'allows_late_checkout': False, 'discount_value': Decimal('0.00')},
            {'weekday': 6, 'name': 'Late Checkout Domingo', 'allows_late_checkout': True, 'discount_value': Decimal('15.00')},
        ]
        
        for config_data in configs:
            config, created = LateCheckoutConfig.objects.get_or_create(
                weekday=config_data['weekday'],
                defaults=config_data
            )
            
            if created:
                self.stdout.write(
                    self.style.SUCCESS(f'Creada configuración para {config.get_weekday_display()}')
                )
            else:
                self.stdout.write(
                    self.style.WARNING(f'Configuración para {config.get_weekday_display()} ya existe')
                )
        
        self.stdout.write(self.style.SUCCESS('Configuración de late checkout completada'))
