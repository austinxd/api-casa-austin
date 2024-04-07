from django.utils import timezone

from datetime import timedelta

from rest_framework.views import APIView
from rest_framework.response import Response

from apps.reservation.models import Reservation

from .serializers import DashboardSerializer
from django.db.models import Count, F, ExpressionWrapper, DecimalField


class DashboardApiView(APIView):
    serializer_class = DashboardSerializer
    
    def get(self, request):
        content = {}

        current_datetime = timezone.now()
        week = current_datetime - timedelta(days=1)
        reservations_week = Reservation.objects.filter(created__gte=week, created__lte=current_datetime).count()
        properties_more_reserved = Reservation.objects.filter(
                created__gte=week,
                created__lte=current_datetime
            ).values(
                'property',
                "property__background_color"
            ).annotate(
                num_reservas=Count('id'),
            ).order_by('-num_reservas')

        content['properties_more_reserved'] = properties_more_reserved.annotate(
            percentage=ExpressionWrapper(
                (F('num_reservas') * 100) / reservations_week, output_field=DecimalField()
                )
            )

        reservations_week = Reservation.objects.filter(created__gte=week, created__lte=current_datetime).count()
        content["reservations_last_week"] = reservations_week

        return Response(content, status=200)
    