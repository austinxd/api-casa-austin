from django.utils import timezone

import calendar
from datetime import datetime, timedelta

from rest_framework.views import APIView
from rest_framework.response import Response

from apps.accounts.models import CustomUser
from apps.property.models import Property, ProfitPropertyAirBnb
from apps.reservation.models import Reservation

from .serializers import DashboardSerializer
from django.db.models import Sum, Q

from apps.core.functions import contar_noches_reserva, noches_restantes_mes



def get_days_without_reservations(fecha_actual, last_day):

    first_day = datetime(fecha_actual.year, fecha_actual.month, 1)
    last_day = datetime(fecha_actual.year, fecha_actual.month, last_day)

    days_without_reservations_per_property = []
    days_without_reservations_total = 0
    total_por_cobrar = 0
    total_facturado = 0

    total_days_for_all_properties = 0
    for p in Property.objects.exclude(deleted=True):
        reservations = Reservation.objects.exclude(
            deleted=True
        ).filter(
            property=p
                ).filter(
                    Q(check_in_date__gte=first_day, check_in_date__lt=last_day) |
                    Q(check_out_date__gte=first_day, check_out_date__lt=last_day)
                ).exclude(check_out_date__lt=fecha_actual)

        noches_reservadas = 0
        # print('*'*50)
        # print('FECHA SERVIDOR', fecha_actual)
        # print('propiedad', p.name)
        for r in reservations.exclude(deleted=True).order_by('check_in_date'):
            # print('x'*50)
            # print('r', r)
            # print('ci', r.check_in_date)
            # print('co', r.check_out_date)
            # print('deleted', r.deleted)
            noches_reservadas += contar_noches_reserva(r.check_in_date, r.check_out_date, last_day.date())
        #     print('Noches reservada: ', noches_reservadas)

        # print('*'*50)
        noches_totales = noches_restantes_mes(fecha_actual.date(), last_day.date())

        # print('Noches evaluar:', noches_totales)

        pagos_recibidos_propiedad_mes = 0

        for r in reservations:
            # opero con una property
            pagos_recibidos_propiedad_mes += r.adelanto_normalizado

        valor_propiedad_mes = reservations.aggregate(pagos=Sum('price_sol'))

        if valor_propiedad_mes['pagos']:
            valor_propiedad_mes = float(valor_propiedad_mes['pagos'])
        else:
            valor_propiedad_mes = 0

        # # Genera una lista de todos los días desde la fecha actual a fin del mes
        # all_days = [fecha_actual + timedelta(days=i) for i in range((last_day - fecha_actual).days + 1)]

        # # Encuentra los días sin reservaciones
        # days_without_reservations = [day.date() for day in all_days if not any((reservation.check_in_date <= day.date() <= reservation.check_out_date) for reservation in reservations)]

        query_profit_airbnb_property = ProfitPropertyAirBnb.objects.filter(
          property = p,
          month=fecha_actual.month,
          year=fecha_actual.year  
        )

        profit_propiedad_mes_airbnb = float(query_profit_airbnb_property.first().profit_sol) if query_profit_airbnb_property else 0

        days_without_reservations_per_property.append({
            'casa':p.name,
            'property__background_color':p.background_color,
            'dias_libres': noches_totales - noches_reservadas,
            'dias_ocupada': noches_reservadas,
            'dinero_por_cobrar': round(valor_propiedad_mes - pagos_recibidos_propiedad_mes, 2),
            'dinero_facturado': round(pagos_recibidos_propiedad_mes + profit_propiedad_mes_airbnb),
        })

        days_without_reservations_total += noches_totales - noches_reservadas

        total_days_for_all_properties += noches_reservadas

        total_por_cobrar += valor_propiedad_mes - pagos_recibidos_propiedad_mes
        total_facturado += pagos_recibidos_propiedad_mes + profit_propiedad_mes_airbnb


    return days_without_reservations_per_property, days_without_reservations_total, total_days_for_all_properties, '%.2f' % total_por_cobrar, '%.2f' % total_facturado


class DashboardApiView(APIView):
    serializer_class = DashboardSerializer
    
    def get(self, request):
        content = {}
        
        base_url = request.scheme + '://' + request.get_host()
        media_url = base_url + "/media/"

        # Best Sellers Card
        fecha_actual = datetime.now()

        last_day_month = calendar.monthrange(fecha_actual.year, fecha_actual.month)[1]

        range_evaluate = (datetime(fecha_actual.year, fecha_actual.month, 1), datetime(fecha_actual.year, fecha_actual.month, last_day_month))
        query_reservation_current_month = Reservation.objects.exclude(deleted=True).filter(check_in_date__range=range_evaluate)
        
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
                'foto_perfil': media_url+str(v.profile_photo) if v.profile_photo else base_url+'/static/default-user.jpg'
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
