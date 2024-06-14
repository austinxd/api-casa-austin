import logging
from django.db.models.signals import post_save
from django.dispatch import receiver
from .models import Reservation, RentalReceipt
from ..core.telegram_notifier import send_telegram_message
from django.conf import settings

logger = logging.getLogger('apps')

# Diccionario para traducir los meses al español
MONTHS_ES = {
    1: "enero", 2: "febrero", 3: "marzo", 4: "abril",
    5: "mayo", 6: "junio", 7: "julio", 8: "agosto",
    9: "septiembre", 10: "octubre", 11: "noviembre", 12: "diciembre"
}

def format_date_es(date):
    day = date.day
    month = MONTHS_ES[date.month]
    year = date.year
    return f"{day} de {month} del {year}"

def notify_new_reservation(reservation):
    client_name = f"{reservation.client.first_name} {reservation.client.last_name}" if reservation.client else "Cliente desconocido"
    temperature_pool_status = "Sí" if reservation.temperature_pool else "No"

    check_in_date = format_date_es(reservation.check_in_date)
    check_out_date = format_date_es(reservation.check_out_date)

    message = (
        f"Reserva en {reservation.property.name}\n"
        f"Cliente: {client_name}\n"
        f"Check-in : {check_in_date}\n"
        f"Check-out : {check_out_date}\n"
        f"Invitados : {reservation.guests}\n"
        f"Temperado : {temperature_pool_status}"
    )

    # Verificar si hay un recibo asociado con una imagen
    image_url = None
    rental_receipt = RentalReceipt.objects.filter(reservation=reservation).first()
    if rental_receipt and rental_receipt.file:
        image_url = f"{settings.MEDIA_URL}{rental_receipt.file.name}"

    logger.debug(f"Enviando mensaje de Telegram: {message} con imagen: {image_url}")
    send_telegram_message(message, image_url)

@receiver(post_save, sender=Reservation)
def notify_reservation_creation(sender, instance, created, **kwargs):
    if created:
        logger.debug(f"Notificación de nueva reserva para: {instance}")
        notify_new_reservation(instance)
