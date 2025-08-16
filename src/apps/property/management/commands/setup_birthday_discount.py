
from django.core.management.base import BaseCommand
from apps.property.pricing_models import AutomaticDiscount
from decimal import Decimal


class Command(BaseCommand):
    help = 'Configura el descuento automático por mes de cumpleaños'

    def handle(self, *args, **options):
        # Verificar si existe el descuento por cumpleaños
        birthday_discount = AutomaticDiscount.objects.filter(
            trigger=AutomaticDiscount.DiscountTrigger.BIRTHDAY,
            is_active=True,
            deleted=False
        ).first()
        
        if not birthday_discount:
            # Crear el descuento por cumpleaños
            birthday_discount = AutomaticDiscount.objects.create(
                name='Descuento Mes de Cumpleaños',
                trigger=AutomaticDiscount.DiscountTrigger.BIRTHDAY,
                discount_percentage=Decimal('15.00'),  # 15% de descuento
                max_discount_usd=Decimal('50.00'),  # Máximo $50 de descuento
                is_active=True
            )
            self.stdout.write(
                self.style.SUCCESS(f'Descuento automático por cumpleaños creado: {birthday_discount}')
            )
        else:
            self.stdout.write(
                self.style.WARNING(f'Descuento por cumpleaños ya existe: {birthday_discount}')
            )
        
        # Listar todos los descuentos automáticos activos
        active_discounts = AutomaticDiscount.objects.filter(is_active=True, deleted=False)
        self.stdout.write('\nDescuentos automáticos activos:')
        for discount in active_discounts:
            self.stdout.write(f'- {discount.name}: {discount.discount_percentage}% ({discount.get_trigger_display()})')
