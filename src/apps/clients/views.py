
from rest_framework import status
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
        logger.info(f"ClientCreateReservationView: New reservation request from client")
        
        # Autenticar cliente
        try:
            authenticator = ClientJWTAuthentication()
            client, validated_token = authenticator.authenticate(request)

            if not client:
                logger.error("ClientCreateReservationView: Authentication failed")
                return Response({'message': 'Token inválido'}, status=401)

            # Crear serializer con contexto
            serializer = ClientReservationSerializer(
                data=request.data, 
                context={'request': request}
            )
            
            if serializer.is_valid():
                reservation = serializer.save()
                
                # Retornar la reserva creada
                response_serializer = ReservationListSerializer(reservation)
                
                logger.info(f"ClientCreateReservationView: Reservation created successfully - ID: {reservation.id}")
                
                return Response({
                    'success': True,
                    'message': 'Reserva creada exitosamente. Está pendiente de aprobación.',
                    'reservation': response_serializer.data
                }, status=201)
            else:
                logger.error(f"ClientCreateReservationView: Validation errors: {serializer.errors}")
                return Response({
                    'success': False,
                    'message': 'Error en los datos enviados',
                    'errors': serializer.errors
                }, status=400)

        except Exception as e:
            logger.error(f"ClientCreateReservationView: Error creating reservation: {str(e)}")
            return Response({
                'success': False,
                'message': 'Error interno del servidor'
            }, status=500)


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
                logger.error("ClientReservationsListView: Authentication failed")
                return Response({'message': 'Token inválido'}, status=401)

            from datetime import date

            # Obtener todas las reservas del cliente
            reservations = Reservation.objects.filter(
                client=client,
                deleted=False
            ).order_by('-created')

            # Clasificar reservas
            today = date.today()
            upcoming_reservations = []
            past_reservations = []
            pending_reservations = []

            for reservation in reservations:
                if reservation.status == 'pending':
                    pending_reservations.append(reservation)
                elif reservation.check_out_date > today:
                    upcoming_reservations.append(reservation)
                else:
                    past_reservations.append(reservation)

            # Serializar las reservas
            upcoming_serializer = ReservationListSerializer(upcoming_reservations, many=True)
            past_serializer = ReservationListSerializer(past_reservations, many=True)
            pending_serializer = ReservationListSerializer(pending_reservations, many=True)

            return Response({
                'upcoming_reservations': upcoming_serializer.data,
                'past_reservations': past_serializer.data,
                'pending_reservations': pending_serializer.data
            })

        except Exception as e:
            logger.error(f"ClientReservationsListView: Error getting reservations: {str(e)}")
            return Response({
                'success': False,
                'message': 'Error interno del servidor'
            }, status=500)

from datetime import datetime

from drf_spectacular.utils import OpenApiParameter, OpenApiTypes, extend_schema
from rest_framework import filters, viewsets, status
from rest_framework.views import APIView
from rest_framework.decorators import action
from rest_framework.response import Response

from apps.core.paginator import CustomPagination

from .models import Clients, MensajeFidelidad, TokenApiClients
from .serializers import ClientsSerializer, MensajeFidelidadSerializer, TokenApiClienteSerializer

from apps.core.functions import generate_audit


class MensajeFidelidadApiView(APIView):
    serializer_class = MensajeFidelidadSerializer
    
    def get(self, request):
        content = self.serializer_class(
            MensajeFidelidad.objects.exclude(
                activo=False
            ).last()
        ).data
        return Response(content, status=200)

class TokenApiClientApiView(APIView):
    serializer_class = TokenApiClienteSerializer
    
    def get(self, request):
        content = self.serializer_class(TokenApiClients.objects.exclude(deleted=True).order_by("created").last()).data
        return Response(content, status=200)    

class ClientsApiView(viewsets.ModelViewSet):
    serializer_class = ClientsSerializer
    filter_backends = [filters.SearchFilter]
    search_fields = [
        "email",
        "number_doc",
        "first_name", 
        "last_name",
        "tel_number"
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
                description="Enviar page_size=valor para determinar tamaño de la pagina, sino enviar page_size=none para no tener paginado",
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
                description="bd=today para recuperar todos los clientes que tengan cumpleaños hoy",
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

        generate_audit(
            serializer.instance,
            self.request.user,
            "create",
            "Cliente creado"
        )


    def partial_update(self, request, *args, **kwargs):
        instance = self.get_object()
        serializer = self.get_serializer(instance, data=request.data, partial=True)
        serializer.is_valid(raise_exception=True)
        

        self.perform_update(serializer)

        generate_audit(
            instance,
            self.request.user,
            "update",
            "Cliente actulizado"
        )
        return Response(serializer.data)

    def destroy(self, request, *args, **kwargs):
        instance = self.get_object()
        
        instance.deleted = True
        instance.save()
        
        generate_audit(
            instance,
            self.request.user,
            "delete",
            "Cliente eliminado"
        )

        return Response(status=status.HTTP_204_NO_CONTENT)

    def get_queryset(self):
        queryset = Clients.objects.exclude(deleted=True).order_by("last_name", "first_name")

        if not "admin" in self.request.user.groups.all().values_list('name', flat=True):
            queryset = queryset.exclude(first_name="Mantenimiento")

        if self.action == "search_clients":
            params = self.request.GET
            self.pagination_class = None
            if not params:
                return queryset.none()
            return queryset

        if self.request.query_params.get('bd') == 'today':
            queryset = queryset.filter(date__month=datetime.now().month, date__day=datetime.now().day)

        return queryset

    @action(
        detail=False,
        methods=["GET"],
        url_name="search",
        url_path="search",
    )
    def search_clients(self, request, *args, **kwargs):
        return super().list(request, *args, **kwargs)
