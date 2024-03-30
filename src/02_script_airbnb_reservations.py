import os
import django
import requests
from datetime import datetime
from rest_framework import serializers

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "config.settings")
django.setup()

from apps.accounts.models import CustomUser
from apps.clients.models import Clients
from apps.property.models import Property
from apps.reservation.models import Reservation
from apps.reservation.serializers import ReservationSerializer


url_base = "https://casaaustin.pe/api/prueba.php?ics_url="  # FIXME: poner en una variable de entorno la url

query_property = Property.objects.exclude(airbnb_url__isnull=True)
reservations_uid = Reservation.objects.all().values_list("uuid_external", flat=True)

usuario = CustomUser.objects.all().first()
cliente = Clients.objects.all().first()

for q in query_property:
    if q.airbnb_url:
        # url_airbnb = 'https://www.airbnb.com.pe/calendar/ical/729211122400817242.ics?s=51ec95949e9fc3a37f27fa7ba8aeb7ab'
        response = requests.get(url_base + q.airbnb_url)
        # response = requests.get(url_base+url_airbnb)
        if response.status_code == 200:
            reservations = response.json()
            for r in reservations:
                date_start = datetime.strptime(r["start_date"], "%Y%m%d").date()
                date_end = datetime.strptime(r["end_date"], "%Y%m%d").date()
                if r["uid"] in reservations_uid:
                    try:
                        reservations_obj = Reservation.objects.get(
                            uuid_external=r["uid"]
                        )
                    except Reservation.DoesNotExist:
                        raise serializers.ValidationError(
                            {"detail": "Reservation not found"},
                            code="Error_reservation",
                        )

                    if reservations_obj.check_in_date != date_start:
                        reservations_obj.check_in_date = date_start

                    if reservations_obj.check_out_date != date_end:
                        reservations_obj.check_out_date = date_end
                    reservations_obj.save()
                else:
                    data = {
                        "uuid_external": r["uid"],
                        "check_in_date": date_start,
                        "check_out_date": date_end,
                        "property": q.id,
                        "origin": "air",
                        "code": r["description"],
                        "price_usd": 0,
                        "price_sol": 15500,
                        "advance_payment": 1500,
                        "client": cliente.id,
                        "seller": usuario.id,
                    }
                    serializer = ReservationSerializer(data=data)
                    if serializer.is_valid():
                        serializer.save()
                    else:
                        print(serializer.errors)
