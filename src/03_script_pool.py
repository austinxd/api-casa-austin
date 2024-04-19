import os
import django
import requests

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "config.settings")
django.setup()

from datetime import date, datetime, time, timedelta

from apps.property.models import Property

from apps.reservation.models import Reservation

def pool_temperature():
    print('Iniciando proceso de encendido o apagado de piscina temperada')
    properties = Property.objects.all()
    tomorrow = datetime.today() + timedelta(days=1)

    for p in properties:
        if p.on_temperature_pool_url and p.off_temperature_pool_url:
            print(p.name)
            query_reservations = Reservation.objects.filter(property=p, check_in_date=tomorrow.date())
            print('Reservas de mañana: ', query_reservations)
            if query_reservations:
                print('-------')
                if query_reservations.first().temperature_pool and p.on_temperature_pool_url:
                    print('La reserva solicitó piscina temperada - Apagar piscina')
                    requests.get(p.on_temperature_pool_url)
                elif not query_reservations.first().temperature_pool and p.off_temperature_pool_url:
                    print('La reserva no solicitó piscina temperada - Apagar piscina')
                    requests.get(p.off_temperature_pool_url) # FIXME: aqui hay que evaluar si ejecutamos off, o tambien manejamos un campo para saber cuando esta apagada o encendida la temperatura
            else:
                """En caso que no existan reservas para el dia siguiente, lo que evaluo es una hora estimada de check out, 
                suele ser 10 AM pero pongo un horario estimativo a las 12 del mediodia,
                donde eso esta sujeto a evaluacion, para asi apagar la temperatura"""
                print('Apagando por defecto')
                hour_check_out = time(11, 0)
                hour_now = datetime.now().time()
                if hour_now >= hour_check_out:
                    requests.get(p.off_temperature_pool_url)

    print('Finalizando controlador de automatizacion de piscina temperada')

if __name__ == "__main__":
    pool_temperature()