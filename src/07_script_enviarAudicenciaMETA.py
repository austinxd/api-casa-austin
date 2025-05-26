#!/usr/bin/env python3

import os
import django
import hashlib
import requests

# Configuración de Django
os.environ.setdefault("DJANGO_SETTINGS_MODULE", "config.settings")
django.setup()

from apps.clients.models import Clients

# Datos de Meta Ads
ACCESS_TOKEN = 'EAATkbUyZBNVYBO1DuycdGet7yZBxdltJNC5CK1lmXSGSenguH0zuLmt0H0fxzaS8Y9KZAcCU5uqAZA52FGEzTqHZCFwwbclO59keYEIJAmBups2NYe6I0e5tmIExprZAi2WiO0Iyhtg2G5hJ1kBqHa6XR29obEZCKrUCjqsSAUioY1XYjkT0n6sHQI1oZCXHXjcnqwZDZD'
AUDIENCE_ID = '120225356885930355'  # Sustituye con tu ID de audiencia real
API_URL = f'https://graph.facebook.com/v19.0/{AUDIENCE_ID}/users'

def encriptar_sha256(texto):
    return hashlib.sha256(texto.strip().lower().encode('utf-8')).hexdigest()

def enviar_audiencia(schema, data):
    payload = {
        'payload': {
            'schema': schema,
            'data': data
        }
    }

    response = requests.post(
        API_URL,
        params={'access_token': ACCESS_TOKEN},
        json=payload
    )

    print(f'Respuesta para {schema}: {response.status_code} {response.text}')
    return response.status_code == 200

def main():
    # Solo usuarios con document_type dni o cex, con teléfono y que no hayan sido enviados aún
    clientes = Clients.objects.filter(
        document_type__in=['dni', 'cex'],
        tel_number__isnull=False,
        enviado_meta=False
    ).exclude(tel_number='').distinct()

    telefonos_hash = []
    emails_hash = []
    clientes_enviados = []

    for cliente in clientes:
        if cliente.tel_number:
            telefono = cliente.tel_number.strip()
            # Normaliza el teléfono a formato internacional (+51)
            if not telefono.startswith('+'):
                telefono = '+51' + telefono
            telefonos_hash.append(encriptar_sha256(telefono))

        if cliente.email:
            emails_hash.append(encriptar_sha256(cliente.email))

        # Marcamos como enviados para actualizar después
        clientes_enviados.append(cliente)

    exito_telefonos = False
    exito_emails = False

    if telefonos_hash:
        exito_telefonos = enviar_audiencia('PHONE_SHA256', telefonos_hash)

    if emails_hash:
        exito_emails = enviar_audiencia('EMAIL_SHA256', emails_hash)

    # Si se enviaron los datos exitosamente, marcamos en la base
    if exito_telefonos or exito_emails:
        for cliente in clientes_enviados:
            cliente.enviado_meta = True
            cliente.save(update_fields=['enviado_meta'])
        print(f"Clientes marcados como enviados: {len(clientes_enviados)}")

    print('Proceso completado para usuarios con DNI o CEX.')

if __name__ == '__main__':
    main()
