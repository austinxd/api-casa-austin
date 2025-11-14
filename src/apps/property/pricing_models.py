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
        verbose_name = "💱 Tipo de Cambio"
        verbose_name_plural = "💱 Tipos de Cambio"
        ordering = ['-created']

    def __str__(self):
        return f"1 USD = {self.usd_to_sol} SOL - {'Activo' if self.is_active else 'Inactivo'}"

    @classmethod
    def get_current_rate(cls):
        """Obtiene el tipo de cambio actual activo"""
        rate = cls.objects.filter(is_active=True).first()
        return rate.usd_to_sol if rate else Decimal('3.800')


class PropertyPricing(BaseModel):
    """Precios base de propiedades por temporada y tipo de día"""

    property = models.OneToOneField(Property, on_delete=models.CASCADE, related_name='pricing')

    # Precios base en temporada baja
    weekday_low_season_usd = models.DecimalField(
        max_digits=10,
        decimal_places=2,
        default=0,
        help_text="Precio base por noche de día de semana en temporada baja (Lunes-Jueves) en USD para 1 persona"
    )
    weekend_low_season_usd = models.DecimalField(
        max_digits=10,
        decimal_places=2,
        default=0,
        help_text="Precio base por noche de fin de semana en temporada baja (Viernes-Domingo) en USD para 1 persona"
    )

    # Precios base en temporada alta
    weekday_high_season_usd = models.DecimalField(
        max_digits=10,
        decimal_places=2,
        default=0,
        help_text="Precio base por noche de día de semana en temporada alta (Lunes-Jueves) en USD para 1 persona"
    )
    weekend_high_season_usd = models.DecimalField(
        max_digits=10,
        decimal_places=2,
        default=0,
        help_text="Precio base por noche de fin de semana en temporada alta (Viernes-Domingo) en USD para 1 persona"
    )

    class Meta:
        verbose_name = "💰 Precio Base de Propiedad"
        verbose_name_plural = "💰 Precios Base de Propiedades"

    def __str__(self):
        return f"Precios de {self.property.name}"

    def get_base_price_for_date(self, date):
        """Obtiene el precio base para una fecha específica considerando temporada y tipo de día"""

        # Verificar si es temporada alta usando el nuevo método de SeasonPricing
        is_high_season = SeasonPricing.is_high_season(date)

        # DEFINICIÓN EMPRESARIAL: Domingo-Jueves = días de semana, Viernes-Sábado = fin de semana
        weekday = date.weekday()  # 0=Lunes, 6=Domingo
        is_weekend = weekday in [4, 5]  # Viernes=4, Sábado=5

        if is_high_season:
            if is_weekend:
                return self.weekend_high_season_usd
            else:
                return self.weekday_high_season_usd
        else:
            if is_weekend:
                return self.weekend_low_season_usd
            else:
                return self.weekday_low_season_usd



    def calculate_total_price_for_date(self, date, guests=1):
        """Calcula el precio total para una fecha específica incluyendo huéspedes adicionales"""
        base_price = self.get_base_price_for_date(date)

        # Agregar precio por persona adicional (después de la primera)
        if guests > 1 and self.property.precio_extra_persona:
            additional_guests = guests - 1
            additional_cost = self.property.precio_extra_persona * additional_guests
            return base_price + additional_cost

        return base_price


class SeasonPricing(BaseModel):
    """Define períodos de temporada alta y baja GLOBALES recurrentes para todas las propiedades"""

    class SeasonType(models.TextChoices):
        LOW = "low", ("Temporada Baja")
        HIGH = "high", ("Temporada Alta")

    name = models.CharField(
        max_length=100,
        help_text="Nombre de la temporada (ej: 'Verano', 'Navidad y Año Nuevo', 'Fiestas Patrias')"
    )
    season_type = models.CharField(max_length=4, choices=SeasonType.choices)

    # Cambiar a mes y día para que sea recurrente cada año
    start_month = models.PositiveIntegerField(
        help_text="Mes de inicio (1-12)",
        validators=[MinValueValidator(1), MaxValueValidator(12)]
    )
    start_day = models.PositiveIntegerField(
        help_text="Día de inicio (1-31)",
        validators=[MinValueValidator(1), MaxValueValidator(31)]
    )
    end_month = models.PositiveIntegerField(
        help_text="Mes de fin (1-12)",
        validators=[MinValueValidator(1), MaxValueValidator(12)]
    )
    end_day = models.PositiveIntegerField(
        help_text="Día de fin (1-31)",
        validators=[MinValueValidator(1), MaxValueValidator(31)]
    )

    is_active = models.BooleanField(default=True)

    class Meta:
        verbose_name = "📅 Temporada Global Recurrente"
        verbose_name_plural = "📅 Temporadas Globales Recurrentes"
        ordering = ['start_month', 'start_day']

    def __str__(self):
        return f"{self.name} - {self.get_season_type_display()} ({self.start_day}/{self.start_month} - {self.end_day}/{self.end_month})"

    def get_date_range_display(self):
        """Devuelve el rango de fechas en formato legible"""
        months = [
            "", "Enero", "Febrero", "Marzo", "Abril", "Mayo", "Junio",
            "Julio", "Agosto", "Septiembre", "Octubre", "Noviembre", "Diciembre"
        ]
        start_month_name = months[self.start_month]
        end_month_name = months[self.end_month]
        return f"{self.start_day} de {start_month_name} - {self.end_day} de {end_month_name}"

    def is_date_in_season(self, date):
        """Verifica si una fecha específica está dentro de esta temporada"""
        month = date.month
        day = date.day

        # Crear tuplas para comparar (mes, día)
        date_tuple = (month, day)
        start_tuple = (self.start_month, self.start_day)
        end_tuple = (self.end_month, self.end_day)

        # Caso 1: La temporada no cruza el año (ej: 15/06 - 15/09)
        if start_tuple <= end_tuple:
            return start_tuple <= date_tuple <= end_tuple

        # Caso 2: La temporada cruza el año (ej: 15/12 - 15/03)
        else:
            return date_tuple >= start_tuple or date_tuple <= end_tuple

    @classmethod
    def is_high_season(cls, date):
        """Verifica si una fecha está en temporada alta GLOBALMENTE"""
        high_seasons = cls.objects.filter(
            season_type=cls.SeasonType.HIGH,
            is_active=True
        )

        for season in high_seasons:
            if season.is_date_in_season(date):
                return True

        return False

    @classmethod
    def get_season_for_date(cls, date):
        """Obtiene la temporada para una fecha específica"""
        seasons = cls.objects.filter(is_active=True)

        for season in seasons:
            if season.is_date_in_season(date):
                return season

        return None


class SpecialDatePricing(BaseModel):
    """Precios especiales para fechas recurrentes anuales"""

    property = models.ForeignKey(Property, on_delete=models.CASCADE, related_name='special_date_pricing')

    # Cambiar a mes y día para que sea recurrente cada año
    month = models.PositiveIntegerField(
        help_text="Mes de la fecha especial (1-12)",
        validators=[MinValueValidator(1), MaxValueValidator(12)]
    )
    day = models.PositiveIntegerField(
        help_text="Día de la fecha especial (1-31)",
        validators=[MinValueValidator(1), MaxValueValidator(31)]
    )

    description = models.CharField(
        max_length=100,
        blank=True,
        null=True,
        help_text="Descripción del día especial (ej: Año Nuevo, Navidad, Día de la Madre)"
    )
    price_usd = models.DecimalField(
        max_digits=10,
        decimal_places=2,
        help_text="Precio base especial por noche en USD para 1 persona"
    )
    minimum_consecutive_nights = models.PositiveIntegerField(
        default=1,
        validators=[MinValueValidator(1)],
        help_text="Número mínimo de noches consecutivas requeridas para esta fecha especial"
    )
    is_active = models.BooleanField(default=True)

    class Meta:
        verbose_name = "🎉 Precio Fecha Especial Recurrente"
        verbose_name_plural = "🎉 Precios Fechas Especiales Recurrentes"
        ordering = ['property', 'month', 'day']
        unique_together = ['property', 'month', 'day']

    def __str__(self):
        return f"{self.property.name} - {self.description} ({self.day}/{self.month}) - ${self.price_usd}"

    def get_date_display(self):
        """Devuelve la fecha en formato legible"""
        months = [
            "", "Enero", "Febrero", "Marzo", "Abril", "Mayo", "Junio",
            "Julio", "Agosto", "Septiembre", "Octubre", "Noviembre", "Diciembre"
        ]
        month_name = months[self.month]
        return f"{self.day} de {month_name}"

    def is_date_special(self, date):
        """Verifica si una fecha específica coincide con esta fecha especial"""
        return date.month == self.month and date.day == self.day

    @classmethod
    def get_special_price_for_date(cls, property, date):
        """Obtiene el precio especial para una fecha específica de una propiedad"""
        special_date = cls.objects.filter(
            property=property,
            month=date.month,
            day=date.day,
            is_active=True
        ).first()

        return special_date

    def calculate_total_price(self, guests=1):
        """Calcula el precio total incluyendo huéspedes adicionales"""
        base_price = self.price_usd

        # Agregar precio por persona adicional (después de la primera)
        if guests > 1 and self.property.precio_extra_persona:
            additional_guests = guests - 1
            additional_cost = self.property.precio_extra_persona * additional_guests
            return base_price + additional_cost

        return base_price


class DiscountCode(BaseModel):
    """Códigos de descuento"""

    class DiscountType(models.TextChoices):
        PERCENTAGE = "percentage", ("Porcentaje")
        FIXED_USD = "fixed_usd", ("Monto Fijo USD")
        FIXED_SOL = "fixed_sol", ("Monto Fijo SOL")

    code = models.CharField(max_length=50, unique=True, help_text="Código de descuento")
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

    # Restricciones por días de la semana
    restrict_weekdays = models.BooleanField(
        default=False,
        help_text="Restringir solo a noches de semana (domingo a jueves)"
    )
    restrict_weekends = models.BooleanField(
        default=False,
        help_text="Restringir solo a noches de fin de semana (viernes y sábado)"
    )
    
    # Aplicar solo al precio base
    apply_only_to_base_price = models.BooleanField(
        default=False,
        help_text="Si está activo, el descuento solo se aplica al precio base (sin incluir huéspedes adicionales)"
    )

    class Meta:
        verbose_name = "🎫 Código de Descuento"
        verbose_name_plural = "🎫 Códigos de Descuento"
        ordering = ['-created']

    def __str__(self):
        return f"{self.code} - {self.description}"

    def is_valid(self, property_id=None, total_amount_usd=None, booking_date=None):
        """Verifica si el código de descuento es válido"""
        from django.utils import timezone
        from datetime import date

        today = date.today()

        # Para códigos de descuento, normally validamos si está vigente HOY
        # Solo usar booking_date para restricciones de días
        check_date = today

        # Si se proporciona booking_date, convertirlo para restricciones de días
        booking_check_date = None
        if booking_date:
            if isinstance(booking_date, str):
                from datetime import datetime
                try:
                    booking_check_date = datetime.strptime(booking_date, '%Y-%m-%d').date()
                except ValueError:
                    booking_check_date = today
            elif hasattr(booking_date, 'date'):
                booking_check_date = booking_date.date()
            else:
                booking_check_date = booking_date
        else:
            # Si no hay booking_date, usar fecha actual para validación general
            # pero no aplicar restricciones de días específicos
            booking_check_date = today

        # Verificar si está activo y no eliminado
        if not self.is_active or self.deleted:
            return False, "Código de descuento inactivo"

        # Debug logging para fechas
        import logging
        logger = logging.getLogger(__name__)
        logger.info(f"Validando fechas - Hoy: {today}, Check date: {check_date}, Start: {self.start_date}, End: {self.end_date}")

        # Verificar fechas
        if check_date < self.start_date:
            logger.info(f"Código no válido - fecha muy temprana: {check_date} < {self.start_date}")
            return False, f"Código válido desde {self.start_date.strftime('%d/%m/%Y')}"

        if check_date > self.end_date:
            logger.info(f"Código expirado - fecha muy tardía: {check_date} > {self.end_date}")
            return False, f"Código expiró el {self.end_date.strftime('%d/%m/%Y')}"

        logger.info(f"Fechas válidas - Código activo")

        # Verificar restricciones por día de la semana (SIEMPRE usar fecha de reserva si se proporciona)
        # Si no se proporciona booking_date, NO aplicar restricciones de días
        if not booking_check_date or booking_check_date == today:
            logger.info(f"⚠️ No se proporcionó fecha de check-in válida para validar restricciones de días")
            # Si no hay fecha de reserva válida, omitir validación de días de semana
            # Esto permite que la cotización funcione pero la reserva real requiere fecha
            if self.restrict_weekdays or self.restrict_weekends:
                logger.info(f"ℹ️ Código tiene restricciones de días pero no se puede validar sin fecha de check-in")
        else:
            day_check_date = booking_check_date

            # Verificar restricciones de días de la semana
            # DEFINICIÓN EMPRESARIAL: Domingo-Jueves = días de semana, Viernes-Sábado = fin de semana
            weekday = day_check_date.weekday()  # 0=Lunes, 6=Domingo
            is_weekend = weekday in [4, 5]  # Viernes=4, Sábado=5
            is_weekday = weekday in [6, 0, 1, 2, 3]  # Domingo=6, Lunes=0, Martes=1, Miércoles=2, Jueves=3

            day_names = ['Lunes', 'Martes', 'Miércoles', 'Jueves', 'Viernes', 'Sábado', 'Domingo']
            day_name = day_names[weekday]

            logger.info(f"📅 Validando día del check-in: {day_check_date} - {weekday} ({day_name}) - {'Fin de semana' if is_weekend else 'Día de semana'}")
            logger.info(f"📅 Según definición empresarial: Domingo-Jueves=semana, Viernes-Sábado=fin de semana")

            if self.restrict_weekdays and not is_weekday:
                logger.info(f"❌ Restringido a días de semana pero check-in {day_check_date} ({day_name}) es fin de semana")
                return False, f"Descuento solo válido para check-in en días de semana (Domingo a Jueves). El check-in seleccionado cae en {day_name}."

            if self.restrict_weekends and not is_weekend:
                logger.info(f"❌ Restringido a fines de semana pero check-in {day_check_date} ({day_name}) es día de semana")
                return False, f"Descuento solo válido para check-in en fines de semana (Viernes y Sábado). El check-in seleccionado cae en {day_name}."
            
            # Verificar configuración ambigua
            if self.restrict_weekdays and self.restrict_weekends:
                # Si ambos están marcados, es un error de configuración
                logger.info(f"❌ Configuración ambigua: ambas restricciones activadas")
                return False, "Configuración de restricción de días ambigua (semana y fin de semana)."


        # Verificar límite de uso
        if self.usage_limit and self.used_count >= self.usage_limit:
            return False, f"Código agotado ({self.used_count}/{self.usage_limit} usos)"

        # Verificar propiedad - El código DEBE tener propiedades específicas asignadas
        if not self.properties.exists():
            return False, "Este código no tiene propiedades asignadas y no es válido"

        if not property_id:
            return False, "Este código requiere especificar una propiedad"

        if not self.properties.filter(id=property_id, deleted=False).exists():
            property_names = list(self.properties.filter(deleted=False).values_list('name', flat=True))
            return False, f"Código válido solo para: {', '.join(property_names)}"

        # Verificar monto mínimo
        if self.min_amount_usd and total_amount_usd and total_amount_usd < self.min_amount_usd:
            return False, f"Monto mínimo requerido: ${self.min_amount_usd:.2f} (actual: ${total_amount_usd:.2f})"

        # NUEVA VALIDACIÓN: Verificar que no sea fecha especial
        if booking_check_date and property_id:
            # Verificar si la fecha de reserva es una fecha especial
            special_date = SpecialDatePricing.objects.filter(
                property_id=property_id,
                month=booking_check_date.month,
                day=booking_check_date.day,
                is_active=True
            ).first()

            if special_date:
                return False, f"Los códigos de descuento no son válidos para fechas especiales como {special_date.description} ({booking_check_date.strftime('%d/%m')})"

        return True, f"Código válido - Descuento aplicado: {self.discount_value}{'%' if self.discount_type == 'percentage' else ' USD'}"

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
    post_action = models.CharField(
        max_length=50,
        blank=True,
        null=True,
        help_text="Acción post-reserva que debe realizar el frontend (ej: temperature_pool)"
    )

    class Meta:
        verbose_name = "🛎️ Servicio Adicional"
        verbose_name_plural = "🛎️ Servicios Adicionales"
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
        verbose_name = "📋 Política de Cancelación"
        verbose_name_plural = "📋 Políticas de Cancelación"
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
        RETURNING = "returning", ("Cliente Frecuente")
        FIRST_TIME = "first_time", ("Primera Reserva")
        LOYALTY = "loyalty", ("Programa de Lealtad")
        LAST_MINUTE = "last_minute", ("Último Minuto")
        GLOBAL_PROMOTION = "global_promotion", ("Promoción Global")

    name = models.CharField(max_length=100, help_text="Nombre del descuento automático")
    description = models.TextField(
        blank=True,
        null=True,
        help_text="Descripción detallada del descuento automático y sus condiciones"
    )
    trigger = models.CharField(max_length=20, choices=DiscountTrigger.choices)
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
    required_achievements = models.ManyToManyField(
        'clients.Achievement',
        blank=True,
        help_text="Logros requeridos para aplicar este descuento automático"
    )
    restrict_weekdays = models.BooleanField(
        default=False,
        help_text="Si está activo, el descuento solo aplica para días de semana (Lunes a Viernes)"
    )
    restrict_weekends = models.BooleanField(
        default=False,
        help_text="Si está activo, el descuento solo aplica para fines de semana (Sábado y Domingo)"
    )
    specific_weekdays = models.CharField(
        max_length=20,
        blank=True,
        null=True,
        help_text="Días específicos de la semana (0=Lun,1=Mar,2=Mié,3=Jue,4=Vie,5=Sáb,6=Dom). Ej: '4' para solo Viernes, '4,5' para Viernes y Sábado"
    )
    is_active = models.BooleanField(default=True)
    start_date = models.DateField(null=True, blank=True, help_text="Fecha de inicio de validez del descuento (opcional)")
    end_date = models.DateField(null=True, blank=True, help_text="Fecha de fin de validez del descuento (opcional)")
    apply_only_to_base_price = models.BooleanField(
        default=False, 
        help_text="Si está activo, el descuento solo se aplica al precio base (sin incluir huéspedes adicionales)"
    )


    class Meta:
        verbose_name = "🤖 Descuento Automático"
        verbose_name_plural = "🤖 Descuentos Automáticos"

    def __str__(self):
        return f"{self.name} ({self.get_trigger_display()})"

    def applies_to_client(self, client, booking_date, property_id=None):
        """Verifica si el descuento automático aplica al cliente"""
        from apps.reservation.models import Reservation
        from apps.clients.models import ClientAchievement, Achievement
        from datetime import date
        import logging

        logger = logging.getLogger(__name__)
        logger.info(f"🔍 Evaluando descuento '{self.name}' con trigger '{self.trigger}'")

        if not self.is_active:
            logger.info(f"❌ Descuento no está activo")
            return False, "Descuento no activo"

        # Verificar validez por fechas (si están definidas)
        if self.start_date and booking_date < self.start_date:
            logger.info(f"❌ Descuento no válido hasta: {self.start_date}")
            return False, f"Descuento válido desde {self.start_date.strftime('%d/%m/%Y')}"

        if self.end_date and booking_date > self.end_date:
            logger.info(f"❌ Descuento expiró el: {self.end_date}")
            return False, f"Descuento expiró el {self.end_date.strftime('%d/%m/%Y')}"

        # Verificar restricciones de días de la semana
        weekday = booking_date.weekday()  # 0=Lunes, 6=Domingo
        is_weekend = weekday in [4, 5]  # Viernes=4, Sábado=5
        is_weekday = weekday in [6, 0, 1, 2, 3]  # Domingo=6, Lunes=0, Martes=1, Miércoles=2, Jueves=3

        day_names = ['Lunes', 'Martes', 'Miércoles', 'Jueves', 'Viernes', 'Sábado', 'Domingo']
        day_name = day_names[weekday]

        logger.info(f"📅 Día de la semana: {weekday} ({day_name}) - {'Fin de semana' if is_weekend else 'Día de semana'}")
        logger.info(f"📅 Según definición empresarial: Domingo-Jueves=semana, Viernes-Sábado=fin de semana")

        # Verificar días específicos (tiene prioridad sobre restrict_weekdays/weekends)
        if self.specific_weekdays:
            specific_days = [int(d.strip()) for d in self.specific_weekdays.split(',') if d.strip().isdigit()]
            if weekday not in specific_days:
                allowed_day_names = [day_names[d] for d in specific_days if 0 <= d <= 6]
                logger.info(f"❌ Restringido a días específicos: {', '.join(allowed_day_names)}, pero hoy es {day_name}")
                return False, f"Descuento solo válido para: {', '.join(allowed_day_names)}. Hoy es {day_name}."
            logger.info(f"✅ Día {day_name} está en días específicos permitidos")
        elif self.restrict_weekdays and not is_weekday:
            logger.info(f"❌ Restringido a días de semana pero {day_name} es fin de semana")
            return False, f"Descuento solo válido para días de semana (Domingo a Jueves). Hoy es {day_name}."
        elif self.restrict_weekends and not is_weekend:
            logger.info(f"❌ Restringido a fines de semana pero {day_name} es día de semana")
            return False, f"Descuento solo válido para fines de semana (Viernes y Sábado). Hoy es {day_name}."

        # NUEVA VALIDACIÓN: Verificar que no sea fecha especial
        if property_id:
            # Verificar si la fecha de reserva es una fecha especial para esta propiedad específica
            special_date = SpecialDatePricing.objects.filter(
                property_id=property_id,
                month=booking_date.month,
                day=booking_date.day,
                is_active=True
            ).first()

            if special_date:
                logger.info(f"❌ Fecha especial detectada: {special_date.description}")
                return False, f"Los descuentos automáticos no aplican en fechas especiales como {special_date.description} ({booking_date.strftime('%d/%m')})"
        else:
            # Si no hay property_id específico, verificar si es fecha especial para CUALQUIER propiedad
            special_dates = SpecialDatePricing.objects.filter(
                month=booking_date.month,
                day=booking_date.day,
                is_active=True
            )

            if special_dates.exists():
                special_descriptions = list(special_dates.values_list('description', flat=True).distinct())
                logger.info(f"❌ Fecha especial detectada: {special_descriptions}")
                return False, f"Los descuentos automáticos no aplican en fechas especiales como {', '.join(special_descriptions)} ({booking_date.strftime('%d/%m')})"

        # Verificar si el cliente tiene los logros requeridos
        if self.required_achievements.exists():
            logger.info(f"🏆 Verificando logros requeridos...")

            # Obtener TODOS los logros del cliente
            client_achievements = ClientAchievement.objects.filter(
                client=client
            ).select_related('achievement')

            if not client_achievements.exists():
                logger.info(f"❌ Cliente no tiene ningún logro")
                required_names = list(self.required_achievements.values_list('name', flat=True))
                return False, f"Requiere tener uno de estos logros: {', '.join(required_names)}"

            # Obtener los IDs de logros que tiene el cliente
            client_achievement_ids = set(client_achievements.values_list('achievement__id', flat=True))
            client_achievement_names = list(client_achievements.values_list('achievement__name', flat=True))
            
            logger.info(f"🏆 Logros del cliente: {client_achievement_names}")
            logger.info(f"🏆 IDs de logros del cliente: {client_achievement_ids}")

            # Verificar si alguno de los logros del cliente está en los requeridos
            required_achievement_ids = set(self.required_achievements.values_list('id', flat=True))
            required_names = list(self.required_achievements.values_list('name', flat=True))

            logger.info(f"🏆 Logros requeridos: {required_names}")
            logger.info(f"🏆 IDs requeridos: {required_achievement_ids}")

            # Verificar si hay intersección entre los logros del cliente y los requeridos
            matching_achievements = client_achievement_ids.intersection(required_achievement_ids)
            
            if not matching_achievements:
                logger.info(f"❌ El cliente no tiene ninguno de los logros requeridos")
                return False, f"Este descuento es exclusivo para: {', '.join(required_names)}. Tus logros actuales ({', '.join(client_achievement_names)}) no califican."

            # Obtener nombres de los logros que coinciden
            matching_achievement_names = list(
                self.required_achievements.filter(id__in=matching_achievements).values_list('name', flat=True)
            )
            logger.info(f"✅ El cliente tiene los siguientes logros requeridos: {matching_achievement_names}")
        else:
            logger.info(f"🏆 Sin logros requeridos - descuento disponible para todos los clientes")

        # Evaluar triggers específicos
        logger.info(f"🎯 Evaluando trigger: {self.trigger}")

        if self.trigger == self.DiscountTrigger.BIRTHDAY:
            logger.info(f"🎂 Verificando cumpleaños - Mes cliente: {client.date.month if client.date else 'N/A'}, Mes booking: {booking_date.month}")
            if client.date and client.date.month == booking_date.month:
                return True, f"¡Feliz cumpleaños! {self.discount_percentage}% de descuento"
            else:
                return False, f"No es su mes de cumpleaños"

        elif self.trigger == self.DiscountTrigger.RETURNING:
            reservations_count = Reservation.objects.filter(
                client=client,
                deleted=False,
                status__in=['approved', 'completed']  # Solo contar reservas exitosas
            ).count()
            logger.info(f"🔄 Cliente frecuente - Reservas previas: {reservations_count}")
            if reservations_count >= 1:  # Al menos una reserva previa
                return True, f"Cliente frecuente: {self.discount_percentage}% de descuento"
            else:
                return False, f"No tiene reservas previas (tiene {reservations_count})"

        elif self.trigger == self.DiscountTrigger.FIRST_TIME:
            reservations_count = Reservation.objects.filter(
                client=client,
                deleted=False
            ).count()
            logger.info(f"🆕 Primera reserva - Reservas previas: {reservations_count}")
            if reservations_count == 0:
                return True, f"¡Bienvenido! {self.discount_percentage}% de descuento en tu primera reserva"
            else:
                return False, f"Ya tiene reservas previas ({reservations_count})"

        elif self.trigger == self.DiscountTrigger.LOYALTY:
            logger.info(f"🏆 Programa de lealtad - Requiere logros específicos")
            # Para programa de lealtad, verificar que tenga al menos los logros requeridos
            if self.required_achievements.exists():
                return True, f"Programa de lealtad: {self.discount_percentage}% de descuento"
            else:
                return False, f"Programa de lealtad requiere logros específicos"

        elif self.trigger == self.DiscountTrigger.LAST_MINUTE:
            from datetime import date, timedelta
            today = date.today()
            tomorrow = today + timedelta(days=1)

            logger.info(f"⏰ Último minuto - Hoy: {today}, Mañana: {tomorrow}, Booking: {booking_date}")

            # Verificar si la fecha de check-in es hoy o mañana
            if booking_date == today:
                return True, f"¡Reserva para hoy! {self.discount_percentage}% de descuento último minuto"
            elif booking_date == tomorrow:
                return True, f"¡Reserva para mañana! {self.discount_percentage}% de descuento último minuto"
            else:
                return False, f"No es reserva de último minuto (booking: {booking_date})"

        elif self.trigger == self.DiscountTrigger.GLOBAL_PROMOTION:
            logger.info(f"🌍 Promoción global - Aplicable para todos los clientes")
            return True, f"Descuento por tiempo limitado: {self.discount_percentage}% de descuento"
        
        

        logger.info(f"❌ Trigger '{self.trigger}' no reconocido")
        return False, "Trigger no reconocido"

    def applies_to_client_global(self, booking_date, property_id=None):
        """Verifica si el descuento automático global aplica (sin cliente específico)"""
        from datetime import date, timedelta
        import logging

        logger = logging.getLogger(__name__)
        logger.info(f"🌍 Evaluando descuento GLOBAL '{self.name}' con trigger '{self.trigger}'")

        if not self.is_active:
            logger.info(f"❌ Descuento no está activo")
            return False, "Descuento no activo"

        # Verificar validez por fechas (si están definidas)
        if self.start_date and booking_date < self.start_date:
            logger.info(f"❌ Descuento no válido hasta: {self.start_date}")
            return False, f"Descuento válido desde {self.start_date.strftime('%d/%m/%Y')}"

        if self.end_date and booking_date > self.end_date:
            logger.info(f"❌ Descuento expiró el: {self.end_date}")
            return False, f"Descuento expiró el {self.end_date.strftime('%d/%m/%Y')}"

        # Verificar restricciones de días de la semana
        weekday = booking_date.weekday()  # 0=Lunes, 6=Domingo
        is_weekend = weekday in [4, 5]  # Viernes=4, Sábado=5
        is_weekday = weekday in [6, 0, 1, 2, 3]  # Domingo=6, Lunes=0, Martes=1, Miércoles=2, Jueves=3

        day_names = ['Lunes', 'Martes', 'Miércoles', 'Jueves', 'Viernes', 'Sábado', 'Domingo']
        day_name = day_names[weekday]

        logger.info(f"📅 Día de la semana: {weekday} ({day_name}) - {'Fin de semana' if is_weekend else 'Día de semana'}")
        logger.info(f"📅 Según definición empresarial: Domingo-Jueves=semana, Viernes-Sábado=fin de semana")

        # Verificar días específicos (tiene prioridad sobre restrict_weekdays/weekends)
        if self.specific_weekdays:
            specific_days = [int(d.strip()) for d in self.specific_weekdays.split(',') if d.strip().isdigit()]
            if weekday not in specific_days:
                allowed_day_names = [day_names[d] for d in specific_days if 0 <= d <= 6]
                logger.info(f"❌ Restringido a días específicos: {', '.join(allowed_day_names)}, pero hoy es {day_name}")
                return False, f"Descuento solo válido para: {', '.join(allowed_day_names)}. Hoy es {day_name}."
            logger.info(f"✅ Día {day_name} está en días específicos permitidos")
        elif self.restrict_weekdays and not is_weekday:
            logger.info(f"❌ Restringido a días de semana pero {day_name} es fin de semana")
            return False, f"Descuento solo válido para días de semana (Domingo a Jueves). Hoy es {day_name}."
        elif self.restrict_weekends and not is_weekend:
            logger.info(f"❌ Restringido a fines de semana pero {day_name} es día de semana")
            return False, f"Descuento solo válido para fines de semana (Viernes y Sábado). Hoy es {day_name}."

        # Verificar que no sea fecha especial
        if property_id:
            special_date = SpecialDatePricing.objects.filter(
                property_id=property_id,
                month=booking_date.month,
                day=booking_date.day,
                is_active=True
            ).first()

            if special_date:
                logger.info(f"❌ Fecha especial detectada: {special_date.description}")
                return False, f"Los descuentos automáticos no aplican en fechas especiales como {special_date.description} ({booking_date.strftime('%d/%m')})"
        else:
            special_dates = SpecialDatePricing.objects.filter(
                month=booking_date.month,
                day=booking_date.day,
                is_active=True
            )

            if special_dates.exists():
                special_descriptions = list(special_dates.values_list('description', flat=True).distinct())
                logger.info(f"❌ Fecha especial detectada: {special_descriptions}")
                return False, f"Los descuentos automáticos no aplican en fechas especiales como {', '.join(special_descriptions)} ({booking_date.strftime('%d/%m')})"

        # Para descuentos globales, solo evaluar triggers que no requieren cliente específico
        logger.info(f"🎯 Evaluando trigger global: {self.trigger}")

        if self.trigger == self.DiscountTrigger.LAST_MINUTE:
            today = date.today()
            tomorrow = today + timedelta(days=1)

            logger.info(f"⏰ Último minuto - Hoy: {today}, Mañana: {tomorrow}, Booking: {booking_date}")

            if booking_date == today:
                return True, "Descuento por tiempo limitado"
            elif booking_date == tomorrow:
                return True, "Descuento por tiempo limitado"
            else:
                return False, f"No es reserva de último minuto (booking: {booking_date})"

        elif self.trigger == self.DiscountTrigger.LOYALTY:
            # Para descuentos globales de lealtad, siempre aplicar
            logger.info(f"🏆 Descuento global de lealtad")
            return True, f"Descuento por tiempo limitado: {self.discount_percentage}% de descuento"

        elif self.trigger == self.DiscountTrigger.GLOBAL_PROMOTION:
            # Para promociones globales, siempre aplicar
            logger.info(f"🌍 Promoción global - Aplicable sin cliente")
            return True, "Descuento por tiempo limitado"

        # Otros triggers que podrían ser globales
        elif self.trigger in [self.DiscountTrigger.FIRST_TIME, self.DiscountTrigger.RETURNING, self.DiscountTrigger.BIRTHDAY]:
            # Estos triggers normally requieren cliente, pero si es global, aplicar como "tiempo limitado"
            logger.info(f"🌍 Trigger {self.trigger} aplicado globalmente")
            return True, f"Descuento por tiempo limitado: {self.discount_percentage}% de descuento"

        logger.info(f"❌ Trigger '{self.trigger}' no reconocido para descuento global")
        return False, "Trigger no reconocido para descuento global"

    def calculate_discount(self, total_amount_usd):
        """Calcula el descuento en USD"""
        discount = total_amount_usd * (self.discount_percentage / 100)
        if self.max_discount_usd:
            discount = min(discount, self.max_discount_usd)
        return discount
    
    def calculate_base_price_discount(self, base_price_usd, extra_person_total_usd):
        """
        Calcula el descuento aplicado SOLO al precio base (sin huéspedes adicionales)
        
        Args:
            base_price_usd: Precio base de la estadía (sin huéspedes adicionales)
            extra_person_total_usd: Precio total de huéspedes adicionales
            
        Returns:
            Decimal: Monto del descuento aplicado solo al precio base
        """
        # Calcular descuento solo sobre el precio base
        base_discount = base_price_usd * (self.discount_percentage / 100)
        
        # Aplicar límite máximo si existe
        if self.max_discount_usd:
            base_discount = min(base_discount, self.max_discount_usd)
            
        return base_discount


class DynamicDiscountConfig(BaseModel):
    """Configuración para generar códigos de descuento dinámicos"""

    name = models.CharField(max_length=100, help_text="Nombre de la configuración")
    prefix = models.CharField(max_length=10, help_text="Prefijo para los códigos generados (ej: PROMO)")
    discount_percentage = models.DecimalField(
        max_digits=5,
        decimal_places=2,
        validators=[MinValueValidator(Decimal('1.00')), MaxValueValidator(Decimal('100.00'))],
        help_text="Porcentaje de descuento"
    )
    validity_days = models.PositiveIntegerField(
        default=7,
        help_text="Días de validez desde la creación del código"
    )
    min_amount_usd = models.DecimalField(
        max_digits=10,
        decimal_places=2,
        default=Decimal('30.00'),
        help_text="Monto mínimo en USD para aplicar descuento"
    )
    max_discount_usd = models.DecimalField(
        max_digits=10,
        decimal_places=2,
        null=True,
        blank=True,
        help_text="Descuento máximo en USD"
    )
    usage_limit = models.PositiveIntegerField(
        default=1,
        help_text="Límite de usos por código generado"
    )
    properties = models.ManyToManyField(
        Property,
        blank=True,
        help_text="Propiedades donde serán válidos los códigos generados (vacío = todas)"
    )
    apply_only_to_base_price = models.BooleanField(
        default=False,
        help_text="Si está activo, los códigos generados solo se aplicarán al precio base (sin incluir huéspedes adicionales)"
    )
    restrict_weekdays = models.BooleanField(
        default=False,
        help_text="Si está activo, los códigos generados solo serán válidos para noches de semana (domingo a jueves)"
    )
    restrict_weekends = models.BooleanField(
        default=False,
        help_text="Si está activo, los códigos generados solo serán válidos para fines de semana (viernes y sábado)"
    )
    is_active = models.BooleanField(default=True)

    class Meta:
        verbose_name = "⚡ Generador de Códigos Dinámicos"
        verbose_name_plural = "⚡ Generadores de Códigos Dinámicos"

    def __str__(self):
        return f"{self.name} ({self.prefix}XX - {self.discount_percentage}%)"

    def generate_code(self):
        """Genera un nuevo código de descuento dinámico"""
        import random
        import string
        from datetime import date, timedelta

        # Generar código único
        suffix = ''.join(random.choices(string.ascii_uppercase + string.digits, k=6))
        code = f"{self.prefix}{suffix}"

        # Verificar que el código no exista
        while DiscountCode.objects.filter(code=code).exists():
            suffix = ''.join(random.choices(string.ascii_uppercase + string.digits, k=6))
            code = f"{self.prefix}{suffix}"

        # Calcular fechas
        start_date = date.today()
        end_date = start_date + timedelta(days=self.validity_days)

        # Crear el código de descuento
        discount_code = DiscountCode.objects.create(
            code=code,
            description=f"Descuento dinámico {self.discount_percentage}% - {self.name}",
            discount_type='percentage',
            discount_value=self.discount_percentage,
            start_date=start_date,
            end_date=end_date,
            usage_limit=self.usage_limit,
            min_amount_usd=self.min_amount_usd,
            max_discount_usd=self.max_discount_usd,
            apply_only_to_base_price=self.apply_only_to_base_price,
            restrict_weekdays=self.restrict_weekdays,
            restrict_weekends=self.restrict_weekends,
            is_active=True
        )

        # Asignar propiedades si están definidas
        if self.properties.exists():
            discount_code.properties.set(self.properties.all())

        return discount_code


class LateCheckoutConfig(BaseModel):
    """Configuración para late checkout por día de la semana"""
    
    WEEKDAY_CHOICES = [
        (0, 'Lunes'),
        (1, 'Martes'), 
        (2, 'Miércoles'),
        (3, 'Jueves'),
        (4, 'Viernes'),
        (5, 'Sábado'),
        (6, 'Domingo'),
    ]
    
    name = models.CharField(max_length=100, verbose_name="Nombre de configuración")
    weekday = models.IntegerField(choices=WEEKDAY_CHOICES, verbose_name="Día de la semana")
    allows_late_checkout = models.BooleanField(default=True, verbose_name="Permite late checkout")
    discount_type = models.CharField(
        max_length=10, 
        choices=[('percentage', 'Porcentaje'), ('fixed', 'Monto fijo')],
        default='percentage',
        verbose_name="Tipo de descuento"
    )
    discount_value = models.DecimalField(
        max_digits=10, 
        decimal_places=2, 
        default=Decimal('10.00'),
        verbose_name="Valor del descuento"
    )
    is_active = models.BooleanField(default=True, verbose_name="Activo")
    
    class Meta:
        verbose_name = "Configuración de Late Checkout"
        verbose_name_plural = "Configuraciones de Late Checkout"
        unique_together = ['weekday']
    
    def __str__(self):
        return f"{self.get_weekday_display()} - {'Permite' if self.allows_late_checkout else 'No permite'} late checkout"
    
    @classmethod
    def allows_late_checkout_for_date(cls, check_date):
        """Verifica si se permite late checkout para una fecha específica"""
        weekday = check_date.weekday()
        config = cls.objects.filter(weekday=weekday, is_active=True).first()
        
        if not config:
            # Por defecto, permitir late checkout excepto viernes y sábados
            return weekday not in [4, 5]  # 4=Viernes, 5=Sábado
        
        return config.allows_late_checkout
    
    @classmethod
    def get_discount_for_date(cls, check_date, base_amount):
        """Calcula el descuento de late checkout para una fecha específica"""
        weekday = check_date.weekday()
        config = cls.objects.filter(weekday=weekday, is_active=True).first()
        
        if not config or not config.allows_late_checkout:
            return Decimal('0.00')
        
        if config.discount_type == 'percentage':
            return base_amount * (config.discount_value / Decimal('100'))
        else:  # fixed
            return config.discount_value


class WelcomeDiscountConfig(BaseModel):
    """Configuración para descuentos de bienvenida a nuevos usuarios"""
    
    name = models.CharField(
        max_length=200,
        default="Descuento de Bienvenida",
        help_text="Nombre descriptivo de la configuración"
    )
    is_active = models.BooleanField(
        default=False,
        help_text="Si está activo, los nuevos usuarios registrados recibirán este descuento"
    )
    discount_percentage = models.DecimalField(
        max_digits=5,
        decimal_places=2,
        help_text="Porcentaje de descuento (ej: 15.00 para 15%)"
    )
    validity_days = models.PositiveIntegerField(
        default=14,
        help_text="Días de validez del código desde su emisión"
    )
    min_amount_usd = models.DecimalField(
        max_digits=10,
        decimal_places=2,
        default=Decimal('0.00'),
        help_text="Monto mínimo de reserva en USD para aplicar el descuento"
    )
    max_discount_usd = models.DecimalField(
        max_digits=10,
        decimal_places=2,
        null=True,
        blank=True,
        help_text="Descuento máximo en USD (opcional)"
    )
    
    # Restricciones de días
    restrict_weekdays = models.BooleanField(
        default=False,
        help_text="Restringir solo a noches de semana (domingo a jueves)"
    )
    restrict_weekends = models.BooleanField(
        default=False,
        help_text="Restringir solo a noches de fin de semana (viernes y sábado)"
    )
    specific_weekdays = models.CharField(
        max_length=20,
        blank=True,
        null=True,
        help_text="Días específicos de la semana (0=Lun,1=Mar,2=Mié,3=Jue,4=Vie,5=Sáb,6=Dom). Ej: '4' para solo Viernes, '4,5' para Viernes y Sábado"
    )
    
    # Aplicar solo al precio base
    apply_only_to_base_price = models.BooleanField(
        default=False,
        help_text="Si está activo, el descuento solo se aplica al precio base (sin incluir huéspedes adicionales)"
    )
    
    # Mensaje promocional personalizado
    promotional_message = models.CharField(
        max_length=500,
        blank=True,
        null=True,
        help_text="Mensaje personalizado para mostrar en la web (ej: '¡Regístrate hoy y recibe 15% OFF!'). Si está vacío, se genera automáticamente."
    )
    
    # Subtítulo o condiciones adicionales
    promotional_subtitle = models.CharField(
        max_length=300,
        blank=True,
        null=True,
        help_text="Texto adicional en letras pequeñas (ej: 'Válido solo para reservas de 3+ noches' o 'No aplica en días festivos')"
    )
    
    # Propiedades aplicables
    properties = models.ManyToManyField(
        Property,
        blank=True,
        help_text="Propiedades donde será válido el descuento (vacío = todas)"
    )
    
    class Meta:
        verbose_name = "🎁 Configuración de Descuento de Bienvenida"
        verbose_name_plural = "🎁 Configuraciones de Descuento de Bienvenida"
    
    def __str__(self):
        status = "✅ ACTIVO" if self.is_active else "❌ Inactivo"
        return f"{self.name} - {self.discount_percentage}% ({status})"
    
    def get_promotional_message(self):
        """Obtiene el mensaje promocional personalizado o genera uno por defecto"""
        if self.promotional_message:
            return self.promotional_message
        return f"¡Regístrate y recibe {self.discount_percentage}% de descuento en tu primera reserva!"
    
    def save(self, *args, **kwargs):
        """Asegurar que solo haya una configuración activa a la vez"""
        if self.is_active:
            # Desactivar todas las demás configuraciones
            WelcomeDiscountConfig.objects.filter(is_active=True).exclude(pk=self.pk).update(is_active=False)
        super().save(*args, **kwargs)
    
    def generate_welcome_code(self, client):
        """Genera un código de bienvenida único para un cliente"""
        from datetime import date, timedelta
        import random
        import string
        import logging
        
        logger = logging.getLogger(__name__)
        
        # Generar código único con longitud validada
        suffix = ''.join(random.choices(string.ascii_uppercase + string.digits, k=6))
        code = f"WELCOME-{suffix}"
        
        # Validar longitud del código (max_length=50 en el modelo)
        if len(code) > 50:
            raise ValueError(f"El código generado '{code}' excede el límite de 50 caracteres")
        
        # Verificar que no existe (máximo 10 intentos para evitar loops infinitos)
        attempts = 0
        max_attempts = 10
        while DiscountCode.objects.filter(code=code).exists() and attempts < max_attempts:
            suffix = ''.join(random.choices(string.ascii_uppercase + string.digits, k=6))
            code = f"WELCOME-{suffix}"
            attempts += 1
        
        if attempts >= max_attempts:
            raise ValueError("No se pudo generar un código único después de 10 intentos")
        
        # Calcular fechas
        start_date = date.today()
        end_date = start_date + timedelta(days=self.validity_days)
        
        logger.info(f"🎫 Generando código de bienvenida: {code} (longitud: {len(code)} chars)")
        
        # Crear el código de descuento
        try:
            discount_code = DiscountCode.objects.create(
                code=code,
                description=f"Descuento de bienvenida para {client.get_full_name() if hasattr(client, 'get_full_name') else client.email}",
                discount_type='percentage',
                discount_value=self.discount_percentage,
                start_date=start_date,
                end_date=end_date,
                usage_limit=1,
                min_amount_usd=self.min_amount_usd,
                max_discount_usd=self.max_discount_usd,
                restrict_weekdays=self.restrict_weekdays,
                restrict_weekends=self.restrict_weekends,
                specific_weekdays=self.specific_weekdays,
                apply_only_to_base_price=self.apply_only_to_base_price,
                is_active=True
            )
            logger.info(f"✅ Código creado exitosamente en base de datos: {code}")
        except Exception as e:
            logger.error(f"❌ Error al crear código de descuento en BD: {str(e)}")
            logger.error(f"   Código: {code} (longitud: {len(code)})")
            logger.error(f"   Tipo de error: {type(e).__name__}")
            raise  # Re-lanzar la excepción para que se maneje arriba
        
        # Asignar propiedades si están definidas
        if self.properties.exists():
            discount_code.properties.set(self.properties.all())
        
        return discount_code
    
    @classmethod
    def get_active_config(cls):
        """Obtiene la configuración activa actual"""
        return cls.objects.filter(is_active=True).first()