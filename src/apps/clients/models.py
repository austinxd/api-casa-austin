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

    class Meta:
        unique_together = ('document_type', 'number_doc')

    def __str__(self):
        return f"{self.email} {self.first_name} {self.last_name} {self.document_type} {self.number_doc}"


    def delete(self, *args, **kwargs):
        self.deleted = True
        self.save()



class ClientPoints(BaseModel):
    """Modelo para el sistema de puntos de clientes"""
    
    class PointTransactionType(models.TextChoices):
        EARNED = "earned", ("Puntos Ganados")
        REDEEMED = "redeemed", ("Puntos Canjeados")
        REFUNDED = "refunded", ("Puntos Devueltos")
        DEDUCTED = "deducted", ("Puntos Descontados")
    
    client = models.ForeignKey(Clients, on_delete=models.CASCADE, related_name='point_transactions')
    reservation = models.ForeignKey('reservation.Reservation', on_delete=models.CASCADE, null=True, blank=True)
    transaction_type = models.CharField(max_length=10, choices=PointTransactionType.choices)
    points = models.DecimalField(max_digits=10, decimal_places=2)
    description = models.TextField()
    
    class Meta:
        ordering = ['-created_at']
    
    def __str__(self):
        return f"{self.client} - {self.transaction_type} - {self.points} puntos"


# Agregar al modelo Clients
def total_points(self):
    """Calcula el total de puntos disponibles del cliente"""
    from django.db.models import Sum, Q
    
    earned = self.point_transactions.filter(
        transaction_type__in=['earned', 'refunded']
    ).aggregate(Sum('points'))['points__sum'] or 0
    
    used = self.point_transactions.filter(
        transaction_type__in=['redeemed', 'deducted']
    ).aggregate(Sum('points'))['points__sum'] or 0
    
    return earned - used

# Método para agregar al modelo Clients
Clients.add_to_class('total_points', total_points)
