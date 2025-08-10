#!/usr/bin/env python3

import os
import django
import hashlib
import requests
import json

# Configuración de Django
os.environ.setdefault("DJANGO_SETTINGS_MODULE", "config.settings")
django.setup()

from apps.clients.models import Clients

# Datos de Meta Ads
ACCESS_TOKEN = 'EAATkbUyZBNVYBO9ZAROZBgquW32WaLgRJZC9YlTzfmWnF48ESwZAeR1IBdNiZBiNDNgj4hs6O5HIJlsWAfgMkpQ3GbmIApsUsrVfEQ22ZCE7idsVjfoRSLH0yS4KRirBI9NtWIalBzWq23jKNm52c1Iv3bJ5328clGZBtaz6hmK6svdw28ZANVYO6jKxCcbKQHRErlAZDZD'
AUDIENCE_ID = '120225356885930355'  # Sustituye con tu ID real de audiencia
API_URL = f'https://graph.facebook.com/v19.0/{AUDIENCE_ID}/users'

def encriptar_sha256(texto):
    """Convierte texto a SHA256, en minúsculas y sin espacios alrededor."""
    return hashlib.sha256(texto.strip().lower().encode('utf-8')).hexdigest()

def enviar_audiencia(schema_list, data_list):
    """Envía los datos a la API de Audiencias Personalizadas de Meta con el nivel 'payload'."""
    payload = {
        'payload': {
            'schema': schema_list,
            'data': data_list
        }
    }

    print(f"Payload enviado a Meta:\n{json.dumps(payload, indent=2)}")

    response = requests.post(
        API_URL,
        params={'access_token': ACCESS_TOKEN},
        json=payload
    )

    print(f'Respuesta de Meta:\nCódigo: {response.status_code}\nContenido: {response.text}')
    return response.status_code == 200

def main():
    # Filtrar clientes con DNI o CEX, teléfono y que no hayan sido enviados aún
    clientes = Clients.objects.filter(
        document_type__in=['dni', 'cex'],
        tel_number__isnull=False,
        enviado_meta=False
    ).exclude(tel_number='').distinct()

    data_list = []

    # Construir lista de listas con los datos encriptados
    for cliente in clientes:
        # Inicializar los hashes como cadenas vacías
        email_hash = ""
        phone_hash = ""

        if cliente.email:
            email_hash = encriptar_sha256(cliente.email)

        if cliente.tel_number:
            telefono = cliente.tel_number.strip()
            if not telefono.startswith('+'):
                telefono = '+' + telefono  # Solo añadir '+' para no duplicar código país
            print(f"Número que se enviará a Meta para cliente {cliente.id} (antes de hash): {telefono}")
            phone_hash = encriptar_sha256(telefono)

        # Siempre agregar ambos campos, aunque estén vacíos
        data_list.append([email_hash, phone_hash])

    # Declarar el esquema que coincide con las columnas de cada fila
    schema_list = ['EMAIL_SHA256', 'PHONE_SHA256']

    # Enviar los datos a la audiencia si hay datos
    if data_list:
        exito = enviar_audiencia(schema_list, data_list)

        if exito:
            for cliente in clientes:
                cliente.enviado_meta = True
                cliente.save(update_fields=['enviado_meta'])
            print(f"Clientes marcados como enviados: {len(clientes)}")

    print('Proceso completado para usuarios con DNI o CEX.')

if __name__ == '__main__':
    main()
