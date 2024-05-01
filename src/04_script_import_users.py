import csv, requests, json

import os
import django

from datetime import datetime

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "config.settings")
django.setup()

from apps.clients.models import Clients, TokenApiClients

from apps.core.functions import normalizar_fecha

URL_BASE = "https://script.google.com/macros/s/AKfycbyoBhxuklU5D3LTguTcYAS85klwFINHxxd-FroauC4CmFVvS0ua/exec"

informe_dni_con_problemas = []

with open('input_clientes.csv', 'r') as file:
    csv_reader = csv.reader(file)
    
    # FIXME obtener de la api
    query_token = TokenApiClients.objects.exclude(deleted=True).last()

    if query_token:
        token_rutificador = query_token.token

        for row in csv_reader:
            print('*'*50)
            print('Próximo DNI a analizar: ', row[0])
            if not Clients.objects.filter(document_type='dni', number_doc=row[0]).exists():
                url = f"{URL_BASE}?op=dni&token={token_rutificador}&formato=json&documento={row[0]}"

                req = requests.get(url)
                try:
                    serialized_data = json.loads(req.content)['data']

                    print('Datos obtenidos del api externo: ',json.loads(req.content)['data'])
                    print('*'*50)
                    print('*'*50)

                    # normalizamos la fecha
                    formatted_date = normalizar_fecha(serialized_data['fechaNacimiento'])

                    try:
                        print(f'No se registró cliente con DNI {row[0]}')
                        print('**Crear cliente**')
                        Clients.objects.create(
                            first_name=serialized_data['nombres'],
                            last_name=serialized_data['apellidoPaterno'] + " " + serialized_data['apellidoMaterno'],
                            document_type='dni',
                            number_doc=row[0],
                            date=formatted_date,
                            sex=serialized_data['sexo'],
                            tel_number=row[1]
                        )
                    except Exception as e:
                        print('No se puede crear cliente', str(e))
                        
                    else:
                        print(f'Cliente con DNI {row[0]} ya esta registrado en el sistema')
                except Exception as e:
                    print('Error procesando solicitud: ', str(e))
                    informe_dni_con_problemas.append(row[0])
    
    else:
        print('** No configuró token rutificador en el sistema **')


if informe_dni_con_problemas:
    print('Los siguientes DNI no puedieron obtenerse de la API', informe_dni_con_problemas)
else:
    print('Todas las solicitudes se procesaron con éxito')