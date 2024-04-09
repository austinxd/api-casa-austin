import os
import django

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "config.settings")
django.setup()

from apps.property.models import Property

from apps.core.functions import update_air_bnb_api


def get_airbnb_reservations():
    print('Comenzando proceso para obtener propeiedades de API de AirBnB')
    query_property = Property.objects.exclude(airbnb_url__isnull=True)

    for q in query_property:
        try:
            if q.airbnb_url:
                update_air_bnb_api(q)
        except Exception as e:
            print('Error obteniendo datos api airbnb:', str(e))

    print('Finalizando proceso para obtener propeiedades de API de AirBnB')

if __name__ == "__main__":
    get_airbnb_reservations()