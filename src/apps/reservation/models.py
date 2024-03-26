import os
from django.conf import settings


from django.db import models

from django.db.models.signals import post_delete
from django.dispatch import receiver

from apps.core.models import BaseModel

from apps.accounts.models import CustomUser
from apps.clients.models import Clients
from apps.property.models import Property

from apps.core.functions import recipt_directory_path


class ManagerCustomReservation(models.Manager):
    def get_queryset(self):
        return super().get_queryset().exclude(deleted=True)

    def all_objects(self):
        return super().get_queryset()
    
class ManagerCustomRecipt(models.Manager):
    def get_queryset(self):
        return super().get_queryset().exclude(deleted=True)

    def all_objects(self):
        return super().get_queryset()

class Reservation(BaseModel):
    class AdvancePaymentTypeChoice(models.TextChoices):
            SOL = "sol", ("Soles")
            USD = "usd", ("Dólares")

    client = models.ForeignKey(Clients, on_delete=models.CASCADE, null=False, blank=False)
    property = models.ForeignKey(Property, on_delete=models.CASCADE, null=False, blank=False)
    seller = models.ForeignKey(CustomUser, on_delete=models.CASCADE, null=False, blank=False)
    check_in_date = models.DateField()
    check_out_date = models.DateField()
    guests = models.PositiveIntegerField(null=False, blank=False, default=1)
    price_usd = models.DecimalField(max_digits=20, decimal_places=2)
    price_sol = models.DecimalField(max_digits=20, decimal_places=2)
    advance_payment = models.DecimalField(max_digits=20, decimal_places=2)
    advance_payment_currency =  models.CharField(
        max_length=3, choices=AdvancePaymentTypeChoice.choices, default=AdvancePaymentTypeChoice.SOL
    )

    objects = ManagerCustomReservation()

    def __str__(self):
        return f"Reserva de {self.client.last_name}, {self.client.first_name} ({self.id})"


class RentalReceipt(BaseModel):
    reservation = models.ForeignKey(Reservation, on_delete=models.CASCADE, null=False, blank=False)
    file = models.FileField(null=False, upload_to=recipt_directory_path)

    objects = ManagerCustomRecipt()


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
