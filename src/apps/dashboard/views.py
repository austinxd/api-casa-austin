import calendar
from datetime import datetime

from rest_framework.views import APIView
from rest_framework.response import Response

from apps.accounts.models import CustomUser
from apps.reservation.models import Reservation

from .serializers import DashboardSerializer
from django.db.models import Sum, Q

from .utils import get_stadistics_period


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
        query_vendedores = CustomUser.objects.exclude(deleted=True).filter(
            Q(groups__name='vendedor') | Q(groups__name='admin')
        )

        for v in query_vendedores:
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
        free_days_per_house, free_days_total, ocuppied_days_total, total_por_cobrar, total_facturado = get_stadistics_period(fecha_actual, last_day_month)

        content['free_days_per_house'] = free_days_per_house
        content['free_days_total'] = free_days_total
        content['ocuppied_days_total'] = ocuppied_days_total

        content['dinero_por_cobrar'] = total_por_cobrar
        content['dinero_total_facturado'] = total_facturado


        # End Free days

        return Response(content, status=200)
