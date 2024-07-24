from datetime import datetime, timedelta
from apps.property.models import Property, ProfitPropertyAirBnb
from apps.reservation.models import Reservation
from django.db.models import Sum, Q

def get_stadistics_period(fecha_actual, last_day):
    first_day = datetime(fecha_actual.year, fecha_actual.month, 1).date()
    last_day = datetime(fecha_actual.year, fecha_actual.month, last_day).date()
    fecha_actual = fecha_actual.date()

    days_without_reservations_per_property = []
    total_free_days = 0
    total_ocuppied_days = 0
    total_por_cobrar = 0
    total_facturado = 0

    for p in Property.objects.exclude(deleted=True):
        # Obtener todas las reservas para la propiedad en el mes actual
        reservations_in_month = Reservation.objects.exclude(
            deleted=True
        ).filter(
            property=p,
            check_in_date__lt=last_day + timedelta(days=1),
            check_out_date__gte=first_day
        )

        # Calcular noches ocupadas para la propiedad
        noches_ocupadas = sum((min(r.check_out_date, last_day) - max(r.check_in_date, first_day)).days for r in reservations_in_month)

        # Calcular noches libres para la propiedad
        total_days_in_month = (last_day - first_day).days + 1
        noches_libres = total_days_in_month - noches_ocupadas

        # Calcular el dinero por cobrar y facturado
        pagos_recibidos_propiedad_mes = reservations_in_month.aggregate(pagos=Sum('adelanto_normalizado'))['pagos'] or 0
        valor_propiedad_mes = reservations_in_month.aggregate(pagos=Sum('price_sol'))['pagos'] or 0
        query_profit_airbnb_property = ProfitPropertyAirBnb.objects.filter(
            property=p,
            month=fecha_actual.month,
            year=fecha_actual.year
        )
        profit_propiedad_mes_airbnb = float(query_profit_airbnb_property.first().profit_sol) if query_profit_airbnb_property else 0

        days_without_reservations_per_property.append({
            'casa': p.name,
            'property__background_color': p.background_color,
            'dias_libres': noches_libres,
            'dias_ocupada': noches_ocupadas,
            'dinero_por_cobrar': round(valor_propiedad_mes - pagos_recibidos_propiedad_mes, 2),
            'dinero_facturado': round(valor_propiedad_mes + profit_propiedad_mes_airbnb),
        })

        total_free_days += noches_libres
        total_ocuppied_days += noches_ocupadas
        total_por_cobrar += valor_propiedad_mes - pagos_recibidos_propiedad_mes
        total_facturado += valor_propiedad_mes + profit_propiedad_mes_airbnb

    return days_without_reservations_per_property, total_free_days, total_ocuppied_days, '%.2f' % total_por_cobrar, '%.2f' % total_facturado
