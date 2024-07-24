from datetime import datetime, timedelta
from apps.property.models import Property, ProfitPropertyAirBnb
from apps.reservation.models import Reservation

from django.db.models import Sum, Q

from apps.core.functions import contar_noches_reserva, noches_restantes_mes

def get_stadistics_period(fecha_actual, last_day):

    first_day = datetime(fecha_actual.year, fecha_actual.month, 1).date()
    last_day = datetime(fecha_actual.year, fecha_actual.month, last_day).date()
    fecha_actual = fecha_actual.date()

    days_without_reservations_per_property = []
    days_without_reservations_total = 0
    total_por_cobrar = 0
    total_facturado = 0

    total_days_for_all_properties = 0
    for p in Property.objects.exclude(deleted=True):
        # Query para contar las noches libres desde hoy en adelante
        reservations_from_current_day = Reservation.objects.exclude(
            deleted=True
        ).filter(
            property=p
        ).filter(
            Q(check_in_date__lt=last_day, check_out_date__gt=first_day)  # Filtrar reservas que intersectan el mes
        ).exclude(check_out_date__lt=fecha_actual)

        noches_reservadas_hoy_a_fin_mes = 0
        for r in reservations_from_current_day.exclude(deleted=True).order_by('check_in_date'):
            noches_reservadas_hoy_a_fin_mes += contar_noches_reserva(
                max(r.check_in_date.date(), fecha_actual), 
                min(r.check_out_date.date(), last_day), 
                last_day
            )
        
        noches_restantes_mes_days = noches_restantes_mes(fecha_actual, last_day)
        dias_libres_hoy_fin_mes = noches_restantes_mes_days - noches_reservadas_hoy_a_fin_mes

        pagos_recibidos_propiedad_mes = 0

        for r in reservations_from_current_day:
            pagos_recibidos_propiedad_mes += r.adelanto_normalizado

        valor_propiedad_mes = reservations_from_current_day.aggregate(pagos=Sum('price_sol'))

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
            'dias_ocupada': noches_reservadas_hoy_a_fin_mes,
            'dinero_por_cobrar': round(valor_propiedad_mes - pagos_recibidos_propiedad_mes, 2),
            'dinero_facturado': round(valor_propiedad_mes + profit_propiedad_mes_airbnb),
        })

        days_without_reservations_total += dias_libres_hoy_fin_mes
        total_days_for_all_properties += noches_reservadas_hoy_a_fin_mes

        total_por_cobrar += valor_propiedad_mes - pagos_recibidos_propiedad_mes
        total_facturado += valor_propiedad_mes + profit_propiedad_mes_airbnb

    return days_without_reservations_per_property, days_without_reservations_total, total_days_for_all_properties, '%.2f' % total_por_cobrar, '%.2f' % total_facturado
