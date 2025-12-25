import calendar
from datetime import datetime

from rest_framework.views import APIView
from rest_framework.response import Response
from rest_framework.permissions import IsAuthenticated
from rest_framework_simplejwt.authentication import JWTAuthentication

from apps.accounts.models import CustomUser
from apps.reservation.models import Reservation

from .serializers import DashboardSerializer
from django.db.models import Sum, Q

from .utils import get_stadistics_period


class DashboardApiView(APIView):
    serializer_class = DashboardSerializer
    authentication_classes = [JWTAuthentication]
    permission_classes = [IsAuthenticated]

    def get(self, request):
        content = {}
        
        base_url = request.scheme + '://' + request.get_host()
        media_url = base_url + "/media/"

        # Obtener parámetros de mes y año
        month = request.GET.get('month')
        year = request.GET.get('year')

        if month and year:
            try:
                month = int(month)
                year = int(year)
            except ValueError:
                return Response({'error': 'Month and year must be integers'}, status=400)
        else:
            fecha_actual = datetime.now()
            month = fecha_actual.month
            year = fecha_actual.year

        # Validar mes y año
        if month < 1 or month > 12:
            return Response({'error': 'Month must be between 1 and 12'}, status=400)

        if year < 1900 or year > 2100:
            return Response({'error': 'Year must be between 1900 and 2100'}, status=400)

        # Best Sellers Card
        last_day_month = calendar.monthrange(year, month)[1]

        range_evaluate = (datetime(year, month, 1), datetime(year, month, last_day_month))
        query_reservation_current_month = Reservation.objects.exclude(deleted=True).filter(check_in_date__range=range_evaluate)
        
        best_sellers = []
        query_vendedores = CustomUser.objects.filter(
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
        fecha_actual = datetime(year, month, 1)
        free_days_per_house, free_days_total, ocuppied_days_total, noches_man, total_por_cobrar, total_facturado = get_stadistics_period(fecha_actual, last_day_month)

        # Calcular puntos canjeados en el mes
        puntos_canjeados_mes = query_reservation_current_month.aggregate(
            total_puntos=Sum('points_redeemed')
        )['total_puntos'] or 0

        # Restar puntos canjeados del dinero por cobrar
        dinero_por_cobrar_ajustado = float(total_por_cobrar) - float(puntos_canjeados_mes)

        content['free_days_per_house'] = free_days_per_house
        content['free_days_total'] = free_days_total
        content['ocuppied_days_total'] = ocuppied_days_total
        content['noches_man'] = noches_man
        content['puntos_canjeados'] = '%.2f' % float(puntos_canjeados_mes)
        content['dinero_por_cobrar'] = '%.2f' % dinero_por_cobrar_ajustado
        content['dinero_total_facturado'] = total_facturado

        # End Free days

        return Response(content, status=200)
