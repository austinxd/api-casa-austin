# Updates the OTP request to use Twilio Verify Service.
from datetime import datetime, timedelta
import random
import string
import jwt
from django.conf import settings
from django.contrib.auth.hashers import make_password, check_password

from drf_spectacular.utils import OpenApiParameter, OpenApiTypes, extend_schema
from rest_framework import filters, viewsets, status
from rest_framework.views import APIView
from rest_framework.decorators import action
from rest_framework.response import Response
from rest_framework.permissions import AllowAny

from apps.core.paginator import CustomPagination

from .models import Clients, MensajeFidelidad, TokenApiClients
from .serializers import (
    ClientsSerializer, MensajeFidelidadSerializer, TokenApiClienteSerializer,
    ClientAuthRequestSerializer, ClientOTPSerializer, ClientLoginSerializer,
    ClientProfileSerializer
)

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

class ClientAuthRequestView(APIView):
    """Vista para solicitar OTP para registro de contraseña"""
    permission_classes = [AllowAny]
    serializer_class = ClientAuthRequestSerializer

    def post(self, request):
        serializer = self.serializer_class(data=request.data)
        if serializer.is_valid():
            document_type = serializer.validated_data['document_type']
            number_doc = serializer.validated_data['number_doc']

            try:
                client = Clients.objects.get(
                    document_type=document_type,
                    number_doc=number_doc,
                    deleted=False
                )

                # Verificar si ya tiene contraseña
                if client.password:
                    return Response({
                        "error": "Este cliente ya tiene una contraseña registrada. Use el login normal."
                    }, status=status.HTTP_400_BAD_REQUEST)

                # Limpiar códigos OTP previos
                client.otp_code = None
                client.otp_expires_at = None
                client.save()

                # Enviar OTP por SMS usando Twilio Verify Service
                from apps.core.functions import send_sms_otp

                sms_result = send_sms_otp(client.tel_number, None)

                if sms_result['success']:
                    return Response({
                        "message": "Código de verificación enviado por SMS",
                        "phone_hint": f"***{client.tel_number[-4:]}" if client.tel_number else None
                    }, status=status.HTTP_200_OK)
                else:
                    return Response({
                        "error": f"Error al enviar código de verificación: {sms_result['message']}"
                    }, status=status.HTTP_500_INTERNAL_SERVER_ERROR)

            except Clients.DoesNotExist:
                return Response({
                    "error": "No se encontró un cliente con ese número de documento"
                }, status=status.HTTP_404_NOT_FOUND)

        return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)

class ClientPasswordSetupView(APIView):
    """Vista para establecer contraseña con verificación OTP"""
    permission_classes = [AllowAny]
    serializer_class = ClientOTPSerializer

    def post(self, request):
        serializer = self.serializer_class(data=request.data)
        if serializer.is_valid():
            document_type = serializer.validated_data['document_type']
            number_doc = serializer.validated_data['number_doc']
            otp_code = serializer.validated_data['otp_code']
            password = serializer.validated_data['password']

            try:
                client = Clients.objects.get(
                    document_type=document_type,
                    number_doc=number_doc,
                    deleted=False
                )

                # Verificar OTP
                if not client.otp_code or client.otp_code != otp_code:
                    return Response({
                        "error": "Código OTP inválido"
                    }, status=status.HTTP_400_BAD_REQUEST)

                # Verificar expiración
                if client.otp_expires_at < datetime.now():
                    return Response({
                        "error": "Código OTP expirado"
                    }, status=status.HTTP_400_BAD_REQUEST)

                # Establecer contraseña
                client.password = make_password(password)
                client.is_active_client = True
                client.otp_code = None
                client.otp_expires_at = None
                client.save()

                return Response({
                    "message": "Contraseña establecida correctamente. Ya puedes iniciar sesión."
                }, status=status.HTTP_200_OK)

            except Clients.DoesNotExist:
                return Response({
                    "error": "Cliente no encontrado"
                }, status=status.HTTP_404_NOT_FOUND)

        return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)

class ClientLoginView(APIView):
    """Vista para login de clientes"""
    permission_classes = [AllowAny]
    serializer_class = ClientLoginSerializer

    def post(self, request):
        serializer = self.serializer_class(data=request.data)
        if serializer.is_valid():
            document_type = serializer.validated_data['document_type']
            number_doc = serializer.validated_data['number_doc']
            password = serializer.validated_data['password']

            try:
                client = Clients.objects.get(
                    document_type=document_type,
                    number_doc=number_doc,
                    deleted=False,
                    is_active_client=True
                )

                if not client.password:
                    return Response({
                        "error": "Este cliente no tiene contraseña configurada"
                    }, status=status.HTTP_400_BAD_REQUEST)

                if check_password(password, client.password):
                    # Actualizar último login
                    client.last_login_client = datetime.now()
                    client.save()

                    # Generar token JWT
                    token_payload = {
                        'client_id': client.id,
                        'document_type': client.document_type,
                        'number_doc': client.number_doc,
                        'exp': datetime.utcnow() + timedelta(days=7)
                    }

                    token = jwt.encode(token_payload, settings.SECRET_KEY, algorithm='HS256')

                    return Response({
                        "message": "Login exitoso",
                        "token": token,
                        "client": ClientProfileSerializer(client).data
                    }, status=status.HTTP_200_OK)
                else:
                    return Response({
                        "error": "Contraseña incorrecta"
                    }, status=status.HTTP_400_BAD_REQUEST)

            except Clients.DoesNotExist:
                return Response({
                    "error": "Cliente no encontrado o inactivo"
                }, status=status.HTTP_404_NOT_FOUND)

        return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)

class ClientProfileView(APIView):
    """Vista para ver y actualizar perfil del cliente"""

    def get_client_from_token(self, request):
        """Extrae el cliente del token JWT"""
        auth_header = request.headers.get('Authorization')
        if not auth_header or not auth_header.startswith('Bearer '):
            return None

        token = auth_header[7:]
        try:
            payload = jwt.decode(token, settings.SECRET_KEY, algorithms=['HS256'])
            client = Clients.objects.get(
                id=payload['client_id'],
                deleted=False,
                is_active_client=True
            )
            return client
        except (jwt.ExpiredSignatureError, jwt.InvalidTokenError, Clients.DoesNotExist):
            return None

    def get(self, request):
        client = self.get_client_from_token(request)
        if not client:
            return Response({
                "error": "Token inválido o expirado"
            }, status=status.HTTP_401_UNAUTHORIZED)

        serializer = ClientProfileSerializer(client)
        return Response(serializer.data, status=status.HTTP_200_OK)

    def patch(self, request):
        client = self.get_client_from_token(request)
        if not client:
            return Response({
                "error": "Token inválido o expirado"
            }, status=status.HTTP_401_UNAUTHORIZED)

        serializer = ClientProfileSerializer(client, data=request.data, partial=True)
        if serializer.is_valid():
            serializer.save()
            return Response(serializer.data, status=status.HTTP_200_OK)

        return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)



class ClientReservationsView(APIView):
    """Vista para que los clientes vean sus reservas"""

    def get_client_from_token(self, request):
        """Extrae el cliente del token JWT"""
        auth_header = request.headers.get('Authorization')
        if not auth_header or not auth_header.startswith('Bearer '):
            return None

        token = auth_header[7:]
        try:
            payload = jwt.decode(token, settings.SECRET_KEY, algorithms=['HS256'])
            client = Clients.objects.get(
                id=payload['client_id'],
                deleted=False,
                is_active_client=True
            )
            return client
        except (jwt.ExpiredSignatureError, jwt.InvalidTokenError, Clients.DoesNotExist):
            return None

    def get(self, request):
        client = self.get_client_from_token(request)
        if not client:
            return Response({
                "error": "Token inválido o expirado"
            }, status=status.HTTP_401_UNAUTHORIZED)

        from apps.reservation.models import Reservation
        from apps.reservation.serializers import ReservationSerializer

        # Obtener todas las reservas del cliente
        reservations = Reservation.objects.filter(
            client=client,
            deleted=False
        ).order_by('-check_in_date')

        # Separar reservas pasadas y futuras
        today = datetime.now().date()
        past_reservations = reservations.filter(check_out_date__lt=today)
        future_reservations = reservations.filter(check_in_date__gte=today)

        # Serializar las reservas
        past_serializer = ReservationSerializer(past_reservations, many=True)
        future_serializer = ReservationSerializer(future_reservations, many=True)

        return Response({
            "past_reservations": past_serializer.data,
            "future_reservations": future_serializer.data,
            "total_reservations": reservations.count()
        }, status=status.HTTP_200_OK)