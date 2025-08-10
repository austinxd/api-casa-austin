from rest_framework import status, permissions
from rest_framework.decorators import api_view
from rest_framework.response import Response
from rest_framework.views import APIView
from rest_framework.permissions import AllowAny

from apps.reservation.models import Reservation
from apps.reservation.serializers import ClientReservationSerializer, ReservationListSerializer
from .auth_views import ClientJWTAuthentication

import logging

logger = logging.getLogger(__name__)


class ClientCreateReservationView(APIView):
    """Vista para que los clientes autenticados puedan crear reservas pendientes"""
    authentication_classes = [ClientJWTAuthentication]
    permission_classes = [AllowAny]

    def post(self, request):
        logger.info(
            f"ClientCreateReservationView: New reservation request from client"
        )

        # Autenticar cliente
        try:
            authenticator = ClientJWTAuthentication()
            client, validated_token = authenticator.authenticate(request)

            if not client:
                logger.error(
                    "ClientCreateReservationView: Authentication failed")
                return Response({'message': 'Token inválido'}, status=401)

            # Crear serializer con contexto
            serializer = ClientReservationSerializer(
                data=request.data, context={'request': request})

            if serializer.is_valid():
                # Establecer deadline de 1 hora para subir voucher
                payment_deadline = timezone.now() + timedelta(hours=1)

                # Crear la reserva y disparar las señales
                reservation = serializer.save(
                    client=client,
                    origin='client',
                    status='incomplete',
                    payment_voucher_deadline=payment_deadline,
                    payment_voucher_uploaded=False,
                    payment_confirmed=False
                )

                # Retornar la reserva creada
                response_serializer = ReservationListSerializer(reservation)

                logger.info(
                    f"ClientCreateReservationView: Reservation created successfully - ID: {reservation.id}"
                )

                return Response(
                    {
                        'success': True,
                        'message':
                        'Reserva creada exitosamente. Está pendiente de<bos>a aprobación.',
                        'reservation': response_serializer.data
                    },
                    status=201)
            else:
                logger.error(
                    f"ClientCreateReservationView: Validation errors: {serializer.errors}"
                )
                return Response(
                    {
                        'success': False,
                        'message': 'Error en los datos enviados',
                        'errors': serializer.errors
                    },
                    status=400)

        except Exception as e:
            logger.error(
                f"ClientCreateReservationView: Error creating reservation: {str(e)}"
            )
            return Response(
                {
                    'success': False,
                    'message': 'Error interno del servidor'
                },
                status=500)


class ClientReservationsListView(APIView):
    """Vista para listar las reservas del cliente autenticado"""
    authentication_classes = [ClientJWTAuthentication]
    permission_classes = [AllowAny]

    def get(self, request):
        logger.info(f"ClientReservationsListView: Request received")

        try:
            authenticator = ClientJWTAuthentication()
            client, validated_token = authenticator.authenticate(request)

            if not client:
                logger.error(
                    "ClientReservationsListView: Authentication failed")
                return Response({'message': 'Token inválido'}, status=401)

            from datetime import date

            # Obtener todas las reservas del cliente
            reservations = Reservation.objects.filter(
                client=client, deleted=False).order_by('-created')

            # Clasificar reservas
            today = date.today()
            upcoming_reservations = []
            past_reservations = []
            pending_reservations = []

            for reservation in reservations:
                if reservation.status in ['incomplete', 'pending']:
                    pending_reservations.append(reservation)
                elif reservation.check_out_date > today:
                    upcoming_reservations.append(reservation)
                else:
                    past_reservations.append(reservation)

            # Serializar las reservas
            upcoming_serializer = ReservationListSerializer(
                upcoming_reservations, many=True)
            past_serializer = ReservationListSerializer(past_reservations,
                                                        many=True)
            pending_serializer = ReservationListSerializer(
                pending_reservations, many=True)

            return Response({
                'upcoming_reservations': upcoming_serializer.data,
                'past_reservations': past_serializer.data,
                'pending_reservations': pending_serializer.data
            })

        except Exception as e:
            logger.error(
                f"ClientReservationsListView: Error getting reservations: {str(e)}"
            )
            return Response(
                {
                    'success': False,
                    'message': 'Error interno del servidor'
                },
                status=500)


from datetime import datetime

from drf_spectacular.utils import OpenApiParameter, OpenApiTypes, extend_schema
from rest_framework import filters, viewsets, status, permissions
from rest_framework.views import APIView
from rest_framework.decorators import action, api_view, permission_classes
from rest_framework.response import Response
from rest_framework.generics import CreateAPIView, ListAPIView
from django.contrib.auth.hashers import make_password, check_password
from django.utils import timezone
from datetime import datetime, timedelta
from django.db.models import Q, Sum, Count
from django.shortcuts import get_object_or_404

from .models import Clients, MensajeFidelidad, TokenApiClients, ClientPoints, ReferralPointsConfig, SearchTracking
from .serializers import (
    ClientsSerializer, MensajeFidelidadSerializer, TokenApiClienteSerializer,
    ClientAuthVerifySerializer, ClientAuthRequestOTPSerializer,
    ClientAuthSetPasswordSerializer, ClientAuthLoginSerializer,
    ClientProfileSerializer, ClientPointsSerializer,
    ClientPointsBalanceSerializer, RedeemPointsSerializer, SearchTrackingSerializer)
from .twilio_service import send_sms
from apps.core.utils import ExportCsvMixin
from apps.reservation.models import Reservation
from apps.reservation.serializers import ClientReservationSerializer

from apps.core.paginator import CustomPagination


def get_client_from_token(request):
    """Helper function to get client from JWT token"""
    try:
        # Verificar que existe el header Authorization
        auth_header = request.META.get('HTTP_AUTHORIZATION')
        if not auth_header:
            logger.error("get_client_from_token: No Authorization header found")
            return None

        if not auth_header.startswith('Bearer '):
            logger.error(f"get_client_from_token: Invalid Authorization header format: {auth_header}")
            return None

        authenticator = ClientJWTAuthentication()
        auth_result = authenticator.authenticate(request)

        if auth_result is None:
            logger.error("get_client_from_token: Authentication failed - no result from authenticator")
            return None

        client, validated_token = auth_result
        if client:
            logger.info(f"get_client_from_token: Client authenticated successfully - ID: {client.id}")
            return client
        else:
            logger.error("get_client_from_token: No client found in auth result")
            return None

    except Exception as e:
        logger.error(f"get_client_from_token: Error authenticating client: {str(e)}")
        return None

from apps.core.functions import generate_audit


class MensajeFidelidadApiView(APIView):
    serializer_class = MensajeFidelidadSerializer

    def get(self, request):
        content = self.serializer_class(
            MensajeFidelidad.objects.exclude(activo=False).last()).data
        return Response(content, status=200)


class TokenApiClientApiView(APIView):
    serializer_class = TokenApiClienteSerializer

    def get(self, request):
        content = self.serializer_class(
            TokenApiClients.objects.exclude(
                deleted=True).order_by("created").last()).data
        return Response(content, status=200)


class ClientsApiView(viewsets.ModelViewSet):
    serializer_class = ClientsSerializer
    filter_backends = [filters.SearchFilter]
    search_fields = [
        "email", "number_doc", "first_name", "last_name", "tel_number"
    ]
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
                description=
                "Enviar page_size=valor para determinar tamaño de la pagina, sino enviar page_size=none para no tener paginado",
                required=False,
            ),
            OpenApiParameter(
                "search",
                OpenApiTypes.STR,
                description="Busqueda por nombre, apellido o email",
                required=False,
            ),
            OpenApiParameter(
                "bd",
                OpenApiTypes.STR,
                description=
                "bd=today para recuperar todos los clientes que tengan cumpleaños hoy",
                required=False,
            ),
        ],
        responses={200: ClientsSerializer},
        methods=["GET"],
    )
    def list(self, request, *args, **kwargs):
        self.pagination_class = self.get_pagination_class()
        return super().list(request, *args, **kwargs)

    def perform_create(self, serializer):
        serializer.save()

        generate_audit(serializer.instance, self.request.user, "create",
                       "Cliente creado")

        # Verificar si hay código de referido
        referral_code = self.request.data.get('referral_code')
        if referral_code:
            referrer = Clients.get_client_by_referral_code(referral_code)
            if referrer:
                serializer.instance.referred_by = referrer
                logger.info(
                    f"Cliente {serializer.instance.first_name} referido por {referrer.first_name} (Código: {referral_code})"
                )
            else:
                logger.warning(
                    f"Referente con código {referral_code} no encontrado")
                pass  # No fallar el registro si el referente no existe
        serializer.instance.save()

    def partial_update(self, request, *args, **kwargs):
        instance = self.get_object()
        serializer = self.get_serializer(instance,
                                         data=request.data,
                                         partial=True)
        serializer.is_valid(raise_exception=True)

        self.perform_update(serializer)

        generate_audit(instance, self.request.user, "update",
                       "Cliente actulizado")
        return Response(serializer.data)

    def destroy(self, request, *args, **kwargs):
        instance = self.get_object()

        instance.deleted = True
        instance.save()

        generate_audit(instance, self.request.user, "delete",
                       "Cliente eliminado")

        return Response(status=status.HTTP_204_NO_CONTENT)

    def get_queryset(self):
        queryset = Clients.objects.exclude(deleted=True).order_by(
            "last_name", "first_name")

        if not "admin" in self.request.user.groups.all().values_list(
                'name', flat=True):
            queryset = queryset.exclude(first_name="Mantenimiento")

        if self.action == "search_clients":
            params = self.request.GET
            self.pagination_class = None
            if not params:
                return queryset.none()
            return queryset

        if self.request.query_params.get('bd') == 'today':
            queryset = queryset.filter(date__month=datetime.now().month,
                                       date__day=datetime.now().day)

        return queryset

    @action(
        detail=False,
        methods=["GET"],
        url_name="search",
        url_path="search",
    )
    def search_clients(self, request, *args, **kwargs):
        return super().list(request, *args, **kwargs)


class ReferralConfigView(APIView):
    authentication_classes = [ClientJWTAuthentication]
    permission_classes = [AllowAny]

    def get(self, request):
        """Obtener configuración actual del sistema de referidos"""
        try:
            # Usar exactamente la misma lógica que ClientReservationsView
            authenticator = ClientJWTAuthentication()
            client, validated_token = authenticator.authenticate(request)

            if not client:
                logger.error("ReferralConfigView: Authentication failed")
                return Response({'message': 'Token inválido'}, status=401)

            config = ReferralPointsConfig.get_current_config()
            if config:
                return Response({
                    'percentage': float(config.percentage),
                    'is_active': config.is_active
                })
            else:
                return Response({
                    'percentage': 5.0,  # Valor por defecto
                    'is_active': True
                })
        except Exception as e:
            logger.error(f"Error getting referral config: {str(e)}")
            return Response(
                {
                    'error': 'Error al obtener configuración de referidos',
                    'detail': str(e)
                },
                status=status.HTTP_500_INTERNAL_SERVER_ERROR)


class ReferralStatsView(APIView):
    authentication_classes = [ClientJWTAuthentication]
    permission_classes = [AllowAny]

    def get(self, request):
        """Obtener estadísticas de referidos del cliente"""
        try:
            # Usar exactamente la misma lógica que ClientReservationsView
            authenticator = ClientJWTAuthentication()
            client, validated_token = authenticator.authenticate(request)

            if not client:
                logger.error("ReferralStatsView: Authentication failed")
                return Response({'message': 'Token inválido'}, status=401)

            # Obtener clientes referidos
            referrals = Clients.objects.filter(
                referred_by=client,
                deleted=False).annotate(reservations_count=Count(
                    'reservation', filter=Q(reservation__deleted=False)), )

            # Calcular puntos ganados por referidos
            referral_points = ClientPoints.objects.filter(
                client=client,
                transaction_type=ClientPoints.TransactionType.REFERRAL,
                deleted=False).aggregate(
                    total_points=Sum('points'))['total_points'] or 0

            # Calcular total de reservas de referidos
            referral_reservations = Reservation.objects.filter(
                client__referred_by=client, deleted=False).count()

            # Preparar datos de referidos para la respuesta
            referrals_data = []
            for referral in referrals:
                # Calcular puntos ganados específicamente por este referido
                points_from_referral = ClientPoints.objects.filter(
                    client=client,
                    referred_client=referral,
                    transaction_type=ClientPoints.TransactionType.REFERRAL,
                    deleted=False).aggregate(
                        total_points=Sum('points'))['total_points'] or 0

                referrals_data.append({
                    'id':
                    referral.id,
                    'first_name':
                    referral.first_name,
                    'last_name':
                    referral.last_name,
                    'created_at':
                    referral.created.isoformat() if hasattr(
                        referral, 'created') else None,
                    'reservations_count':
                    referral.reservations_count,
                    'points_earned':
                    float(points_from_referral)
                })

            return Response({
                'total_referrals': referrals.count(),
                'referral_reservations': referral_reservations,
                'referral_points': float(referral_points),
                'referrals': referrals_data
            })

        except Exception as e:
            logger.error(f"Error getting referral stats: {str(e)}")
            return Response(
                {
                    'error': 'Error al obtener estadísticas de referidos',
                    'detail': str(e)
                },
                status=status.HTTP_500_INTERNAL_SERVER_ERROR)


class SearchTrackingTestView(APIView):
    """Vista de prueba para debuggear tracking de búsquedas"""
    authentication_classes = [ClientJWTAuthentication]
    permission_classes = [AllowAny]

    def post(self, request):
        """Endpoint de prueba para verificar datos recibidos"""
        logger.info("SearchTrackingTestView: Test endpoint called")
        
        return Response({
            'success': True,
            'message': 'Datos recibidos correctamente',
            'data': {
                'request_method': request.method,
                'content_type': request.content_type,
                'request_data': request.data,
                'request_post': dict(request.POST),
                'request_body': request.body.decode('utf-8') if request.body else None,
                'headers': {
                    'authorization': request.META.get('HTTP_AUTHORIZATION', 'Not found'),
                    'content_type': request.META.get('CONTENT_TYPE', 'Not found'),
                }
            }
        }, status=200)


class SearchTrackingView(APIView):
    """Vista para tracking de búsquedas de clientes"""
    authentication_classes = [ClientJWTAuthentication]
    permission_classes = [AllowAny]

    def post(self, request):
        """Registrar o actualizar búsqueda del cliente"""
        logger.info("SearchTrackingView: Tracking search request")
        
        try:
            # Autenticar cliente
            authenticator = ClientJWTAuthentication()
            client, validated_token = authenticator.authenticate(request)

            if not client:
                logger.error("SearchTrackingView: Authentication failed")
                return Response({'message': 'Token inválido'}, status=401)

            # Obtener o crear registro de tracking para este cliente
            search_tracking, created = SearchTracking.objects.get_or_create(
                client=client,
                defaults={'deleted': False}
            )

            # Debug completo de los datos recibidos
            logger.info(f"SearchTrackingView: Request method: {request.method}")
            logger.info(f"SearchTrackingView: Request content type: {request.content_type}")
            logger.info(f"SearchTrackingView: Raw request.data: {request.data}")
            logger.info(f"SearchTrackingView: Raw request.POST: {request.POST}")
            logger.info(f"SearchTrackingView: Raw request.body: {request.body.decode('utf-8') if request.body else 'Empty'}")
            
            # Debug de headers
            logger.info(f"SearchTrackingView: Request headers:")
            for key, value in request.META.items():
                if key.startswith('HTTP_') or key in ['CONTENT_TYPE', 'CONTENT_LENGTH']:
                    logger.info(f"  {key}: {value}")
            
            # Obtener los datos del request
            clean_data = {}
            
            if hasattr(request, 'data') and request.data:
                logger.info(f"SearchTrackingView: Using request.data - Type: {type(request.data)}")
                if hasattr(request.data, 'dict'):
                    clean_data = dict(request.data)
                else:
                    clean_data = request.data.copy() if hasattr(request.data, 'copy') else dict(request.data)
            elif request.POST:
                logger.info(f"SearchTrackingView: Using request.POST - Type: {type(request.POST)}")
                clean_data = dict(request.POST)
            else:
                logger.error(f"SearchTrackingView: No data found in request")
                return Response({
                    'success': False,
                    'message': 'No se recibieron datos'
                }, status=400)

            logger.info(f"SearchTrackingView: Raw clean_data after extraction: {clean_data}")
            logger.info(f"SearchTrackingView: clean_data type: {type(clean_data)}")
            
            # Debug individual de cada campo recibido
            for key, value in clean_data.items():
                logger.info(f"SearchTrackingView: RAW Field '{key}' = '{value}' (type: {type(value)}, str: '{str(value)}', repr: {repr(value)})")

            # Remover campos que puedan causar conflicto
            clean_data.pop('client_id', None)
            clean_data.pop('client', None)

            logger.info(f"SearchTrackingView: After removing client fields: {clean_data}")

            # Validar que los campos requeridos estén presentes
            required_fields = ['check_in_date', 'check_out_date', 'guests']
            
            # Verificar cada campo individualmente
            for field in required_fields:
                value = clean_data.get(field)
                logger.info(f"SearchTrackingView: Field '{field}' = '{value}' (type: {type(value)}, empty: {not value})")
            
            # Verificar campos faltantes o vacíos
            missing_fields = []
            for field in required_fields:
                value = clean_data.get(field)
                if value is None or value == '' or value == 'null' or value == 'undefined':
                    missing_fields.append(field)
            
            logger.info(f"SearchTrackingView: Missing or empty fields: {missing_fields}")
            
            if missing_fields:
                logger.error(f"SearchTrackingView: Missing required fields: {missing_fields}")
                return Response({
                    'success': False,
                    'message': 'Campos requeridos faltantes o vacíos',
                    'errors': {field: f'El campo {field} es requerido y no puede estar vacío' for field in missing_fields},
                    'received_data': clean_data
                }, status=400)

            # Procesar y limpiar los datos recibidos
            processed_data = {}
            
            # Procesar check_in_date
            if 'check_in_date' in clean_data:
                raw_value = clean_data['check_in_date']
                logger.info(f"SearchTrackingView: Processing check_in_date - raw_value: '{raw_value}' (type: {type(raw_value)})")
                
                if isinstance(raw_value, list) and raw_value:
                    raw_value = raw_value[0]  # Si viene como lista, tomar el primer elemento
                    logger.info(f"SearchTrackingView: check_in_date was list, took first element: '{raw_value}'")
                
                if raw_value and str(raw_value).strip() not in ['', 'null', 'undefined', 'None']:
                    try:
                        from datetime import datetime
                        date_str = str(raw_value).strip()
                        
                        # Formato ISO (YYYY-MM-DD)
                        if '-' in date_str:
                            parsed_date = datetime.strptime(date_str, '%Y-%m-%d').date()
                        elif '/' in date_str:
                            # Formato DD/MM/YYYY
                            parsed_date = datetime.strptime(date_str, '%d/%m/%Y').date()
                        else:
                            raise ValueError(f"Formato de fecha no reconocido: {date_str}")
                        
                        processed_data['check_in_date'] = parsed_date
                        logger.info(f"SearchTrackingView: Successfully processed check_in_date: {parsed_date}")
                        
                    except Exception as e:
                        logger.error(f"SearchTrackingView: Error processing check_in_date: {str(e)}")
                        return Response({
                            'success': False,
                            'message': f'Formato de fecha inválido para check_in_date',
                            'errors': {'check_in_date': f'Formato de fecha inválido: {raw_value}'}
                        }, status=400)
            
            # Procesar check_out_date
            if 'check_out_date' in clean_data:
                raw_value = clean_data['check_out_date']
                logger.info(f"SearchTrackingView: Processing check_out_date - raw_value: '{raw_value}' (type: {type(raw_value)})")
                
                if isinstance(raw_value, list) and raw_value:
                    raw_value = raw_value[0]  # Si viene como lista, tomar el primer elemento
                    logger.info(f"SearchTrackingView: check_out_date was list, took first element: '{raw_value}'")
                
                if raw_value and str(raw_value).strip() not in ['', 'null', 'undefined', 'None']:
                    try:
                        from datetime import datetime
                        date_str = str(raw_value).strip()
                        
                        # Formato ISO (YYYY-MM-DD)
                        if '-' in date_str:
                            parsed_date = datetime.strptime(date_str, '%Y-%m-%d').date()
                        elif '/' in date_str:
                            # Formato DD/MM/YYYY
                            parsed_date = datetime.strptime(date_str, '%d/%m/%Y').date()
                        else:
                            raise ValueError(f"Formato de fecha no reconocido: {date_str}")
                        
                        processed_data['check_out_date'] = parsed_date
                        logger.info(f"SearchTrackingView: Successfully processed check_out_date: {parsed_date}")
                        
                    except Exception as e:
                        logger.error(f"SearchTrackingView: Error processing check_out_date: {str(e)}")
                        return Response({
                            'success': False,
                            'message': f'Formato de fecha inválido para check_out_date',
                            'errors': {'check_out_date': f'Formato de fecha inválido: {raw_value}'}
                        }, status=400)
            
            # Procesar guests
            if 'guests' in clean_data:
                raw_value = clean_data['guests']
                logger.info(f"SearchTrackingView: Processing guests - raw_value: '{raw_value}' (type: {type(raw_value)})")
                
                if isinstance(raw_value, list) and raw_value:
                    raw_value = raw_value[0]  # Si viene como lista, tomar el primer elemento
                    logger.info(f"SearchTrackingView: guests was list, took first element: '{raw_value}'")
                
                if raw_value and str(raw_value).strip() not in ['', 'null', 'undefined', 'None']:
                    try:
                        processed_data['guests'] = int(str(raw_value).strip())
                        logger.info(f"SearchTrackingView: Successfully processed guests: {processed_data['guests']}")
                    except (ValueError, TypeError) as e:
                        logger.error(f"SearchTrackingView: Error processing guests: {str(e)}")
                        return Response({
                            'success': False,
                            'message': 'Número de huéspedes inválido',
                            'errors': {'guests': f'El número de huéspedes debe ser un número entero válido: {raw_value}'}
                        }, status=400)
            
            # Copiar property si existe
            if 'property' in clean_data:
                processed_data['property'] = clean_data['property']
            
            logger.info(f"SearchTrackingView: Final processed_data: {processed_data}")
            
            # Usar processed_data en lugar de clean_data
            clean_data = processed_data

            logger.info(f"SearchTrackingView: Final clean_data after conversions: {clean_data}")
            
            # Validar datos antes de pasarlos al serializer
            for field in ['check_in_date', 'check_out_date', 'guests']:
                value = clean_data.get(field)
                logger.info(f"SearchTrackingView: PRE-SERIALIZER field '{field}' = '{value}' (type: {type(value)}, repr: {repr(value)}, bool: {bool(value)})")
                
                if value is None:
                    logger.error(f"SearchTrackingView: CRITICAL - Field '{field}' is None!")
                    return Response({
                        'success': False,
                        'message': f'Campo {field} no puede ser None',
                        'field_value': repr(value),
                        'field_type': str(type(value))
                    }, status=400)

            # Crear contexto para el serializer
            context = {
                'request': request,
                'client': client
            }
            
            logger.info(f"SearchTrackingView: About to create serializer with clean_data: {clean_data}")
            logger.info(f"SearchTrackingView: search_tracking instance ID: {search_tracking.id if search_tracking else 'None'}")
            
            # Actualizar con los nuevos datos
            serializer = SearchTrackingSerializer(
                search_tracking, 
                data=clean_data,
                context=context,
                partial=True
            )
            
            logger.info(f"SearchTrackingView: Serializer created successfully")
            logger.info(f"SearchTrackingView: About to call is_valid() on serializer")

            if serializer.is_valid():
                serializer.save()
                
                logger.info(
                    f"SearchTrackingView: Search tracked successfully for client {client.id} - "
                    f"Check-in: {serializer.validated_data.get('check_in_date')}, "
                    f"Check-out: {serializer.validated_data.get('check_out_date')}, "
                    f"Guests: {serializer.validated_data.get('guests')}"
                )

                return Response({
                    'success': True,
                    'message': 'Búsqueda registrada exitosamente',
                    'data': serializer.data
                }, status=200)
            
            else:
                logger.error(f"SearchTrackingView: Validation errors: {serializer.errors}")
                return Response({
                    'success': False,
                    'message': 'Error en los datos enviados',
                    'errors': serializer.errors
                }, status=400)

        except Exception as e:
            logger.error(f"SearchTrackingView: Error tracking search: {str(e)}")
            return Response({
                'success': False,
                'message': 'Error interno del servidor'
            }, status=500)

    def get(self, request):
        """Obtener última búsqueda del cliente"""
        logger.info("SearchTrackingView: Get last search request")
        
        try:
            # Autenticar cliente
            authenticator = ClientJWTAuthentication()
            auth_result = authenticator.authenticate(request)
            
            if auth_result is None:
                logger.error("SearchTrackingView: Authentication failed - no result")
                return Response({'message': 'Token inválido'}, status=401)
            
            client, validated_token = auth_result
            
            if not client:
                logger.error("SearchTrackingView: Authentication failed - no client")
                return Response({'message': 'Token inválido'}, status=401)

            # Obtener registro de tracking
            try:
                search_tracking = SearchTracking.objects.get(client=client, deleted=False)
                serializer = SearchTrackingSerializer(search_tracking)
                
                return Response({
                    'success': True,
                    'data': serializer.data
                }, status=200)
                
            except SearchTracking.DoesNotExist:
                return Response({
                    'success': True,
                    'message': 'No hay búsquedas registradas',
                    'data': None
                }, status=200)

        except Exception as e:
            logger.error(f"SearchTrackingView: Error getting search: {str(e)}")
            return Response({
                'success': False,
                'message': 'Error interno del servidor'
            }, status=500)