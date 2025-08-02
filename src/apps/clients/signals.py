import logging
from django.db.models.signals import post_save
from django.dispatch import receiver
from .models import Clients
from django.conf import settings
import requests
import hashlib

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
        
        update_meta_audience(instance)
    else:
        # Solo actualizar audiencia si cambió información relevante (no solo last_login)
        if kwargs.get('update_fields'):
            # Si se especificaron campos específicos, verificar si son relevantes
            relevant_fields = {'email', 'tel_number', 'first_name', 'last_name'}
            updated_fields = set(kwargs['update_fields'])
            
            if relevant_fields.intersection(updated_fields):
                logger.debug(f"Cliente actualizado con campos relevantes: {instance}")
                update_meta_audience(instance)
        else:
            # Si no se especificaron campos, asumir que es una actualización relevante
            logger.debug(f"Cliente actualizado: {instance}")
            update_meta_audience(instance)