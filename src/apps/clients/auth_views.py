import jwt
from datetime import datetime, timedelta
from django.conf import settings
from django.contrib.auth.hashers import make_password, check_password
from django.utils import timezone
from rest_framework import status
from rest_framework.views import APIView
from rest_framework.response import Response
from rest_framework.permissions import AllowAny
from rest_framework.decorators import api_view, permission_classes
from rest_framework_simplejwt.tokens import RefreshToken
from rest_framework_simplejwt.authentication import JWTAuthentication
from rest_framework_simplejwt.exceptions import InvalidToken, TokenError

from .models import Clients
from .serializers import (
    ClientAuthVerifySerializer,
    ClientAuthRequestOTPSerializer, 
    ClientAuthSetPasswordSerializer,
    ClientAuthLoginSerializer,
    ClientProfileSerializer
)
from .twilio_service import TwilioOTPService
import logging

logger = logging.getLogger('apps')

# Custom JWT Authentication for Clients
class ClientJWTAuthentication(JWTAuthentication):
    def get_user(self, validated_token):
        """
        Override to get client instead of user
        """
        try:
            client_id = validated_token.get('client_id')
            if client_id:
                return Clients.objects.get(id=client_id, deleted=False)
        except Clients.DoesNotExist:
            pass
        return None

class ClientVerifyDocumentView(APIView):
    permission_classes = [AllowAny]

    def post(self, request):
        serializer = ClientAuthVerifySerializer(data=request.data)
        if not serializer.is_valid():
            return Response({'message': 'Datos inválidos'}, status=400)

        try:
            client = Clients.objects.get(
                document_type=serializer.validated_data['document_type'],
                number_doc=serializer.validated_data['number_doc'],
                deleted=False
            )

            return Response({
                'exists': True,
                'client': {
                    'first_name': client.first_name,
                    'last_name': client.last_name,
                    'email': client.email,
                    'phone': client.tel_number,
                    'has_password': client.is_password_set
                }
            })

        except Clients.DoesNotExist:
            return Response({
                'exists': False,
                'message': 'Cliente no encontrado en nuestros registros'
            }, status=404)


class ClientRequestOTPView(APIView):
    permission_classes = [AllowAny]

    def post(self, request):
        serializer = ClientAuthRequestOTPSerializer(data=request.data)
        if not serializer.is_valid():
            return Response({'message': 'Datos inválidos'}, status=400)

        try:
            client = Clients.objects.get(
                document_type=serializer.validated_data['document_type'],
                number_doc=serializer.validated_data['number_doc'],
                deleted=False
            )

            if not client.tel_number:
                return Response({
                    'message': 'No hay número de teléfono registrado para este cliente'
                }, status=400)

            # Usar Twilio Verify Service
            twilio_service = TwilioOTPService()

            if twilio_service.send_otp_with_verify(client.tel_number):
                return Response({
                    'message': 'Código de verificación enviado',
                    'phone_masked': f"***{client.tel_number[-4:]}"
                })
            else:
                return Response({
                    'message': 'Error al enviar código de verificación'
                }, status=500)

        except Clients.DoesNotExist:
            return Response({
                'message': 'Cliente no encontrado'
            }, status=404)


class ClientSetupPasswordView(APIView):
    permission_classes = [AllowAny]

    def post(self, request):
        serializer = ClientAuthSetPasswordSerializer(data=request.data)
        if not serializer.is_valid():
            return Response({'message': 'Datos inválidos'}, status=400)

        try:
            client = Clients.objects.get(
                document_type=serializer.validated_data['document_type'],
                number_doc=serializer.validated_data['number_doc'],
                deleted=False
            )

            # Verificar OTP con Twilio
            twilio_service = TwilioOTPService()

            if not twilio_service.verify_otp_code(client.tel_number, serializer.validated_data['otp_code']):
                return Response({
                    'message': 'Código OTP inválido o expirado'
                }, status=400)

            # Configurar contraseña
            client.password = make_password(serializer.validated_data['password'])
            client.is_password_set = True
            client.otp_code = None
            client.otp_expires_at = None
            client.save()

            return Response({
                'message': 'Contraseña configurada exitosamente'
            })

        except Clients.DoesNotExist:
            return Response({
                'message': 'Cliente no encontrado'
            }, status=404)


class ClientLoginView(APIView):
    permission_classes = [AllowAny]

    def post(self, request):
        serializer = ClientAuthLoginSerializer(data=request.data)
        if not serializer.is_valid():
            return Response({'message': 'Datos inválidos'}, status=400)

        try:
            client = Clients.objects.get(
                document_type=serializer.validated_data['document_type'],
                number_doc=serializer.validated_data['number_doc'],
                deleted=False
            )

            if not client.is_password_set or not client.password:
                return Response({
                    'message': 'Este cliente no ha configurado una contraseña'
                }, status=400)

            if not check_password(serializer.validated_data['password'], client.password):
                return Response({
                    'message': 'Credenciales inválidas'
                }, status=401)

            # Actualizar último login
            client.last_login = timezone.now()
            client.save()

            # Generar tokens using Simple JWT
            refresh = RefreshToken()
            refresh['client_id'] = str(client.id)
            refresh['document_type'] = client.document_type
            refresh['number_doc'] = client.number_doc

            access_token = refresh.access_token
            access_token['client_id'] = str(client.id)
            access_token['document_type'] = client.document_type
            access_token['number_doc'] = client.number_doc

            return Response({
                'token': str(access_token),
                'refresh': str(refresh),
                'client': ClientProfileSerializer(client).data
            })

        except Clients.DoesNotExist:
            return Response({
                'message': 'Credenciales inválidas'
            }, status=401)


class ClientProfileView(APIView):
    authentication_classes = [ClientJWTAuthentication]
    permission_classes = [AllowAny]

    def get(self, request):
        logger.info("ClientProfileView: Profile request received")

        # Get client from JWT token
        try:
            authenticator = ClientJWTAuthentication()
            user, validated_token = authenticator.authenticate(request)

            if not user:
                logger.error("ClientProfileView: Authentication failed")
                return Response({'message': 'Token inválido'}, status=401)

            logger.info(f"ClientProfileView: Returning profile for client {user.id}")
            return Response(ClientProfileSerializer(user).data)

        except (InvalidToken, TokenError) as e:
            logger.error(f"ClientProfileView: Token validation failed: {str(e)}")
            return Response({'message': 'Token inválido'}, status=401)
        except Exception as e:
            logger.error(f"ClientProfileView: Unexpected error: {str(e)}")
            return Response({'message': 'Error interno del servidor'}, status=500)


class ClientReservationsView(APIView):
    authentication_classes = [ClientJWTAuthentication]
    permission_classes = [AllowAny]

    def get(self, request):
        logger.info("ClientReservationsView: Request received")

        # Get client from JWT token
        try:
            authenticator = ClientJWTAuthentication()
            client, validated_token = authenticator.authenticate(request)

            if not client:
                logger.error("ClientReservationsView: Authentication failed")
                return Response({'message': 'Token inválido'}, status=401)

            from apps.reservation.models import Reservation
            from apps.reservation.serializers import ReservationListSerializer
            from datetime import date

            # Filtrar reservaciones del cliente autenticado
            reservations = Reservation.objects.filter(
                client=client,
                deleted=False
            ).order_by('-check_in_date')

            # Clasificar reservas en próximas y pasadas
            today = date.today()
            upcoming_reservations = []
            past_reservations = []

            for reservation in reservations:
                if reservation.check_out_date > today:
                    upcoming_reservations.append(reservation)
                else:
                    past_reservations.append(reservation)

            # Serializar las reservas
            upcoming_serializer = ReservationListSerializer(upcoming_reservations, many=True)
            past_serializer = ReservationListSerializer(past_reservations, many=True)

            return Response({
                'upcoming_reservations': upcoming_serializer.data,
                'past_reservations': past_serializer.data
            })

        except (InvalidToken, TokenError) as e:
            logger.error(f"ClientReservationsView: Token validation failed: {str(e)}")
            return Response({'message': 'Token inválido'}, status=401)
        except Exception as e:
            logger.error(f"ClientReservationsView: Error getting reservations: {str(e)}")
            return Response({
                'success': False,
                'message': 'Error al obtener las reservaciones'
            }, status=500)


@api_view(['GET'])
@permission_classes([AllowAny])
def get_csrf_token(request):
    """Endpoint para obtener CSRF token si es necesario"""
    from django.middleware.csrf import get_token
    return Response({'csrfToken': get_token(request)})