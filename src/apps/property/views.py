from django.db.models import Q

from drf_spectacular.utils import OpenApiParameter, OpenApiTypes, OpenApiExample, extend_schema
from rest_framework import filters, viewsets
from rest_framework.response import Response
from rest_framework.views import APIView
from rest_framework.exceptions import ValidationError

from apps.core.paginator import CustomPagination
# from apps.core.mixins import AdminMixin

from .models import Property, ProfitPropertyAirBnb
from apps.reservation.models import Reservation

from .serializers import PropertySerializer, ProfitPropertyAirBnbSerializer


class PropertyApiView(viewsets.ReadOnlyModelViewSet):
    serializer_class = PropertySerializer
    queryset = Property.objects.all().order_by("name")
    filter_backends = [filters.SearchFilter]
    search_fields = ["name"]
    pagination_class = CustomPagination

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
            OpenApiParameter(
                "search",
                OpenApiTypes.STR,
                description="Busqueda por nombre de propiedad",
                required=False,
            ),
        ],
        responses={200: PropertySerializer},
        methods=["GET"],
    )
    def list(self, request, *args, **kwargs):
        self.pagination_class = self.get_pagination_class()
        return super().list(request, *args, **kwargs)
    
class ProfitPropertyApiView(viewsets.ModelViewSet):
    serializer_class = ProfitPropertyAirBnbSerializer
    queryset = ProfitPropertyAirBnb.objects.all().order_by("created")
    pagination_class = CustomPagination

    def get_pagination_class(self):
        """Determinar si usar o no paginación
        - page_size = valor
        - valor = un numero entero, será el tamaño de la pagina
        - valor = none, no se pagina el resultado
        """
        if self.request.GET.get("page_size") == "none":
            return None

        return self.pagination_class

    def get_queryset(self):
        queryset = super().get_queryset()

        """
        Custom queryset to search reservations in a given month-year
        """
        if self.action == 'list':
            if self.request.query_params:
                if self.request.query_params.get('year') and self.request.query_params.get('month'):
                    try:
                        month_param = int(self.request.query_params['month'])
                        if not month_param in range(1,13):
                            raise ValidationError({"error":"Parámetro Mes debe ser un número entre el 1 y el 12"})

                    except Exception:
                        raise ValidationError({"error_month_param": "Parámetro Mes debe ser un número entre el 1 y el 12"})
                        
                    try: 
                        year_param = int(self.request.query_params['year'])
                        if year_param < 1:
                            raise ValidationError({"error":"Parámetro Mes debe ser un número entre el 1 y el 12"})
                    
                    except Exception:
                        raise ValidationError({"error_year_param": "Año debe ser un número entero positivo"})

                    queryset = queryset.filter(month=month_param, year=year_param)

        return queryset
    
    
    @extend_schema(
        parameters=[
            OpenApiParameter(
                "page_size",
                OpenApiTypes.INT,
                description="Enviar page_size=valor para determinar tamaño de la pagina, sino enviar page_size=none para no tener paginado",
                required=False,
            ),
        ],
        responses={200: ProfitPropertyAirBnbSerializer},
        methods=["GET"],
    )
    def list(self, request, *args, **kwargs):
        self.pagination_class = self.get_pagination_class()
        return super().list(request, *args, **kwargs)

class CheckAvaiblePorperty(APIView):
    serializer_class = None
    
    def post(self, request, format=None):
        property_field = request.data['property']
        check_out_date = request.data['check_out_date']
        check_in_date = request.data['check_in_date']

        content = {
            'message': 'Propiedad disponible para esa fecha',
            'condition': True
        }
        status_code = 200

        if Reservation.objects.filter(property=property_field,).filter(
                Q(check_in_date__lt=check_out_date) & Q(check_out_date__gt=check_in_date)
            ).exists():
                content = {
                    'message': 'Propiedad no disponible para esa fecha',
                    'condition': False
                }
                status_code = 404

        return Response(content, status=status_code)
    
    def patch(self, request, format=None):
        property_field = request.data['property']
        check_out_date = request.data['check_out_date']
        check_in_date = request.data['check_in_date']
        reservation_id = request.data['reservation_id']

        content = {
            'message': 'Propiedad disponible para esa fecha',
            'condition': True
        }
        status_code = 200

        if Reservation.objects.filter(property=property_field,).filter(
                Q(check_in_date__lt=check_out_date) & Q(check_out_date__gt=check_in_date)
            ).exclude(
                id=reservation_id
            ).exists():
                content = {
                    'message': 'Propiedad no disponible para esa fecha',
                    'condition': False
                }
                status_code = 404

        return Response(content, status=status_code)
