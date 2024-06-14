from django.db.models.signals import post_save
from django.dispatch import receiver
from .models import Reservation
from ..core.telegram_notifier import send_telegram_message

def notify_new_reservation(reservation):
    message = f"Se ha creado una nueva reserva:\nID: {reservation.id}\nCliente: {reservation.cliente}\nFecha de check-in: {reservation.check_in_date}"
    send_telegram_message(message)

@receiver(post_save, sender=Reservation)
def notify_reservation_creation(sender, instance, created, **kwargs):
    if created:
        notify_new_reservation(instance)
