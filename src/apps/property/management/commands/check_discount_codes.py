
from django.core.management.base import BaseCommand
from apps.property.pricing_models import DiscountCode
from decimal import Decimal
from datetime import date, timedelta

class Command(BaseCommand):
    help = 'Verifica y crea códigos de descuento si no existen'

    def handle(self, *args, **options):
        # Verificar si existe el código NUEVARESERVA
        nuevareserva_code = DiscountCode.objects.filter(
            code__iexact='NUEVARESERVA',
            deleted=False
        ).first()
        
        if not nuevareserva_code:
            # Crear el código NUEVARESERVA
            DiscountCode.objects.create(
                code='NUEVARESERVA',
                description='Descuento para nuevas reservas',
                discount_type='percentage',
                discount_value=Decimal('15.00'),  # 15% de descuento
                min_amount_usd=Decimal('50.00'),  # Mínimo $50
                max_discount_usd=Decimal('100.00'),  # Máximo $100 de descuento
                start_date=date.today(),
                end_date=date.today() + timedelta(days=365),  # Válido por 1 año
                usage_limit=None,  # Sin límite de uso
                is_active=True
            )
            self.stdout.write(
                self.style.SUCCESS('Código NUEVARESERVA creado exitosamente')
            )
        else:
            self.stdout.write(
                self.style.WARNING(f'Código NUEVARESERVA ya existe: {nuevareserva_code}')
            )
        
        # Listar todos los códigos activos
        active_codes = DiscountCode.objects.filter(is_active=True, deleted=False)
        self.stdout.write('\nCódigos activos:')
        for code in active_codes:
            self.stdout.write(f'- {code.code}: {code.description}')
