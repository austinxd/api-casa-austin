
from django.core.management.base import BaseCommand
from django.utils import timezone
from datetime import date, timedelta
from decimal import Decimal
from apps.property.pricing_models import DiscountCode


class Command(BaseCommand):
    help = 'Crea códigos de descuento de ejemplo con restricciones de días'

    def handle(self, *args, **options):
        # Código para días de semana
        weekday_code, created = DiscountCode.objects.get_or_create(
            code='DIASEMANA20',
            defaults={
                'description': 'Descuento 20% para reservas en días de semana',
                'discount_type': 'percentage',
                'discount_value': Decimal('20.00'),
                'min_amount_usd': Decimal('100.00'),
                'max_discount_usd': Decimal('150.00'),
                'start_date': date.today(),
                'end_date': date.today() + timedelta(days=365),
                'restrict_weekdays': True,  # Solo días de semana
                'restrict_weekends': False,
                'min_nights': 2,  # Mínimo 2 noches
                'is_active': True
            }
        )
        
        if created:
            self.stdout.write(
                self.style.SUCCESS(f'✅ Código DIASEMANA20 creado - Solo días de semana (Lunes-Jueves)')
            )
        else:
            self.stdout.write(
                self.style.WARNING(f'⚠️ Código DIASEMANA20 ya existe')
            )

        # Código para fines de semana
        weekend_code, created = DiscountCode.objects.get_or_create(
            code='FINDESEMANA15',
            defaults={
                'description': 'Descuento 15% para reservas de fin de semana',
                'discount_type': 'percentage',
                'discount_value': Decimal('15.00'),
                'min_amount_usd': Decimal('80.00'),
                'max_discount_usd': Decimal('120.00'),
                'start_date': date.today(),
                'end_date': date.today() + timedelta(days=365),
                'restrict_weekdays': False,
                'restrict_weekends': True,  # Solo fines de semana
                'min_nights': 2,  # Mínimo 2 noches
                'is_active': True
            }
        )
        
        if created:
            self.stdout.write(
                self.style.SUCCESS(f'✅ Código FINDESEMANA15 creado - Solo fines de semana (Viernes-Domingo)')
            )
        else:
            self.stdout.write(
                self.style.WARNING(f'⚠️ Código FINDESEMANA15 ya existe')
            )

        # Código para estancias largas
        long_stay_code, created = DiscountCode.objects.get_or_create(
            code='ESTANCIALARGA',
            defaults={
                'description': 'Descuento 25% para estancias de 7+ noches',
                'discount_type': 'percentage',
                'discount_value': Decimal('25.00'),
                'min_amount_usd': Decimal('200.00'),
                'max_discount_usd': Decimal('300.00'),
                'start_date': date.today(),
                'end_date': date.today() + timedelta(days=365),
                'restrict_weekdays': False,
                'restrict_weekends': False,
                'min_nights': 7,  # Mínimo 7 noches
                'max_nights': None,
                'is_active': True
            }
        )
        
        if created:
            self.stdout.write(
                self.style.SUCCESS(f'✅ Código ESTANCIALARGA creado - Mínimo 7 noches')
            )
        else:
            self.stdout.write(
                self.style.WARNING(f'⚠️ Código ESTANCIALARGA ya existe')
            )

        # Código para estancias cortas
        short_stay_code, created = DiscountCode.objects.get_or_create(
            code='ESCAPADA10',
            defaults={
                'description': 'Descuento 10% para escapadas de 1-3 noches',
                'discount_type': 'percentage',
                'discount_value': Decimal('10.00'),
                'min_amount_usd': Decimal('50.00'),
                'max_discount_usd': Decimal('75.00'),
                'start_date': date.today(),
                'end_date': date.today() + timedelta(days=365),
                'restrict_weekdays': False,
                'restrict_weekends': False,
                'min_nights': 1,
                'max_nights': 3,  # Máximo 3 noches
                'is_active': True
            }
        )
        
        if created:
            self.stdout.write(
                self.style.SUCCESS(f'✅ Código ESCAPADA10 creado - Máximo 3 noches')
            )
        else:
            self.stdout.write(
                self.style.WARNING(f'⚠️ Código ESCAPADA10 ya existe')
            )

        self.stdout.write('\n📋 Resumen de códigos con restricciones:')
        self.stdout.write('• DIASEMANA20: 20% descuento solo días de semana (L-J), mín. 2 noches')
        self.stdout.write('• FINDESEMANA15: 15% descuento solo fines de semana (V-D), mín. 2 noches') 
        self.stdout.write('• ESTANCIALARGA: 25% descuento para estancias de 7+ noches')
        self.stdout.write('• ESCAPADA10: 10% descuento para escapadas de 1-3 noches')
