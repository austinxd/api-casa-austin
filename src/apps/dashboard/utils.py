from datetime import datetime, timedelta
from apps.property.models import Property, ProfitPropertyAirBnb
from apps.reservation.models import Reservation
from django.db.models import Sum, Q
from apps.core.functions import noches_restantes_mes

def contar_noches_reservadas_del_mes(inicio, fin, first_day, last_day):
    inicio = inicio.date() if isinstance(inicio, datetime) else inicio
    fin = fin.date() if isinstance(fin, datetime) else fin
    first_day = first_day.date() if isinstance(first_day, datetime) else first_day
    last_day = last_day.date() if isinstance(last_day, datetime) else last_day

    if inicio < first_day:
        inicio = first_day
    if fin > last_day:
        fin = last_day + timedelta(days=1)
    return (fin - inicio).days

def contar_noches_entre_fechas(inicio, fin, fecha_actual, last_day):
    inicio = inicio.date() if isinstance(inicio, datetime) else inicio
    fin = fin.date() if isinstance(fin, datetime) else fin
    fecha_actual = fecha_actual.date() if isinstance(fecha_actual, datetime) else fecha_actual
    last_day = last_day.date() if isinstance(last_day, datetime) else last_day

    if inicio < fecha_actual:
        inicio = fecha_actual
    if fin > last_day:
        fin = last_day + timedelta(days=1)
    return (fin - inicio).days

def get_stadistics_period(fecha_actual, last_day):
    first_day = datetime(fecha_actual.year, fecha_actual.month, 1).date()
    last_day = datetime(fecha_actual.year, fecha_actual.month, last_day).date()

    days_without_reservations_per_property = []
    days_without_reservations_total = 0
    total_por_cobrar = 0
    total_facturado = 0

    total_days_for_all_properties = 0
    for p in Property.objects.exclude(deleted=True):
        if fecha_actual.month == datetime.now().month and fecha_actual.year == datetime.now().year:
            # Si el mes actual es el mismo que el mes de hoy, usar fecha_actual en lugar de first_day
            inicio_periodo = fecha_actual.date()
        else:
            inicio_periodo = first_day

        reservations_from_current_day = Reservation.objects.exclude(
            deleted=True
        ).filter(
            property=p
        ).filter(
            Q(check_in_date__gte=inicio_periodo, check_in_date__lt=last_day + timedelta(days=1)) |
            Q(check_out_date__gte=inicio_periodo, check_out_date__lt=last_day + timedelta(days=1))
        ).exclude(check_out_date__lt=fecha_actual)

        query_reservation_check_in_month = Reservation.objects.exclude(
            deleted=True
        ).filter(
            property=p,
            check_in_date__range=(first_day, last_day)
        )

        noches_reservadas = 0
        for r in query_reservation_check_in_month.exclude(origin='man').exclude(deleted=True).order_by('check_in_date'):
            noches_reservadas += contar_noches_reservadas_del_mes(r.check_in_date, r.check_out_date, first_day, last_day)

        noches_reservadas_hoy_a_fin_mes = 0
        noches_restantes_mes_days = 0
        dias_libres_hoy_fin_mes = 0
        if fecha_actual.month == datetime.now().month and fecha_actual.year == datetime.now().year:
            for r in reservations_from_current_day.exclude(deleted=True).order_by('check_in_date'):
                noches_reservadas_hoy_a_fin_mes += contar_noches_entre_fechas(r.check_in_date, r.check_out_date, fecha_actual, last_day)

            noches_restantes_mes_days = noches_restantes_mes(fecha_actual.date(), last_day)
            dias_libres_hoy_fin_mes = noches_restantes_mes_days - noches_reservadas_hoy_a_fin_mes
        else:
            noches_restantes_mes_days = noches_restantes_mes(first_day, last_day)
            dias_libres_hoy_fin_mes = noches_restantes_mes_days - noches_reservadas

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
            'dinero_por_cobrar': round(valor_propiedad_mes - pagos_recibidos_propiedad_mes, 2),
            'dinero_facturado': round(valor_propiedad_mes + profit_propiedad_mes_airbnb),
        })

        days_without_reservations_total += dias_libres_hoy_fin_mes
        total_days_for_all_properties += noches_reservadas
        total_por_cobrar += valor_propiedad_mes - pagos_recibidos_propiedad_mes
        total_facturado += valor_propiedad_mes + profit_propiedad_mes_airbnb

    return days_without_reservations_per_property, days_without_reservations_total, total_days_for_all_properties, '%.2f' % total_por_cobrar, '%.2f' % total_facturado
