import logging
from django.db.models.signals import post_save
from django.dispatch import receiver
from .models import Reservation
from ..core.telegram_notifier import send_telegram_message

logger = logging.getLogger('apps')

def notify_new_reservation(reservation):
    client_name = f"{reservation.client.first_name} {reservation.client.last_name}" if reservation.client else "Cliente desconocido"
    temperature_pool_status = "Sí" if reservation.temperature_pool else "No"
    check_in_date = reservation.check_in_date.strftime("%d de %B del %Y")
    check_out_date = reservation.check_out_date.strftime("%d de %B del %Y")

    message = (
        f"Reserva en {reservation.property}\n"
        f"Cliente: {client_name}\n"
        f"Check-in : {check_in_date}\n"
        f"Check-out : {check_out_date}\n"
        f"Invitados : {reservation.guests}\n"
        f"Temperado : {temperature_pool_status}"
    )
    
    logger.debug(f"Enviando mensaje de Telegram: {message}")
    send_telegram_message(message)

@receiver(post_save, sender=Reservation)
def notify_reservation_creation(sender, instance, created, **kwargs):
    if created:
        logger.debug(f"Notificación de nueva reserva para: {instance}")
        notify_new_reservation(instance)
