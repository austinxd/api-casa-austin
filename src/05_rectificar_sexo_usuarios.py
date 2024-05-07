import csv, requests, json

import os
import django

from datetime import datetime

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "config.settings")
django.setup()

from apps.clients.models import Clients, TokenApiClients

from apps.core.functions import normalizar_fecha

URL_BASE = "https://script.google.com/macros/s/AKfycbxtHPLO20nmW5Vy4r_9MGcC5bQUCFXg1LaKUA-aIUpQ4K3oo-Mz8smlIfcWQJCefWF0Zw/exec"


def import_clients():
    print('*** Comenzar proceso de importación de clientes ***')
    informe_dni_con_problemas = []

    with open('input_clientes.csv', 'r') as file:
        csv_reader = csv.reader(file)
        
        # FIXME obtener de la api
        query_token = TokenApiClients.objects.exclude(deleted=True).last()

        if query_token:
            token_rutificador = query_token.token

            for row in csv_reader:
                print('*'*50)
                current_dni = row[0].strip()
                print('Próximo DNI a analizar: ', current_dni)

                url = f"{URL_BASE}?op=dni&token={token_rutificador}&formato=json&documento={current_dni}"
                req = requests.get(url)

                try:
                    serialized_data = json.loads(req.content)['data']
                    print('Datos Respuesta servidor: ', serialized_data)
                    client = Clients.objects.get(number_doc=current_dni)
                    client.sex = serialized_data['sexo'].lower()
                    client.save()
                except Exception as e:
                    print('Error:', str(e))

if __name__ == "__main__":
    import_clients()