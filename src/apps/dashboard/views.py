from django.utils import timezone

import calendar
from datetime import datetime, timedelta

from rest_framework.views import APIView
from rest_framework.response import Response

from apps.accounts.models import CustomUser
from apps.property.models import Property
from apps.reservation.models import Reservation

from .serializers import DashboardSerializer
from django.db.models import Count, F, ExpressionWrapper, DecimalField, Value, CharField, Sum

from django.db.models.functions import Concat


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
                'nombre': v.first_name,
                'apellido': v.last_name,
                'ventas_soles': total_ventas_mes_vendedor,
                'foto_perfil': media_url+str(v.profile_photo)
            })

        content['best_sellers'] = best_sellers

        # END Best Sellers Card

        return Response(content, status=200)
