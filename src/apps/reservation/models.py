import os
from django.conf import settings


from django.db import models
from django.utils import timezone


from django.db.models.signals import post_delete
from django.dispatch import receiver

from apps.core.models import BaseModel

from apps.accounts.models import CustomUser
from apps.clients.models import Clients
from apps.property.models import Property

from apps.core.functions import recipt_directory_path
from datetime import timedelta

class Reservation(BaseModel):
    ManychatFecha = models.IntegerField(default=0)
    late_checkout = models.BooleanField(default=False)
    late_check_out_date = models.DateField(null=True, blank=True)
    comentarios_reservas = models.TextField(null=True, blank=True, help_text="Comentarios adicionales sobre la reserva.")

    @property
    def adelanto_normalizado(self):
        res = float(self.advance_payment) if self.advance_payment else 0

        if self.advance_payment_currency == 'usd' and self.advance_payment != 0:
            res = (float(self.price_sol) / float(self.price_usd)) * float(self.advance_payment)

        return round(res, 2)

    class AdvancePaymentTypeChoice(models.TextChoices):
        SOL = "sol", ("Soles")
        USD = "usd", ("Dólares")

    class OriginReservationTypeChoice(models.TextChoices):
        AIR = "air", ("Airbnb")
        AUS = "aus", ("Austin")
        MAN = "man", ("Mantenimiento")
        CLIENT = "client", ("Cliente Web")

    class ReservationStatusChoice(models.TextChoices):
        INCOMPLETE = "incomplete", ("Incompleta")
        PENDING = "pending", ("Pendiente")
        APPROVED = "approved", ("Aprobada")
        REJECTED = "rejected", ("Rechazada")
        CANCELLED = "cancelled", ("Cancelada")

    client = models.ForeignKey(Clients, on_delete=models.CASCADE, null=True, blank=True)
    property = models.ForeignKey(Property, on_delete=models.CASCADE, null=False, blank=False)
    seller = models.ForeignKey(CustomUser, on_delete=models.CASCADE, null=True, blank=True)
    check_in_date = models.DateField()
    check_out_date = models.DateField()
    guests = models.PositiveIntegerField(null=False, blank=False, default=1)
    price_usd = models.DecimalField(max_digits=20, decimal_places=2, null=True, blank=True, default=0)
    price_sol = models.DecimalField(max_digits=20, decimal_places=2, null=True, blank=True, default=0)
    advance_payment = models.DecimalField(max_digits=20, decimal_places=2, null=True, blank=True, default=0)
    advance_payment_currency = models.CharField(
        max_length=3, choices=AdvancePaymentTypeChoice.choices, default=AdvancePaymentTypeChoice.SOL
    )
    uuid_external = models.CharField(max_length=100, null=True, blank=True)
    origin = models.CharField(
        max_length=6, choices=OriginReservationTypeChoice.choices, default=OriginReservationTypeChoice.AUS
    )
    status = models.CharField(
        max_length=10, choices=ReservationStatusChoice.choices, default=ReservationStatusChoice.INCOMPLETE,
        help_text="Estado de la reserva"
    )
    tel_contact_number = models.CharField(max_length=255, null=True, blank=True)
    full_payment = models.BooleanField(default=False)
    temperature_pool = models.BooleanField(default=False)
    ip_cliente = models.GenericIPAddressField(null=True, blank=True)
    user_agent = models.TextField(null=True, blank=True)
    referer = models.TextField(null=True, blank=True)
    fbclid = models.CharField(max_length=255, null=True, blank=True)
    utm_source = models.CharField(max_length=255, null=True, blank=True)
    utm_medium = models.CharField(max_length=255, null=True, blank=True)
    utm_campaign = models.CharField(max_length=255, null=True, blank=True)
    fbp = models.CharField(max_length=255, null=True, blank=True)
    fbc = models.CharField(max_length=255, blank=True, null=True)
    points_redeemed = models.DecimalField(
        max_digits=10, 
        decimal_places=2, 
        default=0, 
        help_text="Puntos canjeados en esta reserva"
    )
    discount_code_used = models.CharField(
        max_length=20,
        null=True,
        blank=True,
        help_text="Código de descuento utilizado en esta reserva"
    )
    # Campos para voucher de pago
    payment_voucher_deadline = models.DateTimeField(
        null=True, 
        blank=True,
        help_text="Fecha límite para subir voucher de pago (1 hora después de crear reserva)"
    )
    payment_voucher_uploaded = models.BooleanField(
        default=False,
        help_text="Indica si el cliente ya subió el voucher de pago"
    )
    payment_confirmed = models.BooleanField(
        default=False,
        help_text="Indica si el cliente confirmó que realizó el pago"
    )
    payment_approved_notification_sent = models.BooleanField(
        default=False,
        help_text="Indica si ya se envió la notificación de pago aprobado por WhatsApp"
    )

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        # Guardar el valor original de full_payment para detectar cambios
        self._original_full_payment = self.full_payment

    def save(self, *args, **kwargs):
        # Actualizar el valor original después de guardar
        is_new = self.pk is None
        super().save(*args, **kwargs)
        if not is_new:
            self._original_full_payment = self.full_payment

    def __str__(self):
        if self.client:
            return f"Reserva de {self.client.last_name}, {self.client.first_name} ({self.id}) - {self.origin} -"
        else:
            return f"Reserva desde API Airbnb (sin datos del cliente)"

    def delete(self, *args, **kwargs):
        # Si la reserva tenía puntos canjeados, devolverlos al cliente
        if self.points_redeemed and self.points_redeemed > 0 and self.client:
            from apps.clients.models import ClientPoints
            from decimal import Decimal

            # Devolver puntos al cliente
            self.client.points_balance += Decimal(str(self.points_redeemed))
            self.client.save()

            # Crear transacción de devolución
            ClientPoints.objects.create(
                client=self.client,
                reservation=self,
                transaction_type=ClientPoints.TransactionType.REFUNDED,
                points=Decimal(str(self.points_redeemed)),
                description=f"Devolución de puntos por eliminación de reserva #{self.id} - {self.property.name if self.property else 'Propiedad'}"
            )

        # Verificar logros después de eliminar la reserva
        if self.client:
            # Importar aquí para evitar imports circulares
            from .points_signals import check_and_assign_achievements
            import logging
            
            logger = logging.getLogger(__name__)
            logger.debug(f"Verificando logros para cliente {self.client.id} después de eliminar reserva {self.id}")
            
            # Verificar logros del cliente
            check_and_assign_achievements(self.client)
            
            # También verificar logros del cliente que refirió (si existe)
            if self.client.referred_by:
                logger.debug(f"Verificando logros para cliente referidor {self.client.referred_by.id} después de eliminar reserva {self.id}")
                check_and_assign_achievements(self.client.referred_by)

        self.deleted = True
        self.save()

def recipt_directory_path(instance, filename):
    return f'rental_recipt/{instance.reservation.id}/{filename}'


class RentalReceipt(BaseModel):
    reservation = models.ForeignKey(Reservation, on_delete=models.CASCADE, null=False, blank=False)
    file = models.FileField(null=False, upload_to=recipt_directory_path)

# Model to track used payment tokens
class PaymentToken(BaseModel):
    token = models.CharField(max_length=255, unique=True, null=False, blank=False)
    reservation = models.ForeignKey(Reservation, on_delete=models.CASCADE, null=True, blank=True)
    amount = models.DecimalField(max_digits=10, decimal_places=2, null=True, blank=True)
    transaction_id = models.CharField(max_length=255, null=True, blank=True)
    used_at = models.DateTimeField(default=timezone.now)

    def __str__(self):
        return f"Token: {self.token} - Used at: {self.used_at}"


@receiver(post_delete, sender=RentalReceipt)
def delete_related_instance_file(sender, instance, **kwargs):
    # Verificar si el campo del archivo está configurado en el modelo
    if hasattr(instance, 'file'):
        file = instance.file
        # Obtener la ruta completa del archivo
        file_path = os.path.join(settings.MEDIA_ROOT, str(file))
        # Verificar si el archivo existe y eliminarlo
        if os.path.exists(file_path):
            os.remove(file_path)