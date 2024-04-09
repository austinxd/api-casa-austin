from django.utils import timezone

from datetime import timedelta

from rest_framework.views import APIView
from rest_framework.response import Response

from apps.accounts.models import CustomUser
from apps.property.models import Property
from apps.reservation.models import Reservation

from .serializers import DashboardSerializer
from django.db.models import Count, F, ExpressionWrapper, DecimalField, Value, CharField

from django.db.models.functions import Concat


class DashboardApiView(APIView):
    serializer_class = DashboardSerializer
    
    def get(self, request):
        content = {}
        
        media_url = request.scheme + '://' + request.get_host() + "/media/"

        current_datetime = timezone.now()
        week = current_datetime - timedelta(days=30)
        reservations_week = Reservation.objects.filter(created__gte=week, created__lte=current_datetime).count()
        reservations_week_seller = Reservation.objects.filter(created__gte=week, created__lte=current_datetime, seller__isnull=False).count()
        """" Propiedades """
        properties_more_reserved = Reservation.objects.filter(
                created__gte=week,
                created__lte=current_datetime
            ).values(
                'property',
                'property__background_color',
                'property__name',
            ).annotate(
                num_reservas=Count('id'),
            ).order_by('-num_reservas')

        # Agregar propiedades que no tienen reservas
        properties_list = Reservation.objects.filter(
                created__gte=week,
                created__lte=current_datetime
            ).values_list(
                'property',
                flat=True
            )
        list_properties_without_reserved = []
        prop_without_reserved = Property.objects.exclude(id__in=properties_list)
        for p in prop_without_reserved:
            dict_aux = {
                'property': p.id,
                'property__background_color': p.background_color,
                'property__name': p.name,
                'num_reservas': 0,
                'percentage': float(0)
            }
            list_properties_without_reserved.append(dict_aux)

        content['properties_more_reserved'] = properties_more_reserved.annotate(
            percentage=ExpressionWrapper(
                (F('num_reservas') * 100) / reservations_week, output_field=DecimalField()
                )
            )

        content['properties_more_reserved'] = list(content['properties_more_reserved']) + list_properties_without_reserved

        # """" Vendedores """
        seller_more_reserved = Reservation.objects.filter(
                created__gte=week,
                created__lte=current_datetime,
                seller__isnull=False,
                seller__groups__name='vendedor'
            ).values(
                'seller',
                'seller__email',
                'seller__last_name',
                'seller__first_name'
            ).annotate(
                num_reservas=Count('id'),
                photo=Concat(Value(media_url), F('seller__profile_photo'),  output_field=CharField())
            ).order_by('-num_reservas')
        
        # Agregar propiedades que no tienen reservas
        seller_list = Reservation.objects.filter(
                created__gte=week,
                created__lte=current_datetime,
                seller__isnull=False,
                seller__groups__name='vendedor'
            ).values_list(
                'seller',
                flat=True
            )

        list_seller_without_reserved = []
        seller_without_reserved = CustomUser.objects.filter(groups__name='vendedor').exclude(id__in=seller_list)
        for s in seller_without_reserved:
            dict_aux = {
                'seller': s.id,
                'seller__email': s.email,
                'seller__last_name': s.last_name,
                'seller__first_name': s.first_name,
                'num_reservas': 0,
                'percentage': float(0)
            }
            list_seller_without_reserved.append(dict_aux)

        content['seller_more_reserved'] = seller_more_reserved.annotate(
            percentage=ExpressionWrapper(
                (F('num_reservas') * 100) / reservations_week_seller, output_field=DecimalField()
                )
            )

        content['seller_more_reserved'] = list(content['seller_more_reserved']) + list_seller_without_reserved

        reservations_week = Reservation.objects.filter(created__gte=week, created__lte=current_datetime).count()
        content["reservations_last_week"] = reservations_week
        content["statistic_2"] = abs(reservations_week - 1)
        content["statistic_3"] = abs(reservations_week - 3)
        content["statistic_4"] = abs(reservations_week - 5)
        return Response(content, status=200)
