import logging
from django.db.models.signals import post_save, pre_save
from django.dispatch import receiver
from .models import Reservation, RentalReceipt
from ..core.telegram_notifier import send_telegram_message
from django.conf import settings
from .points_signals import check_and_assign_achievements
from datetime import datetime, date
import hashlib
import requests
import json

logger = logging.getLogger('apps')

# Import staff models for task updating
try:
    from ..staff.models import WorkTask, StaffMember
except ImportError:
    # Fallback in case staff app is not installed
    WorkTask = None
    StaffMember = None

# Diccionarios para fechas en español
MONTHS_ES = {
    1: "enero",
    2: "febrero",
    3: "marzo",
    4: "abril",
    5: "mayo",
    6: "junio",
    7: "julio",
    8: "agosto",
    9: "septiembre",
    10: "octubre",
    11: "noviembre",
    12: "diciembre"
}

DAYS_ES = {
    0: "Lunes",
    1: "Martes",
    2: "Miércoles",
    3: "Jueves",
    4: "Viernes",
    5: "Sábado",
    6: "Domingo"
}


def format_date_es(date):
    day = date.day
    month = MONTHS_ES[date.month]
    week_day = DAYS_ES[date.weekday()]
    return f"{week_day} {day} de {month}"


def calculate_upcoming_age(born):
    today = date.today()
    this_year_birthday = date(today.year, born.month, born.day)
    next_birthday = this_year_birthday if today <= this_year_birthday else date(
        today.year + 1, born.month, born.day)
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
        f"Teléfono : +{reservation.client.tel_number}")

    message_today = (f"******PARA HOYYYY******\n"
                     f"Cliente: {client_name}\n"
                     f"Check-in : {check_in_date}\n"
                     f"Check-out : {check_out_date}\n"
                     f"Invitados : {reservation.guests}\n"
                     f"Temperado : {temperature_pool_status}\n")

    full_image_url = None
    rental_receipt = RentalReceipt.objects.filter(
        reservation=reservation).first()
    if rental_receipt and rental_receipt.file and rental_receipt.file.name:
        image_url = f"{settings.MEDIA_URL}{rental_receipt.file.name}"
        full_image_url = f"http://api.casaaustin.pe{image_url}"

    logger.debug(
        f"Enviando mensaje de Telegram: {message} con imagen: {full_image_url}"
    )

    # Si es una reserva desde el panel del cliente, enviar solo al canal de clientes
    if reservation.origin == 'client':
        client_message = (f"******************************************\n"
                          f"💻 RESERVA DESDE PANEL WEB 💻\n"
                          f"Cliente: {client_name}\n"
                          f"Propiedad: {reservation.property.name}\n"
                          f"Check-in : {check_in_date}\n"
                          f"Check-out : {check_out_date}\n"
                          f"Invitados : {reservation.guests}\n"
                          f"Temperado : {temperature_pool_status}\n"
                          f"💰 Total: {price_sol} soles\n"
                          f"📱 Teléfono: +{reservation.client.tel_number}\n"
                          f"******************************************")
        send_telegram_message(client_message, settings.CLIENTS_CHAT_ID,
                              full_image_url)
    else:
        # Para todas las demás reservas (airbnb, austin, mantenimiento), enviar al canal principal
        send_telegram_message(message, settings.CHAT_ID, full_image_url)

    if reservation.check_in_date == datetime.today().date():
        logger.debug(
            "Reserva para el mismo día detectada, enviando al segundo canal.")
        send_telegram_message(message_today, settings.SECOND_CHAT_ID,
                              full_image_url)

    birthday = format_date_es(
        reservation.client.date
    ) if reservation.client and reservation.client.date else "No disponible"
    upcoming_age = calculate_upcoming_age(
        reservation.client.date
    ) if reservation.client and reservation.client.date else "No disponible"
    message_personal_channel = (
        f"******Reserva en {reservation.property.name}******\n"
        f"Cliente: {client_name}\n"
        f"Cumpleaños: {birthday} (Cumple {upcoming_age} años)\n"
        f"Check-in : {check_in_date}\n"
        f"Check-out : {check_out_date}\n"
        f"Invitados : {reservation.guests}\n"
        f"Temperado : {temperature_pool_status}\n"
        f"Teléfono : https://wa.me/{reservation.client.tel_number}")
    send_telegram_message(message_personal_channel, settings.PERSONAL_CHAT_ID,
                          full_image_url)


def notify_voucher_uploaded(reservation):
    """Notifica cuando un cliente sube su voucher de pago"""
    client_name = f"{reservation.client.first_name} {reservation.client.last_name}" if reservation.client else "Cliente desconocido"

    check_in_date = format_date_es(reservation.check_in_date)
    check_out_date = format_date_es(reservation.check_out_date)
    price_sol = f"{reservation.price_sol:.2f} soles"

    # Contar vouchers existentes para esta reserva
    vouchers_count = RentalReceipt.objects.filter(reservation=reservation).count()
    voucher_info = "PRIMER VOUCHER" if vouchers_count == 1 else f"VOUCHER #{vouchers_count}"
    if vouchers_count == 2:
        voucher_info = "SEGUNDO VOUCHER"

    voucher_message = (f"📄 **{voucher_info} RECIBIDO** 📄\n"
                       f"Cliente: {client_name}\n"
                       f"Propiedad: {reservation.property.name}\n"
                       f"Check-in: {check_in_date}\n"
                       f"Check-out: {check_out_date}\n"
                       f"💰 Total: {price_sol}\n"
                       f"📱 Teléfono: +{reservation.client.tel_number}\n"
                       f"⏰ Estado: Pendiente de validación\n"
                       f"🆔 Reserva ID: {reservation.id}")

    # Obtener la imagen del voucher de pago
    voucher_image_url = None
    rental_receipt = RentalReceipt.objects.filter(
        reservation=reservation).first()
    if rental_receipt and rental_receipt.file and rental_receipt.file.name:
        image_url = f"{settings.MEDIA_URL}{rental_receipt.file.name}"
        voucher_image_url = f"http://api.casaaustin.pe{image_url}"

    logger.debug(
        f"Enviando notificación de voucher subido para reserva: {reservation.id} con imagen: {voucher_image_url}"
    )
    send_telegram_message(voucher_message, settings.CLIENTS_CHAT_ID,
                          voucher_image_url)


def notify_payment_approved(reservation):
    """Notifica al cliente por WhatsApp cuando su pago es aprobado"""
    from ..clients.whatsapp_service import send_whatsapp_payment_approved

    if not reservation.client or not reservation.client.tel_number:
        logger.warning(
            f"No se puede enviar WhatsApp para reserva {reservation.id}: cliente o teléfono no disponible"
        )
        return

    try:
        # Preparar datos para el template - solo primer nombre y primer apellido
        first_name = reservation.client.first_name.split(
        )[0] if reservation.client.first_name else ""

        # Obtener solo el primer apellido si existe
        first_last_name = ""
        if reservation.client.last_name:
            first_last_name = reservation.client.last_name.split()[0]

        # Combinar primer nombre y primer apellido
        client_name = f"{first_name} {first_last_name}".strip()

        # Formatear información del pago - siempre usar advance_payment para aprobaciones manuales
        # El advance_payment representa lo que realmente pagó el cliente
        if reservation.advance_payment and reservation.advance_payment > 0:
            if reservation.advance_payment_currency == 'usd':
                payment_info = f"${reservation.advance_payment:.2f}"
            else:
                payment_info = f"S/{reservation.advance_payment:.2f}"
        else:
            payment_info = "S/0.00"
            logger.warning(
                f"Reserva sin advance_payment para reserva {reservation.id}")

        # Formatear fecha de check-in (formato dd/mm/yyyy)
        check_in_formatted = reservation.check_in_date.strftime("%d/%m/%Y")
        check_in_text = f"Para la reserva del {check_in_formatted}"

        logger.info(
            f"Enviando WhatsApp de pago aprobado a {reservation.client.tel_number} para reserva {reservation.id}"
        )
        logger.info(
            f"Datos: Nombre: {client_name}, Pago: {payment_info}, Check-in: {check_in_text}"
        )

        # Enviar WhatsApp
        success = send_whatsapp_payment_approved(
            phone_number=reservation.client.tel_number,
            client_name=client_name,
            payment_info=payment_info,
            check_in_date=check_in_text)

        if success:
            logger.info(
                f"WhatsApp de pago aprobado enviado exitosamente para reserva {reservation.id}"
            )
        else:
            logger.error(
                f"Error al enviar WhatsApp de pago aprobado para reserva {reservation.id}"
            )

    except Exception as e:
        logger.error(
            f"Error al procesar notificación de pago aprobado para reserva {reservation.id}: {str(e)}"
        )


def hash_data(data):
    if data:
        return hashlib.sha256(data.strip().lower().encode()).hexdigest()
    return None


@receiver(post_save, sender=Reservation)
def reservation_post_save_handler(sender, instance, created, **kwargs):
    """Maneja las notificaciones cuando se crea o actualiza una reserva"""
    if created:
        logger.debug(
            f"Nueva reserva creada: {instance.id} - Origen: {instance.origin}")
        notify_new_reservation(instance)

        # NUEVO: Crear tarea de limpieza automáticamente si la nueva reserva ya está aprobada
        if instance.status == 'approved':
            logger.info(f"New reservation created with approved status {instance.id} - Creating automatic cleaning task")
            create_automatic_cleaning_task(instance)

        # Verificar si la nueva reserva tiene pago completo
        if instance.full_payment:
            logger.debug(
                f"Nueva reserva {instance.id} creada con pago completo - Enviando flujo ChatBot"
            )
            send_chatbot_flow_payment_complete(instance)
    else:
        # Verificar si cambió a estado pending (voucher subido)
        if instance.status == 'pending' and instance.origin == 'client':
            logger.debug(
                f"Reserva {instance.id} cambió a estado pending - Voucher subido"
            )
            notify_voucher_uploaded(instance)

        # Verificar si cambió a estado approved (pago aprobado) y no se ha enviado la notificación
        elif instance.status == 'approved' and instance.origin == 'client' and not instance.payment_approved_notification_sent:
            logger.debug(
                f"Reserva {instance.id} cambió a estado approved - Pago aprobado"
            )
            notify_payment_approved(instance)
            # Marcar como enviado para evitar duplicados
            instance.payment_approved_notification_sent = True
            instance.save(update_fields=['payment_approved_notification_sent'])

        # Verificar si cambió el campo full_payment a True (pago completado)
        if hasattr(instance, '_original_full_payment'):
            if not instance._original_full_payment and instance.full_payment:
                logger.debug(
                    f"Reserva {instance.id} marcada como pago completo - Enviando flujo ChatBot"
                )
                send_chatbot_flow_payment_complete(instance)

        # Verificar logros después de actualizar el estado de la reserva
        try:
            if instance.client:
                check_and_assign_achievements(instance.client.id)

                # También verificar logros del cliente que refirió si existe
                if instance.client.referred_by:
                    check_and_assign_achievements(
                        instance.client.referred_by.id)
        except Exception as e:
            logger.error(
                f"Error verificando logros después de actualizar reserva: {str(e)}"
            )

        # NUEVO: Crear tarea de limpieza automáticamente cuando se aprueba la reserva
        if instance.status == 'approved' and hasattr(instance, '_original_status') and instance._original_status != 'approved':
            logger.info(f"Reservation {instance.id} status changed to approved - Creating automatic cleaning task")
            create_automatic_cleaning_task(instance)

        # NUEVO: Actualizar tareas de limpieza si cambió la fecha de checkout
        if hasattr(instance, '_original_check_out_date'):
            original_checkout = instance._original_check_out_date
            current_checkout = instance.check_out_date
            
            if original_checkout != current_checkout:
                logger.info(f"Checkout date changed for reservation {instance.id}: {original_checkout} -> {current_checkout}")
                update_cleaning_tasks_for_checkout_change(instance, original_checkout, current_checkout)


def send_chatbot_flow_payment_complete(reservation):
    """Envía flujo de ChatBot Builder cuando el pago está completo"""
    if not reservation.client or not reservation.client.id_manychat:
        logger.warning(
            f"No se puede enviar flujo ChatBot para reserva {reservation.id}: cliente o id_manychat no disponible"
        )
        return

    # Configuración de la API ChatBot Builder
    api_token = "1680437.Pgur5IA4kUXccspOK389nZugThdLB9h"
    flow_id = "1727388146335"  # Flujo para pago completo
    api_base_url = "https://app.chatgptbuilder.io/api"

    # URL para enviar el flujo
    url = f"{api_base_url}/contacts/{reservation.client.id_manychat}/send/{flow_id}"

    # Encabezados
    headers = {"X-ACCESS-TOKEN": api_token, "Content-Type": "application/json"}

    try:
        response = requests.post(url, headers=headers)
        if response.status_code == 200:
            logger.info(
                f"✅ Flujo de pago completo enviado a usuario {reservation.client.id_manychat} para reserva {reservation.id}"
            )
        else:
            logger.error(
                f"❌ Error enviando flujo de pago completo a {reservation.client.id_manychat}. Código: {response.status_code}"
            )
            logger.error(f"Respuesta: {response.text}")
    except Exception as e:
        logger.error(
            f"⚠️ Error enviando flujo ChatBot para reserva {reservation.id}: {e}"
        )


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
            logger.warning(
                f"Error procesando fecha de nacimiento '{birthday}': {e}")

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
        user_data[
            "click_id"] = fbclid  # Usualmente no obligatorio si ya tienes fbc/fbp

    # Armamos el payload
    payload = {
        "data": [{
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
        }],
        "access_token":
        settings.META_PIXEL_TOKEN
    }

    # Logging completo para depuración
    logger.debug("Payload enviado a Meta:\n%s", json.dumps(payload, indent=2))

    # Enviar evento a Meta
    response = requests.post(
        "https://graph.facebook.com/v18.0/7378335482264695/events",
        json=payload,
        headers={"Content-Type": "application/json"})

    if response.status_code == 200:
        logger.debug(
            f"Evento de conversión enviado correctamente a Meta. Respuesta: {response.text}"
        )
    else:
        logger.warning(
            f"Error al enviar evento a Meta. Código: {response.status_code} Respuesta: {response.text}"
        )


# ============================================================================
# NUEVOS SIGNALS PARA ACTUALIZACIÓN AUTOMÁTICA DE TAREAS DE LIMPIEZA
# ============================================================================

@receiver(pre_save, sender=Reservation)
def reservation_pre_save_handler(sender, instance, **kwargs):
    """Guarda el estado original antes de modificar la reserva"""
    if instance.pk:  # Solo si la reserva ya existe
        try:
            # Obtener la reserva original desde la base de datos
            original = Reservation.objects.get(pk=instance.pk)
            # Guardar los valores originales en la instancia
            instance._original_check_out_date = original.check_out_date
            instance._original_status = original.status
        except Reservation.DoesNotExist:
            # Si no existe, es una nueva reserva
            instance._original_check_out_date = None
            instance._original_status = None
    else:
        # Nueva reserva
        instance._original_check_out_date = None
        instance._original_status = None


def update_cleaning_tasks_for_checkout_change(reservation, original_checkout, new_checkout):
    """Actualiza las tareas de limpieza cuando cambia la fecha de checkout"""
    if not WorkTask:  # Verificar si el modelo WorkTask está disponible
        logger.warning("WorkTask model not available, skipping task update")
        return
    
    try:
        # Buscar tareas de limpieza relacionadas con esta reserva
        cleaning_tasks = WorkTask.objects.filter(
            reservation=reservation,
            task_type='checkout_cleaning',
            scheduled_date=original_checkout,  # Tareas programadas para la fecha original
            status__in=['pending', 'assigned']  # Solo tareas que aún no han iniciado
        )
        
        updated_count = 0
        for task in cleaning_tasks:
            # Actualizar la fecha programada
            old_date = task.scheduled_date
            task.scheduled_date = new_checkout
            task.save()
            
            logger.info(
                f"✅ Updated cleaning task {task.id} for reservation {reservation.id}: "
                f"{old_date} -> {new_checkout}"
            )
            updated_count += 1
        
        if updated_count > 0:
            logger.info(f"Successfully updated {updated_count} cleaning tasks for reservation {reservation.id}")
        else:
            logger.info(f"No cleaning tasks found to update for reservation {reservation.id}")
            
    except Exception as e:
        logger.error(f"❌ Error updating cleaning tasks for reservation {reservation.id}: {str(e)}")


def create_automatic_cleaning_task(reservation):
    """Crear automáticamente tarea de limpieza cuando se aprueba una reserva"""
    if not WorkTask or not StaffMember:
        logger.warning("Staff models not available, skipping automatic task creation")
        return
    
    try:
        # Verificar que no exista ya una tarea de limpieza para esta reserva
        existing_task = WorkTask.objects.filter(
            reservation=reservation,
            task_type='checkout_cleaning',
            deleted=False
        ).first()
        
        if existing_task:
            logger.info(f"Cleaning task already exists for reservation {reservation.id}")
            return
        
        # Buscar el mejor personal de limpieza disponible
        assigned_staff = find_best_cleaning_staff(reservation.check_out_date, reservation.property)
        
        if not assigned_staff:
            logger.warning(f"No cleaning staff available for reservation {reservation.id} on {reservation.check_out_date}")
            # Crear tarea sin asignar para revisión manual
            assigned_staff = None
        
        # Crear la tarea de limpieza
        cleaning_task = WorkTask.objects.create(
            staff_member=assigned_staff,
            building_property=reservation.property,
            reservation=reservation,
            task_type='checkout_cleaning',
            title=f"Limpieza checkout - {reservation.property.name}",
            description=f"Limpieza post-checkout para reserva #{reservation.id}\nCliente: {f'{reservation.client.first_name} {reservation.client.last_name}'.strip() if reservation.client else 'N/A'}",
            scheduled_date=reservation.check_out_date,
            estimated_duration='02:00:00',  # 2 horas por defecto
            priority='medium',
            status='assigned' if assigned_staff else 'pending',
            requires_photo_evidence=True
        )
        
        if assigned_staff:
            logger.info(
                f"✅ Created and assigned cleaning task {cleaning_task.id} to {assigned_staff.first_name} {assigned_staff.last_name} "
                f"for reservation {reservation.id} on {reservation.check_out_date}"
            )
        else:
            logger.info(
                f"✅ Created unassigned cleaning task {cleaning_task.id} for reservation {reservation.id} "
                f"on {reservation.check_out_date} - requires manual assignment"
            )
            
    except Exception as e:
        logger.error(f"❌ Error creating automatic cleaning task for reservation {reservation.id}: {str(e)}")


def find_best_cleaning_staff(scheduled_date, property_obj):
    """Encuentra el mejor personal de limpieza disponible para una fecha y propiedad específica"""
    if not StaffMember:
        return None
    
    try:
        # Buscar personal de limpieza activo
        cleaning_staff = StaffMember.objects.filter(
            staff_type='cleaning',
            status='active',
            deleted=False
        )
        
        if not cleaning_staff.exists():
            logger.warning("No active cleaning staff found")
            return None
        
        # Evaluar cada miembro del staff y asignar puntuación
        staff_scores = []
        
        for staff in cleaning_staff:
            score = calculate_staff_score(staff, scheduled_date, property_obj)
            if score > 0:  # Solo considerar staff disponible
                staff_scores.append((staff, score))
        
        if not staff_scores:
            logger.warning(f"No available cleaning staff for {scheduled_date}")
            return None
        
        # Ordenar por puntuación (mayor es mejor) y retornar el mejor
        staff_scores.sort(key=lambda x: x[1], reverse=True)
        best_staff = staff_scores[0][0]
        
        logger.info(f"Selected {best_staff.first_name} {best_staff.last_name} as best cleaning staff for {scheduled_date}")
        return best_staff
        
    except Exception as e:
        logger.error(f"Error finding best cleaning staff: {str(e)}")
        return None


def calculate_staff_score(staff, scheduled_date, property_obj):
    """Calcula puntuación para un miembro del staff basado en disponibilidad y carga de trabajo"""
    score = 100  # Puntuación base
    
    try:
        # Verificar disponibilidad en fin de semana
        weekday = scheduled_date.weekday()  # 0=Monday, 6=Sunday
        if weekday >= 5 and not staff.can_work_weekends:  # Sábado o domingo
            return 0  # No disponible en fin de semana
        
        # Contar tareas ya asignadas para esa fecha
        tasks_on_date = WorkTask.objects.filter(
            staff_member=staff,
            scheduled_date=scheduled_date,
            status__in=['pending', 'assigned', 'in_progress'],
            deleted=False
        ).count()
        
        # Verificar límite máximo de propiedades por día
        if tasks_on_date >= staff.max_properties_per_day:
            return 0  # Ya tiene el máximo de tareas
        
        # Reducir puntuación según carga de trabajo actual
        score -= tasks_on_date * 20  # -20 puntos por cada tarea existente
        
        # Bonus por menos carga de trabajo
        if tasks_on_date == 0:
            score += 30  # Bonus por estar completamente libre
        
        # Verificar si tiene horario programado para ese día
        try:
            from ..staff.models import WorkSchedule
            schedule = WorkSchedule.objects.filter(
                staff_member=staff,
                date=scheduled_date,
                deleted=False
            ).first()
            
            if schedule:
                score += 20  # Bonus por tener horario programado
            else:
                score -= 10  # Penalización por no tener horario
                
        except ImportError:
            pass  # WorkSchedule no disponible
        
        return max(score, 0)  # Asegurar que el score no sea negativo
        
    except Exception as e:
        logger.error(f"Error calculating score for staff {staff.id}: {str(e)}")
        return 0
