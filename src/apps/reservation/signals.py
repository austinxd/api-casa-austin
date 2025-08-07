import logging
from django.db.models.signals import post_save
from django.dispatch import receiver
from .models import Reservation, RentalReceipt
from ..core.telegram_notifier import send_telegram_message
from django.conf import settings
from datetime import datetime, date
import hashlib
import requests
import json

logger = logging.getLogger('apps')

# Diccionarios para fechas en español
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

def calculate_upcoming_age(born):
    today = date.today()
    this_year_birthday = date(today.year, born.month, born.day)
    next_birthday = this_year_birthday if today <= this_year_birthday else date(today.year + 1, born.month, born.day)
    return next_birthday.year - born.year

def notify_new_reservation(reservation):
    client_name = f"{reservation.client.first_name} {reservation.client.last_name}" if reservation.client else "Cliente desconocido"
    temperature_pool_status = "Sí" if reservation.temperature_pool else "No"

    check_in_date = format_date_es(reservation.check_in_date)
    check_out_date = format_date_es(reservation.check_out_date)
    price_usd = f"{reservation.price_usd:.2f} dólares"
    price_sol = f"{reservation.price_sol:.2f} soles"
    advance_payment = f"{reservation.advance_payment:.2f} {reservation.advance_payment_currency.upper()}"

    # Determinar el origen de la reserva para personalizar el mensaje
    origin_emoji = ""
    origin_text = ""
    if reservation.origin == 'client':
        origin_emoji = "💻"
        origin_text = "WEB CLIENTE"
    elif reservation.origin == 'air':
        origin_emoji = "🏠"
        origin_text = "AIRBNB"
    elif reservation.origin == 'aus':
        origin_emoji = "📞"
        origin_text = "AUSTIN"
    elif reservation.origin == 'man':
        origin_emoji = "🔧"
        origin_text = "MANTENIMIENTO"

    message = (
        f"{origin_emoji} **{origin_text}** - Reserva en {reservation.property.name}\n"
        f"Cliente: {client_name}\n"
        f"Check-in : {check_in_date}\n"
        f"Check-out : {check_out_date}\n"
        f"Invitados : {reservation.guests}\n"
        f"Temperado : {temperature_pool_status}\n"
        f"Precio (USD) : {price_usd}\n"
        f"Precio (Soles) : {price_sol}\n"
        f"Adelanto : {advance_payment}\n"
        f"Teléfono : +{reservation.client.tel_number}"
    )

    message_today = (
        f"******PARA HOYYYY******\n"
        f"Cliente: {client_name}\n"
        f"Check-in : {check_in_date}\n"
        f"Check-out : {check_out_date}\n"
        f"Invitados : {reservation.guests}\n"
        f"Temperado : {temperature_pool_status}\n"
    )

    full_image_url = None
    rental_receipt = RentalReceipt.objects.filter(reservation=reservation).first()
    if rental_receipt and rental_receipt.file and rental_receipt.file.name:
        image_url = f"{settings.MEDIA_URL}{rental_receipt.file.name}"
        full_image_url = f"http://api.casaaustin.pe{image_url}"

    logger.debug(f"Enviando mensaje de Telegram: {message} con imagen: {full_image_url}")
    
    # Enviar notificación al canal principal para todas las reservas
    send_telegram_message(message, settings.CHAT_ID, full_image_url)
    
    # Si es una reserva desde el panel del cliente, también enviar al canal de clientes
    if reservation.origin == 'client':
        client_message = (
            f"💻 **RESERVA DESDE PANEL WEB** 💻\n"
            f"Cliente: {client_name}\n"
            f"Propiedad: {reservation.property.name}\n"
            f"Check-in : {check_in_date}\n"
            f"Check-out : {check_out_date}\n"
            f"Invitados : {reservation.guests}\n"
            f"Temperado : {temperature_pool_status}\n"
            f"💰 Total: {price_sol} soles\n"
            f"📱 Teléfono: +{reservation.client.tel_number}"
        )
        send_telegram_message(client_message, settings.CLIENTS_CHAT_ID, full_image_url)

    if reservation.check_in_date == datetime.today().date():
        logger.debug("Reserva para el mismo día detectada, enviando al segundo canal.")
        send_telegram_message(message_today, settings.SECOND_CHAT_ID, full_image_url)

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
        f"Teléfono : https://wa.me/{reservation.client.tel_number}"
    )
    send_telegram_message(message_personal_channel, settings.PERSONAL_CHAT_ID, full_image_url)

def hash_data(data):
    if data:
        return hashlib.sha256(data.strip().lower().encode()).hexdigest()
    return None

def send_purchase_event_to_meta(
    phone,
    email,
    first_name,
    last_name,
    amount,
    currency="USD",
    ip=None,
    user_agent=None,
    fbc=None,
    fbp=None,
    fbclid=None,
    utm_source=None,
    utm_medium=None,
    utm_campaign=None,
    birthday=None  # <-- Se añade aquí
):
    user_data = {}

    # Identificadores hash
    if phone:
        user_data["ph"] = [hash_data(phone)]
    if email:
        user_data["em"] = [hash_data(email)]
    if first_name:
        user_data["fn"] = [hash_data(first_name)]
    if last_name:
        user_data["ln"] = [hash_data(last_name)]

    # ✅ Fecha de nacimiento
    if birthday:
        try:
            # Asegurar formato correcto MMDDYYYY
            
            bday = datetime.strptime(birthday, "%Y-%m-%d").strftime("%m%d%Y")
            logger.debug(f"Fecha de nacimiento sin hash: {bday}")
            user_data["db"] = [hash_data(bday)]
        except Exception as e:
            logger.warning(f"Error procesando fecha de nacimiento '{birthday}': {e}")

    # Datos del navegador
    if ip:
        user_data["client_ip_address"] = ip
    if user_agent:
        user_data["client_user_agent"] = user_agent

    # Meta click ID y cookies
    if fbc:
        user_data["fbc"] = fbc
    if fbp:
        user_data["fbp"] = fbp
    if fbclid:
        user_data["click_id"] = fbclid  # Usualmente no obligatorio si ya tienes fbc/fbp

    # Armamos el payload
    payload = {
        "data": [
            {
                "event_name": "Purchase",
                "event_time": int(datetime.now().timestamp()),
                "action_source": "website",
                "user_data": user_data,
                "custom_data": {
                    "value": float(amount),
                    "currency": currency,
                    "utm_source": utm_source,
                    "utm_medium": utm_medium,
                    "utm_campaign": utm_campaign,
                }
            }
        ],
        "access_token": settings.META_PIXEL_TOKEN
    }

    # Logging completo para depuración
    logger.debug("Payload enviado a Meta:\n%s", json.dumps(payload, indent=2))

    # Enviar evento a Meta
    response = requests.post(
        "https://graph.facebook.com/v18.0/7378335482264695/events",
        json=payload,
        headers={"Content-Type": "application/json"}
    )

    if response.status_code == 200:
        logger.debug(f"Evento de conversión enviado correctamente a Meta. Respuesta: {response.text}")
    else:
        logger.warning(f"Error al enviar evento a Meta. Código: {response.status_code} Respuesta: {response.text}")