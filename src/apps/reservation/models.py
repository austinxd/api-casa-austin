
import os
from django.conf import settings
from django.db import models
from django.db.models.signals import post_delete
from django.dispatch import receiver
from datetime import timedelta

from apps.core.models import BaseModel
from apps.accounts.models import CustomUser
from apps.clients.models import Clients
from apps.property.models import Property
from apps.core.functions import recipt_directory_path

class Reservation(BaseModel):
    # Choice classes
    class AdvancePaymentTypeChoice(models.TextChoices):
        SOL = "sol", ("Soles")
        USD = "usd", ("Dólares")

    class OriginReservationTypeChoice(models.TextChoices):
        AIR = "air", ("Airbnb")
        AUS = "aus", ("Austin")
        MAN = "man", ("Mantenimiento")

    # Model fields
    ManychatFecha = models.IntegerField(default=0)
    late_checkout = models.BooleanField(default=False)
    late_check_out_date = models.DateField(null=True, blank=True)
    comentarios_reservas = models.TextField(null=True, blank=True, help_text="Comentarios adicionales sobre la reserva.")
    
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
        max_length=3, choices=OriginReservationTypeChoice.choices, default=OriginReservationTypeChoice.AUS
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

    def __str__(self):
        if self.client:
            return f"Reserva de {self.client.last_name}, {self.client.first_name} ({self.id}) - {self.origin} -"
        else:
            return f"Reserva desde API Airbnb (sin datos del cliente)"

    def delete(self, *args, **kwargs):
        self.deleted = True
        self.save()

    @property
    def get_advance_payment_normalized(self):
        res = float(self.advance_payment) if self.advance_payment else 0

        if self.advance_payment_currency == 'usd' and self.advance_payment != 0:
            res = (float(self.price_sol) / float(self.price_usd)) * float(self.advance_payment)

        return round(res, 2)

    @property
    def calculate_points_earned(self):
        """Calcula los puntos ganados por esta reserva (5% del precio en soles)"""
        if self.price_sol:
            return float(self.price_sol) * 0.05
        return 0.0


def recipt_directory_path(instance, filename):
    return f'rental_recipt/{instance.reservation.id}/{filename}'


class RentalReceipt(BaseModel):
    reservation = models.ForeignKey(Reservation, on_delete=models.CASCADE, null=False, blank=False)
    file = models.FileField(null=False, upload_to=recipt_directory_path)


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
