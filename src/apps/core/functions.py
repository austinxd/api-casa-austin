import os
import requests
from django.conf import settings
from datetime import datetime
from rest_framework import serializers

from icalendar import Calendar, Event
from pathlib import Path

from slugify import slugify

from django.contrib.admin.models import LogEntry, CHANGE, ADDITION, DELETION
from django.contrib.contenttypes.models import ContentType
from django.contrib.admin.models import LogEntry


URL_BASE = settings.AIRBNB_API_URL_BASE+"="


def check_user_has_rol(rol_str, user):
    """ Retorna True si el usuario tiene entre sus grupos 'rol_str'
    """
    return rol_str in user.groups.all().values_list('name', flat=True)


def recipt_directory_path(instance, filename):
    upload_to = os.path.join('rental_recipt', str(instance.reservation.id), filename)
    return upload_to

def user_directory_path(instance, filename):
    upload_to = os.path.join('user_profile_photo', str(instance.id), filename)
    return upload_to

def update_air_bnb_api(property):
    from apps.reservation import serializers as reservation_serializer

    reservations_uid = reservation_serializer.Reservation.objects.exclude(origin='aus').values_list("uuid_external", flat=True)

    print('Request to AirBnb: ', URL_BASE + property.airbnb_url)
    response = requests.get(URL_BASE + property.airbnb_url)

    if response.status_code == 200:
        reservations = response.json()
        print('Reservations from AirBnB', reservations)
        for r in reservations:
            print('Sync AirBnB Reservation, Property:', property.name)
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
                    'seller': reservation_serializer.CustomUser.objects.get(first_name='AirBnB').id
                }
                serializer = reservation_serializer.ReservationSerializer(data=data, context={"script": True})
                if serializer.is_valid():
                    serializer.save()
                else:
                    print(serializer.errors)

def confeccion_ics():
    from apps.reservation.models import Reservation
    from apps.property.models import Property

    query_reservations = Reservation.objects.exclude(deleted=True).filter(origin='aus')

    print('Comenzando proceso para confeccionar ICS')
    

    for prop in Property.objects.exclude(deleted=True):
        cal = Calendar()
        cal.add('VERSION', str(2.0))
        cal.add('PRODID', "-//hacksw/handcal//NONSGML v1.0//EN")

        for res in query_reservations.filter(property=prop, check_in_date__gte=datetime.now()):
            # Creating icalendar/event
            event = Event()
            
            event.add('uid', str(res.id))
            event.add('description', f"Reserva de Casa Austin - {res.id}")
            event.add('dtstart',  datetime.combine(res.check_in_date, datetime.min.time()))
            event.add('dtend', datetime.combine(res.check_out_date, datetime.min.time()))
            event.add('dtstamp', res.created)

            # Adding events to calendar
            cal.add_component(event)

        directory = str(Path(__file__).parent.parent.parent) + "/media/"
        casa_sluged = slugify(prop.name)

        f = open(os.path.join(directory, f'{casa_sluged}.ics'), 'wb')
        f.write(cal.to_ical())
        f.close()

    print('Finalizando proceso para confeccionar ICS')

def generate_audit(model_instance, user, flag_req, text_str):
    """ Generar un registro de auditoria LogEntry en las views
    Params:
        - model_instance: Instancia del modelo que se esta creando
        - user: Usuario que lanza la request
        - flag: Un string que indica la acción a registrar create, update, delete (ADDITION, CHANGE, DELETION)
        - text_str: Un string mensaje que da información al estilo Descripción de la acción realizada
    """
    
    flag = ADDITION

    if flag_req == 'create':
        flag = ADDITION
    elif flag_req == 'update':
        flag = CHANGE
    elif flag_req == 'delete':
        flag = DELETION

    content_type = ContentType.objects.get_for_model(model_instance)
    LogEntry.objects.log_action(
        user_id=user.pk,
        content_type_id=content_type.pk,
        object_id=model_instance.pk,
        object_repr=str(model_instance),
        action_flag=flag,
        change_message=text_str,
    )
