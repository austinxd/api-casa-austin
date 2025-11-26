from django.db import models

from apps.core.models import BaseModel

class MensajeFidelidad(models.Model):
    activo = models.BooleanField(default=True)
    mensaje = models.CharField(
        max_length=255,
        null=False,
        blank=False, 
        help_text="Mensaje que se enviará a los clientes luego de saludarlos. Ej: Hola Augusto, --mensaje--"
    )

class ReferralPointsConfig(models.Model):
    """Configuración del porcentaje de puntos por referidos"""
    percentage = models.DecimalField(
        max_digits=5, 
        decimal_places=2, 
        default=10.00,
        help_text="Porcentaje de puntos que recibe el cliente que refirió (ej: 10.00 = 10%)"
    )
    is_active = models.BooleanField(default=True, help_text="Activar/desactivar el sistema de referidos")
    created = models.DateTimeField(auto_now_add=True)
    updated = models.DateTimeField(auto_now=True)
    
    class Meta:
        verbose_name = "Configuración de Puntos por Referidos"
        verbose_name_plural = "Configuración de Puntos por Referidos"
        ordering = ['-created']
    
    def __str__(self):
        return f"Referidos: {self.percentage}% - {'Activo' if self.is_active else 'Inactivo'}"
    
    @classmethod
    def get_current_config(cls):
        """Obtiene la configuración actual activa"""
        return cls.objects.filter(is_active=True).first()

class TokenApiClients(BaseModel):
    token = models.CharField(max_length=250, null=False, blank=False)

    class Meta:
        verbose_name = "Token rutificador"
        verbose_name_plural = "Tokens rutificadores"
        ordering = ['-created']

    def __str__(self):
        return f"Token: {self.token} creado: {self.created}"

class Clients(BaseModel):
    class DocumentTypeChoice(models.TextChoices):
        DNI = "dni", ("Documento Nacional de Identidad")
        CARNET_EXTRANJERIA = "cex", ("Carnet de Extranjeria")
        PAS = "pas", ("Pasaporte")
        RUC = "ruc", ("RUC")

    class GeneroChoice(models.TextChoices):
        M = "m", ("Masculino")
        F = "f", ("Femenino")
        E = "e", ("Empresa")

    document_type = models.CharField(
        max_length=3,
        choices=DocumentTypeChoice.choices,
        default=DocumentTypeChoice.DNI,
        null=False,
        blank=False
    )
    number_doc = models.CharField(max_length=50, null=False, blank=False, default="1")
    first_name = models.CharField(max_length=30, null=False, blank=False, default="nombre")
    last_name = models.CharField(max_length=40, null=True, blank=True)
    sex = models.CharField(
        max_length=1, choices=GeneroChoice.choices, default=None, null=True, blank=True
    )

    email = models.EmailField(max_length=150, null=True, blank=True)
    date = models.DateField(null=True)
    tel_number = models.CharField(max_length=50, null=False, blank=False)
    enviado_meta = models.BooleanField(default=False, help_text="Indica si el cliente ha sido enviado a Meta Ads")


    manychat = models.PositiveIntegerField(null=True, blank=True)
    id_manychat = models.CharField(max_length=255, null=True, blank=True)
    comentarios_clientes = models.TextField(blank=True, null=True, help_text="Comentarios sobre el cliente")
    
    # Campos de autenticación
    password = models.CharField(max_length=128, null=True, blank=True, help_text="Contraseña hasheada del cliente")
    is_password_set = models.BooleanField(default=False, help_text="Indica si el cliente ya configuró su contraseña")
    otp_code = models.CharField(max_length=6, null=True, blank=True, help_text="Código OTP temporal")
    otp_expires_at = models.DateTimeField(null=True, blank=True, help_text="Fecha de expiración del OTP")
    last_login = models.DateTimeField(null=True, blank=True, help_text="Último login del cliente")
    
    # Integración con Facebook OAuth
    facebook_id = models.CharField(max_length=100, null=True, blank=True, help_text="ID único de Facebook del usuario")
    facebook_linked = models.BooleanField(default=False, help_text="Indica si el cliente ha vinculado su cuenta de Facebook")
    facebook_profile_data = models.JSONField(null=True, blank=True, help_text="Datos del perfil de Facebook (nombre, foto, etc.)")
    facebook_linked_at = models.DateTimeField(null=True, blank=True, help_text="Fecha en que se vinculó la cuenta de Facebook")
    
    # Descuento de bienvenida
    welcome_discount_issued = models.BooleanField(default=False, help_text="Indica si ya se le emitió un código de descuento de bienvenida")
    welcome_discount_issued_at = models.DateTimeField(null=True, blank=True, help_text="Fecha en que se emitió el código de bienvenida")
    
    # Sistema de puntos
    points_balance = models.DecimalField(max_digits=10, decimal_places=2, default=0, help_text="Balance actual de puntos")
    points_expires_at = models.DateTimeField(null=True, blank=True, help_text="Fecha de expiración de los puntos actuales")
    
    # Sistema de referidos
    referred_by = models.ForeignKey('self', on_delete=models.SET_NULL, null=True, blank=True, help_text="Cliente que refirió a este cliente")
    referral_code = models.CharField(max_length=8, unique=True, null=True, blank=True, help_text="Código de referido único y corto")

    class Meta:
        unique_together = ('document_type', 'number_doc')
    
    def calculate_points_from_reservation(self, price_sol):
        """Calcula puntos basado en el precio en soles (5%)"""
        from decimal import Decimal
        return Decimal(str(float(price_sol) * 0.05))
    
    def add_points(self, points, reservation, description="Puntos ganados por reserva"):
        """Agrega puntos al cliente y actualiza la fecha de expiración"""
        from datetime import datetime, timedelta
        from django.utils import timezone
        from decimal import Decimal
        
        # Asegurar que points sea Decimal
        if not isinstance(points, Decimal):
            points = Decimal(str(points))
        
        # Crear transacción
        ClientPoints.objects.create(
            client=self,
            reservation=reservation,
            transaction_type=ClientPoints.TransactionType.EARNED,
            points=points,
            description=description,
            expires_at=timezone.now() + timedelta(days=365)  # 1 año desde ahora
        )
        
        # Actualizar balance
        self.points_balance += points
        # Actualizar fecha de expiración (1 año desde el último check_out)
        if reservation and reservation.check_out_date:
            checkout_datetime = timezone.make_aware(
                datetime.combine(reservation.check_out_date, datetime.min.time())
            )
            self.points_expires_at = checkout_datetime + timedelta(days=365)
        
        self.save()
    
    def get_available_points(self):
        """Retorna los puntos disponibles (no expirados)"""
        from django.utils import timezone
        if self.points_expires_at and self.points_expires_at < timezone.now():
            return 0
        return float(self.points_balance)
    
    def redeem_points(self, points, reservation, description="Puntos canjeados en reserva"):
        """Canjea puntos del cliente"""
        from decimal import Decimal
        
        # Asegurar que points sea Decimal
        if not isinstance(points, Decimal):
            points = Decimal(str(points))
            
        if self.points_balance >= points:
            # Crear transacción
            ClientPoints.objects.create(
                client=self,
                reservation=reservation,
                transaction_type=ClientPoints.TransactionType.REDEEMED,
                points=-points,  # Negativo para indicar que se restaron
                description=description
            )
            
            # Actualizar balance
            self.points_balance -= points
            self.save()
            return True
        return False
    
    def adjust_points_manually(self, points, description, staff_user=None):
        """Ajusta puntos manualmente (puede ser positivo o negativo) con motivo"""
        from datetime import timedelta
        from django.utils import timezone
        from decimal import Decimal
        
        # Asegurar que points sea Decimal
        if not isinstance(points, Decimal):
            points = Decimal(str(points))
        
        # Si se están agregando puntos, establecer expiración
        expires_at = None
        if points > 0:
            expires_at = timezone.now() + timedelta(days=365)
        
        # Construir descripción completa con usuario staff si está disponible
        full_description = description
        if staff_user:
            full_description = f"{description} (Otorgado por: {staff_user})"
        
        # Determinar tipo de transacción según si se agregan o restan puntos
        transaction_type = ClientPoints.TransactionType.EARNED if points > 0 else ClientPoints.TransactionType.REDEEMED
        
        # Crear transacción
        ClientPoints.objects.create(
            client=self,
            reservation=None,
            transaction_type=transaction_type,
            points=points,
            description=full_description,
            expires_at=expires_at
        )
        
        # Actualizar balance
        self.points_balance += points
        
        # Si se están agregando puntos, actualizar fecha de expiración
        if points > 0:
            self.points_expires_at = expires_at
        
        self.save()
        return True
    
    def add_referral_points(self, points, reservation, referred_client, description="Puntos por referido"):
        """Agrega puntos por referir a otro cliente"""
        from datetime import datetime, timedelta
        from django.utils import timezone
        from decimal import Decimal
        
        # Asegurar que points sea Decimal
        if not isinstance(points, Decimal):
            points = Decimal(str(points))
        
        # Crear transacción de referido
        ClientPoints.objects.create(
            client=self,
            reservation=reservation,
            referred_client=referred_client,
            transaction_type=ClientPoints.TransactionType.REFERRAL,
            points=points,
            description=description,
            expires_at=timezone.now() + timedelta(days=365)  # 1 año desde ahora
        )
        
        # Actualizar balance
        self.points_balance += points
        # Actualizar fecha de expiración si es necesario
        if reservation and reservation.check_out_date:
            checkout_datetime = timezone.make_aware(
                datetime.combine(reservation.check_out_date, datetime.min.time())
            )
            self.points_expires_at = checkout_datetime + timedelta(days=365)
        
        self.save()
    
    def expire_points(self):
        """Expira los puntos del cliente"""
        from django.utils import timezone
        
        if self.points_balance > 0:
            # Crear transacción de expiración
            ClientPoints.objects.create(
                client=self,
                transaction_type=ClientPoints.TransactionType.EXPIRED,
                points=-self.points_balance,
                description=f"Puntos expirados - {self.points_balance} puntos"
            )
            
            # Resetear balance
            self.points_balance = 0
            self.points_expires_at = None
            self.save()
    
    @property
    def points_are_expired(self):
        """Verifica si los puntos están expirados"""
        from django.utils import timezone
        
        if self.points_expires_at and timezone.now() > self.points_expires_at:
            return True
        return False
    
    def generate_referral_code(self):
        """Genera un código de referido único de 6-8 caracteres"""
        import random
        import string
        
        if self.referral_code:
            return self.referral_code
            
        # Generar código basado en el nombre y números aleatorios
        first_part = self.first_name[:3].upper() if len(self.first_name) >= 3 else self.first_name.upper()
        
        # Asegurar que tengamos al menos 3 caracteres
        while len(first_part) < 3:
            first_part += 'A'
            
        # Agregar números aleatorios
        numbers = ''.join(random.choices(string.digits, k=3))
        
        code = first_part + numbers
        
        # Verificar que sea único
        counter = 1
        original_code = code
        while Clients.objects.filter(referral_code=code, deleted=False).exists():
            code = original_code + str(counter)
            counter += 1
            if counter > 99:  # Evitar bucle infinito
                code = ''.join(random.choices(string.ascii_uppercase + string.digits, k=8))
                break
        
        self.referral_code = code
        self.save()
        return code
    
    def get_referral_code(self):
        """Obtiene el código de referido, generándolo si no existe"""
        if not self.referral_code:
            return self.generate_referral_code()
        return self.referral_code
    
    @classmethod
    def get_client_by_referral_code(cls, referral_code):
        """Obtiene un cliente por su código de referido"""
        try:
            return cls.objects.get(referral_code=referral_code, deleted=False)
        except cls.DoesNotExist:
            return None
    
    def link_facebook_account(self, facebook_id, profile_data):
        """Vincula la cuenta de Facebook del cliente"""
        from django.utils import timezone
        
        self.facebook_id = facebook_id
        self.facebook_profile_data = profile_data
        self.facebook_linked = True
        self.facebook_linked_at = timezone.now()
        self.save()
        
        return True
    
    def unlink_facebook_account(self):
        """Desvincula la cuenta de Facebook del cliente"""
        self.facebook_id = None
        self.facebook_profile_data = None
        self.facebook_linked = False
        self.facebook_linked_at = None
        self.save()
        
        return True
    
    def get_facebook_profile_picture(self):
        """Obtiene la URL de la foto de perfil de Facebook"""
        if self.facebook_profile_data and isinstance(self.facebook_profile_data, dict):
            picture_data = self.facebook_profile_data.get('picture', {})
            if isinstance(picture_data, dict):
                data = picture_data.get('data', {})
                if isinstance(data, dict):
                    return data.get('url')
        return None
    
    @property
    def is_facebook_linked(self):
        """Propiedad para verificar si el cliente tiene Facebook vinculado"""
        return bool(self.facebook_linked and self.facebook_id)
    
    @property
    def is_authenticated(self):
        """Propiedad requerida por DRF IsAuthenticated permission"""
        return True
    
    @property
    def is_anonymous(self):
        """Propiedad de compatibilidad con Django User model"""
        return False
    
    @classmethod
    def get_client_by_facebook_id(cls, facebook_id):
        """Obtiene un cliente por su Facebook ID"""
        return cls.objects.filter(facebook_id=facebook_id, deleted=False).first()
    
    def get_referral_stats(self, year, month):
        """
        Obtiene estadísticas de referidos para un mes específico
        
        Args:
            year (int): Año
            month (int): Mes (1-12)
            
        Returns:
            dict: Estadísticas del mes
        """
        from django.db.models import Sum, Count, Q
        from django.utils import timezone
        from datetime import datetime, date
        import calendar
        
        # Calcular rango de fechas del mes
        start_date = date(year, month, 1)
        last_day = calendar.monthrange(year, month)[1]
        end_date = date(year, month, last_day)
        
        # 1. Reservas hechas por referidos en este mes
        referral_reservations = self.get_related_reservation_model().objects.filter(
            client__referred_by=self,
            created__date__gte=start_date,
            created__date__lte=end_date,
            status='approved',
            deleted=False
        ).aggregate(
            count=Count('id'),
            total_revenue=Sum('price_sol')
        )
        
        # 2. Nuevos referidos registrados en este mes
        new_referrals = Clients.objects.filter(
            referred_by=self,
            created__date__gte=start_date,
            created__date__lte=end_date,
            deleted=False
        ).count()
        
        # 3. Puntos ganados por referidos en este mes
        referral_points = ClientPoints.objects.filter(
            client=self,
            transaction_type=ClientPoints.TransactionType.REFERRAL,
            created__date__gte=start_date,
            created__date__lte=end_date,
            deleted=False
        ).aggregate(total=Sum('points'))
        
        return {
            'referral_reservations_count': referral_reservations['count'] or 0,
            'total_referral_revenue': referral_reservations['total_revenue'] or 0,
            'referrals_made_count': new_referrals,
            'points_earned': referral_points['total'] or 0,
        }
    
    def get_related_reservation_model(self):
        """Obtiene el modelo Reservation de forma lazy para evitar imports circulares"""
        from apps.reservation.models import Reservation
        return Reservation


class ClientPoints(BaseModel):
    """Modelo para el historial de transacciones de puntos"""
    
    class TransactionType(models.TextChoices):
        EARNED = "earned", ("Bonificación de puntos")
        REDEEMED = "redeemed", ("Redención de puntos")
        EXPIRED = "expired", ("Puntos Expirados")
        REFUNDED = "refunded", ("Puntos Devueltos")
        REFERRAL = "referral", ("Puntos por Referido")
    
    client = models.ForeignKey(Clients, on_delete=models.CASCADE, related_name='points_transactions')
    reservation = models.ForeignKey('reservation.Reservation', on_delete=models.CASCADE, null=True, blank=True)
    referred_client = models.ForeignKey(Clients, on_delete=models.CASCADE, null=True, blank=True, related_name='referral_transactions', help_text="Cliente referido que generó estos puntos")
    transaction_type = models.CharField(max_length=8, choices=TransactionType.choices)
    points = models.DecimalField(max_digits=10, decimal_places=2, help_text="Cantidad de puntos (puede ser negativo para canjes)")
    description = models.TextField(help_text="Descripción de la transacción")
    expires_at = models.DateTimeField(null=True, blank=True, help_text="Fecha de expiración de los puntos")
    
    class Meta:
        ordering = ['-created']
        verbose_name = "Transacción de Puntos"
        verbose_name_plural = "Transacciones de Puntos"
    
    def __str__(self):
        return f"{self.client.first_name} - {self.transaction_type} - {self.points} puntos"

    def delete(self, *args, **kwargs):
        self.deleted = True
        self.save()


class SearchTracking(BaseModel):
    """Modelo para tracking de búsquedas de clientes"""
    client = models.ForeignKey(Clients, on_delete=models.CASCADE, related_name='search_tracking', null=True, blank=True, help_text="Cliente que realiza la búsqueda (null para usuarios anónimos)")
    check_in_date = models.DateField(help_text="Fecha de check-in buscada")
    check_out_date = models.DateField(help_text="Fecha de check-out buscada")
    guests = models.PositiveIntegerField(help_text="Número de huéspedes")
    property = models.ForeignKey('property.Property', on_delete=models.CASCADE, null=True, blank=True, help_text="Propiedad buscada")
    search_timestamp = models.DateTimeField(auto_now=True, help_text="Timestamp de la última búsqueda")
    
    # Campos adicionales para usuarios anónimos
    session_key = models.CharField(max_length=100, null=True, blank=True, help_text="Clave de sesión para usuarios anónimos")
    ip_address = models.GenericIPAddressField(null=True, blank=True, help_text="Dirección IP del usuario")
    user_agent = models.TextField(null=True, blank=True, help_text="User agent del navegador")
    referrer = models.URLField(null=True, blank=True, help_text="URL de referencia")
    
    class Meta:
        verbose_name = "Tracking de Búsqueda"
        verbose_name_plural = "Tracking de Búsquedas"
        ordering = ['-search_timestamp']
    
    def __str__(self):
        return f"{self.client.first_name} - {self.check_in_date} a {self.check_out_date} - {self.guests} huéspedes"
    
    def save(self, *args, **kwargs):
        """Override save to ensure required fields are not null"""
        import logging
        logger = logging.getLogger(__name__)
        
        logger.info(f"SearchTracking.save: About to save with:")
        logger.info(f"  check_in_date={self.check_in_date} (type: {type(self.check_in_date)}, repr: {repr(self.check_in_date)})")
        logger.info(f"  check_out_date={self.check_out_date} (type: {type(self.check_out_date)}, repr: {repr(self.check_out_date)})")
        logger.info(f"  guests={self.guests} (type: {type(self.guests)}, repr: {repr(self.guests)})")
        
        if self.check_in_date is None:
            logger.error("SearchTracking.save: check_in_date is None!")
            raise ValueError("check_in_date cannot be null")
        if self.check_out_date is None:
            logger.error("SearchTracking.save: check_out_date is None!")
            raise ValueError("check_out_date cannot be null")
        if self.guests is None:
            logger.error("SearchTracking.save: guests is None!")
            raise ValueError("guests cannot be null")
            
        logger.info("SearchTracking.save: All validations passed, calling super().save()")
        super().save(*args, **kwargs)
        logger.info("SearchTracking.save: Successfully saved!")


class Achievement(BaseModel):
    """Modelo para definir logros/insignias"""
    
    name = models.CharField(max_length=100, help_text="Nombre del logro")
    description = models.TextField(help_text="Descripción del logro")
    icon = models.CharField(max_length=50, null=True, blank=True, help_text="Emoji o icono del logro")
    
    # Requisitos para obtener el logro
    required_reservations = models.PositiveIntegerField(default=0, help_text="Número mínimo de reservas requeridas")
    required_referrals = models.PositiveIntegerField(default=0, help_text="Número mínimo de referidos requeridos")
    required_referral_reservations = models.PositiveIntegerField(default=0, help_text="Número mínimo de reservas de referidos requeridas")
    
    # Configuración
    is_active = models.BooleanField(default=True, help_text="Activar/desactivar este logro")
    order = models.PositiveIntegerField(default=0, help_text="Orden de visualización")
    
    class Meta:
        ordering = ['order', 'required_reservations', 'required_referrals']
        verbose_name = "Logro"
        verbose_name_plural = "Logros"
    
    def __str__(self):
        return f"{self.name} ({self.required_reservations} reservas, {self.required_referrals} referidos, {self.required_referral_reservations} reservas de referidos)"
    
    def check_client_qualifies(self, client):
        """Verifica si un cliente cumple los requisitos para este logro"""
        from apps.reservation.models import Reservation
        
        # Contar reservas del cliente
        client_reservations = Reservation.objects.filter(
            client=client,
            deleted=False,
            status='approved'
        ).count()
        
        # Contar referidos del cliente
        client_referrals = Clients.objects.filter(
            referred_by=client,
            deleted=False
        ).count()
        
        # Contar reservas de los referidos
        referral_reservations = Reservation.objects.filter(
            client__referred_by=client,
            deleted=False,
            status='approved'
        ).count()
        
        # Verificar si cumple todos los requisitos
        return (
            client_reservations >= self.required_reservations and
            client_referrals >= self.required_referrals and
            referral_reservations >= self.required_referral_reservations
        )


class ClientAchievement(BaseModel):
    """Modelo para rastrear logros obtenidos por clientes"""
    
    client = models.ForeignKey(Clients, on_delete=models.CASCADE, related_name='achievements')
    achievement = models.ForeignKey(Achievement, on_delete=models.CASCADE)
    earned_at = models.DateTimeField(auto_now_add=True, help_text="Fecha cuando se obtuvo el logro")
    
    class Meta:
        unique_together = ('client', 'achievement')
        ordering = ['-earned_at']
        verbose_name = "Logro de Cliente"
        verbose_name_plural = "Logros de Clientes"
    
    def __str__(self):
        return f"{self.client.first_name} - {self.achievement.name}"


class ReferralRanking(BaseModel):
    """Modelo para almacenar estadísticas mensuales de ranking de referidos"""
    
    client = models.ForeignKey(Clients, on_delete=models.CASCADE, related_name='referral_rankings')
    year = models.PositiveIntegerField(help_text="Año del ranking")
    month = models.PositiveIntegerField(help_text="Mes del ranking (1-12)")
    referral_reservations_count = models.PositiveIntegerField(default=0, help_text="Cantidad de reservas hechas por referidos en este mes")
    total_referral_revenue = models.DecimalField(max_digits=10, decimal_places=2, default=0, help_text="Total facturado por reservas de referidos en soles")
    referrals_made_count = models.PositiveIntegerField(default=0, help_text="Cantidad de nuevos referidos en este mes")
    position = models.PositiveIntegerField(null=True, blank=True, help_text="Posición en el ranking mensual (1 = primer lugar)")
    points_earned = models.DecimalField(max_digits=10, decimal_places=2, default=0, help_text="Puntos ganados por referidos este mes")
    
    class Meta:
        unique_together = ('client', 'year', 'month')
        ordering = ['-year', '-month', 'position']
        verbose_name = "Ranking Mensual de Referidos"
        verbose_name_plural = "Ranking Mensual de Referidos"
        
    def __str__(self):
        return f"{self.client.first_name} - {self.month}/{self.year} - {self.referral_reservations_count} reservas de referidos"
    
    @property
    def ranking_date_display(self):
        """Retorna fecha del ranking en formato legible"""
        months = {
            1: "Enero", 2: "Febrero", 3: "Marzo", 4: "Abril", 
            5: "Mayo", 6: "Junio", 7: "Julio", 8: "Agosto",
            9: "Septiembre", 10: "Octubre", 11: "Noviembre", 12: "Diciembre"
        }
        return f"{months.get(self.month, self.month)} {self.year}"
    
    @classmethod
    def get_current_month_ranking(cls, limit=10):
        """Obtiene el ranking del mes actual"""
        from django.utils import timezone
        now = timezone.now()
        return cls.objects.filter(
            year=now.year,
            month=now.month,
            deleted=False
        ).select_related('client').order_by('position')[:limit]
    
    @classmethod
    def get_month_ranking(cls, year, month, limit=10):
        """Obtiene el ranking de un mes específico"""
        return cls.objects.filter(
            year=year,
            month=month,
            deleted=False
        ).select_related('client').order_by('position')[:limit]


class PushToken(BaseModel):
    """Modelo para almacenar tokens de dispositivos Expo Push"""
    
    class DeviceType(models.TextChoices):
        IOS = "ios", ("iOS")
        ANDROID = "android", ("Android")
    
    client = models.ForeignKey(
        Clients, 
        on_delete=models.CASCADE, 
        related_name='push_tokens',
        help_text="Cliente propietario del dispositivo"
    )
    expo_token = models.CharField(
        max_length=255, 
        unique=True,
        help_text="Token Expo Push (ExponentPushToken[xxx])"
    )
    device_type = models.CharField(
        max_length=10,
        choices=DeviceType.choices,
        default=DeviceType.ANDROID,
        help_text="Tipo de dispositivo"
    )
    device_name = models.CharField(
        max_length=100,
        null=True,
        blank=True,
        help_text="Nombre del dispositivo (opcional)"
    )
    is_active = models.BooleanField(
        default=True,
        help_text="Token activo para recibir notificaciones"
    )
    last_used = models.DateTimeField(
        null=True,
        blank=True,
        help_text="Última vez que se envió una notificación"
    )
    failed_attempts = models.PositiveIntegerField(
        default=0,
        help_text="Intentos fallidos consecutivos"
    )
    
    class Meta:
        verbose_name = "Token Push"
        verbose_name_plural = "Tokens Push"
        ordering = ['-created']
    
    def __str__(self):
        return f"{self.client.first_name} - {self.device_type} - {'Activo' if self.is_active else 'Inactivo'}"
    
    def mark_as_used(self):
        """Marca el token como usado y resetea intentos fallidos"""
        from django.utils import timezone
        self.last_used = timezone.now()
        self.failed_attempts = 0
        self.save(update_fields=['last_used', 'failed_attempts'])
    
    def mark_as_failed(self):
        """Incrementa el contador de fallos"""
        self.failed_attempts += 1
        if self.failed_attempts >= 3:
            self.is_active = False
        self.save(update_fields=['failed_attempts', 'is_active'])
    
    @classmethod
    def get_active_tokens_for_client(cls, client):
        """Obtiene todos los tokens activos de un cliente"""
        return cls.objects.filter(
            client=client,
            is_active=True,
            deleted=False
        )
    
    @classmethod
    def register_token(cls, client, expo_token, device_type='android', device_name=None):
        """Registra o actualiza un token de dispositivo"""
        token, created = cls.objects.update_or_create(
            expo_token=expo_token,
            defaults={
                'client': client,
                'device_type': device_type,
                'device_name': device_name,
                'is_active': True,
                'failed_attempts': 0,
                'deleted': False
            }
        )
        return token, created


class AdminPushToken(BaseModel):
    """Tokens de notificaciones push para administradores"""
    
    class DeviceType(models.TextChoices):
        IOS = "ios", ("iOS")
        ANDROID = "android", ("Android")
    
    user = models.ForeignKey(
        'accounts.CustomUser',
        on_delete=models.CASCADE, 
        related_name='push_tokens',
        help_text="Usuario administrador propietario del dispositivo"
    )
    expo_token = models.CharField(
        max_length=255, 
        unique=True,
        help_text="Token Expo Push (ExponentPushToken[xxx])"
    )
    device_type = models.CharField(
        max_length=10,
        choices=DeviceType.choices,
        default=DeviceType.ANDROID,
        help_text="Tipo de dispositivo"
    )
    device_name = models.CharField(
        max_length=100,
        null=True,
        blank=True,
        help_text="Nombre del dispositivo (opcional)"
    )
    is_active = models.BooleanField(
        default=True,
        help_text="Token activo para recibir notificaciones"
    )
    last_used = models.DateTimeField(
        null=True,
        blank=True,
        help_text="Última vez que se envió una notificación"
    )
    failed_attempts = models.PositiveIntegerField(
        default=0,
        help_text="Intentos fallidos consecutivos"
    )
    
    class Meta:
        verbose_name = "Token Push Administrador"
        verbose_name_plural = "Tokens Push Administradores"
        ordering = ['-created']
    
    def __str__(self):
        return f"{self.user.get_full_name()} - {self.device_type} - {'Activo' if self.is_active else 'Inactivo'}"
    
    def mark_as_used(self):
        """Marca el token como usado y resetea intentos fallidos"""
        from django.utils import timezone
        self.last_used = timezone.now()
        self.failed_attempts = 0
        self.save(update_fields=['last_used', 'failed_attempts'])
    
    def mark_as_failed(self):
        """Incrementa el contador de fallos"""
        self.failed_attempts += 1
        if self.failed_attempts >= 3:
            self.is_active = False
        self.save(update_fields=['failed_attempts', 'is_active'])
    
    @classmethod
    def get_active_tokens_for_user(cls, user):
        """Obtiene todos los tokens activos de un usuario administrador"""
        return cls.objects.filter(
            user=user,
            is_active=True,
            deleted=False
        )
    
    @classmethod
    def get_all_active_admin_tokens(cls):
        """Obtiene TODOS los tokens activos de administradores para broadcast"""
        return cls.objects.filter(
            is_active=True,
            deleted=False
        )
    
    @classmethod
    def register_token(cls, user, expo_token, device_type='android', device_name=None):
        """Registra o actualiza un token de dispositivo"""
        token, created = cls.objects.update_or_create(
            expo_token=expo_token,
            defaults={
                'user': user,
                'device_type': device_type,
                'device_name': device_name,
                'is_active': True,
                'failed_attempts': 0,
                'deleted': False
            }
        )
        return token, created


class NotificationLog(BaseModel):
    """
    Historial de notificaciones push enviadas
    Almacena todas las notificaciones enviadas tanto a clientes como a administradores
    """
    # Receptor - puede ser cliente o administrador
    client = models.ForeignKey(
        Clients,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='notification_logs',
        verbose_name='Cliente'
    )
    admin = models.ForeignKey(
        'accounts.CustomUser',
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='notification_logs',
        verbose_name='Administrador'
    )
    
    # Contenido de la notificación
    title = models.CharField(
        max_length=200,
        verbose_name='Título'
    )
    body = models.TextField(
        verbose_name='Cuerpo'
    )
    notification_type = models.CharField(
        max_length=50,
        verbose_name='Tipo de Notificación',
        help_text='Ej: reservation_created, payment_approved, admin_reservation_created, etc.'
    )
    
    # Metadata adicional
    data = models.JSONField(
        default=dict,
        blank=True,
        verbose_name='Datos Adicionales',
        help_text='Datos JSON enviados con la notificación'
    )
    
    # Información del dispositivo
    expo_token = models.CharField(
        max_length=255,
        blank=True,
        null=True,
        verbose_name='Token Expo'
    )
    device_type = models.CharField(
        max_length=20,
        blank=True,
        null=True,
        verbose_name='Tipo de Dispositivo'
    )
    
    # Estado
    success = models.BooleanField(
        default=False,
        verbose_name='Enviado Exitosamente'
    )
    error_message = models.TextField(
        blank=True,
        null=True,
        verbose_name='Mensaje de Error'
    )
    read = models.BooleanField(
        default=False,
        verbose_name='Leída'
    )
    read_at = models.DateTimeField(
        null=True,
        blank=True,
        verbose_name='Leída el'
    )
    
    # Timestamp
    sent_at = models.DateTimeField(
        auto_now_add=True,
        verbose_name='Enviada el'
    )

    class Meta:
        verbose_name = 'Log de Notificación'
        verbose_name_plural = 'Logs de Notificaciones'
        ordering = ['-sent_at']
        indexes = [
            models.Index(fields=['client', '-sent_at']),
            models.Index(fields=['admin', '-sent_at']),
            models.Index(fields=['notification_type', '-sent_at']),
            models.Index(fields=['read', '-sent_at']),
            models.Index(fields=['success', '-sent_at']),
        ]

    def __str__(self):
        recipient = self.client or self.admin
        if hasattr(recipient, 'get_full_name'):
            recipient_name = recipient.get_full_name()
        else:
            recipient_name = str(recipient)
        status = '✅' if self.success else '❌'
        read_status = '👁️' if self.read else '📭'
        return f"{status} {read_status} {self.notification_type} → {recipient_name} ({self.sent_at.strftime('%Y-%m-%d %H:%M')})"

    @classmethod
    def log_notification(cls, recipient, title, body, notification_type, data=None, 
                        expo_token=None, device_type=None, success=False, error_message=None):
        """
        Crea un registro de notificación enviada
        
        Args:
            recipient: Instancia de Clients o CustomUser
            title: Título de la notificación
            body: Cuerpo de la notificación
            notification_type: Tipo de notificación
            data: Datos JSON adicionales
            expo_token: Token Expo usado
            device_type: Tipo de dispositivo
            success: Si se envió exitosamente
            error_message: Mensaje de error si falló
        """
        from apps.accounts.models import CustomUser
        
        log_data = {
            'title': title,
            'body': body,
            'notification_type': notification_type,
            'data': data or {},
            'expo_token': expo_token,
            'device_type': device_type,
            'success': success,
            'error_message': error_message
        }
        
        # Determinar si es cliente o administrador
        if isinstance(recipient, Clients):
            log_data['client'] = recipient
        elif isinstance(recipient, CustomUser):
            log_data['admin'] = recipient
        
        return cls.objects.create(**log_data)

    def mark_as_read(self):
        """Marca la notificación como leída"""
        if not self.read:
            from django.utils import timezone
            self.read = True
            self.read_at = timezone.now()
            self.save(update_fields=['read', 'read_at'])

