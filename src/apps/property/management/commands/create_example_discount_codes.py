from django.core.management.base import BaseCommand
from apps.property.pricing_models import DiscountCode
from decimal import Decimal
from datetime import date, timedelta


class Command(BaseCommand):
    help = 'Crea códigos de descuento de ejemplo con diferentes restricciones'

    def handle(self, *args, **options):
        # Código para días de semana
        weekday_code, created = DiscountCode.objects.get_or_create(
            code='SEMANA20',
            defaults={
                'description': 'Descuento 20% para noches de semana',
                'discount_type': 'percentage',
                'discount_value': Decimal('20.00'),
                'min_amount_usd': Decimal('50.00'),
                'start_date': date.today(),
                'end_date': date.today() + timedelta(days=365),
                'restrict_weekdays': True,
                'restrict_weekends': False,
                'is_active': True
            }
        )

        if created:
            self.stdout.write(
                self.style.SUCCESS(f'✅ Código SEMANA20 creado - Solo para noches de semana')
            )
        else:
            self.stdout.write(
                self.style.WARNING(f'⚠️ Código SEMANA20 ya existe')
            )

        # Código para fines de semana
        weekend_code, created = DiscountCode.objects.get_or_create(
            code='WEEKEND15',
            defaults={
                'description': 'Descuento 15% para noches de fin de semana',
                'discount_type': 'percentage',
                'discount_value': Decimal('15.00'),
                'min_amount_usd': Decimal('80.00'),
                'start_date': date.today(),
                'end_date': date.today() + timedelta(days=365),
                'restrict_weekdays': False,
                'restrict_weekends': True,
                'is_active': True
            }
        )

        if created:
            self.stdout.write(
                self.style.SUCCESS(f'✅ Código WEEKEND15 creado - Solo para noches de fin de semana')
            )
        else:
            self.stdout.write(
                self.style.WARNING(f'⚠️ Código WEEKEND15 ya existe')
            )

        # Código sin restricciones
        general_code, created = DiscountCode.objects.get_or_create(
            code='GENERAL10',
            defaults={
                'description': 'Descuento 10% para cualquier día',
                'discount_type': 'percentage',
                'discount_value': Decimal('10.00'),
                'min_amount_usd': Decimal('30.00'),
                'start_date': date.today(),
                'end_date': date.today() + timedelta(days=365),
                'restrict_weekdays': False,
                'restrict_weekends': False,
                'is_active': True
            }
        )

        if created:
            self.stdout.write(
                self.style.SUCCESS(f'✅ Código GENERAL10 creado - Para cualquier día')
            )
        else:
            self.stdout.write(
                self.style.WARNING(f'⚠️ Código GENERAL10 ya existe')
            )

        self.stdout.write(
            self.style.SUCCESS('\n🎯 Códigos de ejemplo creados exitosamente:')
        )
        self.stdout.write('• SEMANA20: 20% descuento solo para noches de semana (domingo-jueves)')
        self.stdout.write('• WEEKEND15: 15% descuento solo para noches de fin de semana (viernes-sábado)')
        self.stdout.write('• GENERAL10: 10% descuento para cualquier día')