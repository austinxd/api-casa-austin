from django.db.models import Q

from drf_spectacular.utils import OpenApiParameter, OpenApiTypes, extend_schema
from rest_framework import filters, viewsets, status
from rest_framework.response import Response
from rest_framework.views import APIView
from rest_framework.exceptions import ValidationError
from rest_framework.decorators import action
from rest_framework.parsers import MultiPartParser, FormParser

from apps.core.paginator import CustomPagination
from apps.core.functions import update_air_bnb_api

from .models import Property, ProfitPropertyAirBnb, PropertyPhoto
from apps.reservation.models import Reservation

from .serializers import PropertyListSerializer, PropertyDetailSerializer, PropertySerializer, ProfitPropertyAirBnbSerializer, PropertyPhotoSerializer


class PropertyApiView(viewsets.ReadOnlyModelViewSet):
    serializer_class = PropertyListSerializer
    queryset = Property.objects.exclude(deleted=True).order_by("name")
    filter_backends = [filters.SearchFilter]
    search_fields = ["name"]
    pagination_class = CustomPagination
    lookup_field = 'slug'  # Usar slug para URLs amigables

    def get_serializer_class(self):
        """Usar diferentes serializers según la acción"""
        if self.action == 'retrieve':
            return PropertyDetailSerializer
        return PropertyListSerializer

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
    queryset = ProfitPropertyAirBnb.objects.exclude(deleted=True).order_by("created")
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

        try:
            property_object = Property.objects.get(id=property_field)

            update_air_bnb_api(property_object)
        except:
            print('No puedo obtener propiedad solicitada')

        if Reservation.objects.exclude(deleted=True).filter(property=property_field,).filter(
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

        if Reservation.objects.exclude(deleted=True).filter(property=property_field,).filter(
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


class PropertyPhotoViewSet(viewsets.ModelViewSet):
    """ViewSet para manejar las fotos de propiedades"""
    serializer_class = PropertyPhotoSerializer
    queryset = PropertyPhoto.objects.exclude(deleted=True).order_by('order')
    parser_classes = (MultiPartParser, FormParser)

    def get_queryset(self):
        """Filter photos by property if property_id is provided"""
        queryset = super().get_queryset()
        property_id = self.request.query_params.get('property_id')
        if property_id:
            queryset = queryset.filter(property_id=property_id)
        return queryset

    @action(detail=False, methods=['post'])
    def upload_photo(self, request):
        """Upload a photo for a specific property"""
        property_id = request.data.get('property_id')

        if not property_id:
            return Response(
                {"error": "property_id es requerido"}, 
                status=status.HTTP_400_BAD_REQUEST
            )

        try:
            property_instance = Property.objects.get(id=property_id, deleted=False)
        except Property.DoesNotExist:
            return Response(
                {"error": "Propiedad no encontrada"}, 
                status=status.HTTP_404_NOT_FOUND
            )

        # Create the photo instance
        serializer = self.get_serializer(data=request.data)
        if serializer.is_valid():
            serializer.save(property=property_instance)
            return Response(serializer.data, status=status.HTTP_201_CREATED)

        return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)