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

    # Si es una reserva desde el panel del cliente, enviar solo al canal de clientes
    if reservation.origin == 'client':
        client_message = (
            f"*************************************************\n"
            f"💻 RESERVA DESDE PANEL WEB 💻\n"
            f"Cliente: {client_name}\n"
            f"Propiedad: {reservation.property.name}\n"
            f"Check-in : {check_in_date}\n"
            f"Check-out : {check_out_date}\n"
            f"Invitados : {reservation.guests}\n"
            f"Temperado : {temperature_pool_status}\n"
            f"💰 Total: {price_sol} soles\n"
            f"📱 Teléfono: +{reservation.client.tel_number}\n"
            f"*************************************************"
        )
        send_telegram_message(client_message, settings.CLIENTS_CHAT_ID, full_image_url)
    else:
        # Para todas las demás reservas (airbnb, austin, mantenimiento), enviar al canal principal
        send_telegram_message(message, settings.CHAT_ID, full_image_url)

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

def notify_voucher_uploaded(reservation):
    """Notifica cuando un cliente sube su voucher de pago"""
    client_name = f"{reservation.client.first_name} {reservation.client.last_name}" if reservation.client else "Cliente desconocido"

    check_in_date = format_date_es(reservation.check_in_date)
    check_out_date = format_date_es(reservation.check_out_date)
    price_sol = f"{reservation.price_sol:.2f} soles"

    voucher_message = (
        f"📄 **VOUCHER RECIBIDO** 📄\n"
        f"Cliente: {client_name}\n"
        f"Propiedad: {reservation.property.name}\n"
        f"Check-in: {check_in_date}\n"
        f"Check-out: {check_out_date}\n"
        f"💰 Total: {price_sol}\n"
        f"📱 Teléfono: +{reservation.client.tel_number}\n"
        f"⏰ Estado: Pendiente de validación\n"
        f"🆔 Reserva ID: {reservation.id}"
    )

    # Obtener la imagen del voucher de pago
    voucher_image_url = None
    rental_receipt = RentalReceipt.objects.filter(reservation=reservation).first()
    if rental_receipt and rental_receipt.file and rental_receipt.file.name:
        image_url = f"{settings.MEDIA_URL}{rental_receipt.file.name}"
        voucher_image_url = f"http://api.casaaustin.pe{image_url}"

    logger.debug(f"Enviando notificación de voucher subido para reserva: {reservation.id} con imagen: {voucher_image_url}")
    send_telegram_message(voucher_message, settings.CLIENTS_CHAT_ID, voucher_image_url)


def notify_payment_approved(reservation):
    """Notifica al cliente por WhatsApp cuando su pago es aprobado"""
    from ..clients.whatsapp_service import send_whatsapp_payment_approved
    
    if not reservation.client or not reservation.client.tel_number:
        logger.warning(f"No se puede enviar WhatsApp para reserva {reservation.id}: cliente o teléfono no disponible")
        return
    
    try:
        # Preparar datos para el template - solo primer nombre y primer apellido
        first_name = reservation.client.first_name.split()[0] if reservation.client.first_name else ""
        
        # Obtener solo el primer apellido si existe
        first_last_name = ""
        if reservation.client.last_name:
            first_last_name = reservation.client.last_name.split()[0]
        
        # Combinar primer nombre y primer apellido
        client_name = f"{first_name} {first_last_name}".strip()
        
        # Formatear información del pago
        if reservation.advance_payment_currency == 'usd':
            payment_info = f"${reservation.advance_payment:.2f}"
        else:
            payment_info = f"S/{reservation.advance_payment:.2f}"
        
        # Formatear fecha de check-in (formato dd/mm/yyyy)
        check_in_formatted = reservation.check_in_date.strftime("%d/%m/%Y")
        check_in_text = f"Para la reserva del {check_in_formatted}"
        
        logger.info(f"Enviando WhatsApp de pago aprobado a {reservation.client.tel_number} para reserva {reservation.id}")
        logger.info(f"Datos: Nombre: {client_name}, Pago: {payment_info}, Check-in: {check_in_text}")
        
        # Enviar WhatsApp
        success = send_whatsapp_payment_approved(
            phone_number=reservation.client.tel_number,
            client_name=client_name,
            payment_info=payment_info,
            check_in_date=check_in_text
        )
        
        if success:
            logger.info(f"WhatsApp de pago aprobado enviado exitosamente para reserva {reservation.id}")
        else:
            logger.error(f"Error al enviar WhatsApp de pago aprobado para reserva {reservation.id}")
            
    except Exception as e:
        logger.error(f"Error al procesar notificación de pago aprobado para reserva {reservation.id}: {str(e)}")

def hash_data(data):
    if data:
        return hashlib.sha256(data.strip().lower().encode()).hexdigest()
    return None

@receiver(post_save, sender=Reservation)
def reservation_post_save_handler(sender, instance, created, **kwargs):
    """Maneja las notificaciones cuando se crea o actualiza una reserva"""
    if created:
        logger.debug(f"Nueva reserva creada: {instance.id} - Origen: {instance.origin}")
        notify_new_reservation(instance)
    else:
        # Verificar si cambió a estado pending (voucher subido)
        if instance.status == 'pending' and instance.origin == 'client':
            logger.debug(f"Reserva {instance.id} cambió a estado pending - Voucher subido")
            notify_voucher_uploaded(instance)
        
        # Verificar si cambió a estado approved (pago aprobado) y no se ha enviado la notificación
        elif instance.status == 'approved' and instance.origin == 'client' and not instance.payment_approved_notification_sent:
            logger.debug(f"Reserva {instance.id} cambió a estado approved - Pago aprobado")
            notify_payment_approved(instance)
            # Marcar como enviado para evitar duplicados
            instance.payment_approved_notification_sent = True
            instance.save(update_fields=['payment_approved_notification_sent'])

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