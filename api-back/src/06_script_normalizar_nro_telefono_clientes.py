import csv, requests, json

import os
import django

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "config.settings")
django.setup()

from apps.clients.models import Clients

def remove_unicode_202c(s):
    return s.replace('‬', '')


def normalizar_tel_clientes():
    print('*** Comenzar proceso de normalizar telefonos de clientes clientes ***')
    for c in Clients.objects.all():
        
        c.tel_number = remove_unicode_202c(c.tel_number)

        if c.tel_number and len(c.tel_number) < 11 and c.tel_number[:2] != "51":
            c.tel_number = "51"+c.tel_number
            c.save()

    print('*** Finalizar proceso de normalizar telefonos de clientes clientes ***')



if __name__ == "__main__":
    normalizar_tel_clientes()