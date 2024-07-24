from datetime import datetime
from apps.property.models import Property, ProfitPropertyAirBnb
from apps.reservation.models import Reservation
from django.db.models import Sum, Q
from apps.core.functions import contar_noches_reserva, noches_restantes_mes

def get_stadistics_period(fecha_actual, last_day):

    first_day = datetime(fecha_actual.year, fecha_actual.month, 1)
    last_day = datetime(fecha_actual.year, fecha_actual.month, last_day)

    days_without_reservations_per_property = []
    days_without_reservations_total = 0
    total_por_cobrar = 0
    total_facturado = 0

    total_days_for_all_properties = 0
    for p in Property.objects.exclude(deleted=True):
        # Query para contar las noches libres de acá en adelante
        reservations_from_current_day = Reservation.objects.exclude(
            deleted=True
        ).filter(
            property=p,
            check_in_date__gte=fecha_actual,
            check_out_date__lte=last_day
        ).exclude(check_out_date__lt=fecha_actual)
        
        # Query para contar las ganancias en todo el mes
        query_reservation_check_in_month = Reservation.objects.exclude(
            deleted=True
        ).filter(
            property=p,
            check_in_date__range=(first_day, last_day)
        )

        # Contar noches reservadas desde hoy hasta fin de mes
        noches_reservadas_hoy_a_fin_mes = sum(
            contar_noches_reserva(r.check_in_date, r.check_out_date, last_day.date())
            for r in reservations_from_current_day
        )
        
        # Calcular noches restantes en el mes
        noches_restantes_mes_days = noches_restantes_mes(fecha_actual.date(), last_day.date())
        dias_libres_hoy_fin_mes = noches_restantes_mes_days - noches_reservadas_hoy_a_fin_mes

        # Continuar con los cálculos de dinero
        pagos_recibidos_propiedad_mes = query_reservation_check_in_month.aggregate(
            pagos=Sum('advance_payment')
        )['pagos'] or 0

        valor_propiedad_mes = query_reservation_check_in_month.aggregate(
            pagos=Sum('price_sol')
        )['pagos'] or 0

        query_profit_airbnb_property = ProfitPropertyAirBnb.objects.filter(
            property=p, month=fecha_actual.month, year=fecha_actual.year
        )

        profit_propiedad_mes_airbnb = query_profit_airbnb_property.aggregate(
            profit=Sum('profit_sol')
        )['profit'] or 0

        dinero_facturado = valor_propiedad_mes + profit_propiedad_mes_airbnb
        dinero_por_cobrar = valor_propiedad_mes - pagos_recibidos_propiedad_mes

        days_without_reservations_per_property.append({
            'casa': p.name,
            'property__background_color': p.background_color,
            'dias_libres': dias_libres_hoy_fin_mes,
            'dias_ocupada': noches_reservadas_hoy_a_fin_mes,
            'dinero_por_cobrar': round(dinero_por_cobrar, 2),
            'dinero_facturado': round(dinero_facturado, 2),
        })

        days_without_reservations_total += dias_libres_hoy_fin_mes
        total_days_for_all_properties += noches_reservadas_hoy_a_fin_mes
        total_por_cobrar += dinero_por_cobrar
        total_facturado += dinero_facturado

    return days_without_reservations_per_property, days_without_reservations_total, total_days_for_all_properties, '%.2f' % total_por_cobrar, '%.2f' % total_facturado
