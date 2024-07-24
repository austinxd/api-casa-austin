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
        noches_ocupadas = sum(
            (min(r.check_out_date, last_day) - max(r.check_in_date, first_day)).days
            for r in reservations_in_month
        )

        # Calcular noches libres para la propiedad
        if fecha_actual.month == first_day.month and fecha_actual.year == first_day.year:
            # Si estamos en el mes actual, considerar solo los días restantes del mes
            noches_restantes_mes_days = (last_day - fecha_actual).days + 1
            reservas_restantes_mes = reservations_in_month.filter(
                Q(check_in_date__gte=fecha_actual) | Q(check_out_date__gt=fecha_actual)
            )
            noches_ocupadas_restantes_mes = sum(
                (min(r.check_out_date, last_day) - max(r.check_in_date, fecha_actual)).days
                for r in reservas_restantes_mes
            )
            noches_libres = noches_restantes_mes_days - noches_ocupadas_restantes_mes
        else:
            # Si no estamos en el mes actual, considerar todos los días del mes
            total_days_in_month = (last_day - first_day).days + 1
            noches_libres = total_days_in_month - noches_ocupadas

        # Calcular el valor total de las reservas y los pagos recibidos para la propiedad en el mes actual
        valor_propiedad_mes = reservations_in_month.aggregate(pagos=Sum('price_sol'))['pagos'] or 0
        pagos_recibidos_propiedad_mes = reservations_in_month.aggregate(pagos=Sum('adelanto_normalizado'))['pagos'] or 0

        # Calcular el total facturado incluyendo el profit de Airbnb si existe
        query_profit_airbnb_property = ProfitPropertyAirBnb.objects.filter(
            property=p,
            month=fecha_actual.month,
            year=fecha_actual.year
        )
        profit_propiedad_mes_airbnb = float(query_profit_airbnb_property.first().profit_sol) if query_profit_airbnb_property else 0

        dinero_facturado = valor_propiedad_mes + profit_propiedad_mes_airbnb
        dinero_por_cobrar = dinero_facturado - pagos_recibidos_propiedad_mes

        days_without_reservations_per_property.append({
            'casa': p.name,
            'property__background_color': p.background_color,
            'dias_libres': noches_libres,
            'dias_ocupada': noches_ocupadas,
            'dinero_por_cobrar': round(dinero_por_cobrar, 2),
            'dinero_facturado': round(dinero_facturado, 2),
        })

        total_free_days += noches_libres
        total_ocuppied_days += noches_ocupadas
        total_por_cobrar += dinero_por_cobrar
        total_facturado += dinero_facturado

    return days_without_reservations_per_property, total_free_days, total_ocuppied_days, '%.2f' % total_por_cobrar, '%.2f' % total_facturado
