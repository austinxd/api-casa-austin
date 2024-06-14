from django.db.models.signals import post_save
from django.dispatch import receiver
from .models import Reservation
from ..core.telegram_notifier import send_telegram_message

def notify_new_reservation(reservation):
    client_name = f"{reservation.client.first_name} {reservation.client.last_name}" if reservation.client else "Cliente desconocido"
    message = (
        f"Se ha creado una nueva reserva:\n"
        f"ID: {reservation.id}\n"
        f"Cliente: {client_name}\n"
        f"Fecha de check-in: {reservation.check_in_date}\n"
        f"Propiedad: {reservation.property}\n"
        f"Invitados: {reservation.guests}"
    )
    send_telegram_message(message)

@receiver(post_save, sender=Reservation)
def notify_reservation_creation(sender, instance, created, **kwargs):
    if created:
        notify_new_reservation(instance)
