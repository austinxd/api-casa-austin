from django.db.models import Q
from django.conf import settings

from drf_spectacular.utils import OpenApiParameter, OpenApiTypes, extend_schema
from rest_framework import filters, viewsets, status
from rest_framework.response import Response
from rest_framework.views import APIView
from rest_framework.exceptions import ValidationError
from rest_framework.decorators import action
from rest_framework.parsers import MultiPartParser, FormParser
from rest_framework.permissions import AllowAny

from apps.core.paginator import CustomPagination
from apps.core.functions import update_air_bnb_api

from .models import Property, ProfitPropertyAirBnb, PropertyPhoto
from .pricing_models import ExchangeRate, DiscountCode, DynamicDiscountConfig, SeasonPricing, AdditionalService, CancellationPolicy
from apps.reservation.models import Reservation
from apps.clients.models import Clients as Client

from .serializers import PropertyListSerializer, PropertyDetailSerializer, PropertySerializer, ProfitPropertyAirBnbSerializer, PropertyPhotoSerializer
from .pricing_serializers import PricingCalculationSerializer, AutomaticDiscountSerializer

# Importar el servicio de cálculo de precios del archivo correspondiente
from .pricing_service import PricingCalculationService


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

    @action(detail=False, methods=['post'])
    def test_upload(self, request):
        """Test endpoint to check upload limits"""
        if 'test_file' in request.FILES:
            file = request.FILES['test_file']
            return Response({
                "success": True,
                "file_name": file.name,
                "file_size": file.size,
                "content_type": file.content_type,
                "message": f"Archivo recibido correctamente: {file.size} bytes"
            })
        return Response({"error": "No se recibió ningún archivo"}, status=400)


class CalculatePricingAPIView(APIView):
    """
    Endpoint público para calcular precios de propiedades
    GET /api/v1/properties/calculate-pricing/
    """
    permission_classes = [AllowAny]

    @extend_schema(
        parameters=[
            OpenApiParameter(
                name='property_id',
                type=OpenApiTypes.STR,
                location=OpenApiParameter.QUERY,
                description='UUID de la propiedad (opcional - si no se especifica, muestra todas)',
                required=False
            ),
            OpenApiParameter(
                name='check_in_date',
                type=OpenApiTypes.DATE,
                location=OpenApiParameter.QUERY,
                description='Fecha de check-in (YYYY-MM-DD)',
                required=True
            ),
            OpenApiParameter(
                name='check_out_date',
                type=OpenApiTypes.DATE,
                location=OpenApiParameter.QUERY,
                description='Fecha de check-out (YYYY-MM-DD)',
                required=True
            ),
            OpenApiParameter(
                name='guests',
                type=OpenApiTypes.INT,
                location=OpenApiParameter.QUERY,
                description='Número de huéspedes (por defecto: 1)',
                required=False
            ),
            OpenApiParameter(
                name='client_id',
                type=OpenApiTypes.STR,
                location=OpenApiParameter.QUERY,
                description='UUID del cliente (opcional - para descuentos automáticos)',
                required=False
            ),
            OpenApiParameter(
                name='discount_code',
                type=OpenApiTypes.STR,
                location=OpenApiParameter.QUERY,
                description='Código de descuento (opcional)',
                required=False
            ),
            OpenApiParameter(
                name='additional_services',
                type=OpenApiTypes.STR,
                location=OpenApiParameter.QUERY,
                description='IDs de servicios adicionales separados por comas (ej: 1,3,5)',
                required=False
            ),
        ],
        responses={
            200: PricingCalculationSerializer,
            400: 'Bad Request - Parámetros inválidos',
            404: 'Not Found - Propiedad no encontrada'
        },
        description='Calcula precios de propiedades con descuentos, servicios adicionales y políticas de cancelación'
    )
    def get(self, request):
        try:
            # Validar parámetros requeridos
            check_in_date_str = request.query_params.get('check_in_date')
            check_out_date_str = request.query_params.get('check_out_date')
            guests_str = request.query_params.get('guests')

            if not all([check_in_date_str, check_out_date_str]):
                return Response({
                    'error': 1,
                    'error_message': 'Parámetros requeridos: check_in_date, check_out_date'
                }, status=status.HTTP_400_BAD_REQUEST)

            # Parsear y validar fechas
            try:
                from datetime import datetime
                check_in_date = datetime.strptime(check_in_date_str, '%Y-%m-%d').date()
                check_out_date = datetime.strptime(check_out_date_str, '%Y-%m-%d').date()
            except ValueError:
                return Response({
                    'error': 2,
                    'error_message': 'Formato de fecha inválido. Use YYYY-MM-DD'
                }, status=status.HTTP_400_BAD_REQUEST)

            # Validar que la fecha de entrada no sea en el pasado
            if check_in_date < datetime.now().date():
                return Response({
                    'error': 8,
                    'error_message': 'La fecha de entrada no puede ser en el pasado'
                }, status=status.HTTP_400_BAD_REQUEST)

            # Validar que la fecha de salida sea posterior a la de entrada
            if check_out_date <= check_in_date:
                return Response({
                    'error': 9,
                    'error_message': 'La fecha de salida debe ser posterior a la fecha de entrada'
                }, status=status.HTTP_400_BAD_REQUEST)

            # Validar número de huéspedes (asignar 1 por defecto si no se envía)
            if not guests_str:
                guests = 1
            else:
                try:
                    guests = int(guests_str)
                    if guests < 1:
                        raise ValueError()
                except ValueError:
                    return Response({
                        'error': 3,
                        'error_message': 'El número de huéspedes debe ser un entero mayor a 0'
                    }, status=status.HTTP_400_BAD_REQUEST)

            # Parámetros opcionales
            property_id = request.query_params.get('property_id')
            client_id = request.query_params.get('client_id')
            discount_code = request.query_params.get('discount_code')
            additional_services_param = request.query_params.get('additional_services')

            # Validar property_id si se proporciona
            if property_id:
                try:
                    from uuid import UUID
                    # Validar que sea un UUID válido
                    UUID(property_id)
                    if not Property.objects.filter(id=property_id, deleted=False).exists():
                        return Response({
                            'error': 4,
                            'error_message': 'Propiedad no encontrada'
                        }, status=status.HTTP_404_NOT_FOUND)
                except ValueError:
                    return Response({
                        'error': 5,
                        'error_message': 'property_id debe ser un UUID válido'
                    }, status=status.HTTP_400_BAD_REQUEST)

            # Validar client_id si se proporciona
            if client_id:
                try:
                    from uuid import UUID
                    # Validar que sea un UUID válido
                    UUID(client_id)
                    if not Client.objects.filter(id=client_id, deleted=False).exists():
                        return Response({
                            'error': 6,
                            'error_message': 'Cliente no encontrado'
                        }, status=status.HTTP_404_NOT_FOUND)
                except ValueError:
                    return Response({
                        'error': 7,
                        'error_message': 'client_id debe ser un UUID válido'
                    }, status=status.HTTP_400_BAD_REQUEST)

            # Validar additional_services si se proporciona
            additional_services_ids = []
            if additional_services_param:
                try:
                    # Dividir por comas y convertir a enteros
                    service_ids_str = additional_services_param.split(',')
                    additional_services_ids = [int(sid.strip()) for sid in service_ids_str if sid.strip()]
                    
                    # Verificar que los servicios existen
                    from .pricing_models import AdditionalService
                    existing_services = AdditionalService.objects.filter(
                        id__in=additional_services_ids,
                        is_active=True
                    ).count()
                    
                    if existing_services != len(additional_services_ids):
                        return Response({
                            'error': 11,
                            'error_message': 'Uno o más servicios adicionales no existen o están inactivos'
                        }, status=status.HTTP_400_BAD_REQUEST)
                        
                except (ValueError, TypeError):
                    return Response({
                        'error': 12,
                        'error_message': 'additional_services debe contener IDs numéricos separados por comas (ej: 1,3,5)'
                    }, status=status.HTTP_400_BAD_REQUEST)

            # Calcular precios usando el servicio
            pricing_service = PricingCalculationService()
            pricing_data = pricing_service.calculate_pricing(
                check_in_date=check_in_date,
                check_out_date=check_out_date,
                guests=guests,
                property_id=property_id,
                client_id=client_id,
                discount_code=discount_code,
                additional_services_ids=additional_services_ids
            )

            return Response({
                'success': True,
                'error': 0,
                'data': pricing_data,
                'message': 'Cálculo de precios realizado exitosamente'
            }, status=status.HTTP_200_OK)

        except ValidationError as e:
            return Response({
                'error': 9,
                'error_message': str(e)
            }, status=status.HTTP_400_BAD_REQUEST)

        except Exception as e:
            return Response({
                'error': 10,
                'error_message': 'Error interno del servidor',
                'detail': str(e) if settings.DEBUG else None
            }, status=status.HTTP_500_INTERNAL_SERVER_ERROR)


class GenerateSimpleDiscountAPIView(APIView):
    """
    Endpoint para generar un código de descuento simple válido por X días
    POST /api/v1/properties/generate-simple-discount/
    """
    permission_classes = [AllowAny]

    @extend_schema(
        request={
            'application/json': {
                'type': 'object',
                'properties': {
                    'validity_days': {
                        'type': 'integer',
                        'description': 'Número de días de validez del código (por defecto: 7)',
                        'minimum': 1,
                        'maximum': 365
                    },
                    'discount_percentage': {
                        'type': 'number',
                        'description': 'Porcentaje de descuento (por defecto: 10)',
                        'minimum': 1,
                        'maximum': 100
                    }
                }
            }
        },
        responses={
            200: {
                'type': 'object',
                'properties': {
                    'success': {'type': 'boolean'},
                    'data': {
                        'type': 'object',
                        'properties': {
                            'code': {'type': 'string'},
                            'discount_percentage': {'type': 'number'},
                            'created_date': {'type': 'string', 'format': 'date'},
                            'expiration_date': {'type': 'string', 'format': 'date'},
                            'validity_days': {'type': 'integer'},
                            'days_remaining': {'type': 'integer'},
                            'is_active': {'type': 'boolean'}
                        }
                    },
                    'message': {'type': 'string'}
                }
            },
            400: 'Bad Request - Parámetros inválidos'
        },
        description='Genera un código de descuento simple válido por X días'
    )
    def post(self, request):
        try:
            from datetime import date, timedelta
            import random
            import string
            
            # Obtener parámetros con valores por defecto
            validity_days = request.data.get('validity_days', 7)
            discount_percentage = request.data.get('discount_percentage', 10)
            
            # Validar parámetros
            try:
                validity_days = int(validity_days)
                if validity_days < 1 or validity_days > 365:
                    return Response({
                        'success': False,
                        'error': 1,
                        'message': 'validity_days debe estar entre 1 y 365'
                    }, status=status.HTTP_400_BAD_REQUEST)
            except (ValueError, TypeError):
                return Response({
                    'success': False,
                    'error': 2,
                    'message': 'validity_days debe ser un número entero'
                }, status=status.HTTP_400_BAD_REQUEST)
            
            try:
                discount_percentage = float(discount_percentage)
                if discount_percentage < 1 or discount_percentage > 100:
                    return Response({
                        'success': False,
                        'error': 3,
                        'message': 'discount_percentage debe estar entre 1 y 100'
                    }, status=status.HTTP_400_BAD_REQUEST)
            except (ValueError, TypeError):
                return Response({
                    'success': False,
                    'error': 4,
                    'message': 'discount_percentage debe ser un número'
                }, status=status.HTTP_400_BAD_REQUEST)
            
            # Generar código único
            while True:
                code = 'SIMPLE' + ''.join(random.choices(string.ascii_uppercase + string.digits, k=6))
                if not DiscountCode.objects.filter(code=code).exists():
                    break
            
            # Calcular fechas
            start_date = date.today()
            end_date = start_date + timedelta(days=validity_days)
            
            # Crear el código de descuento
            discount_code = DiscountCode.objects.create(
                code=code,
                description=f"Descuento temporal {discount_percentage}% válido por {validity_days} días",
                discount_type='percentage',
                discount_value=discount_percentage,
                start_date=start_date,
                end_date=end_date,
                usage_limit=1,  # Una sola vez por defecto
                is_active=True
            )
            
            return Response({
                'success': True,
                'data': {
                    'code': discount_code.code,
                    'discount_percentage': float(discount_code.discount_value),
                    'created_date': discount_code.start_date.isoformat(),
                    'expiration_date': discount_code.end_date.isoformat(),
                    'validity_days': validity_days,
                    'days_remaining': (discount_code.end_date - start_date).days,
                    'is_active': discount_code.is_active
                },
                'message': f'Código de descuento {discount_code.code} generado exitosamente'
            }, status=status.HTTP_200_OK)
            
        except Exception as e:
            return Response({
                'success': False,
                'error': 5,
                'message': 'Error interno del servidor',
                'detail': str(e) if settings.DEBUG else None
            }, status=status.HTTP_500_INTERNAL_SERVER_ERROR)


class GenerateDynamicDiscountAPIView(APIView):
    """
    Endpoint para generar códigos de descuento dinámicos
    POST /api/v1/properties/generate-discount/
    """
    permission_classes = [AllowAny]

    @extend_schema(
        request={
            'application/json': {
                'type': 'object',
                'properties': {
                    'config_name': {
                        'type': 'string',
                        'description': 'Nombre de la configuración de descuento a usar'
                    }
                },
                'required': ['config_name']
            }
        },
        responses={
            200: {
                'type': 'object',
                'properties': {
                    'success': {'type': 'boolean'},
                    'error': {'type': 'integer'},
                    'data': {
                        'type': 'object',
                        'properties': {
                            'code': {'type': 'string'},
                            'description': {'type': 'string'},
                            'discount_percentage': {'type': 'number'},
                            'min_amount_usd': {'type': 'number'},
                            'max_discount_usd': {'type': 'number'},
                            'start_date': {'type': 'string', 'format': 'date'},
                            'end_date': {'type': 'string', 'format': 'date'},
                            'validity_days': {'type': 'integer'},
                            'usage_limit': {'type': 'integer'},
                            'expires_in_hours': {'type': 'number'}
                        }
                    },
                    'message': {'type': 'string'}
                }
            },
            400: 'Bad Request - Parámetros inválidos',
            404: 'Not Found - Configuración no encontrada'
        },
        description='Genera un código de descuento dinámico basado en una configuración predefinida'
    )
    def post(self, request):
        try:
            config_name = request.data.get('config_name')
            
            if not config_name:
                return Response({
                    'success': False,
                    'error': 1,
                    'message': 'config_name es requerido'
                }, status=status.HTTP_400_BAD_REQUEST)

            # Buscar la configuración
            try:
                config = DynamicDiscountConfig.objects.get(
                    name__iexact=config_name.strip(),
                    is_active=True,
                    deleted=False
                )
            except DynamicDiscountConfig.DoesNotExist:
                # Listar configuraciones disponibles para debugging
                available_configs = DynamicDiscountConfig.objects.filter(
                    is_active=True, 
                    deleted=False
                ).values_list('name', flat=True)
                
                return Response({
                    'success': False,
                    'error': 2,
                    'message': f'Configuración "{config_name}" no encontrada',
                    'available_configs': list(available_configs)
                }, status=status.HTTP_404_NOT_FOUND)

            # Generar el código
            discount_code = config.generate_code()
            
            # Calcular cuántas horas quedan hasta la expiración
            from datetime import datetime, timezone
            now = datetime.now().date()
            days_until_expiry = (discount_code.end_date - now).days
            expires_in_hours = days_until_expiry * 24

            return Response({
                'success': True,
                'error': 0,
                'data': {
                    'code': discount_code.code,
                    'description': discount_code.description,
                    'discount_percentage': float(discount_code.discount_value),
                    'min_amount_usd': float(discount_code.min_amount_usd) if discount_code.min_amount_usd else None,
                    'max_discount_usd': float(discount_code.max_discount_usd) if discount_code.max_discount_usd else None,
                    'start_date': discount_code.start_date.isoformat(),
                    'end_date': discount_code.end_date.isoformat(),
                    'validity_days': config.validity_days,
                    'usage_limit': discount_code.usage_limit,
                    'expires_in_hours': expires_in_hours
                },
                'message': f'Código de descuento {discount_code.code} generado exitosamente'
            }, status=status.HTTP_200_OK)

        except Exception as e:
            return Response({
                'success': False,
                'error': 3,
                'message': 'Error interno del servidor',
                'detail': str(e) if settings.DEBUG else None
            }, status=status.HTTP_500_INTERNAL_SERVER_ERROR)

    @extend_schema(
        responses={
            200: {
                'type': 'object',
                'properties': {
                    'success': {'type': 'boolean'},
                    'data': {
                        'type': 'array',
                        'items': {
                            'type': 'object',
                            'properties': {
                                'name': {'type': 'string'},
                                'prefix': {'type': 'string'},
                                'discount_percentage': {'type': 'number'},
                                'validity_days': {'type': 'integer'},
                                'min_amount_usd': {'type': 'number'},
                                'usage_limit': {'type': 'integer'}
                            }
                        }
                    },
                    'message': {'type': 'string'}
                }
            }
        },
        description='Lista las configuraciones disponibles para generar códigos dinámicos'
    )
    def get(self, request):
        """Lista las configuraciones disponibles"""
        configs = DynamicDiscountConfig.objects.filter(
            is_active=True, 
            deleted=False
        ).values(
            'name', 'prefix', 'discount_percentage', 
            'validity_days', 'min_amount_usd', 'usage_limit'
        )
        
        return Response({
            'success': True,
            'data': list(configs),
            'message': f'{len(configs)} configuraciones disponibles'
        }, status=status.HTTP_200_OK)


class AutomaticDiscountDetailAPIView(APIView):
    """
    Endpoint para obtener los detalles de un descuento automático específico
    GET /api/v1/property/automaticdiscount/{discount_id}/
    """
    permission_classes = [AllowAny]

    @extend_schema(
        responses={
            200: AutomaticDiscountSerializer,
            404: 'Not Found - Descuento automático no encontrado'
        },
        description='Obtiene los detalles de un descuento automático específico por su ID'
    )
    def get(self, request, discount_id):
        try:
            # Validar que el ID sea un UUID válido
            try:
                from uuid import UUID
                UUID(discount_id)
            except ValueError:
                return Response({
                    'success': False,
                    'error': 1,
                    'message': 'ID debe ser un UUID válido'
                }, status=status.HTTP_400_BAD_REQUEST)

            # Buscar el descuento automático
            try:
                from .pricing_models import AutomaticDiscount
                automatic_discount = AutomaticDiscount.objects.get(
                    id=discount_id,
                    deleted=False
                )
            except AutomaticDiscount.DoesNotExist:
                return Response({
                    'success': False,
                    'error': 2,
                    'message': 'Descuento automático no encontrado'
                }, status=status.HTTP_404_NOT_FOUND)

            # Serializar y retornar
            serializer = AutomaticDiscountSerializer(automatic_discount)
            
            return Response({
                'success': True,
                'is_active': automatic_discount.is_active,
                'data': serializer.data,
                'message': 'Descuento automático obtenido exitosamente'
            }, status=status.HTTP_200_OK)

        except Exception as e:
            return Response({
                'success': False,
                'error': 3,
                'message': 'Error interno del servidor',
                'detail': str(e) if settings.DEBUG else None
            }, status=status.HTTP_500_INTERNAL_SERVER_ERROR)

                