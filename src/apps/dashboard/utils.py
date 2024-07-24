from datetime import datetime, timedelta
from apps.property.models import Property, ProfitPropertyAirBnb
from apps.reservation.models import Reservation
from django.db.models import Sum, Q
from apps.core.functions import noches_restantes_mes

def convertir_a_fecha(fecha):
    """
    Convierte un objeto datetime o date a un objeto date.
    """
    return fecha.date() if isinstance(fecha, datetime) else fecha

def contar_noches_reservadas_del_mes(inicio, fin, first_day, last_day):
    """
    Cuenta las noches de una reserva dentro del mes en curso.
    """
    inicio = convertir_a_fecha(inicio)
    fin = convertir_a_fecha(fin)
    first_day = convertir_a_fecha(first_day)
    last_day = convertir_a_fecha(last_day)

    if inicio < first_day:
        inicio = first_day
    if fin > last_day:
        fin = last_day + timedelta(days=1)
    return (fin - inicio).days

def contar_noches_entre_fechas(inicio, fin, fecha_actual, last_day):
    """
    Cuenta las noches de una reserva desde la fecha actual hasta el fin de la reserva o fin de mes.
    """
    inicio = convertir_a_fecha(inicio)
    fin = convertir_a_fecha(fin)
    fecha_actual = convertir_a_fecha(fecha_actual)
    last_day = convertir_a_fecha(last_day)

    if inicio < fecha_actual:
        inicio = fecha_actual
    if fin > last_day:
        fin = last_day + timedelta(days=1)
    return (fin - inicio).days

def get_stadistics_period(fecha_actual, last_day):
    today = datetime.now().date()
    fecha_actual = convertir_a_fecha(fecha_actual)
    es_mes_actual = (fecha_actual.month == today.month and fecha_actual.year == today.year)

    first_day = datetime(fecha_actual.year, fecha_actual.month, 1).date()
    last_day = datetime(fecha_actual.year, fecha_actual.month, last_day).date()
    fecha_inicio_calculo = today if es_mes_actual else first_day

    days_without_reservations_per_property = []
    days_without_reservations_total = 0
    total_por_cobrar = 0
    total_facturado = 0
    total_noches_man = 0

    total_days_for_all_properties = 0
    for p in Property.objects.exclude(deleted=True):
        # Query para contar las noches libres de acá en adelante
        reservations_from_current_day = Reservation.objects.exclude(
            deleted=True
        ).filter(
            property=p
        ).filter(
            Q(check_in_date__gte=fecha_inicio_calculo, check_in_date__lt=last_day + timedelta(days=1)) |
            Q(check_out_date__gte=fecha_inicio_calculo, check_out_date__lt=last_day + timedelta(days=1))
        )

        if es_mes_actual:
            reservations_from_current_day = reservations_from_current_day.exclude(check_out_date__lt=today)

        # Query para contar las reservas en todo el mes
        query_reservation_check_in_month = Reservation.objects.exclude(
            deleted=True
        ).filter(
            property=p,
            check_in_date__range=(first_day, last_day)
        )

        # Query para contar las noches de "man"
        query_reservation_check_in_month_man = query_reservation_check_in_month.filter(origin='man')

        noches_reservadas = 0
        for r in query_reservation_check_in_month.exclude(origin='man').exclude(deleted=True).order_by('check_in_date'):
            noches_reservadas += contar_noches_reservadas_del_mes(r.check_in_date, r.check_out_date, first_day, last_day)

        noches_reservadas_hoy_a_fin_mes = 0
        for r in reservations_from_current_day.exclude(deleted=True).order_by('check_in_date'):
            noches_reservadas_hoy_a_fin_mes += contar_noches_entre_fechas(r.check_in_date, r.check_out_date, fecha_inicio_calculo, last_day)

        noches_man = 0
        for r in query_reservation_check_in_month_man.exclude(deleted=True).order_by('check_in_date'):
            noches_man += contar_noches_reservadas_del_mes(r.check_in_date, r.check_out_date, first_day, last_day)

        # Calcula las noches restantes incluyendo la noche del día de hoy
        noches_restantes_mes_days = noches_restantes_mes(fecha_inicio_calculo, last_day)
        dias_libres_hoy_fin_mes = noches_restantes_mes_days - noches_reservadas_hoy_a_fin_mes

        pagos_recibidos_propiedad_mes = 0
        for r in query_reservation_check_in_month:
            pagos_recibidos_propiedad_mes += r.adelanto_normalizado

        valor_propiedad_mes = query_reservation_check_in_month.aggregate(pagos=Sum('price_sol'))

        if valor_propiedad_mes['pagos']:
            valor_propiedad_mes = float(valor_propiedad_mes['pagos'])
        else:
            valor_propiedad_mes = 0

        query_profit_airbnb_property = ProfitPropertyAirBnb.objects.filter(
            property=p,
            month=fecha_actual.month,
            year=fecha_actual.year
        )

        profit_propiedad_mes_airbnb = float(query_profit_airbnb_property.first().profit_sol) if query_profit_airbnb_property else 0

        days_without_reservations_per_property.append({
            'casa': p.name,
            'property__background_color': p.background_color,
            'dias_libres': dias_libres_hoy_fin_mes,
            'dias_ocupada': noches_reservadas,
            'noches_man': noches_man,
            'dinero_por_cobrar': round(valor_propiedad_mes - pagos_recibidos_propiedad_mes, 2),
            'dinero_facturado': round(valor_propiedad_mes + profit_propiedad_mes_airbnb),
        })

        days_without_reservations_total += dias_libres_hoy_fin_mes
        total_days_for_all_properties += noches_reservadas
        total_noches_man += noches_man
        total_por_cobrar += valor_propiedad_mes - pagos_recibidos_propiedad_mes
        total_facturado += valor_propiedad_mes + profit_propiedad_mes_airbnb

    return days_without_reservations_per_property, days_without_reservations_total, total_days_for_all_properties, total_noches_man, '%.2f' % total_por_cobrar, '%.2f' % total_facturado
