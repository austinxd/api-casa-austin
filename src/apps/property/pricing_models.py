
from django.db import models
from django.core.validators import MinValueValidator, MaxValueValidator
from decimal import Decimal
from apps.core.models import BaseModel
from apps.property.models import Property
from apps.clients.models import Clients


class ExchangeRate(BaseModel):
    """Tipo de cambio USD a SOL"""
    usd_to_sol = models.DecimalField(
        max_digits=6, 
        decimal_places=3, 
        default=3.800,
        validators=[MinValueValidator(Decimal('1.000'))],
        help_text="Tipo de cambio de USD a SOL (ej: 3.800)"
    )
    is_active = models.BooleanField(default=True, help_text="Tipo de cambio activo")
    
    class Meta:
        verbose_name = "Tipo de Cambio"
        verbose_name_plural = "Tipos de Cambio"
        ordering = ['-created']
    
    def __str__(self):
        return f"1 USD = {self.usd_to_sol} SOL - {'Activo' if self.is_active else 'Inactivo'}"
    
    @classmethod
    def get_current_rate(cls):
        """Obtiene el tipo de cambio actual activo"""
        rate = cls.objects.filter(is_active=True).first()
        return rate.usd_to_sol if rate else Decimal('3.800')


class SeasonPricing(BaseModel):
    """Precios por temporada para propiedades"""
    
    class SeasonType(models.TextChoices):
        LOW = "low", ("Temporada Baja")
        HIGH = "high", ("Temporada Alta")
        PEAK = "peak", ("Temporada Peak")
    
    property = models.ForeignKey(Property, on_delete=models.CASCADE, related_name='season_pricing')
    season_type = models.CharField(max_length=4, choices=SeasonType.choices)
    start_date = models.DateField(help_text="Fecha de inicio de la temporada")
    end_date = models.DateField(help_text="Fecha de fin de la temporada")
    price_usd = models.DecimalField(
        max_digits=10, 
        decimal_places=2, 
        help_text="Precio base por noche en USD"
    )
    multiplier = models.DecimalField(
        max_digits=3, 
        decimal_places=2, 
        default=1.00,
        validators=[MinValueValidator(Decimal('0.50'))],
        help_text="Multiplicador del precio base (ej: 1.5 = 50% más caro)"
    )
    is_active = models.BooleanField(default=True)
    
    class Meta:
        verbose_name = "Precio de Temporada"
        verbose_name_plural = "Precios de Temporada"
        ordering = ['property', 'start_date']
    
    def __str__(self):
        return f"{self.property.name} - {self.get_season_type_display()} - ${self.price_usd}"


class DiscountCode(BaseModel):
    """Códigos de descuento"""
    
    class DiscountType(models.TextChoices):
        PERCENTAGE = "percentage", ("Porcentaje")
        FIXED_USD = "fixed_usd", ("Monto Fijo USD")
        FIXED_SOL = "fixed_sol", ("Monto Fijo SOL")
    
    code = models.CharField(max_length=20, unique=True, help_text="Código de descuento")
    description = models.CharField(max_length=200, help_text="Descripción del descuento")
    discount_type = models.CharField(max_length=10, choices=DiscountType.choices)
    discount_value = models.DecimalField(
        max_digits=10, 
        decimal_places=2,
        help_text="Valor del descuento (porcentaje sin % o monto fijo)"
    )
    min_amount_usd = models.DecimalField(
        max_digits=10, 
        decimal_places=2, 
        null=True, 
        blank=True,
        help_text="Monto mínimo en USD para aplicar descuento"
    )
    max_discount_usd = models.DecimalField(
        max_digits=10, 
        decimal_places=2, 
        null=True, 
        blank=True,
        help_text="Descuento máximo en USD (para porcentajes)"
    )
    start_date = models.DateField(help_text="Fecha de inicio de validez")
    end_date = models.DateField(help_text="Fecha de fin de validez")
    usage_limit = models.PositiveIntegerField(
        null=True, 
        blank=True, 
        help_text="Límite de usos (null = ilimitado)"
    )
    used_count = models.PositiveIntegerField(default=0, help_text="Veces usado")
    is_active = models.BooleanField(default=True)
    properties = models.ManyToManyField(
        Property, 
        blank=True, 
        help_text="Propiedades aplicables (vacío = todas)"
    )
    
    class Meta:
        verbose_name = "Código de Descuento"
        verbose_name_plural = "Códigos de Descuento"
        ordering = ['-created']
    
    def __str__(self):
        return f"{self.code} - {self.description}"
    
    def is_valid(self, property_id=None, total_amount_usd=None):
        """Verifica si el código de descuento es válido"""
        from django.utils import timezone
        from datetime import date
        
        today = date.today()
        
        # Verificar si está activo
        if not self.is_active:
            return False, "Código de descuento inactivo"
        
        # Verificar fechas
        if today < self.start_date or today > self.end_date:
            return False, "Código de descuento expirado o no válido aún"
        
        # Verificar límite de uso
        if self.usage_limit and self.used_count >= self.usage_limit:
            return False, "Código de descuento agotado"
        
        # Verificar propiedad
        if property_id and self.properties.exists():
            if not self.properties.filter(id=property_id).exists():
                return False, "Código no válido para esta propiedad"
        
        # Verificar monto mínimo
        if self.min_amount_usd and total_amount_usd and total_amount_usd < self.min_amount_usd:
            return False, f"Monto mínimo requerido: ${self.min_amount_usd}"
        
        return True, "Código válido"
    
    def calculate_discount(self, total_amount_usd):
        """Calcula el descuento en USD"""
        if self.discount_type == self.DiscountType.PERCENTAGE:
            discount = total_amount_usd * (self.discount_value / 100)
            if self.max_discount_usd:
                discount = min(discount, self.max_discount_usd)
            return discount
        elif self.discount_type == self.DiscountType.FIXED_USD:
            return min(self.discount_value, total_amount_usd)
        elif self.discount_type == self.DiscountType.FIXED_SOL:
            # Convertir SOL a USD
            exchange_rate = ExchangeRate.get_current_rate()
            discount_usd = self.discount_value / exchange_rate
            return min(discount_usd, total_amount_usd)
        
        return Decimal('0.00')


class AdditionalService(BaseModel):
    """Servicios adicionales disponibles"""
    
    class ServiceType(models.TextChoices):
        OPTIONAL = "optional", ("Opcional")
        MANDATORY = "mandatory", ("Obligatorio")
    
    name = models.CharField(max_length=100, help_text="Nombre del servicio")
    description = models.TextField(help_text="Descripción del servicio")
    price_usd = models.DecimalField(max_digits=10, decimal_places=2, help_text="Precio en USD")
    service_type = models.CharField(max_length=9, choices=ServiceType.choices, default=ServiceType.OPTIONAL)
    is_per_night = models.BooleanField(default=False, help_text="¿Se cobra por noche?")
    is_per_person = models.BooleanField(default=False, help_text="¿Se cobra por persona?")
    is_active = models.BooleanField(default=True)
    properties = models.ManyToManyField(
        Property, 
        blank=True, 
        help_text="Propiedades donde está disponible (vacío = todas)"
    )
    
    class Meta:
        verbose_name = "Servicio Adicional"
        verbose_name_plural = "Servicios Adicionales"
        ordering = ['name']
    
    def __str__(self):
        return f"{self.name} - ${self.price_usd}"
    
    def calculate_price(self, nights=1, guests=1):
        """Calcula el precio del servicio"""
        price = self.price_usd
        
        if self.is_per_night:
            price *= nights
        
        if self.is_per_person:
            price *= guests
        
        return price


class CancellationPolicy(BaseModel):
    """Políticas de cancelación"""
    
    name = models.CharField(max_length=100, help_text="Nombre de la política")
    description = models.TextField(help_text="Descripción detallada de la política")
    days_before_checkin = models.PositiveIntegerField(
        help_text="Días antes del check-in para aplicar esta política"
    )
    refund_percentage = models.DecimalField(
        max_digits=5, 
        decimal_places=2,
        validators=[MinValueValidator(Decimal('0.00')), MaxValueValidator(Decimal('100.00'))],
        help_text="Porcentaje de reembolso (0-100)"
    )
    is_default = models.BooleanField(default=False, help_text="¿Es la política por defecto?")
    is_active = models.BooleanField(default=True)
    properties = models.ManyToManyField(
        Property, 
        blank=True, 
        help_text="Propiedades aplicables (vacío = todas)"
    )
    
    class Meta:
        verbose_name = "Política de Cancelación"
        verbose_name_plural = "Políticas de Cancelación"
        ordering = ['days_before_checkin']
    
    def __str__(self):
        return f"{self.name} - {self.refund_percentage}% ({self.days_before_checkin} días antes)"
    
    @classmethod
    def get_applicable_policy(cls, property_id=None, days_before=None):
        """Obtiene la política aplicable"""
        policies = cls.objects.filter(is_active=True)
        
        if property_id:
            # Buscar política específica para la propiedad
            specific_policies = policies.filter(properties__id=property_id)
            if specific_policies.exists():
                policies = specific_policies
            else:
                # Si no hay específica, usar políticas generales
                policies = policies.filter(properties__isnull=True)
        
        if days_before is not None:
            # Encontrar la política más específica para los días
            policy = policies.filter(days_before_checkin__lte=days_before).order_by('-days_before_checkin').first()
            if policy:
                return policy
        
        # Retornar política por defecto
        return policies.filter(is_default=True).first()


class AutomaticDiscount(BaseModel):
    """Descuentos automáticos para clientes"""
    
    class DiscountTrigger(models.TextChoices):
        BIRTHDAY = "birthday", ("Mes de Cumpleaños")
        RETURNING = "returning", ("Cliente Recurrente")
        FIRST_TIME = "first_time", ("Primera Reserva")
        LOYALTY = "loyalty", ("Programa de Lealtad")
    
    name = models.CharField(max_length=100, help_text="Nombre del descuento automático")
    trigger = models.CharField(max_length=10, choices=DiscountTrigger.choices)
    discount_percentage = models.DecimalField(
        max_digits=5, 
        decimal_places=2,
        validators=[MinValueValidator(Decimal('0.00')), MaxValueValidator(Decimal('100.00'))],
        help_text="Porcentaje de descuento"
    )
    max_discount_usd = models.DecimalField(
        max_digits=10, 
        decimal_places=2, 
        null=True, 
        blank=True,
        help_text="Descuento máximo en USD"
    )
    min_reservations = models.PositiveIntegerField(
        default=1, 
        help_text="Mínimo de reservas previas (para cliente recurrente)"
    )
    is_active = models.BooleanField(default=True)
    
    class Meta:
        verbose_name = "Descuento Automático"
        verbose_name_plural = "Descuentos Automáticos"
        ordering = ['trigger']
    
    def __str__(self):
        return f"{self.name} - {self.discount_percentage}%"
    
    def applies_to_client(self, client):
        """Verifica si el descuento aplica al cliente"""
        if not self.is_active or not client:
            return False, "Descuento inactivo o cliente no válido"
        
        from datetime import date
        from apps.reservation.models import Reservation
        
        if self.trigger == self.DiscountTrigger.BIRTHDAY:
            if client.date and client.date.month == date.today().month:
                return True, f"Descuento por cumpleaños: {self.discount_percentage}%"
        
        elif self.trigger == self.DiscountTrigger.RETURNING:
            reservation_count = Reservation.objects.filter(
                client=client, 
                deleted=False,
                status__in=['approved', 'completed']
            ).count()
            if reservation_count >= self.min_reservations:
                return True, f"Descuento cliente recurrente: {self.discount_percentage}%"
        
        elif self.trigger == self.DiscountTrigger.FIRST_TIME:
            reservation_count = Reservation.objects.filter(
                client=client, 
                deleted=False
            ).count()
            if reservation_count == 0:
                return True, f"Descuento primera reserva: {self.discount_percentage}%"
        
        return False, "No aplica descuento automático"
    
    def calculate_discount(self, total_amount_usd):
        """Calcula el descuento en USD"""
        discount = total_amount_usd * (self.discount_percentage / 100)
        if self.max_discount_usd:
            discount = min(discount, self.max_discount_usd)
        return discount
