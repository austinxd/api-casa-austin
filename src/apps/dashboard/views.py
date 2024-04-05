from django.db.models import Q

from drf_spectacular.utils import OpenApiParameter, OpenApiTypes, OpenApiExample, extend_schema
from rest_framework import viewsets

from datetime import datetime, timedelta

from apps.core.paginator import CustomPagination
# from apps.core.mixins import AdminMixin

# from .models import Property, ProfitPropertyAirBnb
from apps.reservation.models import Reservation

from .serializers import DashboardSerializer
from django.db.models import Count, F, ExpressionWrapper, DecimalField


class DashboardApiView(viewsets.ReadOnlyModelViewSet):
    serializer_class = DashboardSerializer
    # queryset = Reservation.objects.all()
    # filter_backends = [filters.SearchFilter]
    # search_fields = ["name"]
    pagination_class = CustomPagination
    
    def get_queryset(self):
        week = datetime.now() - timedelta(days=1)
        reservations_week = Reservation.objects.filter(created__gte=week, created__lte=datetime.now()).count()
        properties_more_reserved = Reservation.objects.filter(created__gte=week, created__lte=datetime.now()).values('property').annotate(num_reservas=Count('id')).order_by('-num_reservas')[:4]
        properties_more_reserved = properties_more_reserved.annotate(percentage=ExpressionWrapper((F('num_reservas') * 100) / reservations_week, output_field=DecimalField()))
        # queryset = Reservation.objects.all()
        
        return properties_more_reserved

    def get_pagination_class(self):
        """Determinar si usar o no paginación
        - page_size = valor
        - valor = un numero entero, será el tamaño de la pagina
        - valor = none, no se pagina el resultado
        """
        if self.request.GET.get("page_size") == "none":
            return None

        return self.pagination_class

    @extend_schema(
        parameters=[
            OpenApiParameter(
                "page_size",
                OpenApiTypes.INT,
                description="Enviar page_size=valor para determinar tamaño de la pagina, sino enviar page_size=none para no tener paginado",
                required=False,
            ),
        ],
        responses={200: DashboardSerializer},
        methods=["GET"],
    )
    def list(self, request, *args, **kwargs):
        self.pagination_class = self.get_pagination_class()
        response = super().list(request, *args, **kwargs)
        week = datetime.now() - timedelta(days=1)
        reservations_week = Reservation.objects.filter(created__gte=week, created__lte=datetime.now()).count()
        response.data["reservations_last_week"] = reservations_week
        return response
    
    