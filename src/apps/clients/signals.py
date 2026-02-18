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
    """Envía notificación de Telegram y Push cuando se registra un nuevo cliente"""
    try:
        client_name = f"{client.first_name} {client.last_name}" if client.last_name else client.first_name
        document_info = f"{client.get_document_type_display()}: {client.number_doc}"
        
        # Telegram notification
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
        logger.debug(f"Notificación Telegram enviada para nuevo cliente: {client.id}")
        
        # Push notification to admins
        try:
            from apps.clients.expo_push_service import ExpoPushService
            
            referred_by_text = ""
            if client.referred_by:
                referrer_name = f"{client.referred_by.first_name} {client.referred_by.last_name}" if client.referred_by.last_name else client.referred_by.first_name
                referred_by_text = f"\nReferido por: {referrer_name}"
            
            result = ExpoPushService.send_to_admins(
                title="Nuevo Cliente Registrado",
                body=f"{client_name}\n{document_info} | 📱 +{client.tel_number}{referred_by_text}",
                data={
                    "type": "admin_client_registered",
                    "notification_type": "admin_client_registered",
                    "client_id": str(client.id),
                    "client_name": client_name,
                    "document_type": client.document_type,
                    "number_doc": client.number_doc,
                    "email": client.email or "",
                    "tel_number": client.tel_number,
                    "referral_code": client.referral_code or "",
                    "referred_by_id": str(client.referred_by.id) if client.referred_by else "",
                    "referred_by_name": f"{client.referred_by.first_name} {client.referred_by.last_name}" if client.referred_by and client.referred_by.last_name else (client.referred_by.first_name if client.referred_by else ""),
                    "is_password_set": client.is_password_set,
                    "screen": "AdminClients"
                }
            )
            
            if result and result.get('success'):
                logger.info(f"✅ Notificación push enviada a {result.get('sent', 0)} administrador(es) para nuevo cliente")
        except ImportError:
            logger.warning("ExpoPushService no disponible - notificación push deshabilitada")
        except Exception as push_error:
            logger.error(f"Error enviando notificación push para nuevo cliente {client.id}: {str(push_error)}")
            
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


def notify_whatsapp_successful_registration(client):
    """Envía notificación de WhatsApp al cliente cuando se registra exitosamente"""
    try:
        # Solo el primer nombre para la plantilla WhatsApp
        first_name = client.first_name.split()[0] if client.first_name else "Cliente"
        
        if client.tel_number:
            from apps.clients.whatsapp_service import send_whatsapp_successful_registration
            
            logger.info(f"Enviando WhatsApp de bienvenida a {client.tel_number} para cliente {client.id}")
            whatsapp_success = send_whatsapp_successful_registration(
                phone_number=client.tel_number,
                client_name=first_name
            )
            
            if whatsapp_success:
                logger.info(f"WhatsApp de bienvenida enviado exitosamente para cliente {client.id}")
            else:
                logger.error(f"Error al enviar WhatsApp de bienvenida para cliente {client.id}")
        else:
            logger.warning(f"Cliente {client.id} no tiene teléfono - no se envía WhatsApp de bienvenida")
            
    except Exception as e:
        logger.error(f"Error enviando WhatsApp de bienvenida para cliente {client.id}: {str(e)}")


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
        # Filtrar logros para excluir el más bajo
        # El logro más bajo es el que tiene los requisitos mínimos (ordenado por order, required_reservations, etc.)
        lowest_achievement = Achievement.objects.filter(
            is_active=True,
            deleted=False
        ).order_by('order', 'required_reservations', 'required_referrals', 'required_referral_reservations').first()
        
        # Filtrar achievements para excluir el logro más bajo
        filtered_achievements = []
        if lowest_achievement:
            filtered_achievements = [ach for ach in achievements if ach.achievement.id != lowest_achievement.id]
        else:
            filtered_achievements = achievements
        
        # Solo enviar notificación si hay logros después de filtrar
        if not filtered_achievements:
            logger.debug(f"No se envía notificación para cliente {client.id} - solo se asignó el logro más bajo")
            return
        
        client_name = f"{client.first_name} {client.last_name}" if client.last_name else client.first_name
        
        achievements_list = "\n".join([f"🏆 {ach.achievement.name}" for ach in filtered_achievements])
        
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

def register_client_activity_feed(client):
    """Registra el nuevo cliente en el Activity Feed"""
    try:
        # Importación local para evitar problemas de dependencias circulares
        from apps.events.models import ActivityFeed
        
        # Verificar si el cliente fue referido y obtener información del referente
        referred_by_info = None
        referral_info = ""
        if client.referred_by:
            # Usar formato de privacidad para el nombre del referente
            private_name = ActivityFeed.format_client_name_private(client.referred_by)
            referred_by_info = {
                'id': str(client.referred_by.id),
                'name': private_name,
                'referral_code': client.referred_by.get_referral_code()
            }
            referral_info = f"referido por {private_name}"
            
            # Obtener porcentaje de puntos por referidos
            try:
                from apps.clients.models import ReferralPointsConfig
                config = ReferralPointsConfig.objects.filter(is_active=True).first()
                referral_percentage = float(config.percentage) if config else 10.0
            except:
                referral_percentage = 10.0
                
            referred_by_info['points_percentage'] = referral_percentage
        
        # Solo datos mínimos necesarios para el mensaje público
        activity_data = {
            'referral_info': referral_info,
            'referred_by_info': referred_by_info,
            'registration_method': 'web_form'  # Información pública general
        }
        
        # Crear actividad en el feed
        activity = ActivityFeed.create_activity(
            activity_type=ActivityFeed.ActivityType.CLIENT_REGISTERED,
            client=client,
            activity_data=activity_data,
            is_public=True,  # Los nuevos registros son públicos
            importance_level=2
        )
        
        logger.info(f"✅ Actividad de registro registrada en feed para cliente {client.id}: {activity.id}")
        
    except Exception as e:
        logger.error(f"❌ Error registrando actividad en feed para cliente {client.id}: {str(e)}")

def link_chat_session_to_new_client(client):
    """Vincula sesiones de chat sin cliente que coincidan por teléfono"""
    try:
        import re
        from apps.chatbot.models import ChatSession

        phone = client.tel_number
        if not phone:
            return

        digits = re.sub(r'\D', '', phone)
        variants = {digits}
        if digits.startswith('51') and len(digits) > 9:
            variants.add(digits[2:])
        elif len(digits) == 9:
            variants.add(f'51{digits}')
        # También agregar con +
        variants.add(f'+{digits}')

        session = ChatSession.objects.filter(
            wa_id__in=list(variants),
            client__isnull=True,
            deleted=False,
        ).order_by('-last_message_at').first()

        if session:
            session.client = client
            session.client_was_new = True  # Siempre True: el cliente se acaba de crear
            session.save(update_fields=['client', 'client_was_new'])
            logger.info(f"🤖 Sesión de chat {session.id} vinculada a nuevo cliente {client.id}")
    except Exception as e:
        logger.error(f"Error vinculando sesión de chat a nuevo cliente {client.id}: {e}")


@receiver(post_save, sender=Clients)
def update_audience_on_client_creation(sender, instance, created, **kwargs):
    if created:
        logger.debug(f"Nuevo cliente creado: {instance}")

        # 🤖 Vincular sesiones de chat existentes sin cliente
        link_chat_session_to_new_client(instance)

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
        
        # Registrar actividad en el ActivityFeed
        register_client_activity_feed(instance)
        
        # Enviar notificación interna de nuevo cliente registrado (Telegram)
        notify_new_client_registration(instance)
        
        # Enviar notificación de bienvenida al cliente (WhatsApp)
        notify_whatsapp_successful_registration(instance)
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