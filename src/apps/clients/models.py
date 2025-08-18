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
    last_name = models.CharField(max_length=30, null=True, blank=True)
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


class ClientPoints(BaseModel):
    """Modelo para el historial de transacciones de puntos"""
    
    class TransactionType(models.TextChoices):
        EARNED = "earned", ("Puntos Ganados")
        REDEEMED = "redeemed", ("Puntos Canjeados")
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
    client = models.OneToOneField(Clients, on_delete=models.CASCADE, related_name='search_tracking', help_text="Cliente que realiza la búsqueda")
    check_in_date = models.DateField(help_text="Fecha de check-in buscada")
    check_out_date = models.DateField(help_text="Fecha de check-out buscada")
    guests = models.PositiveIntegerField(help_text="Número de huéspedes")
    property = models.ForeignKey('property.Property', on_delete=models.CASCADE, null=True, blank=True, help_text="Propiedad buscada")
    search_timestamp = models.DateTimeField(auto_now=True, help_text="Timestamp de la última búsqueda")
    
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

