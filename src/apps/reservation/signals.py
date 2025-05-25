import logging
from django.db.models.signals import post_save
from django.dispatch import receiver
from .models import Reservation, RentalReceipt
from ..core.telegram_notifier import send_telegram_message
from django.conf import settings
from datetime import datetime, date
import hashlib
import requests

logger = logging.getLogger('apps')

# Diccionario para traducir los meses al español
MONTHS_ES = {
    1: "enero", 2: "febrero", 3: "marzo", 4: "abril",
    5: "mayo", 6: "junio", 7: "julio", 8: "agosto",
    9: "septiembre", 10: "octubre", 11: "noviembre", 12: "diciembre"
}

# Diccionario para traducir los días de la semana al español
DAYS_ES = {
    0: "Lunes", 1: "Martes", 2: "Miércoles", 3: "Jueves",
    4: "Viernes", 5: "Sábado", 6: "Domingo"
}

def format_date_es(date):
    day = date.day
    month = MONTHS_ES[date.month]
    week_day = DAYS_ES[date.weekday()]
    return f"{week_day} {day} de {month}"

def calculate_upcoming_age(born):
    today = date.today()
    this_year_birthday = date(today.year, born.month, born.day)
    next_birthday = this_year_birthday if today <= this_year_birthday else date(today.year + 1, born.month, born.day)
    return next_birthday.year - born.year

def notify_new_reservation(reservation):
    client_name = f"{reservation.client.first_name} {reservation.client.last_name}" if reservation.client else "Cliente desconocido"
    temperature_pool_status = "Sí" if reservation.temperature_pool else "No"

    # Formatear fechas
    check_in_date = format_date_es(reservation.check_in_date)
    check_out_date = format_date_es(reservation.check_out_date)
    
    # Obtener precios y adelanto
    price_usd = f"{reservation.price_usd:.2f} dólares"
    price_sol = f"{reservation.price_sol:.2f} soles"
    advance_payment = f"{reservation.advance_payment:.2f} {reservation.advance_payment_currency.upper()}"

    message = (
        f"******Reserva en {reservation.property.name}******\n"
        f"Cliente: {client_name}\n"
        f"Check-in : {check_in_date}\n"
        f"Check-out : {check_out_date}\n"
        f"Invitados : {reservation.guests}\n"
        f"Temperado : {temperature_pool_status}\n"
        f"Precio (USD) : {price_usd}\n"
        f"Precio (Soles) : {price_sol}\n"
        f"Adelanto : {advance_payment}\n"
        f"Teléfono : +{reservation.tel_contact_number}"
    )

    message_today = (
        f"******PARA HOYYYY******\n"
        f"Cliente: {client_name}\n"
        f"Check-in : {check_in_date}\n"
        f"Check-out : {check_out_date}\n"
        f"Invitados : {reservation.guests}\n"
        f"Temperado : {temperature_pool_status}\n"
    )

    # Inicializar full_image_urls
    full_image_url = None

    # Verificar si hay un recibo asociado con una imagen
    rental_receipt = RentalReceipt.objects.filter(reservation=reservation).first()
    logger.debug(f"RentalReceipt encontrado: {rental_receipt}")
    if rental_receipt and rental_receipt.file:
        logger.debug(f"Archivo de recibo: {rental_receipt.file}")
        if rental_receipt.file.name:
            image_url = f"{settings.MEDIA_URL}{rental_receipt.file.name}"
            full_image_url = f"http://api.casaaustin.pe{image_url}"
            logger.debug(f"URL de la imagen completa: {full_image_url}")
        else:
            logger.debug("El campo file del RentalReceipt no tiene un nombre de archivo.")

    # Enviar mensaje al primer canal
    logger.debug(f"Enviando mensaje de Telegram: {message} con imagen: {full_image_url}")
    send_telegram_message(message, settings.CHAT_ID, full_image_url)

    # Verificar si la reserva es para el mismo día y enviar un mensaje al segundo canal
    if reservation.check_in_date == datetime.today().date():
        logger.debug("Reserva para el mismo día detectada, enviando al segundo canal.")
        send_telegram_message(message_today, settings.SECOND_CHAT_ID, full_image_url)
    
    # Enviar mensaje al usuario personal con el formato específico
    birthday = format_date_es(reservation.client.date) if reservation.client and reservation.client.date else "No disponible"
    upcoming_age = calculate_upcoming_age(reservation.client.date) if reservation.client and reservation.client.date else "No disponible"
    message_personal_channel = (
        f"******Reserva en {reservation.property.name}******\n"
        f"Cliente: {client_name}\n"
        f"Cumpleaños: {birthday} (Cumple {upcoming_age} años)\n"
        f"Check-in : {check_in_date}\n"
        f"Check-out : {check_out_date}\n"
        f"Invitados : {reservation.guests}\n"
        f"Temperado : {temperature_pool_status}\n"
        f"Teléfono : https://wa.me/{reservation.tel_contact_number}"
    )
    logger.debug(f"Enviando mensaje de Telegram al canal personal: {message_personal_channel} con imagen: {full_image_url}")
    send_telegram_message(message_personal_channel, settings.PERSONAL_CHAT_ID, full_image_url)

# 🚀 Función para enviar el evento a Meta Ads
def send_purchase_event_to_meta(phone, amount, currency="USD"):
    phone_hashed = hashlib.sha256(phone.encode()).hexdigest()
    payload = {
        "data": [
            {
                "event_name": "Purchase",
                "event_time": int(datetime.now().timestamp()),
                "action_source": "website",
                "user_data": {
                    "ph": [phone_hashed]
                },
                "custom_data": {
                    "value": float(amount),  # 👈 convierte a float
                    "currency": currency
                }
            }
        ]
    }
    response = requests.post(
        f"https://graph.facebook.com/v18.0/{settings.META_PIXEL_ID}/events",
        params={"access_token": settings.META_ACCESS_TOKEN},
        json=payload
    )
    if response.status_code == 200:
        logger.debug("Evento de conversión enviado correctamente a Meta.")
    else:
        logger.warning(f"Error al enviar evento a Meta: {response.text}")



@receiver(post_save, sender=Reservation)
def notify_reservation_creation(sender, instance, created, **kwargs):
    if created:
        logger.debug(f"Notificación de nueva reserva para: {instance}")
        notify_new_reservation(instance)
        # Enviar conversión a Meta Ads solo si es la primera reserva del cliente
        if Reservation.objects.filter(client=instance.client).count() == 1:
            send_purchase_event_to_meta(
                phone=instance.tel_contact_number,
                amount=instance.price_usd,
                currency="USD"
            )