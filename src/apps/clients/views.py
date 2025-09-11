from rest_framework import status, permissions
from rest_framework.decorators import api_view
from rest_framework.response import Response
from rest_framework.views import APIView
from rest_framework.permissions import AllowAny
from django.db.models import Q, Sum, Count
from django.shortcuts import get_object_or_404
from datetime import datetime, timedelta
from apps.reservation.models import Reservation
from apps.reservation.serializers import ClientReservationSerializer, ReservationListSerializer, ReservationRetrieveSerializer
from .auth_views import ClientJWTAuthentication

import logging

logger = logging.getLogger(__name__)


class ClientReservationDetailView(APIView):
    """Vista para obtener el detalle de una reserva específica del cliente autenticado"""
    authentication_classes = [ClientJWTAuthentication]
    permission_classes = [AllowAny]

    def get(self, request, reservation_id):
        logger.info(f"ClientReservationDetailView: Request for reservation {reservation_id}")
        logger.info(f"ClientReservationDetailView: reservation_id type: {type(reservation_id)}, content: '{reservation_id}', is_digit: {reservation_id.isdigit()}")

        try:
            # Usar la misma lógica de autenticación que ClientProfileView
            authenticator = ClientJWTAuthentication()
            auth_result = authenticator.authenticate(request)

            if auth_result is None:
                logger.error("ClientReservationDetailView: Authentication failed - no result")
                return Response({'message': 'Token inválido'}, status=401)

            client, validated_token = auth_result  # Unpack the result

            if not client:
                logger.error("ClientReservationDetailView: Authentication failed - no client")
                return Response({'message': 'Token inválido'}, status=401)

            # Buscar la reserva por ID o UUID
            logger.info(f"ClientReservationDetailView: Searching reservation {reservation_id} for client {client.id}")
            logger.info(f"ClientReservationDetailView: Client object details - ID: {client.id}, Name: {client.first_name} {client.last_name}, Email: {client.email}")

            reservation = None

            try:
                # Intentar buscar por ID numérico primero
                if reservation_id.isdigit():
                    logger.info(f"ClientReservationDetailView: Searching by numeric ID: {reservation_id}")
                    logger.info(f"ClientReservationDetailView: Query will be: Reservation.objects.get(id={reservation_id}, client={client.id}, deleted=False)")
                    reservation = Reservation.objects.get(
                        id=reservation_id,
                        client=client,
                        deleted=False
                    )
                else:
                    # Si no es numérico, intentar múltiples formatos de UUID
                    logger.info(f"ClientReservationDetailView: Searching by UUID: {reservation_id}")

                    # Primero intentar con UUID con guiones
                    try:
                        logger.info(f"ClientReservationDetailView: Query will be: Reservation.objects.get(uuid_external='{reservation_id}', client={client.id}, deleted=False)")
                        reservation = Reservation.objects.get(
                            uuid_external=reservation_id,
                            client=client,
                            deleted=False
                        )
                        logger.info(f"ClientReservationDetailView: Found reservation by UUID with dashes")
                    except Reservation.DoesNotExist:
                        # Si no existe, intentar sin guiones
                        uuid_clean = reservation_id.replace("-", "")
                        logger.info(f"ClientReservationDetailView: Trying UUID without dashes: {uuid_clean}")
                        logger.info(f"ClientReservationDetailView: Query will be: Reservation.objects.get(uuid_external='{uuid_clean}', client={client.id}, deleted=False)")
                        reservation = Reservation.objects.get(
                            uuid_external=uuid_clean,
                            client=client,
                            deleted=False
                        )
                        logger.info(f"ClientReservationDetailView: Found reservation by UUID without dashes")

            except Reservation.DoesNotExist:
                # Debug: Buscar si la reserva existe pero no pertenece al cliente
                logger.error(f"ClientReservationDetailView: Reservation {reservation_id} not found for client {client.id}")

                # NUEVO DEBUG: Buscar la reserva por ID directamente (como se muestra en el endpoint que SÍ funciona)
                logger.error(f"ClientReservationDetailView: === BÚSQUEDA DIRECTA POR ID ===")
                direct_search = Reservation.objects.filter(id=reservation_id, deleted=False)
                logger.error(f"ClientReservationDetailView: Direct search by ID results: {direct_search.count()}")
                if direct_search.exists():
                    direct_reservation = direct_search.first()
                    logger.error(f"ClientReservationDetailView: ENCONTRADO! Reserva ID {direct_reservation.id} pertenece al cliente {direct_reservation.client_id}, esperado: {client.id}")
                    logger.error(f"ClientReservationDetailView: Status: {direct_reservation.status}, UUID: {direct_reservation.uuid_external}")

                    # Verificar si es el mismo cliente
                    if direct_reservation.client_id == client.id:
                        logger.error(f"ClientReservationDetailView: ¡ES EL MISMO CLIENTE! Hay un problema con la query original.")
                        # Intentar retornar esta reserva
                        from apps.reservation.serializers import ReservationRetrieveSerializer
                        serializer = ReservationRetrieveSerializer(direct_reservation, context={'request': request})
                        return Response({
                            'success': True,
                            'reservation': serializer.data,
                            'debug_note': 'Encontrada con búsqueda directa - revisar lógica original'
                        })

                # Verificar si la reserva existe para cualquier cliente (incluyendo deleted)
                debug_filters = Q(uuid_external=reservation_id) | Q(uuid_external=reservation_id.replace("-", ""))

                # Si es numérico, también buscar por ID
                if reservation_id.isdigit():
                    debug_filters |= Q(id=reservation_id)

                debug_reservations_all = Reservation.objects.filter(debug_filters)

                debug_reservations_active = debug_reservations_all.filter(deleted=False)

                logger.error(f"ClientReservationDetailView: Debug - Total reservations found: {debug_reservations_all.count()}")
                logger.error(f"ClientReservationDetailView: Debug - Active reservations found: {debug_reservations_active.count()}")

                if debug_reservations_all.exists():
                    for debug_reservation in debug_reservations_all:
                        logger.error(f"ClientReservationDetailView: Found reservation ID: {debug_reservation.id}, "
                                   f"UUID: {debug_reservation.uuid_external}, "
                                   f"Client: {debug_reservation.client_id if debug_reservation.client else 'None'}, "
                                   f"Client Expected: {client.id}, "
                                   f"Status: {debug_reservation.status}, "
                                   f"Deleted: {debug_reservation.deleted}")

                    if debug_reservations_active.exists():
                        debug_reservation = debug_reservations_active.first()
                        if debug_reservation.client_id == client.id:
                            logger.error(f"ClientReservationDetailView: ENCONTRADA! La reserva SÍ pertenece al cliente {client.id}. "
                                       f"Status: {debug_reservation.status}. Revisar lógica de búsqueda.")
                        else:
                            logger.error(f"ClientReservationDetailView: Reservation exists but belongs to different client. "
                                       f"Expected client: {client.id}, Found client: {debug_reservation.client_id if debug_reservation.client else 'None'}")
                    else:
                        logger.error(f"ClientReservationDetailView: Reservation exists but is deleted")
                else:
                    logger.error(f"ClientReservationDetailView: Reservation {reservation_id} does not exist in database at all")

                return Response({
                    'success': False,
                    'message': 'Reserva no encontrada'
                }, status=404)

            # Serializar la reserva con todos los detalles
            serializer = ReservationRetrieveSerializer(reservation, context={'request': request})

            logger.info(f"ClientReservationDetailView: Reservation {reservation_id} retrieved successfully")

            return Response({
                'success': True,
                'reservation': serializer.data
            })

        except Exception as e:
            logger.error(f"ClientReservationDetailView: Error getting reservation detail: {str(e)}")
            return Response({
                'success': False,
                'message': 'Error interno del servidor'
            }, status=500)


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
                        'Reserva creada exitosamente. Está pendiente de aprobación.',
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
from rest_framework.generics import CreateAPIView, ListAPIView
from django.contrib.auth.hashers import make_password, check_password
from django.utils import timezone
from datetime import datetime, timedelta
from django.db.models import Q, Sum, Count
from django.shortcuts import get_object_or_404

from .models import Clients, MensajeFidelidad, TokenApiClients, ClientPoints, ReferralPointsConfig, SearchTracking, Achievement, ClientAchievement
from .serializers import (
    ClientsSerializer, MensajeFidelidadSerializer, TokenApiClienteSerializer,
    ClientAuthVerifySerializer, ClientAuthRequestOTPSerializer,
    ClientAuthSetPasswordSerializer, ClientAuthLoginSerializer,
    ClientProfileSerializer, ClientPointsSerializer,
    ClientPointsBalanceSerializer, RedeemPointsSerializer, SearchTrackingSerializer,
    AchievementSerializer, ClientAchievementSerializer)
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


# Added helper method to get client IP address
    def get_client_ip(self, request):
        """Obtener IP real del cliente"""
        x_forwarded_for = request.META.get('HTTP_X_FORWARDED_FOR')
        if x_forwarded_for:
            ip = x_forwarded_for.split(',')[0]
        else:
            ip = request.META.get('REMOTE_ADDR')
        return ip


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


class GoogleSheetsDebugView(APIView):
    """Vista específica para debuggear el envío a Google Sheets"""
    permission_classes = [AllowAny]

    def post(self, request):
        """Debuggear envío a Google Sheets con datos de prueba"""
        logger.info("GoogleSheetsDebugView: === INICIO DEBUG GOOGLE SHEETS ===")

        try:
            # Crear datos de prueba
            test_data = [
                {
                    'id': 'debug-test-001',
                    'search_timestamp': '2025-09-01T20:15:00.000000+00:00',
                    'check_in_date': '2025-09-15',
                    'check_out_date': '2025-09-17',
                    'guests': 4,
                    'client_info': {
                        'id': 'client-123',
                        'first_name': 'Test',
                        'last_name': 'User',
                        'email': 'test@example.com',
                        'tel_number': '+51999888777'
                    },
                    'property_info': {
                        'id': 'prop-456',
                        'name': 'Test Property'
                    },
                    'technical_data': {
                        'ip_address': '192.168.1.1',
                        'session_key': 'test-session',
                        'user_agent': 'Mozilla/5.0 Test Browser',
                        'referrer': 'https://test.com'
                    },
                    'created': '2025-09-01T20:14:50.000000+00:00'
                },
                {
                    'id': 'debug-test-002',
                    'search_timestamp': '2025-09-01T20:16:00.000000+00:00',
                    'check_in_date': '2025-09-20',
                    'check_out_date': '2025-09-22',
                    'guests': 2,
                    'client_info': {
                        'id': 'client-789',
                        'first_name': 'Another',
                        'last_name': 'Test',
                        'email': 'another@example.com',
                        'tel_number': '+51888777666'
                    },
                    'property_info': {
                        'id': 'prop-101',
                        'name': 'Another Test Property'
                    },
                    'technical_data': {
                        'ip_address': '192.168.1.2',
                        'session_key': 'test-session-2',
                        'user_agent': 'Mozilla/5.0 Another Test Browser',
                        'referrer': 'https://another-test.com'
                    },
                    'created': '2025-09-01T20:15:50.000000+00:00'
                }
            ]

            logger.info(f"GoogleSheetsDebugView: Datos de prueba creados: {len(test_data)} registros")

            # Usar el mismo método de envío que SearchTrackingExportView
            export_view = SearchTrackingExportView()
            result = export_view.send_to_google_sheets(test_data)

            logger.info(f"GoogleSheetsDebugView: Resultado del envío: {result}")

            return Response({
                'success': True,
                'message': 'Debug de Google Sheets completado',
                'test_data_sent': test_data,
                'google_sheets_result': result
            })

        except Exception as e:
            logger.error(f"GoogleSheetsDebugView: Error: {str(e)}")
            import traceback
            logger.error(f"GoogleSheetsDebugView: Traceback: {traceback.format_exc()}")
            return Response({
                'success': False,
                'message': 'Error en debug de Google Sheets',
                'error': str(e)
            }, status=500)


class SearchTrackingView(APIView):
    """Vista para tracking de búsquedas de clientes - Versión simplificada para debug"""
    authentication_classes = [ClientJWTAuthentication]
    permission_classes = [AllowAny]

    def post(self, request):
        """Registrar o actualizar búsqueda del cliente"""
        logger.info("SearchTrackingView: === INICIO DEBUG ===")

        try:
            # Autenticar cliente
            authenticator = ClientJWTAuthentication()
            client, validated_token = authenticator.authenticate(request)

            if not client:
                logger.error("SearchTrackingView: Authentication failed")
                return Response({'message': 'Token inválido'}, status=401)

            logger.info(f"SearchTrackingView: Cliente autenticado: {client.id}")

            # Log de lo que recibe Django
            logger.info(f"SearchTrackingView: === DATOS RECIBIDOS ===")
            logger.info(f"SearchTrackingView: request.method = {request.method}")
            logger.info(f"SearchTrackingView: request.content_type = {request.content_type}")
            logger.info(f"SearchTrackingView: request.data = {request.data}")
            logger.info(f"SearchTrackingView: type(request.data) = {type(request.data)}")

            # Extraer y procesar datos PRIMERO
            raw_data = request.data
            logger.info(f"SearchTrackingView: === PROCESANDO DATOS ===")
            logger.info(f"SearchTrackingView: raw_data = {raw_data}")

            # Procesar check_in_date
            check_in_date = None
            if 'check_in_date' in raw_data and raw_data['check_in_date']:
                check_in_str = raw_data['check_in_date']
                logger.info(f"SearchTrackingView: Procesando check_in_date: {check_in_str}")
                check_in_date = datetime.strptime(check_in_str, '%Y-%m-%d').date()
                logger.info(f"SearchTrackingView: check_in_date procesado: {check_in_date}")

            # Procesar check_out_date
            check_out_date = None
            if 'check_out_date' in raw_data and raw_data['check_out_date']:
                check_out_str = raw_data['check_out_date']
                logger.info(f"SearchTrackingView: Procesando check_out_date: {check_out_str}")
                check_out_date = datetime.strptime(check_out_str, '%Y-%m-%d').date()
                logger.info(f"SearchTrackingView: check_out_date procesado: {check_out_date}")

            # Procesar guests
            guests = None
            if 'guests' in raw_data and raw_data['guests'] is not None:
                guests = int(raw_data['guests'])
                logger.info(f"SearchTrackingView: guests procesado: {guests}")

            # Procesar property (opcional)
            property_obj = None
            if 'property' in raw_data and raw_data['property']:
                from apps.property.models import Property
                try:
                    property_obj = Property.objects.get(id=raw_data['property'])
                    logger.info(f"SearchTrackingView: property procesado: {property_obj}")
                except Property.DoesNotExist:
                    logger.warning(f"SearchTrackingView: Property con ID {raw_data['property']} no encontrada")

            # Ahora intentar obtener o crear el registro con los datos ya procesados
            logger.info(f"SearchTrackingView: === CREANDO/ACTUALIZANDO CON DATOS PROCESADOS ===")
            logger.info(f"SearchTrackingView: check_in_date = {check_in_date}")
            logger.info(f"SearchTrackingView: check_out_date = {check_out_date}")
            logger.info(f"SearchTrackingView: guests = {guests}")

            # Verificar que tenemos los datos requeridos
            if not check_in_date:
                raise ValueError("check_in_date es requerido")
            if not check_out_date:
                raise ValueError("check_out_date es requerido")
            if guests is None:
                raise ValueError("guests es requerido")

            # Intentar actualizar si existe, o crear nuevo
            try:
                search_tracking = SearchTracking.objects.get(client=client, deleted=False)
                logger.info(f"SearchTrackingView: Actualizando registro existente: {search_tracking.id}")
                # Actualizar con nuevos datos
                search_tracking.check_in_date = check_in_date
                search_tracking.check_out_date = check_out_date
                search_tracking.guests = guests
                search_tracking.property = property_obj
                search_tracking.search_timestamp = timezone.now()
                search_tracking.save()
                created = False
            except SearchTracking.DoesNotExist:
                logger.info(f"SearchTrackingView: Creando nuevo registro")
                # Crear nuevo registro
                search_tracking = SearchTracking.objects.create(
                    client=client,
                    check_in_date=check_in_date,
                    check_out_date=check_out_date,
                    guests=guests,
                    property=property_obj,
                    search_timestamp=timezone.now(),
                    deleted=False
                )
                created = True

            logger.info(f"SearchTrackingView: ¡ÉXITO! Búsqueda guardada correctamente (created: {created})")

            # Serializar respuesta
            serializer = SearchTrackingSerializer(search_tracking)

            return Response({
                'success': True,
                'message': 'Búsqueda registrada exitosamente',
                'data': serializer.data
            }, status=200)

        except ValueError as ve:
            logger.error(f"SearchTrackingView: Error de valor al procesar datos: {str(ve)}")
            return Response({
                'success': False,
                'message': 'Error en formato de datos',
                'errors': str(ve)
            }, status=400)

        except Exception as e:
            logger.error(f"SearchTrackingView: Error al actualizar directamente: {str(e)}")
            return Response({
                'success': False,
                'message': 'Error al guardar búsqueda',
                'errors': str(e)
            }, status=500)

        except Exception as e:
            logger.error(f"SearchTrackingView: EXCEPCIÓN: {str(e)}")
            import traceback
            logger.error(f"SearchTrackingView: TRACEBACK: {traceback.format_exc()}")
            return Response({
                'success': False,
                'message': 'Error interno del servidor'
            }, status=500)

    def get(self, request):
        """Obtener última búsqueda del cliente"""
        logger.info("SearchTrackingView: Get last search request")

        try:
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


class PublicAchievementsListView(APIView):
    """Vista pública para obtener todos los logros disponibles"""
    permission_classes = [AllowAny]

    def get(self, request):
        """Obtener lista de todos los logros disponibles"""
        logger.info("PublicAchievementsListView: Request for public achievements")
        try:
            # Obtener todos los logros activos y no eliminados, ordenados
            achievements = Achievement.objects.filter(
                is_active=True,
                deleted=False
            ).order_by('order', 'required_reservations', 'required_referrals')

            # Serializar los datos
            serializer = AchievementSerializer(achievements, many=True)

            logger.info(f"PublicAchievementsListView: Found {achievements.count()} achievements.")
            return Response({
                'success': True,
                'data': {
                    'total_achievements': achievements.count(),
                    'achievements': serializer.data
                }
            })

        except Exception as e:
            logger.error(f"PublicAchievementsListView: Error getting achievements: {str(e)}")
            return Response({
                'success': False,
                'message': 'Error interno del servidor'
            }, status=500)


class ClientAchievementsView(APIView):
    """Vista para obtener logros del cliente autenticado"""
    authentication_classes = [ClientJWTAuthentication]
    permission_classes = [AllowAny]

    def get(self, request):
        """Obtener logros del cliente y verificar si se han ganado nuevos"""
        logger.info("ClientAchievementsView: Request for client achievements")

        try:
            # Autenticar cliente
            authenticator = ClientJWTAuthentication()
            auth_result = authenticator.authenticate(request)

            if auth_result is None:
                logger.error("ClientAchievementsView: Authentication failed - no result")
                return Response({'message': 'Token inválido'}, status=401)

            client, validated_token = auth_result

            if not client:
                logger.error("ClientAchievementsView: Authentication failed - no client")
                return Response({'message': 'Token inválido'}, status=401)

            logger.info(f"ClientAchievementsView: Client authenticated - ID: {client.id}")

            from apps.reservation.models import Reservation

            # Obtener logros ya ganados por el cliente
            client_achievements = ClientAchievement.objects.filter(
                client=client,
                deleted=False
            ).select_related('achievement').order_by('-earned_at')

            # Obtener todos los logros disponibles y activos para comparación
            all_achievements = Achievement.objects.filter(
                is_active=True,
                deleted=False
            ).order_by('order', 'required_reservations')

            # Calcular estadísticas relevantes del cliente
            client_reservations = Reservation.objects.filter(
                client=client,
                deleted=False,
                status='approved' # Solo considerar reservas aprobadas
            ).count()

            client_referrals = Clients.objects.filter(
                referred_by=client,
                deleted=False
            ).count()

            referral_reservations = Reservation.objects.filter(
                client__referred_by=client, # Reservas hechas por referidos
                deleted=False,
                status='approved'
            ).count()

            # Verificar si el cliente ha ganado nuevos logros
            newly_earned_achievements = []
            earned_achievement_ids = set(client_achievements.values_list('achievement_id', flat=True))

            for achievement in all_achievements:
                if achievement.id not in earned_achievement_ids:
                    # Verificar si el cliente cumple los requisitos para este logro
                    if achievement.check_client_qualifies(client, client_reservations, client_referrals, referral_reservations):
                        # Otorgar el nuevo logro
                        try:
                            new_client_achievement = ClientAchievement.objects.create(
                                client=client,
                                achievement=achievement,
                                earned_at=timezone.now() # Registrar cuándo se ganó
                            )
                            newly_earned_achievements.append(new_client_achievement)
                            logger.info(f"ClientAchievementsView: Nuevo logro otorgado: '{achievement.name}' a {client.first_name} (ID: {client.id})")
                        except Exception as e:
                            logger.error(f"ClientAchievementsView: Error al otorgar logro '{achievement.name}': {str(e)}")

            # Si se ganaron nuevos logros, recargar la lista de logros ganados
            if newly_earned_achievements:
                client_achievements = ClientAchievement.objects.filter(
                    client=client,
                    deleted=False
                ).select_related('achievement').order_by('-earned_at')
                earned_achievement_ids = set(client_achievements.values_list('achievement_id', flat=True)) # Actualizar IDs ganados

            # Determinar logros disponibles (aún no ganados)
            available_achievements = all_achievements.exclude(id__in=earned_achievement_ids)

            # Serializar los datos
            achievements_serializer = ClientAchievementSerializer(client_achievements, many=True)
            available_serializer = AchievementSerializer(available_achievements, many=True)

            logger.info(f"ClientAchievementsView: Logros del cliente {client.id}: {len(client_achievements)} ganados, {len(available_achievements)} disponibles.")
            return Response({
                'success': True,
                'data': {
                    'total_achievements': all_achievements.count(),
                    'earned_achievements': achievements_serializer.data,
                    'available_achievements': available_serializer.data,
                    'new_achievements_count': len(newly_earned_achievements),
                    'client_stats': { # Estadísticas para contexto de logros
                        'reservations': client_reservations,
                        'referrals': client_referrals,
                        'referral_reservations': referral_reservations
                    }
                }
            })

        except Exception as e:
            logger.error(f"ClientAchievementsView: Error getting client achievements: {str(e)}")
            import traceback
            logger.error(f"ClientAchievementsView: TRACEBACK: {traceback.format_exc()}")
            return Response({
                'success': False,
                'message': 'Error interno del servidor'
            }, status=500)


class BotClientProfileView(APIView):
    """Vista para bot - obtener perfil completo del cliente sin autenticación"""
    permission_classes = [AllowAny]
    authentication_classes = []

    def get(self, request, tel_number):
        logger.info(f"BotClientProfileView: Request for tel_number {tel_number}")

        try:
            # Buscar cliente por número de teléfono o documento de identidad
            client = Clients.objects.filter(
                Q(tel_number=tel_number) | Q(number_doc=tel_number),
                deleted=False
            ).first()

            if not client:
                logger.warning(f"BotClientProfileView: Client not found for identifier {tel_number}")
                return Response({
                    'success': False,
                    'message': 'Cliente no encontrado'
                }, status=404)

            logger.info(f"BotClientProfileView: Client found - ID: {client.id}, Name: {client.first_name}")

            # Obtener reservas futuras y pasadas aprobadas
            from datetime import date
            today = date.today()

            upcoming_reservations = Reservation.objects.filter(
                client=client,
                deleted=False,
                check_out_date__gte=today,  # Incluye reservas que terminan hoy o después
                status='approved'
            ).order_by('check_in_date')

            past_reservations = Reservation.objects.filter(
                client=client,
                deleted=False,
                check_out_date__lt=today,  # Reservas que ya terminaron
                status='approved'
            ).order_by('-check_in_date')  # Más recientes primero

            # Obtener nivel más alto (logro más importante)
            highest_achievement = None
            earned_achievements = ClientAchievement.objects.filter(
                client=client,
                deleted=False
            ).select_related('achievement').order_by(
                '-achievement__required_reservations',
                '-achievement__required_referrals',
                '-achievement__required_referral_reservations'
            )

            if earned_achievements.exists():
                highest_achievement_obj = earned_achievements.first()
                icon = highest_achievement_obj.achievement.icon or ""
                name = highest_achievement_obj.achievement.name
                name_with_icon = f"{icon} {name}" if icon else name

                highest_achievement = {
                    'name_icono': name_with_icon,
                    'description': highest_achievement_obj.achievement.description,
                    'earned_at': highest_achievement_obj.earned_at.isoformat()
                }

            # Serializar reservas futuras
            upcoming_reservations_data = []
            if upcoming_reservations.exists():
                for reservation in upcoming_reservations:
                    upcoming_reservations_data.append({
                        'id': reservation.id,
                        'property_name': reservation.property.name if reservation.property else 'Sin propiedad',
                        'check_in_date': reservation.check_in_date.isoformat(),
                        'check_out_date': reservation.check_out_date.isoformat(),
                        'guests': reservation.guests,
                        'nights': (reservation.check_out_date - reservation.check_in_date).days,
                        'price_sol': float(reservation.price_sol) if reservation.price_sol else 0,
                        'status': reservation.get_status_display() if hasattr(reservation, 'get_status_display') else reservation.status,
                        'payment_full': reservation.full_payment,
                        'temperature_pool': reservation.temperature_pool
                    })

            # Serializar reservas pasadas
            # Solo indicar si tiene reservas pasadas
            has_past_reservations = past_reservations.exists()

            # Preparar respuesta
            response_data = {
                'success': True,
                'client_profile': {
                    'id': client.id,
                    'first_name': client.first_name,
                    'last_name': client.last_name or '',
                    'full_name': f"{client.first_name} {client.last_name or ''}".strip(),
                    'email': client.email,
                    'tel_number': client.tel_number,
                    'document_type': client.get_document_type_display(),
                    'number_doc': client.number_doc,
                    'birth_date': client.date.isoformat() if client.date else None,
                    'available_points': client.get_available_points(),
                    'points_balance': float(client.points_balance),
                    'referral_code': client.get_referral_code(),
                    'highest_level': highest_achievement,
                    'upcoming_reservations': upcoming_reservations_data,
                    'has_past_reservations': has_past_reservations
                }
            }

            logger.info(f"BotClientProfileView: Profile data retrieved successfully for {client.first_name}")
            return Response(response_data)

        except Exception as e:
            logger.error(f"BotClientProfileView: Error getting client profile: {str(e)}")
            return Response({
                'success': False,
                'message': 'Error interno del servidor'
            }, status=500)


# Configuración de serializers y paginación importados al principio del archivo.


# Added helper method to get client IP address
    def get_client_ip(self, request):
        """Obtener IP real del cliente"""
        x_forwarded_for = request.META.get('HTTP_X_FORWARDED_FOR')
        if x_forwarded_for:
            ip = x_forwarded_for.split(',')[0]
        else:
            ip = request.META.get('REMOTE_ADDR')
        return ip


class ClientProfileView(APIView):
    """Vista para el perfil del cliente autenticado"""
    authentication_classes = [ClientJWTAuthentication]
    permission_classes = [AllowAny]

    def get(self, request):
        logger.info(f"ClientProfileView: Request received")

        try:
            authenticator = ClientJWTAuthentication()
            auth_result = authenticator.authenticate(request)

            if auth_result is None:
                logger.error("ClientProfileView: Authentication failed - no result")
                return Response({'message': 'Token inválido'}, status=401)

            client, validated_token = auth_result

            if not client:
                logger.error("ClientProfileView: Authentication failed - no client")
                return Response({'message': 'Token inválido'}, status=401)

            logger.info(f"ClientProfileView: Client authenticated - ID: {client.id}, Name: {client.first_name} {client.last_name}")

            # Obtener el logro más alto del cliente
            highest_achievement = None
            earned_achievements = ClientAchievement.objects.filter(
                client=client,
                deleted=False
            ).select_related('achievement').order_by(
                '-achievement__required_reservations',
                '-achievement__required_referrals',
                '-achievement__required_referral_reservations'
            )

            if earned_achievements.exists():
                highest_achievement_obj = earned_achievements.first()
                icon = highest_achievement_obj.achievement.icon or ""
                name = highest_achievement_obj.achievement.name
                name_with_icon = f"{icon} {name}" if icon else name

                highest_achievement = {
                    'name_icono': name_with_icon,
                    'description': highest_achievement_obj.achievement.description,
                    'earned_at': highest_achievement_obj.earned_at.isoformat()
                }

            # Serializar el perfil del cliente
            serializer = ClientProfileSerializer(client, context={'request': request})
            profile_data = serializer.data

            # Agregar información de logros al perfil
            profile_data['highest_level'] = highest_achievement

            # Agregar información de puntos disponibles
            profile_data['available_points'] = client.get_available_points()
            profile_data['points_balance'] = float(client.points_balance)

            # Obtener reservas futuras para el cliente
            from datetime import date
            today = date.today()
            upcoming_reservations = Reservation.objects.filter(
                client=client,
                deleted=False,
                check_out_date__gte=today,
                status='approved'
            ).order_by('check_in_date')

            upcoming_reservations_data = []
            if upcoming_reservations.exists():
                for res in upcoming_reservations:
                    upcoming_reservations_data.append({
                        'id': res.id,
                        'property_name': res.property.name if res.property else 'Sin propiedad',
                        'check_in_date': res.check_in_date.isoformat(),
                        'check_out_date': res.check_out_date.isoformat(),
                        'guests': res.guests,
                        'nights': (res.check_out_date - res.check_in_date).days,
                        'status': res.get_status_display() if hasattr(res, 'get_status_display') else res.status,
                        'payment_full': res.full_payment,
                        'temperature_pool': res.temperature_pool
                    })
            profile_data['upcoming_reservations'] = upcoming_reservations_data

            # Obtener última búsqueda del cliente (si existe)
            search_tracking = SearchTracking.objects.filter(
                client=client,
                deleted=False
            ).order_by('-search_timestamp').first()

            if search_tracking:
                search_serializer = SearchTrackingSerializer(search_tracking)
                profile_data['last_search'] = search_serializer.data
            else:
                profile_data['last_search'] = None
                logger.info(f"ClientProfileView: No hay búsquedas registradas para el cliente {client.id}")

            logger.info(f"ClientProfileView: Perfil del cliente {client.id} recuperado con éxito")

            return Response({
                'success': True,
                'client_profile': profile_data
            })

        except Exception as e:
            logger.error(f"ClientProfileView: Error getting client profile: {str(e)}")
            import traceback
            logger.error(f"ClientProfileView: TRACEBACK: {traceback.format_exc()}")
            return Response({
                'success': False,
                'message': 'Error interno del servidor'
            }, status=500)

    def post(self, request):
        """Actualizar perfil del cliente"""
        logger.info(f"ClientProfileView: Update profile request")

        try:
            authenticator = ClientJWTAuthentication()
            client, validated_token = authenticator.authenticate(request)

            if not client:
                logger.error("ClientProfileView: Authentication failed")
                return Response({'message': 'Token inválido'}, status=401)

            logger.info(f"ClientProfileView: Client authenticated - ID: {client.id}")

            # Usar serializer para validar y actualizar datos
            serializer = ClientProfileSerializer(client, data=request.data, partial=True, context={'request': request})

            if serializer.is_valid():
                serializer.save()
                logger.info(f"ClientProfileView: Profile updated successfully for client {client.id}")

                # Generar auditoría de la actualización
                generate_audit(client, client, "update", "Perfil del cliente actualizado")

                # Retornar datos actualizados
                updated_profile_data = serializer.data
                updated_profile_data['available_points'] = client.get_available_points()
                updated_profile_data['points_balance'] = float(client.points_balance)

                return Response({
                    'success': True,
                    'message': 'Perfil actualizado correctamente',
                    'client_profile': updated_profile_data
                })
            else:
                logger.error(f"ClientProfileView: Validation errors: {serializer.errors}")
                return Response({
                    'success': False,
                    'message': 'Error en los datos enviados',
                    'errors': serializer.errors
                }, status=400)

        except Exception as e:
            logger.error(f"ClientProfileView: Error updating profile: {str(e)}")
            import traceback
            logger.error(f"ClientProfileView: TRACEBACK: {traceback.format_exc()}")
            return Response({
                'success': False,
                'message': 'Error interno del servidor'
            }, status=500)


class ClientAuthRequestOTPView(APIView):
    """Vista para solicitar código OTP para verificación de email/teléfono"""
    permission_classes = [AllowAny]
    authentication_classes = []

    def post(self, request):
        logger.info("ClientAuthRequestOTPView: Request OTP received")

        try:
            email = request.data.get('email')
            phone_number = request.data.get('phone_number')

            if not email and not phone_number:
                return Response({
                    'success': False,
                    'message': 'Debe proporcionar un email o un número de teléfono.'
                }, status=400)

            client = None
            if email:
                client = Clients.objects.filter(email=email, deleted=False).first()
                if not client:
                    return Response({
                        'success': False,
                        'message': 'Cliente no encontrado con este email.'
                    }, status=404)
            elif phone_number:
                client = Clients.objects.filter(tel_number=phone_number, deleted=False).first()
                if not client:
                    return Response({
                        'success': False,
                        'message': 'Cliente no encontrado con este número de teléfono.'
                    }, status=404)

            # Generar y enviar OTP
            otp_code = client.generate_otp()
            logger.info(f"ClientAuthRequestOTPView: OTP generated for client {client.id}: {otp_code}")

            # Enviar OTP por SMS o Email según corresponda
            if client.tel_number and client.tel_number.startswith('+'): # Asumir que el número tiene código de país y es para SMS
                message = f"Tu código de verificación es: {otp_code}"
                send_sms(client.tel_number, message)
                logger.info(f"ClientAuthRequestOTPView: OTP enviado por SMS a {client.tel_number}")
            elif client.email:
                # Aquí iría la lógica para enviar el email con el OTP
                # Por ahora, solo registramos que se enviaría
                logger.info(f"ClientAuthRequestOTPView: Se enviaría OTP por email a {client.email}")
                # Ejemplo de envío de email (requiere configuración de Django email backend)
                # from django.core.mail import send_mail
                # subject = 'Tu código de verificación'
                # message_body = f'Hola {client.first_name},\n\nTu código de verificación es: {otp_code}\n\nGracias.'
                # from_email = 'your_email@example.com'
                # recipient_list = [client.email]
                # send_mail(subject, message_body, from_email, recipient_list, fail_silently=False)

            return Response({
                'success': True,
                'message': 'Código de verificación enviado exitosamente.'
            })

        except Exception as e:
            logger.error(f"ClientAuthRequestOTPView: Error requesting OTP: {str(e)}")
            return Response({
                'success': False,
                'message': 'Error interno del servidor'
            }, status=500)


class ClientAuthVerifyOTPView(APIView):
    """Vista para verificar el código OTP y generar token JWT"""
    permission_classes = [AllowAny]
    authentication_classes = []

    def post(self, request):
        logger.info("ClientAuthVerifyOTPView: Verify OTP received")

        try:
            email = request.data.get('email')
            phone_number = request.data.get('phone_number')
            otp_code = request.data.get('otp_code')

            if not email and not phone_number:
                return Response({
                    'success': False,
                    'message': 'Debe proporcionar un email o un número de teléfono.'
                }, status=400)

            if not otp_code:
                return Response({
                    'success': False,
                    'message': 'Debe proporcionar el código de verificación (OTP).'
                }, status=400)

            client = None
            if email:
                client = Clients.objects.filter(email=email, deleted=False).first()
            elif phone_number:
                client = Clients.objects.filter(tel_number=phone_number, deleted=False).first()

            if not client:
                return Response({
                    'success': False,
                    'message': 'Cliente no encontrado.'
                }, status=404)

            # Verificar OTP
            if client.verify_otp(otp_code):
                logger.info(f"ClientAuthVerifyOTPView: OTP verified successfully for client {client.id}")

                # Generar token JWT
                from .utils import generate_jwt_token
                token = generate_jwt_token(client)

                # Guardar el token para el cliente (opcional, pero útil para revocación)
                # TokenApiClients.objects.create(client=client, key=token) # Requiere modelo TokenApiClients

                return Response({
                    'success': True,
                    'message': 'Verificación exitosa. Token generado.',
                    'token': token,
                    'client_id': client.id
                })
            else:
                logger.warning(f"ClientAuthVerifyOTPView: Invalid OTP for client {client.id}")
                return Response({
                    'success': False,
                    'message': 'Código de verificación inválido.'
                }, status=400)

        except Exception as e:
            logger.error(f"ClientAuthVerifyOTPView: Error verifying OTP: {str(e)}")
            return Response({
                'success': False,
                'message': 'Error interno del servidor'
            }, status=500)


class ClientAuthLoginView(APIView):
    """Vista para login de clientes (email/teléfono y contraseña)"""
    permission_classes = [AllowAny]
    authentication_classes = []

    def post(self, request):
        logger.info("ClientAuthLoginView: Login request received")

        try:
            email = request.data.get('email')
            phone_number = request.data.get('phone_number')
            password = request.data.get('password')

            if not (email or phone_number) or not password:
                return Response({
                    'success': False,
                    'message': 'Por favor, proporcione email/número de teléfono y contraseña.'
                }, status=400)

            client = None
            if email:
                client = Clients.objects.filter(email=email, deleted=False).first()
            elif phone_number:
                client = Clients.objects.filter(tel_number=phone_number, deleted=False).first()

            if not client:
                logger.warning("ClientAuthLoginView: Client not found")
                return Response({
                    'success': False,
                    'message': 'Credenciales inválidas.'
                }, status=401)

            # Verificar contraseña
            if client.check_password(password): # Asume que el modelo Client tiene un método check_password o usa make_password/check_password de Django
                logger.info(f"ClientAuthLoginView: Login successful for client {client.id}")

                # Generar token JWT
                from .utils import generate_jwt_token
                token = generate_jwt_token(client)

                return Response({
                    'success': True,
                    'message': 'Inicio de sesión exitoso.',
                    'token': token,
                    'client_id': client.id
                })
            else:
                logger.warning(f"ClientAuthLoginView: Invalid password for client {client.id}")
                return Response({
                    'success': False,
                    'message': 'Credenciales inválidas.'
                }, status=401)

        except Exception as e:
            logger.error(f"ClientAuthLoginView: Error during login: {str(e)}")
            return Response({
                'success': False,
                'message': 'Error interno del servidor'
            }, status=500)


class ClientAuthSetPasswordView(APIView):
    """Vista para establecer contraseña (generalmente después de verificación OTP)"""
    permission_classes = [AllowAny]
    authentication_classes = []

    def post(self, request):
        logger.info("ClientAuthSetPasswordView: Set password request received")

        try:
            email = request.data.get('email')
            phone_number = request.data.get('phone_number')
            new_password = request.data.get('new_password')
            otp_code = request.data.get('otp_code') # Asumimos que OTP también se envía para seguridad

            if not (email or phone_number) or not new_password or not otp_code:
                return Response({
                    'success': False,
                    'message': 'Por favor, proporcione email/número de teléfono, nueva contraseña y código OTP.'
                }, status=400)

            client = None
            if email:
                client = Clients.objects.filter(email=email, deleted=False).first()
            elif phone_number:
                client = Clients.objects.filter(tel_number=phone_number, deleted=False).first()

            if not client:
                logger.warning("ClientAuthSetPasswordView: Client not found")
                return Response({
                    'success': False,
                    'message': 'Cliente no encontrado.'
                }, status=404)

            # Verificar OTP primero
            if not client.verify_otp(otp_code):
                logger.warning(f"ClientAuthSetPasswordView: Invalid OTP for client {client.id}")
                return Response({
                    'success': False,
                    'message': 'Código de verificación inválido.'
                }, status=400)

            # Establecer nueva contraseña
            client.set_password(new_password) # Asume que el modelo Client tiene un método set_password
            client.save()
            logger.info(f"ClientAuthSetPasswordView: Password reset successfully for client {client.id}")

            # Opcional: Invalidar OTP después de su uso
            client.otp_code = None
            client.otp_expiry = None
            client.save()

            return Response({
                'success': True,
                'message': 'Contraseña actualizada correctamente.'
            })

        except Exception as e:
            logger.error(f"ClientAuthSetPasswordView: Error setting password: {str(e)}")
            return Response({
                'success': False,
                'message': 'Error interno del servidor'
            }, status=500)


class ClientPointsView(APIView):
    """Vista para gestionar puntos de fidelidad del cliente"""
    authentication_classes = [ClientJWTAuthentication]
    permission_classes = [AllowAny]

    def get(self, request):
        """Obtener saldo de puntos del cliente"""
        logger.info("ClientPointsView: Get points request")

        try:
            authenticator = ClientJWTAuthentication()
            client, validated_token = authenticator.authenticate(request)

            if not client:
                logger.error("ClientPointsView: Authentication failed")
                return Response({'message': 'Token inválido'}, status=401)

            logger.info(f"ClientPointsView: Client authenticated - ID: {client.id}")

            # Obtener serializer para el balance de puntos
            serializer = ClientPointsBalanceSerializer(client)

            return Response({
                'success': True,
                'data': serializer.data
            })

        except Exception as e:
            logger.error(f"ClientPointsView: Error getting points balance: {str(e)}")
            return Response({
                'success': False,
                'message': 'Error interno del servidor'
            }, status=500)

    def post(self, request):
        """Redimir puntos de fidelidad"""
        logger.info("ClientPointsView: Redeem points request")

        try:
            authenticator = ClientJWTAuthentication()
            client, validated_token = authenticator.authenticate(request)

            if not client:
                logger.error("ClientPointsView: Authentication failed")
                return Response({'message': 'Token inválido'}, status=401)

            logger.info(f"ClientPointsView: Client authenticated - ID: {client.id}")

            serializer = RedeemPointsSerializer(data=request.data, context={'client': client})

            if serializer.is_valid():
                # El serializer se encarga de la lógica de redención (descontar puntos, crear registro, etc.)
                result = serializer.save() # save() debería retornar el resultado de la redención

                if result and result.get('success'):
                    logger.info(f"ClientPointsView: Points redeemed successfully for client {client.id}")
                    return Response({
                        'success': True,
                        'message': result.get('message', 'Puntos redimidos exitosamente.'),
                        'new_balance': result.get('new_balance')
                    })
                else:
                    logger.warning(f"ClientPointsView: Failed to redeem points for client {client.id}. Reason: {result.get('message')}")
                    return Response({
                        'success': False,
                        'message': result.get('message', 'No se pudieron redimir los puntos.')
                    }, status=400)
            else:
                logger.error(f"ClientPointsView: Validation errors for redeem points: {serializer.errors}")
                return Response({
                    'success': False,
                    'message': 'Error en los datos de redención',
                    'errors': serializer.errors
                }, status=400)

        except Exception as e:
            logger.error(f"ClientPointsView: Error redeeming points: {str(e)}")
            return Response({
                'success': False,
                'message': 'Error interno del servidor'
            }, status=500)


class ClientPointsHistoryView(APIView):
    """Vista para obtener el historial de transacciones de puntos de fidelidad del cliente"""
    authentication_classes = [ClientJWTAuthentication]
    permission_classes = [AllowAny]

    def get(self, request):
        logger.info("ClientPointsHistoryView: Get points history request")

        try:
            authenticator = ClientJWTAuthentication()
            client, validated_token = authenticator.authenticate(request)

            if not client:
                logger.error("ClientPointsHistoryView: Authentication failed")
                return Response({'message': 'Token inválido'}, status=401)

            logger.info(f"ClientPointsHistoryView: Client authenticated - ID: {client.id}")

            # Obtener transacciones de puntos del cliente
            points_history = ClientPoints.objects.filter(
                client=client,
                deleted=False
            ).order_by('-created_at') # Ordenar por fecha de creación descendente

            # Serializar el historial
            serializer = ClientPointsSerializer(points_history, many=True)

            return Response({
                'success': True,
                'data': {
                    'points_history': serializer.data,
                    'total_transactions': points_history.count()
                }
            })

        except Exception as e:
            logger.error(f"ClientPointsHistoryView: Error getting points history: {str(e)}")
            return Response({
                'success': False,
                'message': 'Error interno del servidor'
            }, status=500)


# Vistas relacionadas con SearchTracking (ajustadas para permitir clientes null si es necesario)

class SearchTrackingTestView(APIView):
    """Vista de prueba para debuggear tracking de búsquedas"""
    authentication_classes = [ClientJWTAuthentication]
    permission_classes = [AllowAny]

    def post(self, request):
        """Endpoint de prueba para verificar datos recibidos"""
        logger.info("SearchTrackingTestView: Test endpoint called")

        # Aquí se podría simular la lógica de SearchTrackingView para probarla
        # Por ahora, solo retornamos la información recibida

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


class SearchTrackingExportView(APIView):
    """Vista para exportar datos de tracking de búsquedas en formato JSON y enviar a Google Sheets"""
    permission_classes = [AllowAny]

    def send_to_google_sheets(self, data):
        """Enviar datos a Google Sheets usando Google Apps Script webhook"""
        import requests
        from django.conf import settings

        # URL del webhook de Google Apps Script
        GOOGLE_SCRIPT_WEBHOOK = getattr(settings, 'GOOGLE_SCRIPT_WEBHOOK', None)

        if not GOOGLE_SCRIPT_WEBHOOK:
            logger.warning("SearchTrackingExportView: GOOGLE_SCRIPT_WEBHOOK no configurado")
            return {'success': False, 'message': 'Webhook no configurado'}

        try:
            # Validar que tenemos datos
            if not data:
                return {'success': False, 'message': 'No hay datos para enviar'}

            # Enviar todos los datos en una sola request como array
            payload = {
                'action': 'insert_search_tracking',
                'data': data,
                'timestamp': timezone.now().isoformat()
            }

            response = requests.post(
                GOOGLE_SCRIPT_WEBHOOK,
                json=payload,
                headers={'Content-Type': 'application/json'},
                timeout=60
            )

            if response.status_code == 200:
                try:
                    response_data = response.json()

                    if response_data.get('success'):
                        logger.info(f"SearchTrackingExportView: {len(data)} registros enviados exitosamente a Google Sheets")
                        return {
                            'success': True,
                            'successful_sends': len(data),
                            'failed_sends': 0,
                            'total_records': len(data),
                            'google_response': response_data
                        }
                    else:
                        logger.error(f"SearchTrackingExportView: Google Apps Script retornó error: {response_data.get('message', 'Error desconocido')}")
                        return {
                            'success': False,
                            'message': response_data.get('message', 'Error desde Google Apps Script')
                        }
                except ValueError:
                    # Si la respuesta no es JSON válido
                    return {
                        'success': True,
                        'successful_sends': len(data),
                        'failed_sends': 0,
                        'total_records': len(data),
                        'message': 'Datos enviados, respuesta no es JSON válido'
                    }
            else:
                logger.error(f"SearchTrackingExportView: Error HTTP {response.status_code}")
                return {
                    'success': False,
                    'message': f'Error HTTP {response.status_code}'
                }

        except requests.exceptions.Timeout:
            logger.error("SearchTrackingExportView: Timeout enviando a Google Sheets")
            return {'success': False, 'message': 'Timeout al enviar datos'}
        except Exception as e:
            logger.error(f"SearchTrackingExportView: Error enviando a Google Sheets: {str(e)}")
            return {'success': False, 'message': str(e)}

    def get(self, request):
        """Exportar todos los datos de SearchTracking en formato JSON y opcionalmente enviar a Google Sheets"""
        try:
            # Obtener todos los registros de SearchTracking no eliminados
            search_tracking_queryset = SearchTracking.objects.filter(
                deleted=False
            ).select_related('client', 'property').order_by('-search_timestamp')

            # Filtros opcionales
            client_id = request.GET.get('client_id')
            date_from = request.GET.get('date_from')
            date_to = request.GET.get('date_to')
            property_id = request.GET.get('property_id')

            if client_id:
                search_tracking_queryset = search_tracking_queryset.filter(client_id=client_id)

            if date_from:
                try:
                    from datetime import datetime
                    date_from_parsed = datetime.strptime(date_from, '%Y-%m-%d').date()
                    search_tracking_queryset = search_tracking_queryset.filter(search_timestamp__date__gte=date_from_parsed)
                except ValueError:
                    pass

            if date_to:
                try:
                    from datetime import datetime
                    date_to_parsed = datetime.strptime(date_to, '%Y-%m-%d').date()
                    search_tracking_queryset = search_tracking_queryset.filter(search_timestamp__date__lte=date_to_parsed)
                except ValueError:
                    pass

            if property_id:
                search_tracking_queryset = search_tracking_queryset.filter(property_id=property_id)

            # Preparar datos para exportación
            export_data = []
            for tracking in search_tracking_queryset:
                data = {
                    'id': str(tracking.id),
                    'search_timestamp': tracking.search_timestamp.isoformat() if tracking.search_timestamp else None,
                    'check_in_date': tracking.check_in_date.strftime('%Y-%m-%d') if tracking.check_in_date else None,
                    'check_out_date': tracking.check_out_date.strftime('%Y-%m-%d') if tracking.check_out_date else None,
                    'guests': tracking.guests,
                    'client_info': {
                        'id': str(tracking.client.id) if tracking.client else 'ANONIMO',
                        'first_name': tracking.client.first_name if tracking.client else 'Usuario',
                        'last_name': tracking.client.last_name if tracking.client else 'Anónimo',
                        'email': tracking.client.email if tracking.client else 'anonimo@casaaustin.pe',
                        'tel_number': tracking.client.tel_number if tracking.client else 'Sin teléfono',
                    } if tracking.client else {
                        'id': 'ANONIMO',
                        'first_name': 'Usuario',
                        'last_name': 'Anónimo',
                        'email': 'anonimo@casaaustin.pe',
                        'tel_number': 'Sin teléfono',
                    },
                    'property_info': {
                        'id': str(tracking.property.id) if tracking.property else 'SIN_PROPIEDAD',
                        'name': tracking.property.name if tracking.property else 'Búsqueda general',
                    } if tracking.property else {
                        'id': 'SIN_PROPIEDAD',
                        'name': 'Búsqueda general',
                    },
                    'technical_data': {
                        'ip_address': str(tracking.ip_address) if tracking.ip_address else None,
                        'session_key': str(tracking.session_key) if tracking.session_key else None,
                        'user_agent': str(tracking.user_agent) if tracking.user_agent else None,
                        'referrer': str(tracking.referrer) if tracking.referrer else None,
                    },
                    'created': tracking.created.strftime('%Y-%m-%d') if hasattr(tracking, 'created') and tracking.created else None,
                }

                export_data.append(data)

            # Preparar respuesta con metadatos
            response_data = {
                'success': True,
                'metadata': {
                    'total_records': len(export_data),
                    'export_timestamp': timezone.now().isoformat(),
                    'filters_applied': {
                        'client_id': client_id,
                        'date_from': date_from,
                        'date_to': date_to,
                        'property_id': property_id,
                    },
                    'fields': [
                        'id', 'search_timestamp', 'check_in_date', 'check_out_date',
                        'guests', 'client_info', 'property_info', 'technical_data', 'created'
                    ]
                },
                'data': export_data
            }

            # Verificar si se debe enviar a Google Sheets
            send_to_sheets = request.GET.get('send_to_sheets', 'false').lower() == 'true'
            google_sheets_result = None

            if send_to_sheets:
                google_sheets_result = self.send_to_google_sheets(export_data)
                response_data['google_sheets_sync'] = google_sheets_result

            logger.info(f"SearchTrackingExportView: Exported {len(export_data)} search tracking records")
            return Response(response_data)

        except Exception as e:
            logger.error(f"SearchTrackingExportView: Error exporting data: {str(e)}")
            return Response({
                'success': False,
                'message': 'Error al exportar datos de tracking'
            }, status=500)


class SearchTrackingView(APIView):
    """Vista para tracking de búsquedas de clientes"""
    authentication_classes = [ClientJWTAuthentication]
    permission_classes = [AllowAny]

    def get_client_ip(self, request):
        """Obtener IP real del cliente"""
        x_forwarded_for = request.META.get('HTTP_X_FORWARDED_FOR')
        if x_forwarded_for:
            ip = x_forwarded_for.split(',')[0].strip()
        else:
            ip = request.META.get('REMOTE_ADDR')
        return ip

    def post(self, request):
        """Registrar o actualizar búsqueda del cliente"""
        logger.info("SearchTrackingView: === INICIO === ")

        try:
            # Autenticar cliente
            authenticator = ClientJWTAuthentication()
            auth_result = authenticator.authenticate(request)

            client = None
            if auth_result:
                client, validated_token = auth_result
                logger.info(f"SearchTrackingView: Cliente autenticado: {client.id if client else 'Anónimo'}")
            else:
                # Permitir búsquedas anónimas si el cliente no está autenticado
                logger.info("SearchTrackingView: Cliente no autenticado. Procesando como anónimo.")
                # Aquí se podría usar la IP para identificar al usuario anónimo si fuera necesario
                client_ip = self.get_client_ip(request)
                logger.info(f"SearchTrackingView: IP del cliente anónimo: {client_ip}")


            # Log de lo que recibe Django
            logger.info(f"SearchTrackingView: === DATOS RECIBIDOS ===")
            logger.info(f"SearchTrackingView: request.method = {request.method}")
            logger.info(f"SearchTrackingView: request.content_type = {request.content_type}")
            logger.info(f"SearchTrackingView: request.data = {request.data}")
            logger.info(f"SearchTrackingView: type(request.data) = {type(request.data)}")

            # Extraer y procesar datos
            raw_data = request.data
            logger.info(f"SearchTrackingView: === PROCESANDO DATOS ===")
            logger.info(f"SearchTrackingView: raw_data = {raw_data}")

            # Procesar fechas y número de huéspedes
            check_in_date = None
            check_out_date = None
            guests = None
            property_obj = None # Asumiendo que 'property' en raw_data es un ID

            try:
                from datetime import datetime
                from django.utils import timezone

                if 'check_in_date' in raw_data and raw_data['check_in_date']:
                    check_in_str = raw_data['check_in_date']
                    logger.info(f"SearchTrackingView: Procesando check_in_date: {check_in_str}")
                    # Intentar varios formatos de fecha si es necesario, o definir uno estricto
                    check_in_date = datetime.strptime(check_in_str, '%Y-%m-%d').date()
                    logger.info(f"SearchTrackingView: check_in_date procesado: {check_in_date}")

                if 'check_out_date' in raw_data and raw_data['check_out_date']:
                    check_out_str = raw_data['check_out_date']
                    logger.info(f"SearchTrackingView: Procesando check_out_date: {check_out_str}")
                    check_out_date = datetime.strptime(check_out_str, '%Y-%m-%d').date()
                    logger.info(f"SearchTrackingView: check_out_date procesado: {check_out_date}")

                if 'guests' in raw_data and raw_data['guests'] is not None:
                    guests = int(raw_data['guests'])
                    logger.info(f"SearchTrackingView: guests procesado: {guests}")

                if 'property' in raw_data and raw_data['property']:
                    from apps.property.models import Property
                    try:
                        property_obj = Property.objects.get(id=raw_data['property'])
                        logger.info(f"SearchTrackingView: property procesado: {property_obj.id if property_obj else 'None'}")
                    except Property.DoesNotExist:
                        logger.warning(f"SearchTrackingView: Property con ID {raw_data['property']} no encontrada")
                    except ValueError:
                         logger.warning(f"SearchTrackingView: Formato de ID de propiedad inválido: {raw_data['property']}")


                # Validaciones básicas requeridas para guardar el tracking
                if not check_in_date:
                    raise ValueError("check_in_date es requerido.")
                if not check_out_date:
                    raise ValueError("check_out_date es requerido.")
                if guests is None: # guests puede ser 0, pero no None
                    raise ValueError("guests es requerido.")

            except ValueError as ve:
                logger.error(f"SearchTrackingView: Error en formato de datos: {str(ve)}")
                return Response({
                    'success': False,
                    'message': 'Error en formato de datos',
                    'errors': str(ve)
                }, status=400)
            except Exception as e:
                 logger.error(f"SearchTrackingView: Error procesando datos: {str(e)}")
                 return Response({
                    'success': False,
                    'message': 'Error al procesar datos de búsqueda',
                    'errors': str(e)
                }, status=500)


            # Obtener datos adicionales del request
            ip_address = self.get_client_ip(request)
            session_key = request.session.session_key if hasattr(request, 'session') and request.session.session_key else None
            user_agent = request.META.get('HTTP_USER_AGENT', '')[:500]  # Limitar longitud
            referrer = request.META.get('HTTP_REFERER', '')

            logger.info(f"SearchTrackingView: Datos adicionales capturados - IP: {ip_address}, Session: {session_key}")

            # Guardar registro de SearchTracking (siempre crear nuevo)
            search_tracking = SearchTracking.objects.create(
                client=client,  # Puede ser None para usuarios anónimos
                check_in_date=check_in_date,
                check_out_date=check_out_date,
                guests=guests,
                property=property_obj,
                search_timestamp=timezone.now(),
                ip_address=ip_address,
                session_key=session_key,
                user_agent=user_agent,
                referrer=referrer,
                deleted=False
            )

            if client:
                logger.info(f"SearchTrackingView: Nuevo registro creado para cliente {client.id}: {search_tracking.id}")
            else:
                logger.info(f"SearchTrackingView: Nuevo registro anónimo creado: {search_tracking.id} para IP {ip_address}")

            # Serializar la respuesta
            serializer = SearchTrackingSerializer(search_tracking)

            return Response({
                'success': True,
                'message': 'Búsqueda registrada exitosamente',
                'data': serializer.data
            }, status=200)

        except Exception as e:
            logger.error(f"SearchTrackingView: Error al guardar/actualizar SearchTracking: {str(e)}")
            return Response({
                'success': False,
                'message': 'Error al guardar la búsqueda',
                'errors': str(e)
            }, status=500)

    def get(self, request):
        """Obtener última búsqueda del cliente autenticado"""
        logger.info("SearchTrackingView: Get last search request")

        try:
            authenticator = ClientJWTAuthentication()
            auth_result = authenticator.authenticate(request)

            if auth_result is None:
                logger.error("SearchTrackingView: Authentication failed - no result")
                return Response({'message': 'Token inválido'}, status=401)

            client, validated_token = auth_result

            if not client:
                logger.error("SearchTrackingView: Authentication failed - no client")
                return Response({'message': 'Token inválido'}, status=401)

            # Obtener la búsqueda más reciente del cliente
            try:
                search_tracking = SearchTracking.objects.filter(
                    client=client,
                    deleted=False
                ).order_by('-search_timestamp').first()

                if search_tracking:
                    serializer = SearchTrackingSerializer(search_tracking)
                    logger.info(f"SearchTrackingView: Última búsqueda para cliente {client.id} encontrada.")
                    return Response({
                        'success': True,
                        'data': serializer.data
                    }, status=200)
                else:
                    logger.info(f"SearchTrackingView: No hay búsquedas registradas para el cliente {client.id}")
                    return Response({
                        'success': True,
                        'message': 'No hay búsquedas registradas',
                        'data': None
                    }, status=200)

            except Exception as get_error:
                logger.error(f"SearchTrackingView: Error obteniendo búsqueda: {str(get_error)}")
                return Response({
                    'success': False,
                    'message': 'Error interno del servidor'
                }, status=500)

        except Exception as e:
            logger.error(f"SearchTrackingView: Error getting search: {str(e)}")
            return Response({
                'success': False,
                'message': 'Error interno del servidor'
            }, status=500)


class PublicAchievementsListView(APIView):
    """Vista pública para obtener todos los logros disponibles"""
    permission_classes = [AllowAny]

    def get(self, request):
        """Obtener lista de todos los logros disponibles"""
        logger.info("PublicAchievementsListView: Request for public achievements")
        try:
            # Obtener todos los logros activos y no eliminados, ordenados
            achievements = Achievement.objects.filter(
                is_active=True,
                deleted=False
            ).order_by('order', 'required_reservations', 'required_referrals')

            # Serializar los datos
            serializer = AchievementSerializer(achievements, many=True)

            logger.info(f"PublicAchievementsListView: Found {achievements.count()} achievements.")
            return Response({
                'success': True,
                'data': {
                    'total_achievements': achievements.count(),
                    'achievements': serializer.data
                }
            })

        except Exception as e:
            logger.error(f"PublicAchievementsListView: Error getting achievements: {str(e)}")
            return Response({
                'success': False,
                'message': 'Error interno del servidor'
            }, status=500)


class ClientAchievementsView(APIView):
    """Vista para obtener logros del cliente autenticado"""
    authentication_classes = [ClientJWTAuthentication]
    permission_classes = [AllowAny]

    def get(self, request):
        """Obtener logros del cliente y verificar si se han ganado nuevos"""
        logger.info("ClientAchievementsView: Request for client achievements")

        try:
            # Autenticar cliente
            authenticator = ClientJWTAuthentication()
            auth_result = authenticator.authenticate(request)

            if auth_result is None:
                logger.error("ClientAchievementsView: Authentication failed - no result")
                return Response({'message': 'Token inválido'}, status=401)

            client, validated_token = auth_result

            if not client:
                logger.error("ClientAchievementsView: Authentication failed - no client")
                return Response({'message': 'Token inválido'}, status=401)

            logger.info(f"ClientAchievementsView: Client authenticated - ID: {client.id}")

            from apps.reservation.models import Reservation

            # Obtener logros ya ganados por el cliente
            client_achievements = ClientAchievement.objects.filter(
                client=client,
                deleted=False
            ).select_related('achievement').order_by('-earned_at')

            # Obtener todos los logros disponibles y activos para comparación
            all_achievements = Achievement.objects.filter(
                is_active=True,
                deleted=False
            ).order_by('order', 'required_reservations')

            # Calcular estadísticas relevantes del cliente
            client_reservations = Reservation.objects.filter(
                client=client,
                deleted=False,
                status='approved' # Solo considerar reservas aprobadas
            ).count()

            client_referrals = Clients.objects.filter(
                referred_by=client,
                deleted=False
            ).count()

            referral_reservations = Reservation.objects.filter(
                client__referred_by=client, # Reservas hechas por referidos
                deleted=False,
                status='approved'
            ).count()

            # Verificar si el cliente ha ganado nuevos logros
            newly_earned_achievements = []
            earned_achievement_ids = set(client_achievements.values_list('achievement_id', flat=True))

            for achievement in all_achievements:
                if achievement.id not in earned_achievement_ids:
                    # Verificar si el cliente cumple los requisitos para este logro
                    if achievement.check_client_qualifies(client, client_reservations, client_referrals, referral_reservations):
                        # Otorgar el nuevo logro
                        try:
                            new_client_achievement = ClientAchievement.objects.create(
                                client=client,
                                achievement=achievement,
                                earned_at=timezone.now() # Registrar cuándo se ganó
                            )
                            newly_earned_achievements.append(new_client_achievement)
                            logger.info(f"ClientAchievementsView: Nuevo logro otorgado: '{achievement.name}' a {client.first_name} (ID: {client.id})")
                        except Exception as e:
                            logger.error(f"ClientAchievementsView: Error al otorgar logro '{achievement.name}': {str(e)}")

            # Si se ganaron nuevos logros, recargar la lista de logros ganados
            if newly_earned_achievements:
                client_achievements = ClientAchievement.objects.filter(
                    client=client,
                    deleted=False
                ).select_related('achievement').order_by('-earned_at')
                earned_achievement_ids = set(client_achievements.values_list('achievement_id', flat=True)) # Actualizar IDs ganados

            # Determinar logros disponibles (aún no ganados)
            available_achievements = all_achievements.exclude(id__in=earned_achievement_ids)

            # Serializar los datos
            achievements_serializer = ClientAchievementSerializer(client_achievements, many=True)
            available_serializer = AchievementSerializer(available_achievements, many=True)

            logger.info(f"ClientAchievementsView: Logros del cliente {client.id}: {len(client_achievements)} ganados, {len(available_achievements)} disponibles.")
            return Response({
                'success': True,
                'data': {
                    'total_achievements': all_achievements.count(),
                    'earned_achievements': achievements_serializer.data,
                    'available_achievements': available_serializer.data,
                    'new_achievements_count': len(newly_earned_achievements),
                    'client_stats': { # Estadísticas para contexto de logros
                        'reservations': client_reservations,
                        'referrals': client_referrals,
                        'referral_reservations': referral_reservations
                    }
                }
            })

        except Exception as e:
            logger.error(f"ClientAchievementsView: Error getting client achievements: {str(e)}")
            import traceback
            logger.error(f"ClientAchievementsView: TRACEBACK: {traceback.format_exc()}")
            return Response({
                'success': False,
                'message': 'Error interno del servidor'
            }, status=500)


class BotClientProfileView(APIView):
    """Vista para bot - obtener perfil completo del cliente sin autenticación"""
    permission_classes = [AllowAny]
    authentication_classes = []

    def get(self, request, tel_number):
        logger.info(f"BotClientProfileView: Request for tel_number {tel_number}")

        try:
            # Buscar cliente por número de teléfono o documento de identidad
            client = Clients.objects.filter(
                Q(tel_number=tel_number) | Q(number_doc=tel_number),
                deleted=False
            ).first()

            if not client:
                logger.warning(f"BotClientProfileView: Client not found for identifier {tel_number}")
                return Response({
                    'success': False,
                    'message': 'Cliente no encontrado'
                }, status=404)

            logger.info(f"BotClientProfileView: Client found - ID: {client.id}, Name: {client.first_name}")

            # Obtener reservas futuras y pasadas aprobadas
            from datetime import date
            today = date.today()

            upcoming_reservations = Reservation.objects.filter(
                client=client,
                deleted=False,
                check_out_date__gte=today,  # Incluye reservas que terminan hoy o después
                status='approved'
            ).order_by('check_in_date')

            past_reservations = Reservation.objects.filter(
                client=client,
                deleted=False,
                check_out_date__lt=today,  # Reservas que ya terminaron
                status='approved'
            ).order_by('-check_in_date')  # Más recientes primero

            # Obtener nivel más alto (logro más importante)
            highest_achievement = None
            earned_achievements = ClientAchievement.objects.filter(
                client=client,
                deleted=False
            ).select_related('achievement').order_by(
                '-achievement__required_reservations',
                '-achievement__required_referrals',
                '-achievement__required_referral_reservations'
            )

            if earned_achievements.exists():
                highest_achievement_obj = earned_achievements.first()
                icon = highest_achievement_obj.achievement.icon or ""
                name = highest_achievement_obj.achievement.name
                name_with_icon = f"{icon} {name}" if icon else name

                highest_achievement = {
                    'name_icono': name_with_icon,
                    'description': highest_achievement_obj.achievement.description,
                    'earned_at': highest_achievement_obj.earned_at.isoformat()
                }

            # Serializar reservas futuras
            upcoming_reservations_data = []
            if upcoming_reservations.exists():
                for reservation in upcoming_reservations:
                    upcoming_reservations_data.append({
                        'id': reservation.id,
                        'property_name': reservation.property.name if reservation.property else 'Sin propiedad',
                        'check_in_date': reservation.check_in_date.isoformat(),
                        'check_out_date': reservation.check_out_date.isoformat(),
                        'guests': reservation.guests,
                        'nights': (reservation.check_out_date - reservation.check_in_date).days,
                        'price_sol': float(reservation.price_sol) if reservation.price_sol else 0,
                        'status': reservation.get_status_display() if hasattr(reservation, 'get_status_display') else reservation.status,
                        'payment_full': reservation.full_payment,
                        'temperature_pool': reservation.temperature_pool
                    })

            # Serializar reservas pasadas
            # Solo indicar si tiene reservas pasadas
            has_past_reservations = past_reservations.exists()

            # Preparar respuesta
            response_data = {
                'success': True,
                'client_profile': {
                    'id': client.id,
                    'first_name': client.first_name,
                    'last_name': client.last_name or '',
                    'full_name': f"{client.first_name} {client.last_name or ''}".strip(),
                    'email': client.email,
                    'tel_number': client.tel_number,
                    'document_type': client.get_document_type_display(),
                    'number_doc': client.number_doc,
                    'birth_date': client.date.isoformat() if client.date else None,
                    'available_points': client.get_available_points(),
                    'points_balance': float(client.points_balance),
                    'referral_code': client.get_referral_code(),
                    'highest_level': highest_achievement,
                    'upcoming_reservations': upcoming_reservations_data,
                    'has_past_reservations': has_past_reservations
                }
            }

            logger.info(f"BotClientProfileView: Profile data retrieved successfully for {client.first_name}")
            return Response(response_data)

        except Exception as e:
            logger.error(f"BotClientProfileView: Error getting client profile: {str(e)}")
            return Response({
                'success': False,
                'message': 'Error interno del servidor'
            }, status=500)


# Configuración de serializers y paginación importados al principio del archivo.