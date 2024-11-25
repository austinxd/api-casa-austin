import logging
from django.db.models.signals import post_save
from django.dispatch import receiver
from .models import Reservation
from ..core.telegram_notifier import send_telegram_message
from django.conf import settings
from datetime import datetime, date

logger = logging.getLogger('apps')

# Diccionario para traducir los meses al español
MONTHS_ES = {
    1: "enero", 2: "febrero", 3: "marzo", 4: "abril",
    5: "mayo", 6: "junio", 7: "julio", 8: "agosto",
    9: "septiembre", 10: "octubre", 11: "noviembre", 12: "diciembre"
}

DAYS_ES = {
    0: "Lunes", 1: "Martes", 2: "Miércoles", 3: "Jueves",
    4: "Viernes", 5: "Sábado", 6: "Domingo"
}

def format_date_es(date):
    day = date.day
    month = MONTHS_ES[date.month]
    week_day = DAYS_ES[date.weekday()]
    return f"{week_day} {day} de {month}"

def notify_new_reservation(reservation):
    client_name = f"{reservation.client.first_name} {reservation.client.last_name}" if reservation.client else "Cliente desconocido"
    temperature_pool_status = "Sí" if reservation.temperature_pool else "No"

    check_in_date = format_date_es(reservation.check_in_date)
    check_out_date = format_date_es(reservation.check_out_date)
    price_usd = f"{reservation.price_usd:.2f} USD"
    price_sol = f"{reservation.price_sol:.2f} soles"
    advance_payment = f"{reservation.advance_payment:.2f} {reservation.advance_payment_currency.upper()}"

    # Mensaje general para el primer canal
    message = (
        f"******Reserva en {reservation.property.name}******\n"
        f"Cliente: {client_name}\n"
        f"Check-in: {check_in_date}\n"
        f"Check-out: {check_out_date}\n"
        f"Invitados: {reservation.guests}\n"
        f"Temperado: {temperature_pool_status}\n"
        f"Precio (USD): {price_usd}\n"
        f"Precio (Soles): {price_sol}\n"
        f"Adelanto: {advance_payment}\n"
        f"Teléfono: +{reservation.tel_contact_number}"
    )

    logger.debug(f"Enviando notificación de nueva reserva: {message}")
    send_telegram_message(message, settings.CHAT_ID)

    # Mensaje "PARA HOYYYY" para el canal secundario
    if reservation.check_in_date == datetime.today().date():
        message_today = f"******PARA HOYYYY******\n{message}"
        logger.debug("Reserva para el mismo día detectada. Enviando al canal secundario.")
        send_telegram_message(message_today, settings.SECOND_CHAT_ID)

    # Mensaje personalizado para el canal personal
    birthday = format_date_es(reservation.client.date) if reservation.client and reservation.client.date else "No disponible"
    upcoming_age = (
        f"{reservation.client.date.year - datetime.now().year}"
        if reservation.client and reservation.client.date
        else "No disponible"
    )

    message_personal = (
        f"******Reserva en {reservation.property.name}******\n"
        f"Cliente: {client_name}\n"
        f"Cumpleaños: {birthday} (Cumple {upcoming_age} años)\n"
        f"Check-in: {check_in_date}\n"
        f"Check-out: {check_out_date}\n"
        f"Invitados: {reservation.guests}\n"
        f"Temperado: {temperature_pool_status}\n"
        f"Teléfono: +{reservation.tel_contact_number}"
    )
    logger.debug(f"Enviando mensaje personal: {message_personal}")
    send_telegram_message(message_personal, settings.PERSONAL_CHAT_ID)

def notify_modified_reservation(reservation):
    client_name = f"{reservation.client.first_name} {reservation.client.last_name}" if reservation.client else "Cliente desconocido"
    check_in_date = format_date_es(reservation.check_in_date)
    check_out_date = format_date_es(reservation.check_out_date)

    price_usd = f"{reservation.price_usd:.2f} USD"
    price_sol = f"{reservation.price_sol:.2f} soles"

    # Mensaje general para el primer canal
    message = (
        f"******Modificación de reserva en {reservation.property.name}******\n"
        f"Cliente: {client_name}\n"
        f"Check-in: {check_in_date}\n"
        f"Check-out: {check_out_date}\n"
        f"Invitados: {reservation.guests}\n"
        f"Precio actualizado (USD): {price_usd}\n"
        f"Precio actualizado (Soles): {price_sol}\n"
    )

    logger.debug(f"Enviando notificación de modificación: {message}")
    send_telegram_message(message, settings.CHAT_ID)

    # Mensaje "PARA HOYYYY" para el canal secundario
    if reservation.check_in_date == datetime.today().date():
        message_today = f"******Modificación PARA HOYYYY******\n{message}"
        logger.debug("Modificación para el mismo día detectada. Enviando al canal secundario.")
        send_telegram_message(message_today, settings.SECOND_CHAT_ID)

@receiver(post_save, sender=Reservation)
def notify_reservation_changes(sender, instance, created, **kwargs):
    # Prevenir señales duplicadas
    if getattr(instance, '_disable_signals', False):
        logger.debug(f"Señal desactivada temporalmente para la reserva: {instance.id}")
        return

    if created:
        logger.debug(f"Notificación de nueva reserva para: {instance}")
        notify_new_reservation(instance)
    else:
        logger.debug(f"Notificación de modificación de reserva para: {instance}")
        notify_modified_reservation(instance)
