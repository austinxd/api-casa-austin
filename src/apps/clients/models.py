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
    
    def get_available_points(self):
        """Retorna los puntos disponibles (no expirados)"""
        if self.points_are_expired:
            self.expire_points()
            return 0
        return float(self.points_balance)


class ClientPoints(BaseModel):
    """Modelo para el historial de transacciones de puntos"""
    
    class TransactionType(models.TextChoices):
        EARNED = "earned", ("Puntos Ganados")
        REDEEMED = "redeemed", ("Puntos Canjeados")
        EXPIRED = "expired", ("Puntos Expirados")
    
    client = models.ForeignKey(Clients, on_delete=models.CASCADE, related_name='points_transactions')
    reservation = models.ForeignKey('reservation.Reservation', on_delete=models.CASCADE, null=True, blank=True)
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
