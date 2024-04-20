from django.utils import timezone

import calendar
from datetime import datetime, timedelta

from rest_framework.views import APIView
from rest_framework.response import Response

from apps.accounts.models import CustomUser
from apps.property.models import Property
from apps.reservation.models import Reservation

from .serializers import DashboardSerializer
from django.db.models import Count, F, ExpressionWrapper, DecimalField, Value, CharField, Sum, Q

from django.db.models.functions import Concat


def get_days_without_reservations(fecha_actual, last_day):

    first_day = datetime(fecha_actual.year, fecha_actual.month, 1)
    last_day = datetime(fecha_actual.year, fecha_actual.month, last_day)

    days_without_reservations_per_property = []
    days_without_reservations_total = 0
    total_por_cobrar = 0
    total_facturado = 0

    total_days_for_all_properties = 0
    for p in Property.objects.exclude(deleted=True):
        reservations = Reservation.objects.filter(
            property=p
                ).filter(
                    Q(check_in_date__gte=first_day, check_in_date__lt=last_day) |
                    Q(check_out_date__gte=first_day, check_out_date__lt=last_day)
                )


        adelantos_propiedad_mes = reservations.aggregate(adelantos=Sum('advance_payment'))
        dinero_cobrado_propiedad_mes = reservations.aggregate(pagos=Sum('price_sol'))

        if adelantos_propiedad_mes['adelantos']:
            adelantos_propiedad_mes = float(adelantos_propiedad_mes['adelantos'])
        else:
            adelantos_propiedad_mes = 0

        if dinero_cobrado_propiedad_mes['pagos']:
            dinero_cobrado_propiedad_mes = float(dinero_cobrado_propiedad_mes['pagos'])
        else:
            dinero_cobrado_propiedad_mes = 0

        # Genera una lista de todos los días desde la fecha actual a fin del mes
        all_days = [fecha_actual + timedelta(days=i) for i in range((last_day - fecha_actual).days + 1)]

        # Encuentra los días sin reservaciones
        days_without_reservations = [day.date() for day in all_days if not any((reservation.check_in_date <= day.date() <= reservation.check_out_date) for reservation in reservations)]

        days_without_reservations_per_property.append({
            'casa':p.name,
            'property__background_color':p.background_color,
            'dias_libres': len(days_without_reservations),
            'dias_ocupada': len(all_days) - len(days_without_reservations),
            'dinero_por_cobrar': adelantos_propiedad_mes,
            'dinero_facturado': dinero_cobrado_propiedad_mes,
        })

        days_without_reservations_total += len(days_without_reservations)

        total_days_for_all_properties += len(all_days)

        total_por_cobrar += dinero_cobrado_propiedad_mes - adelantos_propiedad_mes
        total_facturado += dinero_cobrado_propiedad_mes

    total_days_for_all_properties -= days_without_reservations_total

    return days_without_reservations_per_property, days_without_reservations_total, total_days_for_all_properties, '%.2f' % total_por_cobrar, '%.2f' % total_facturado


class DashboardApiView(APIView):
    serializer_class = DashboardSerializer
    
    def get(self, request):
        content = {}
        
        media_url = request.scheme + '://' + request.get_host() + "/media/"

        # Best Sellers Card
        fecha_actual = datetime.now()

        last_day_month = calendar.monthrange(fecha_actual.year, fecha_actual.month)[1]

        range_evaluate = (datetime(fecha_actual.year, fecha_actual.month, 1), datetime(fecha_actual.year, fecha_actual.month, last_day_month))
        query_reservation_current_month = Reservation.objects.filter(check_in_date__range=range_evaluate)
        
        best_sellers = []
        for v in CustomUser.objects.filter(groups__name='vendedor'):
            total_ventas_mes_vendedor = query_reservation_current_month.filter(seller=v).aggregate(total_ventas=Sum('price_sol'))

            if total_ventas_mes_vendedor['total_ventas'] is None:
                total_ventas_mes_vendedor = 0
            else:
                total_ventas_mes_vendedor = '%.2f' % float(total_ventas_mes_vendedor['total_ventas'])

            best_sellers.append({
                'id': v.id,
                'nombre': v.first_name,
                'apellido': v.last_name,
                'ventas_soles': total_ventas_mes_vendedor,
                'foto_perfil': media_url+str(v.profile_photo)
            })

        content['best_sellers'] = best_sellers

        # END Best Sellers Card

        # Free days
        free_days_per_house, free_days_total, ocuppied_days_total, total_por_cobrar, total_facturado = get_days_without_reservations(fecha_actual, last_day_month)

        content['free_days_per_house'] = free_days_per_house
        content['free_days_total'] = free_days_total
        content['ocuppied_days_total'] = ocuppied_days_total

        content['dinero_por_cobrar'] = total_por_cobrar
        content['dinero_total_facturado'] = total_facturado


        # End Free days

        return Response(content, status=200)
