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
    """Convierte texto a SHA256, en minúsculas y sin espacios alrededor."""
    return hashlib.sha256(texto.strip().lower().encode('utf-8')).hexdigest()

def enviar_audiencia(schema_list, data_list):
    """Envía los datos a la API de Audiencias Personalizadas de Meta."""
    payload = {
        'schema': schema_list,
        'data': data_list
    }

    response = requests.post(
        API_URL,
        params={'access_token': ACCESS_TOKEN},
        json=payload
    )

    print(f'Respuesta para {schema_list}: {response.status_code} {response.text}')
    return response.status_code == 200

def main():
    # Filtrar clientes con DNI o CEX, teléfono y que no hayan sido enviados aún
    clientes = Clients.objects.filter(
        document_type__in=['dni', 'cex'],
        tel_number__isnull=False,
        enviado_meta=False
    ).exclude(tel_number='').distinct()

    data_list = []

    # Armar lista de listas con datos hash
    for cliente in clientes:
        row = []
        if cliente.email:
            row.append(encriptar_sha256(cliente.email))
        if cliente.tel_number:
            telefono = cliente.tel_number.strip()
            if not telefono.startswith('+'):
                telefono = '+51' + telefono
            row.append(encriptar_sha256(telefono))
        if row:
            data_list.append(row)

    # Verificar qué esquemas se están enviando
    schema_list = []
    if any(cliente.email for cliente in clientes):
        schema_list.append('EMAIL_SHA256')
    if any(cliente.tel_number for cliente in clientes):
        schema_list.append('PHONE_SHA256')

    # Enviar datos a la audiencia
    if data_list and schema_list:
        exito = enviar_audiencia(schema_list, data_list)

        if exito:
            for cliente in clientes:
                cliente.enviado_meta = True
                cliente.save(update_fields=['enviado_meta'])
            print(f"Clientes marcados como enviados: {len(clientes)}")

    print('Proceso completado para usuarios con DNI o CEX.')

if __name__ == '__main__':
    main()
