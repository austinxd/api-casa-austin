from rest_framework import status, permissions
from rest_framework.decorators import api_view
from rest_framework.response import Response
from rest_framework.views import APIView
from rest_framework.permissions import AllowAny, IsAuthenticated
from django.db.models import Q, Sum, Count, Max, F, Value
from django.db.models.functions import Coalesce
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

            # Verificar si el cliente tiene reservas pendientes de completar
            from apps.reservation.models import Reservation
            pending_statuses = ['incomplete', 'pending', 'under_review']
            existing_pending = Reservation.objects.filter(
                client=client,
                status__in=pending_statuses,
                deleted=False
            ).first()

            if existing_pending:
                # Determinar mensaje según el estado
                status_messages = {
                    'incomplete': 'pendiente de subir comprobante de pago',
                    'pending': 'pendiente de aprobación',
                    'under_review': 'en revisión'
                }
                status_text = status_messages.get(existing_pending.status, 'en proceso')

                logger.warning(
                    f"ClientCreateReservationView: Client {client.id} already has a {existing_pending.status} reservation (ID: {existing_pending.id})"
                )
                return Response({
                    'success': False,
                    'message': f'Ya tienes una reserva {status_text}. Debes completarla o esperar su resolución antes de crear otra.',
                    'existing_reservation_id': str(existing_pending.id),
                    'existing_reservation_status': existing_pending.status
                }, status=400)

            # Crear serializer con contexto
            serializer = ClientReservationSerializer(
                data=request.data, context={'request': request})

            if serializer.is_valid():
                try:
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
                except serializers.ValidationError as ve:
                    # Capturar errores de validación lanzados durante save() (ej: códigos de descuento)
                    logger.error(
                        f"ClientCreateReservationView: Validation error during save: {str(ve)}"
                    )
                    # Extraer el mensaje de error
                    error_message = str(ve)
                    if hasattr(ve, 'detail'):
                        if isinstance(ve.detail, dict):
                            error_message = next(iter(ve.detail.values()))[0] if ve.detail else str(ve)
                        elif isinstance(ve.detail, list):
                            error_message = ve.detail[0] if ve.detail else str(ve)
                    
                    return Response(
                        {
                            'success': False,
                            'message': error_message
                        },
                        status=400)
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

        except serializers.ValidationError as ve:
            # Capturar ValidationError que pueda venir de autenticación u otros lugares
            logger.error(
                f"ClientCreateReservationView: Validation error: {str(ve)}"
            )
            return Response(
                {
                    'success': False,
                    'message': str(ve)
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
from django.db.models import Q, Sum, Count, Max, F, Value
from django.db.models.functions import Coalesce
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
    permission_classes = [IsAuthenticated]
    filter_backends = [filters.SearchFilter, filters.OrderingFilter]
    search_fields = [
        "email", "number_doc", "first_name", "last_name", "tel_number"
    ]
    ordering_fields = ['points_balance', 'first_name', 'last_name', 'created', 'level']
    ordering = ['-points_balance']
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
            OpenApiParameter(
                "ordering",
                OpenApiTypes.STR,
                description=
                "Ordenar por: points_balance, level, first_name, last_name, created. Usar '-' para orden descendente. Ejemplo: -points_balance o -level",
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
        from apps.clients.models import ClientAchievement
        
        queryset = Clients.objects.exclude(deleted=True).annotate(
            level=Coalesce(Max('achievements__achievement__required_reservations'), Value(-1))
        ).order_by("last_name", "first_name")

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

            # Solo indicar si tiene reservas pasadas
            has_past_reservations = past_reservations.exists()

            # Obtener campo is_password_set directamente
            is_password_set = client.is_password_set
            logger.info(f"BotClientProfileView: Client {client.id} - is_password_set: {is_password_set}")

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
                    'has_past_reservations': has_past_reservations,
                    'is_password_set': is_password_set
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


class ReferralRankingView(APIView):
    """Vista para obtener el ranking mensual de referidos"""
    authentication_classes = [ClientJWTAuthentication]
    permission_classes = [AllowAny]

    def get(self, request):
        """Obtiene el ranking histórico global o de un mes específico"""
        from django.utils import timezone
        from .serializers import ReferralRankingListSerializer, ClientReferralRankingSerializer
        from .models import ReferralRanking
        from django.db.models import Sum, Count
        
        try:
            # Parámetros opcionales
            year = request.GET.get('year')
            month = request.GET.get('month')
            limit = int(request.GET.get('limit', 10))
            
            # Si se especifican parámetros, devolver ranking de mes específico
            if year and month:
                target_year = int(year)
                target_month = int(month)
                
                rankings = ReferralRanking.get_month_ranking(target_year, target_month, limit)
                
                months = {
                    1: "Enero", 2: "Febrero", 3: "Marzo", 4: "Abril",
                    5: "Mayo", 6: "Junio", 7: "Julio", 8: "Agosto",
                    9: "Septiembre", 10: "Octubre", 11: "Noviembre", 12: "Diciembre"
                }
                
                response_data = {
                    'type': 'monthly',
                    'ranking_period': f"{months.get(target_month, target_month)} {target_year}",
                    'year': target_year,
                    'month': target_month,
                    'total_participants': rankings.count(),
                    'rankings': ClientReferralRankingSerializer(rankings, many=True).data
                }
            
            else:
                # Sin parámetros: devolver ranking histórico global
                from django.db.models import Sum, Count, Max
                from collections import defaultdict
                
                # Obtener todos los rankings históricos y agrupar por cliente
                all_rankings = ReferralRanking.objects.filter(deleted=False).select_related('client')
                
                # Agrupar stats por cliente (totales históricos)
                client_totals = defaultdict(lambda: {
                    'client': None,
                    'total_referral_reservations': 0,
                    'total_referral_revenue': 0,
                    'total_new_referrals': 0,
                    'total_points_earned': 0,
                    'months_active': set(),
                    'best_position': 999
                })
                
                for ranking in all_rankings:
                    client_id = ranking.client.id
                    client_totals[client_id]['client'] = ranking.client
                    client_totals[client_id]['total_referral_reservations'] += ranking.referral_reservations_count
                    client_totals[client_id]['total_referral_revenue'] += ranking.total_referral_revenue
                    client_totals[client_id]['total_new_referrals'] += ranking.referrals_made_count
                    client_totals[client_id]['total_points_earned'] += ranking.points_earned
                    client_totals[client_id]['months_active'].add(f"{ranking.year}-{ranking.month:02d}")
                    if ranking.position < client_totals[client_id]['best_position']:
                        client_totals[client_id]['best_position'] = ranking.position
                
                # Convertir a lista - incluir todos los que han hecho referidos (aunque no tengan reservas)
                global_rankings = []
                for client_id, totals in client_totals.items():
                    if totals['client'] and totals['total_new_referrals'] > 0:  # Cambiar criterio: que hayan hecho referidos
                        global_rankings.append({
                            'client': totals['client'],
                            'total_referral_reservations': totals['total_referral_reservations'],
                            'total_referral_revenue': totals['total_referral_revenue'],
                            'total_new_referrals': totals['total_new_referrals'],
                            'total_points_earned': totals['total_points_earned'],
                            'months_active': len(totals['months_active']),
                            'best_position': totals['best_position'] if totals['best_position'] < 999 else None
                        })
                
                # Ordenar por: 1) reservas de referidos, 2) cantidad de referidos hechos
                global_rankings.sort(key=lambda x: (x['total_referral_reservations'], x['total_new_referrals']), reverse=True)
                
                # Asignar posiciones globales
                for i, ranking in enumerate(global_rankings[:limit]):
                    ranking['global_position'] = i + 1
                
                # Serializar para respuesta
                rankings_data = []
                for ranking in global_rankings[:limit]:
                    rankings_data.append({
                        'global_position': ranking['global_position'],
                        'client_id': ranking['client'].id,
                        'client_name': f"{ranking['client'].first_name} {ranking['client'].last_name or ''}".strip(),
                        'total_referral_reservations': ranking['total_referral_reservations'],
                        'total_referral_revenue': ranking['total_referral_revenue'],
                        'total_new_referrals': ranking['total_new_referrals'],
                        'total_points_earned': ranking['total_points_earned'],
                        'months_active': ranking['months_active'],
                        'best_monthly_position': ranking['best_position']
                    })
                
                response_data = {
                    'type': 'global_historical',
                    'ranking_period': 'Ranking Histórico Global',
                    'total_participants': len(global_rankings),
                    'showing': min(limit, len(global_rankings)),
                    'rankings': rankings_data
                }
            
            return Response(response_data)
            
        except Exception as e:
            logger.error(f"ReferralRankingView: Error getting ranking: {str(e)}")
            return Response({
                'error': 'Error obteniendo el ranking de referidos'
            }, status=500)


class CurrentReferralRankingView(APIView):
    """Vista para obtener el ranking del mes actual"""
    authentication_classes = [ClientJWTAuthentication] 
    permission_classes = [AllowAny]

    def get(self, request):
        """Obtiene el ranking del mes actual"""
        from django.utils import timezone
        from .serializers import ReferralRankingListSerializer, ClientReferralRankingSerializer
        from .models import ReferralRanking
        
        try:
            limit = int(request.GET.get('limit', 10))
            
            # Obtener ranking del mes actual
            rankings = ReferralRanking.get_current_month_ranking(limit)
            
            # Preparar respuesta
            now = timezone.now()
            months = {
                1: "Enero", 2: "Febrero", 3: "Marzo", 4: "Abril",
                5: "Mayo", 6: "Junio", 7: "Julio", 8: "Agosto", 
                9: "Septiembre", 10: "Octubre", 11: "Noviembre", 12: "Diciembre"
            }
            
            response_data = {
                'type': 'current_month',
                'ranking_period': f"{months.get(now.month, now.month)} {now.year}",
                'year': now.year,
                'month': now.month,
                'total_participants': rankings.count(),
                'rankings': ClientReferralRankingSerializer(rankings, many=True).data
            }
            
            return Response(response_data)
            
        except Exception as e:
            logger.error(f"CurrentReferralRankingView: Error getting current ranking: {str(e)}")
            return Response({
                'error': 'Error obteniendo el ranking actual de referidos'
            }, status=500)


class ClientReferralStatsView(APIView):
    """Vista para obtener estadísticas de referidos del cliente autenticado"""
    authentication_classes = [ClientJWTAuthentication]
    permission_classes = [AllowAny]

    def get(self, request):
        """Obtiene estadísticas de referidos del cliente autenticado"""
        try:
            # Autenticar cliente
            authenticator = ClientJWTAuthentication()
            auth_result = authenticator.authenticate(request)

            if auth_result is None:
                return Response({'message': 'Token inválido'}, status=401)

            client, validated_token = auth_result

            if not client:
                return Response({'message': 'Token inválido'}, status=401)

            # Obtener parámetros
            year = request.GET.get('year')
            month = request.GET.get('month')
            
            # Si no se especifica año/mes, usar mes actual
            from django.utils import timezone
            now = timezone.now()
            target_year = int(year) if year else now.year
            target_month = int(month) if month else now.month
            
            # Obtener estadísticas del cliente para el mes
            stats = client.get_referral_stats(target_year, target_month)
            
            # Obtener posición en el ranking si existe
            from .models import ReferralRanking
            ranking_entry = ReferralRanking.objects.filter(
                client=client,
                year=target_year,
                month=target_month,
                deleted=False
            ).first()
            
            # Agregar información de ranking
            stats['ranking_position'] = ranking_entry.position if ranking_entry else None
            stats['is_in_ranking'] = ranking_entry is not None
            stats['year'] = target_year
            stats['month'] = target_month
            
            months = {
                1: "Enero", 2: "Febrero", 3: "Marzo", 4: "Abril",
                5: "Mayo", 6: "Junio", 7: "Julio", 8: "Agosto",
                9: "Septiembre", 10: "Octubre", 11: "Noviembre", 12: "Diciembre"
            }
            stats['period_display'] = f"{months.get(target_month, target_month)} {target_year}"
            
            return Response(stats)
            
        except Exception as e:
            logger.error(f"ClientReferralStatsView: Error getting client stats: {str(e)}")
            return Response({
                'error': 'Error obteniendo estadísticas de referidos'
            }, status=500)


class PublicReferralStatsView(APIView):
    """
    Vista pública unificada para estadísticas de referidos con filtros
    
    Parámetros de URL:
    - scope: 'all' (default) o 'with_reservations'
    - order_by: 'total_referrals' (default) o 'referrals_with_reservations'
    - limit: número de resultados en top_rankings (default: 10)
    - client_id: UUID del cliente para ver detalles de sus referidos
    """
    authentication_classes = []
    permission_classes = [AllowAny]

    def get(self, request):
        """Obtiene estadísticas de referidos con filtros configurables"""
        try:
            from django.db.models import Count, Q, Sum
            from apps.reservation.models import Reservation
            from .models import Clients
            
            # Leer parámetros de filtrado
            client_id = request.GET.get('client_id')
            scope = request.GET.get('scope', 'all')  # 'all' o 'with_reservations'
            order_by = request.GET.get('order_by', 'total_referrals')  # 'total_referrals' o 'referrals_with_reservations'
            try:
                limit = int(request.GET.get('limit', 10))
            except ValueError:
                limit = 10
            
            # Si se solicita detalle de un cliente específico
            if client_id:
                try:
                    client = Clients.objects.get(id=client_id, deleted=False)
                except Clients.DoesNotExist:
                    return Response({
                        'error': 'Cliente no encontrado'
                    }, status=404)
                
                # Obtener todos los referidos del cliente
                referrals = Clients.objects.filter(
                    referred_by=client,
                    deleted=False
                ).order_by('-created_at')
                
                # Preparar detalles de cada referido
                referrals_details = []
                for referral in referrals:
                    # Obtener reservas del referido
                    reservations = Reservation.objects.filter(
                        client=referral,
                        deleted=False
                    ).order_by('-check_in')
                    
                    reservations_data = []
                    for reservation in reservations:
                        reservations_data.append({
                            'id': str(reservation.id),
                            'property_name': reservation.property.name if reservation.property else 'N/A',
                            'check_in': reservation.check_in.strftime('%Y-%m-%d') if reservation.check_in else None,
                            'check_out': reservation.check_out.strftime('%Y-%m-%d') if reservation.check_out else None,
                            'status': reservation.status,
                            'total_price': float(reservation.price_sol) if reservation.price_sol else 0.0,
                            'created_at': reservation.created_at.strftime('%Y-%m-%d %H:%M') if reservation.created_at else None
                        })
                    
                    referrals_details.append({
                        'id': str(referral.id),
                        'name': f"{referral.first_name} {referral.last_name}" if referral.last_name else referral.first_name,
                        'email': referral.email,
                        'phone': referral.tel_number,
                        'created_at': referral.created_at.strftime('%Y-%m-%d %H:%M') if referral.created_at else None,
                        'total_reservations': reservations.count(),
                        'approved_reservations': reservations.filter(status='approved').count(),
                        'total_spent': float(reservations.filter(status='approved').aggregate(total=Sum('price_sol'))['total'] or 0),
                        'reservations': reservations_data
                    })
                
                # Respuesta con detalles del cliente
                response = {
                    'type': 'client_detail',
                    'client': {
                        'id': str(client.id),
                        'name': f"{client.first_name} {client.last_name}" if client.last_name else client.first_name,
                        'email': client.email,
                        'phone': client.tel_number
                    },
                    'total_referrals': referrals.count(),
                    'referrals_with_reservations': sum(1 for r in referrals_details if r['total_reservations'] > 0),
                    'referrals_without_reservations': sum(1 for r in referrals_details if r['total_reservations'] == 0),
                    'total_reservations_from_referrals': sum(r['total_reservations'] for r in referrals_details),
                    'total_revenue_from_referrals': sum(r['total_spent'] for r in referrals_details),
                    'referrals': referrals_details
                }
                
                return Response(response)
            
            # Validar parámetros para listado general
            if scope not in ['all', 'with_reservations']:
                return Response({
                    'error': 'Parámetro scope inválido. Use: all, with_reservations'
                }, status=400)
            
            if order_by not in ['total_referrals', 'referrals_with_reservations']:
                return Response({
                    'error': 'Parámetro order_by inválido. Use: total_referrals, referrals_with_reservations'
                }, status=400)
            
            # Obtener TODOS los clientes únicos que aparecen como "referred_by"
            clients_with_referrals_ids = Clients.objects.filter(
                deleted=False
            ).exclude(
                referred_by__isnull=True
            ).values_list('referred_by_id', flat=True).distinct()
            
            clients_with_referrals = Clients.objects.filter(
                id__in=clients_with_referrals_ids,
                deleted=False
            )
            
            # Preparar estadísticas por cada cliente
            referral_stats = []
            total_referrals_count = 0
            total_with_reservations = 0
            
            for client in clients_with_referrals:
                # Contar TODOS los referidos de este cliente
                all_referrals = Clients.objects.filter(
                    referred_by=client,
                    deleted=False
                ).count()
                
                # Contar referidos que SÍ tienen reservas aprobadas
                referrals_with_reservations = Clients.objects.filter(
                    referred_by=client,
                    deleted=False,
                    reservation__status='approved',
                    reservation__deleted=False
                ).distinct().count()
                
                total_referrals_count += all_referrals
                total_with_reservations += referrals_with_reservations
                
                # Filtrar según scope
                if scope == 'with_reservations' and referrals_with_reservations == 0:
                    continue
                
                referral_stats.append({
                    'client_name': f"{client.first_name} {client.last_name[0]}." if client.last_name else client.first_name,
                    'total_referrals': all_referrals,
                    'referrals_with_reservations': referrals_with_reservations,
                    'referrals_without_reservations': all_referrals - referrals_with_reservations
                })
            
            # Ordenar según parámetro order_by
            referral_stats.sort(key=lambda x: x[order_by], reverse=True)
            
            # Agregar posiciones al ranking
            for idx, stat in enumerate(referral_stats, start=1):
                stat['position'] = idx
            
            # Preparar respuesta según scope
            if scope == 'all':
                response = {
                    'type': 'all_referrals',
                    'scope': 'all',
                    'period_display': 'Todos los tiempos - Incluye referidos sin reservas',
                    'total_clients_with_referrals': len(referral_stats),
                    'total_referrals': total_referrals_count,
                    'total_referrals_with_reservations': total_with_reservations,
                    'total_referrals_without_reservations': total_referrals_count - total_with_reservations,
                    'top_rankings': referral_stats[:limit]
                }
            else:  # with_reservations
                response = {
                    'type': 'with_reservations',
                    'scope': 'with_reservations',
                    'period_display': 'Todos los tiempos - Solo referidos con reservas',
                    'total_clients_with_referrals': len(referral_stats),
                    'total_referrals_with_reservations': sum(x['referrals_with_reservations'] for x in referral_stats),
                    'top_rankings': referral_stats[:limit]
                }
            
            return Response(response)
            
        except Exception as e:
            logger.error(f"PublicReferralStatsView: Error getting referral stats: {str(e)}")
            return Response({
                'error': 'Error obteniendo estadísticas de referidos'
            }, status=500)


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

            # Solo indicar si tiene reservas pasadas
            has_past_reservations = past_reservations.exists()

            # Obtener campo is_password_set directamente
            is_password_set = client.is_password_set
            logger.info(f"BotClientProfileView: Client {client.id} - is_password_set: {is_password_set}")

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
                    'has_past_reservations': has_past_reservations,
                    'is_password_set': is_password_set
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


class ClientInfoByReferralCodeView(APIView):
    """
    GET /api/v1/clients/by-referral-code/{referral_code}/
    Obtiene información del cliente usando su código de referido.
    Endpoint público - no requiere autenticación.
    """
    permission_classes = [AllowAny]
    
    def get(self, request, referral_code):
        from django.utils import timezone
        from apps.clients.models import Clients
        
        try:
            # Buscar cliente por código de referido
            client = Clients.objects.filter(
                deleted=False,
                referral_code=referral_code
            ).first()
            
            if not client:
                return Response({
                    'success': False,
                    'error': 'Cliente no encontrado con ese código de referido'
                }, status=status.HTTP_404_NOT_FOUND)
            
            # Obtener reservas ACTIVAS (en curso ahora mismo)
            # Usar hora local del servidor (GMT-5) no UTC
            local_now = timezone.localtime(timezone.now())
            current_date = local_now.date()
            current_time = local_now.time()
            
            # Una reserva está activa si:
            # - Check-in ya pasó (fecha < hoy O fecha == hoy y hora >= 15:00)
            # - Check-out no ha pasado (fecha > hoy O fecha == hoy y hora < 11:00)
            from datetime import time
            
            active_reservations = []
            reservations = Reservation.objects.filter(
                client=client,
                deleted=False
            ).select_related('property')
            
            for reservation in reservations:
                # Verificar si la reserva está activa
                is_after_checkin = (
                    reservation.check_in_date < current_date or
                    (reservation.check_in_date == current_date and current_time >= time(15, 0))
                )
                
                is_before_checkout = (
                    reservation.check_out_date > current_date or
                    (reservation.check_out_date == current_date and current_time < time(11, 0))
                )
                
                if is_after_checkin and is_before_checkout:
                    # Obtener thumbnail de la propiedad (foto principal)
                    property_thumbnail = None
                    if reservation.property:
                        from apps.property.models import PropertyPhoto
                        main_photo = PropertyPhoto.objects.filter(
                            property=reservation.property,
                            is_main=True,
                            deleted=False
                        ).first()
                        
                        if main_photo:
                            property_thumbnail = main_photo.get_thumbnail_url()
                    
                    active_reservations.append({
                        'id': str(reservation.id),
                        'property_name': reservation.property.name if reservation.property else None,
                        'property_thumbnail': property_thumbnail,
                        'check_in_date': reservation.check_in_date.isoformat(),
                        'check_out_date': reservation.check_out_date.isoformat(),
                    })
            
            # Obtener el porcentaje de descuento para referidos basado en el nivel del cliente
            from apps.clients.models import Achievement, ClientAchievement
            from apps.property.models import ReferralDiscountByLevel
            
            referral_discount_percentage = 0
            
            # Obtener el achievement más alto ganado del cliente
            client_achievements = ClientAchievement.objects.filter(
                client=client,
                deleted=False
            ).select_related('achievement').order_by('-achievement__order', '-earned_at')
            
            if client_achievements.exists():
                highest_achievement = client_achievements.first().achievement
                
                # Buscar el descuento configurado para ese nivel
                discount_config = ReferralDiscountByLevel.objects.filter(
                    achievement=highest_achievement,
                    is_active=True,
                    deleted=False
                ).first()
                
                if discount_config:
                    referral_discount_percentage = float(discount_config.discount_percentage)
            
            # Preparar respuesta
            response_data = {
                'success': True,
                'client': {
                    'first_name': client.first_name.split()[0] if client.first_name else '',  # Solo primer nombre
                    'last_name': client.last_name.split()[0] if client.last_name else '',  # Solo primer apellido
                    'facebook_linked': client.facebook_linked,
                    'profile_picture': client.get_facebook_profile_picture() if client.facebook_linked else None,
                    'referral_discount_percentage': referral_discount_percentage,
                },
                'active_reservations': active_reservations
            }
            
            return Response(response_data)
            
        except Exception as e:
            logger.error(f"ClientInfoByReferralCodeView: Error: {str(e)}")
            return Response({
                'success': False,
                'error': 'Error interno del servidor'
            }, status=status.HTTP_500_INTERNAL_SERVER_ERROR)


class SearchesByCheckInDateView(APIView):
    """
    Vista para ver qué usuarios han buscado disponibilidad para una fecha de check-in específica.
    Solo accesible para admin/staff.

    GET /api/v1/clients/searches-by-checkin/?date=2025-12-19

    Parámetros opcionales:
    - date: Fecha de check-in (YYYY-MM-DD) - Requerido
    - include_anonymous: true/false - Incluir búsquedas anónimas (default: true)
    - property_id: ID de propiedad para filtrar

    Response:
    {
        "success": true,
        "check_in_date": "2025-12-19",
        "total_searches": 15,
        "unique_clients": 8,
        "anonymous_searches": 3,
        "searches_by_client": [
            {
                "client": {
                    "id": "uuid",
                    "first_name": "Juan",
                    "last_name": "Pérez",
                    "email": "juan@example.com",
                    "tel_number": "+51987654321"
                },
                "search_count": 3,
                "searches": [
                    {
                        "id": "uuid",
                        "check_in_date": "2025-12-19",
                        "check_out_date": "2025-12-22",
                        "guests": 4,
                        "property": {"id": 1, "name": "Villa Paradise"},
                        "search_timestamp": "2025-12-18T14:30:00Z",
                        "ip_address": "192.168.1.1"
                    }
                ]
            }
        ],
        "anonymous_searches_detail": [...]
    }
    """
    permission_classes = [IsAuthenticated]

    def get(self, request):
        # Verificar que es admin o staff
        if not (request.user.is_staff or request.user.is_superuser):
            return Response({
                'success': False,
                'error': 'No tiene permisos para esta operación'
            }, status=status.HTTP_403_FORBIDDEN)

        # Obtener fecha de check-in del query param
        date_str = request.query_params.get('date')
        if not date_str:
            return Response({
                'success': False,
                'error': 'El parámetro "date" es requerido (formato: YYYY-MM-DD)'
            }, status=status.HTTP_400_BAD_REQUEST)

        try:
            check_in_date = datetime.strptime(date_str, '%Y-%m-%d').date()
        except ValueError:
            return Response({
                'success': False,
                'error': 'Formato de fecha inválido. Use YYYY-MM-DD'
            }, status=status.HTTP_400_BAD_REQUEST)

        # Solo mostrar búsquedas para fechas futuras o de hoy
        from datetime import date
        if check_in_date < date.today():
            return Response({
                'success': True,
                'check_in_date': str(check_in_date),
                'total_searches': 0,
                'unique_clients': 0,
                'anonymous_searches_count': 0,
                'searches_by_client': [],
                'anonymous_searches_detail': [],
                'message': 'Solo se muestran búsquedas para fechas futuras'
            })

        # Parámetros opcionales
        include_anonymous = request.query_params.get('include_anonymous', 'true').lower() == 'true'
        property_id = request.query_params.get('property_id')
        level_id = request.query_params.get('level')  # ID del achievement/nivel para filtrar

        try:
            # Importar servicio de pricing
            from apps.property.pricing_service import PricingCalculationService
            pricing_service = PricingCalculationService()

            # Helper para obtener level_info del cliente
            def get_client_level_info(client):
                from .models import ClientAchievement
                earned = ClientAchievement.objects.filter(
                    client=client,
                    deleted=False
                ).select_related('achievement').order_by(
                    '-achievement__required_reservations',
                    '-achievement__required_referrals'
                ).first()
                if earned:
                    return {
                        'name': earned.achievement.name,
                        'icon': earned.achievement.icon,
                    }
                return None

            # Helper para calcular precio y disponibilidad
            def calculate_search_price(check_in, check_out, guests, property_obj=None):
                if not check_out:
                    return None

                try:
                    result = pricing_service.calculate_pricing(
                        check_in_date=check_in,
                        check_out_date=check_out,
                        guests=guests,
                        property_id=str(property_obj.id) if property_obj else None
                    )

                    if result and result.get('properties'):
                        # Si hay propiedad específica
                        if property_obj:
                            prop_pricing = result['properties'][0]
                            if not prop_pricing.get('available', False):
                                return None  # No mostrar si no está disponible
                            return {
                                'total_nights': prop_pricing.get('total_nights'),
                                'price_usd': float(prop_pricing.get('final_price_usd', 0)),
                                'price_sol': float(prop_pricing.get('final_price_sol', 0)),
                                'available': True,
                                'property_name': prop_pricing.get('property_name'),
                            }
                        else:
                            # Sin propiedad específica: devolver lista de casas disponibles
                            available_properties = [p for p in result['properties'] if p.get('available', False)]

                            if not available_properties:
                                return None  # No mostrar si no hay disponibilidad

                            return {
                                'total_nights': result.get('total_nights', (check_out - check_in).days),
                                'available': True,
                                'properties': [
                                    {
                                        'name': p.get('property_name'),
                                        'price_usd': float(p.get('final_price_usd', 0)),
                                        'price_sol': float(p.get('final_price_sol', 0)),
                                    }
                                    for p in available_properties
                                ]
                            }
                except Exception as e:
                    prop_name = property_obj.name if property_obj else 'todas'
                    logger.warning(f"Error calculando precio para {prop_name} ({check_in} - {check_out}): {e}")
                return None

            # Obtener IDs de clientes con reservas activas FUTURAS (para excluirlos)
            # Reservas activas = estado PENDING, UNDER_REVIEW o APPROVED, no eliminadas, y con fecha futura
            from datetime import date
            today = date.today()
            active_statuses = [
                Reservation.ReservationStatusChoice.PENDING,
                Reservation.ReservationStatusChoice.UNDER_REVIEW,
                Reservation.ReservationStatusChoice.APPROVED,
            ]
            clients_with_active_reservations = Reservation.objects.filter(
                status__in=active_statuses,
                deleted=False,
                check_in_date__gte=today  # Solo reservas futuras
            ).values_list('client_id', flat=True).distinct()

            # Si se especifica nivel, obtener clientes con ese achievement
            clients_with_level = None
            if level_id:
                clients_with_level = ClientAchievement.objects.filter(
                    achievement_id=level_id,
                    deleted=False
                ).values_list('client_id', flat=True).distinct()

            # Construir query base
            base_query = SearchTracking.objects.filter(
                check_in_date=check_in_date,
                deleted=False
            ).select_related('client', 'property').order_by('-search_timestamp')

            # Filtrar por propiedad si se especifica
            if property_id:
                base_query = base_query.filter(property_id=property_id)

            # Separar búsquedas de clientes registrados (no eliminados, sin reservas activas) y anónimos
            client_searches = base_query.filter(
                client__isnull=False,
                client__deleted=False  # Solo clientes no eliminados
            ).exclude(
                client_id__in=clients_with_active_reservations  # Excluir clientes con reservas activas
            )

            # Filtrar por nivel si se especifica
            if clients_with_level is not None:
                client_searches = client_searches.filter(client_id__in=clients_with_level)

            anonymous_searches = base_query.filter(client__isnull=True) if include_anonymous else SearchTracking.objects.none()

            # Agrupar búsquedas por cliente, deduplicando por (check_in, check_out, guests)
            searches_by_client = {}
            for search in client_searches:
                client_id = str(search.client.id)
                if client_id not in searches_by_client:
                    searches_by_client[client_id] = {
                        'client': {
                            'id': str(search.client.id),
                            'first_name': search.client.first_name,
                            'last_name': search.client.last_name,
                            'email': search.client.email,
                            'tel_number': search.client.tel_number,
                            'number_doc': search.client.number_doc,
                            'level_info': get_client_level_info(search.client),
                        },
                        'search_count': 0,
                        'searches': [],
                        '_seen_searches': set()  # Para deduplicar
                    }

                # Clave única: fechas + guests (ignorar property para agrupar)
                search_key = f"{search.check_in_date}_{search.check_out_date}_{search.guests}"

                # Saltar si ya vimos esta combinación (la primera es la más reciente)
                if search_key in searches_by_client[client_id]['_seen_searches']:
                    continue

                # Calcular precio para esta búsqueda (solo si hay disponibilidad)
                pricing = calculate_search_price(
                    search.check_in_date,
                    search.check_out_date,
                    search.guests,
                    search.property
                )

                # Solo agregar búsquedas con disponibilidad
                if pricing:
                    searches_by_client[client_id]['_seen_searches'].add(search_key)
                    searches_by_client[client_id]['search_count'] += 1
                    searches_by_client[client_id]['searches'].append({
                        'id': str(search.id),
                        'check_in_date': str(search.check_in_date),
                        'check_out_date': str(search.check_out_date),
                        'guests': search.guests,
                        'property': {
                            'id': str(search.property.id) if search.property else None,
                            'name': search.property.name if search.property else None
                        } if search.property else None,
                        'pricing': pricing,
                        'search_timestamp': search.search_timestamp.isoformat() if search.search_timestamp else None,
                        'ip_address': search.ip_address,
                    })

            # Formatear búsquedas anónimas (solo con disponibilidad)
            anonymous_searches_detail = []
            for search in anonymous_searches:
                pricing = calculate_search_price(
                    search.check_in_date,
                    search.check_out_date,
                    search.guests,
                    search.property
                )
                # Solo agregar si hay disponibilidad
                if pricing:
                    anonymous_searches_detail.append({
                        'id': str(search.id),
                        'check_in_date': str(search.check_in_date),
                        'check_out_date': str(search.check_out_date),
                        'guests': search.guests,
                        'property': {
                            'id': str(search.property.id) if search.property else None,
                            'name': search.property.name if search.property else None
                        } if search.property else None,
                        'pricing': pricing,
                        'search_timestamp': search.search_timestamp.isoformat() if search.search_timestamp else None,
                        'ip_address': search.ip_address,
                        'session_key': search.session_key,
                    })

            # Filtrar clientes sin búsquedas disponibles y remover campo interno
            searches_by_client_filtered = {}
            for k, v in searches_by_client.items():
                if v['search_count'] > 0:
                    # Remover campo interno antes de retornar
                    del v['_seen_searches']
                    searches_by_client_filtered[k] = v

            # Estadísticas (solo búsquedas con disponibilidad)
            total_available_searches = sum(c['search_count'] for c in searches_by_client_filtered.values()) + len(anonymous_searches_detail)
            unique_clients = len(searches_by_client_filtered)

            return Response({
                'success': True,
                'check_in_date': str(check_in_date),
                'total_searches': total_available_searches,
                'unique_clients': unique_clients,
                'anonymous_searches_count': len(anonymous_searches_detail),
                'searches_by_client': list(searches_by_client_filtered.values()),
                'anonymous_searches_detail': anonymous_searches_detail if include_anonymous else []
            })

        except Exception as e:
            logger.error(f"SearchesByCheckInDateView: Error: {str(e)}")
            return Response({
                'success': False,
                'error': f'Error interno del servidor: {str(e)}'
            }, status=status.HTTP_500_INTERNAL_SERVER_ERROR)
