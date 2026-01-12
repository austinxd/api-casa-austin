import os
import requests
from django.conf import settings
from datetime import datetime, timedelta
from rest_framework import serializers

from icalendar import Calendar, Event
from pathlib import Path

from slugify import slugify

from django.contrib.admin.models import LogEntry, CHANGE, ADDITION, DELETION
from django.contrib.contenttypes.models import ContentType
from django.contrib.admin.models import LogEntry


URL_BASE = settings.AIRBNB_API_URL_BASE+"="


def get_month_name(month_number):
    if month_number == 1:
        return 'enero'
    elif month_number == 2:
        return 'febrero'
    elif month_number == 3:
        return 'marzo'
    elif month_number == 4:
        return 'abril'
    elif month_number == 5:
        return 'mayo'
    elif month_number == 6:
        return 'junio'
    elif month_number == 7:
        return 'julio'
    elif month_number == 8:
        return 'agosto'
    elif month_number == 9:
        return 'septiembre'
    elif month_number == 10:
        return 'octubre'
    elif month_number == 11:
        return 'noviembre'
    
    return 'diciembre'

def normalizar_fecha(date_unformated):
    """ Funcion que normaliza fechas formato LATAM a formato BD
        Params:
            - date_unformated: DD/MM/YYYY
        Return:
            - formated_date: yyyy-mm-dd
    """
    date_obj = datetime.strptime(date_unformated, "%d/%m/%Y")
    return date_obj.strftime("%Y-%m-%d")

def noches_restantes_mes(fecha_actual, fecha_fin_mes):
    """ Retornar las noches que quedan en el mesa dada una fecha
    """

    diferencia = (fecha_fin_mes + timedelta(days=1)) - fecha_actual
    noches = diferencia.days

    return noches

def contar_noches_reserva(fecha_inicio, fecha_fin, limit, count_all_month=True):
    """ Dado dos objetos Datefield retornar la diferencia entre dias entre ambos valores
        Params:
            - Fecha inicio a evaluar (Check in)
            - Fecha fin a evaluar (Check out)
            - Fecha limite a evaluar (último día del mes)
        
        Return:
            - Noches entre reservas
    """

    dia_actual = datetime.now().date()

    eval_fecha_fin = fecha_fin if fecha_fin < limit else limit + timedelta(days=1)  # En caso que salga por el else me intersa saber el dia siguiente porque es la noche del ultimo dia del mes
    
    eval_fecha_inicio = fecha_inicio
    # True cuenta todos los dias del mes
    if count_all_month:
        eval_fecha_inicio = dia_actual if dia_actual > fecha_inicio else fecha_inicio

    diferencia = eval_fecha_fin - eval_fecha_inicio
    noches = diferencia.days

    return noches


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
    import logging
    logger = logging.getLogger(__name__)
    logger.info(f"🔄 update_air_bnb_api iniciado para propiedad: {property.name}")

    from apps.reservation import serializers as reservation_serializer

    reservations_uid = reservation_serializer.Reservation.objects.exclude(origin='aus').values_list("uuid_external", flat=True)

    # print('Request to AirBnb: ', URL_BASE + property.airbnb_url)
    response = requests.get(URL_BASE + property.airbnb_url)

    if response.status_code == 200:
        reservations = response.json()
        # print('Reservations from AirBnB', reservations)
        for r in reservations:
            # print('Sync AirBnB Reservation, Property:', property.name)
            date_start = datetime.strptime(r["start_date"], "%Y%m%d").date()
            date_end = datetime.strptime(r["end_date"], "%Y%m%d").date()
            if r["uid"] in reservations_uid:
                # Reserva ya existe - NO modificar para respetar cambios manuales
                # (extensiones de fecha, late_checkout, etc.)
                logger.info(f"⏭️ Reserva con uid {r['uid']} ya existe - saltando para respetar cambios manuales")
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
                    "seller": reservation_serializer.CustomUser.objects.get(first_name='AirBnB').id,
                    "client": reservation_serializer.Clients.objects.get(first_name='AirBnB').id
                }
                serializer = reservation_serializer.ReservationSerializer(data=data, context={"script": True})
                if serializer.is_valid():
                    serializer.save()
                else:
                    # print(serializer.errors)
                    pass

def confeccion_ics():
    from apps.reservation.models import Reservation
    from apps.property.models import Property

    query_reservations = Reservation.objects.exclude(deleted=True)
 
    # print('Comenzando proceso para confeccionar ICS')
    

    for prop in Property.objects.exclude(deleted=True):
        # print('Procesando propiedad ', prop.name)
        cal = Calendar()
        cal.add('VERSION', str(2.0))
        cal.add('PRODID', "-//hacksw/handcal//NONSGML v1.0//EN")
        
        for res in query_reservations.filter(property=prop, check_out_date__gte=datetime.now()):
            # print('Procesando reserva ', res)
            # Creating icalendar/event
            event = Event()

            # Calcular effective_checkout_date defensivamente para late_checkout
            effective_checkout = res.check_out_date
            if res.late_checkout and res.late_check_out_date:
                if res.check_out_date == res.late_check_out_date:
                    # Datos inconsistentes: calcular la fecha correcta
                    effective_checkout = res.late_check_out_date + timedelta(days=1)

            event.add('uid', str(res.id))
            event.add('description', f"Reserva de Casa Austin - {res.id} ({res.origin})")
            event.add('dtstart',  datetime.combine(res.check_in_date, datetime.min.time()))
            event.add('dtend', datetime.combine(effective_checkout, datetime.min.time()))
            event.add('dtstamp', res.created)

            # Adding events to calendar
            cal.add_component(event)

        directory = str(Path(__file__).parent.parent.parent) + "/media/"
        casa_sluged = slugify(prop.name)

        f = open(os.path.join(directory, f'{casa_sluged}.ics'), 'wb')
        f.write(cal.to_ical())
        f.close()

    # print('Finalizando proceso para confeccionar ICS')

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
