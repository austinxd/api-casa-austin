
from django.core.management.base import BaseCommand
from apps.property.pricing_models import (
    ExchangeRate, 
    CancellationPolicy, 
    AutomaticDiscount,
    AdditionalService
)
from decimal import Decimal


class Command(BaseCommand):
    help = 'Configura valores por defecto para el sistema de precios'

    def handle(self, *args, **options):
        self.stdout.write('Configurando valores por defecto...')
        
        # Crear tipo de cambio por defecto
        if not ExchangeRate.objects.filter(is_active=True).exists():
            ExchangeRate.objects.create(
                usd_to_sol=Decimal('3.800'),
                is_active=True
            )
            self.stdout.write(self.style.SUCCESS('Tipo de cambio por defecto creado: 1 USD = 3.800 SOL'))
        
        # Crear política de cancelación por defecto
        if not CancellationPolicy.objects.filter(is_default=True).exists():
            CancellationPolicy.objects.create(
                name="Política Estándar",
                description="Cancelación gratuita hasta 7 días antes del check-in. Después de este período, se retiene el 50% del pago.",
                days_before_checkin=7,
                refund_percentage=Decimal('50.00'),
                is_default=True,
                is_active=True
            )
            self.stdout.write(self.style.SUCCESS('Política de cancelación por defecto creada'))
        
        # Crear descuentos automáticos por defecto
        if not AutomaticDiscount.objects.filter(trigger='birthday').exists():
            AutomaticDiscount.objects.create(
                name="Descuento Cumpleaños",
                trigger="birthday",
                discount_percentage=Decimal('10.00'),
                max_discount_usd=Decimal('50.00'),
                is_active=True
            )
            self.stdout.write(self.style.SUCCESS('Descuento por cumpleaños creado'))
        
        if not AutomaticDiscount.objects.filter(trigger='returning').exists():
            returning_discount = AutomaticDiscount.objects.create(
                name="Cliente Recurrente",
                trigger="returning",
                discount_percentage=Decimal('5.00'),
                max_discount_usd=Decimal('30.00'),
                is_active=True
            )
            self.stdout.write(self.style.SUCCESS('Descuento cliente recurrente creado'))
        
        if not AutomaticDiscount.objects.filter(trigger='first_time').exists():
            AutomaticDiscount.objects.create(
                name="Primera Reserva",
                trigger="first_time",
                discount_percentage=Decimal('15.00'),
                max_discount_usd=Decimal('75.00'),
                is_active=True
            )
            self.stdout.write(self.style.SUCCESS('Descuento primera reserva creado'))
        
        if not AutomaticDiscount.objects.filter(trigger='last_minute').exists():
            AutomaticDiscount.objects.create(
                name="Último Minuto",
                description="Descuento especial para reservas realizadas para el día de hoy o mañana",
                trigger="last_minute",
                discount_percentage=Decimal('20.00'),
                max_discount_usd=Decimal('100.00'),
                is_active=True
            )
            self.stdout.write(self.style.SUCCESS('Descuento último minuto creado'))
        
        # Crear servicios adicionales por defecto
        services = [
            {
                'name': 'Limpieza Adicional',
                'description': 'Servicio de limpieza extra durante la estancia',
                'price_usd': Decimal('25.00'),
                'service_type': 'optional',
                'is_per_night': False,
                'is_per_person': False,
                'post_action': None
            },
            {
                'name': 'Desayuno',
                'description': 'Desayuno continental para huéspedes',
                'price_usd': Decimal('15.00'),
                'service_type': 'optional',
                'is_per_night': True,
                'is_per_person': True,
                'post_action': None
            },
            {
                'name': 'Transfer Aeropuerto',
                'description': 'Traslado desde/hacia el aeropuerto',
                'price_usd': Decimal('30.00'),
                'service_type': 'optional',
                'is_per_night': False,
                'is_per_person': False,
                'post_action': None
            },
            {
                'name': 'Calentamiento de Piscina',
                'description': 'Servicio de calentamiento de piscina durante la estancia',
                'price_usd': Decimal('50.00'),
                'service_type': 'optional',
                'is_per_night': True,
                'is_per_person': False,
                'post_action': 'temperature_pool'
            }
        ]
        
        for service_data in services:
            if not AdditionalService.objects.filter(name=service_data['name']).exists():
                AdditionalService.objects.create(**service_data)
                self.stdout.write(self.style.SUCCESS(f'Servicio adicional creado: {service_data["name"]}'))
        
        self.stdout.write(self.style.SUCCESS('¡Configuración completada exitosamente!'))
