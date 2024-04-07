from datetime import datetime, timedelta

from rest_framework.views import APIView
from rest_framework.response import Response

from apps.reservation.models import Reservation

from .serializers import DashboardSerializer
from django.db.models import Count, F, ExpressionWrapper, DecimalField


class DashboardApiView(APIView):
    serializer_class = DashboardSerializer
    
    def get(self, request):
        content = {}

        week = datetime.now() - timedelta(days=1)
        reservations_week = Reservation.objects.filter(created__gte=week, created__lte=datetime.now()).count()
        properties_more_reserved = Reservation.objects.filter(
            created__gte=week,
            created__lte=datetime.now()
        ).values('property').annotate(num_reservas=Count('id')).order_by('-num_reservas')[:4]
        content['properties_more_reserved'] = properties_more_reserved.annotate(
            percentage=ExpressionWrapper((F('num_reservas') * 100) / reservations_week, output_field=DecimalField())
        )

        reservations_week = Reservation.objects.filter(created__gte=week, created__lte=datetime.now()).count()
        content["reservations_last_week"] = reservations_week

        return Response(content, status=200)
    