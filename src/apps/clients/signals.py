import logging
from django.db.models.signals import post_save
from django.dispatch import receiver
from .models import Clients, Achievement, ClientAchievement
from django.conf import settings
import requests
import hashlib
from ..core.telegram_notifier import send_telegram_message

logger = logging.getLogger('apps')

def hash_data(data):
    if data:
        return hashlib.sha256(data.strip().lower().encode()).hexdigest()
    return None

def update_meta_audience(client):
    email_hash = ""
    phone_hash = ""

    if client.email:
        email_hash = hash_data(client.email)
    if client.tel_number:
        telefono = client.tel_number.strip()
        if not telefono.startswith('+'):
            telefono = f"+{telefono}"
        phone_hash = hash_data(telefono)

    schema_list = ['EMAIL_SHA256', 'PHONE_SHA256']
    data_list = [[email_hash, phone_hash]]

    payload = {
        'payload': {
            'schema': schema_list,
            'data': data_list
        }
    }

    response = requests.post(
        f"https://graph.facebook.com/v19.0/{settings.META_AUDIENCE_ID}/users",
        params={'access_token': settings.META_AUDIENCE_TOKEN},
        json=payload
    )

    if response.status_code == 200:
        logger.debug(f"Audiencia actualizada para cliente {client.id}. Respuesta: {response.text}")
    else:
        logger.warning(f"Error al actualizar audiencia de cliente {client.id}. Código: {response.status_code} Respuesta: {response.text}")

def notify_new_client_registration(client):
    """Envía notificación de Telegram cuando se registra un nuevo cliente"""
    try:
        client_name = f"{client.first_name} {client.last_name}" if client.last_name else client.first_name
        document_info = f"{client.get_document_type_display()}: {client.number_doc}"
        
        message = (
            f"🆕 **NUEVO CLIENTE REGISTRADO** 🆕\n"
            f"👤 Cliente: {client_name}\n"
            f"📄 Documento: {document_info}\n"
            f"📧 Email: {client.email or 'No proporcionado'}\n"
            f"📱 Teléfono: +{client.tel_number}\n"
            f"🔑 Contraseña: {'✅ Configurada' if client.is_password_set else '❌ Pendiente'}\n"
            f"🔗 Código referido: {client.referral_code or 'Generando...'}"
        )
        
        send_telegram_message(message, settings.CLIENTS_CHAT_ID)
        logger.debug(f"Notificación enviada para nuevo cliente: {client.id}")
    except Exception as e:
        logger.error(f"Error enviando notificación de nuevo cliente {client.id}: {str(e)}")

def notify_password_setup(client):
    """Envía notificación de Telegram cuando un cliente configura su contraseña"""
    try:
        client_name = f"{client.first_name} {client.last_name}" if client.last_name else client.first_name
        
        message = (
            f"🔐 **CONTRASEÑA CONFIGURADA** 🔐\n"
            f"👤 Cliente: {client_name}\n"
            f"📄 Documento: {client.get_document_type_display()}: {client.number_doc}\n"
            f"📱 Teléfono: +{client.tel_number}\n"
            f"✅ El cliente ya puede acceder a su panel"
        )
        
        send_telegram_message(message, settings.CLIENTS_CHAT_ID)
        logger.debug(f"Notificación enviada para configuración de contraseña: {client.id}")
    except Exception as e:
        logger.error(f"Error enviando notificación de configuración de contraseña {client.id}: {str(e)}")


def check_and_assign_achievements(client):
    """Verifica y asigna automáticamente logros al cliente según sus métricas"""
    try:
        # Obtener todos los logros activos ordenados por requisitos
        achievements = Achievement.objects.filter(
            is_active=True,
            deleted=False
        ).order_by('order', 'required_reservations', 'required_referrals')
        
        new_achievements = []
        
        for achievement in achievements:
            # Verificar si el cliente ya tiene este logro
            if ClientAchievement.objects.filter(
                client=client,
                achievement=achievement,
                deleted=False
            ).exists():
                continue
            
            # Verificar si el cliente cumple los requisitos
            if achievement.check_client_qualifies(client):
                # Asignar el logro
                client_achievement = ClientAchievement.objects.create(
                    client=client,
                    achievement=achievement
                )
                new_achievements.append(client_achievement)
                logger.info(f"Logro automático asignado: {achievement.name} a {client.first_name} {client.last_name}")
        
        # Si se asignaron logros, enviar notificación
        if new_achievements:
            notify_new_achievements(client, new_achievements)
            
    except Exception as e:
        logger.error(f"Error verificando logros para cliente {client.id}: {str(e)}")


def notify_new_achievements(client, achievements):
    """Envía notificación cuando se asignan nuevos logros automáticamente"""
    try:
        client_name = f"{client.first_name} {client.last_name}" if client.last_name else client.first_name
        
        achievements_list = "\n".join([f"🏆 {ach.achievement.name}" for ach in achievements])
        
        message = (
            f"🎉 **NUEVOS LOGROS ASIGNADOS** 🎉\n"
            f"👤 Cliente: {client_name}\n"
            f"📄 Documento: {client.get_document_type_display()}: {client.number_doc}\n"
            f"🏅 Logros obtenidos:\n{achievements_list}"
        )
        
        send_telegram_message(message, settings.CLIENTS_CHAT_ID)
        logger.debug(f"Notificación enviada para logros asignados a cliente: {client.id}")
    except Exception as e:
        logger.error(f"Error enviando notificación de logros para cliente {client.id}: {str(e)}")

@receiver(post_save, sender=Clients)
def update_audience_on_client_creation(sender, instance, created, **kwargs):
    if created:
        logger.debug(f"Nuevo cliente creado: {instance}")

        # Generar código de referido si no existe
        if not instance.referral_code:
            try:
                referral_code = instance.generate_referral_code()
                # Guardar el cliente con el nuevo código de referido
                instance.save(update_fields=['referral_code'])
                logger.debug(f"Código de referido generado para cliente {instance.id}: {referral_code}")
            except Exception as e:
                logger.error(f"Error generando código de referido para cliente {instance.id}: {str(e)}")

        # Verificar y asignar logros automáticamente
        check_and_assign_achievements(instance)

        update_meta_audience(instance)
        
        # Enviar notificación de nuevo cliente registrado
        notify_new_client_registration(instance)
    else:
        # Solo actualizar audiencia si cambió información relevante (no solo last_login)
        if kwargs.get('update_fields'):
            # Si se especificaron campos específicos, verificar si son relevantes
            relevant_fields = {'email', 'tel_number', 'first_name', 'last_name', 'is_password_set'}
            updated_fields = set(kwargs['update_fields'])

            if relevant_fields.intersection(updated_fields):
                logger.debug(f"Cliente actualizado con campos relevantes: {instance}")
                update_meta_audience(instance)
                
                # Si se configuró la contraseña, enviar notificación
                if 'is_password_set' in updated_fields and instance.is_password_set:
                    notify_password_setup(instance)
        else:
            # Si no se especificaron campos, asumir que es una actualización relevante
            logger.debug(f"Cliente actualizado: {instance}")
            update_meta_audience(instance)
            # También verificar logros en actualizaciones generales
            check_and_assign_achievements(instance)