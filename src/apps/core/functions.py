import os
import requests
from django.conf import settings
from datetime import datetime
from rest_framework import serializers


URL_BASE = settings.AIRBNB_API_URL_BASE+"="

def recipt_directory_path(instance, filename):
    upload_to = os.path.join('rental_recipt', str(instance.reservation.id), filename)
    return upload_to

def user_directory_path(instance, filename):
    upload_to = os.path.join('user_profile_photo', str(instance.id), filename)
    return upload_to

def update_air_bnb_api(property):
    from apps.reservation import serializers as reservation_serializer

    reservations_uid = reservation_serializer.Reservation.objects.all().values_list("uuid_external", flat=True)

    print('Request a:', f"{URL_BASE}{property.airbnb_url} ({property.name})")
    response = requests.get(URL_BASE + property.airbnb_url)

    if response.status_code == 200:
        reservations = response.json()
        for r in reservations:
            date_start = datetime.strptime(r["start_date"], "%Y%m%d").date()
            date_end = datetime.strptime(r["end_date"], "%Y%m%d").date()
            if r["uid"] in reservations_uid:
                try:
                    reservations_obj = reservation_serializer.Reservation.objects.get(
                        uuid_external=r["uid"]
                    )
                except reservation_serializer.Reservation.DoesNotExist:
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
                    "property": property.id,
                    "origin": "air",
                    "price_usd": 0,
                    "price_sol": 0,
                    "advance_payment": 0,
                }
                serializer = reservation_serializer.ReservationSerializer(data=data, context={"script": True})
                if serializer.is_valid():
                    serializer.save()
                else:
                    print(serializer.errors)