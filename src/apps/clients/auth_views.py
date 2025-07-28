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

            # Generar JWT token
            payload = {
                'client_id': str(client.id),  # Convert UUID to string
                'document_type': client.document_type,
                'number_doc': client.number_doc,
                'exp': datetime.utcnow() + timedelta(days=30),
                'iat': datetime.utcnow()
            }

            token = jwt.encode(payload, settings.SECRET_KEY, algorithm='HS256')

            return Response({
                'token': token,
                'client': ClientProfileSerializer(client).data
            })

        except Clients.DoesNotExist:
            return Response({
                'message': 'Credenciales inválidas'
            }, status=401)


class ClientProfileView(APIView):

    def get(self, request):
        logger.info("ClientProfileView: Profile request received")
        logger.info(f"Request headers: {dict(request.headers)}")
        
        client = self.get_client_from_token(request)
        if not client:
            logger.error("ClientProfileView: Authentication failed")
            return Response({'message': 'Token inválido'}, status=401)

        logger.info(f"ClientProfileView: Returning profile for client {client.id}")
        return Response(ClientProfileSerializer(client).data)

    def get_client_from_token(self, request):
        auth_header = request.headers.get('Authorization')
        logger.info(f"Authorization header received: {auth_header[:50] if auth_header else 'None'}...")

        if not auth_header or not auth_header.startswith('Bearer '):
            logger.error("No Authorization header or invalid format")
            return None

        token = auth_header.split(' ')[1]
        logger.info(f"Extracted token: {token[:20]}...")

        try:
            logger.info(f"Decoding token with SECRET_KEY")
            payload = jwt.decode(token, settings.SECRET_KEY, algorithms=['HS256'])
            logger.info(f"Token decoded successfully. Payload: {payload}")

            client_id = payload.get('client_id')
            logger.info(f"Looking for client with ID: {client_id}")

            client = Clients.objects.get(id=client_id, deleted=False)
            logger.info(f"Client found: {client.first_name} {client.last_name}")
            return client

        except jwt.ExpiredSignatureError:
            logger.error("Token has expired")
            return None
        except jwt.InvalidTokenError as e:
            logger.error(f"Invalid token: {str(e)}")
            return None
        except Clients.DoesNotExist:
            logger.error(f"Client not found for id: {client_id}")
            return None
        except Exception as e:
            logger.error(f"Unexpected error validating token: {str(e)}")
            import traceback
            logger.error(f"Traceback: {traceback.format_exc()}")
            return None


class ClientReservationsView(APIView):

    def get(self, request):
        logger.info("ClientReservationsView: Request received")
        logger.info(f"Authorization header: {request.headers.get('Authorization', 'No header')}")

        client = self.get_client_from_token(request)
        if not client:
            logger.error("ClientReservationsView: Invalid token or client not found")
            return Response({'message': 'Token inválido'}, status=401)

        try:
            from apps.reservation.models import Reservation
            from apps.reservation.serializers import ReservationListSerializer

            # Filtrar reservaciones del cliente autenticado
            reservations = Reservation.objects.filter(
                client=client,
                deleted=False
            ).order_by('-check_in_date')

            serializer = ReservationListSerializer(reservations, many=True)

            return Response({
                'success': True,
                'reservations': serializer.data
            })

        except Exception as e:
            logger.error(f"Error getting client reservations: {str(e)}")
            return Response({
                'success': False,
                'message': 'Error al obtener las reservaciones'
            }, status=500)

    def get_client_from_token(self, request):
        auth_header = request.headers.get('Authorization')
        logger.info(f"Authorization header received: {auth_header[:50] if auth_header else 'None'}...")

        if not auth_header or not auth_header.startswith('Bearer '):
            logger.error("No Authorization header or invalid format")
            return None

        token = auth_header.split(' ')[1]
        logger.info(f"Extracted token: {token[:20]}...")

        try:
            logger.info(f"Decoding token with SECRET_KEY")
            payload = jwt.decode(token, settings.SECRET_KEY, algorithms=['HS256'])
            logger.info(f"Token decoded successfully. Payload: {payload}")

            client_id = payload.get('client_id')
            logger.info(f"Looking for client with ID: {client_id}")

            client = Clients.objects.get(id=client_id, deleted=False)
            logger.info(f"Client found: {client.first_name} {client.last_name}")
            return client

        except jwt.ExpiredSignatureError:
            logger.error("Token has expired")
            return None
        except jwt.InvalidTokenError as e:
            logger.error(f"Invalid token: {str(e)}")
            return None
        except Clients.DoesNotExist:
            logger.error(f"Client not found for id: {client_id}")
            return None
        except Exception as e:
            logger.error(f"Unexpected error validating token: {str(e)}")
            import traceback
            logger.error(f"Traceback: {traceback.format_exc()}")
            return None


@api_view(['GET'])
@permission_classes([AllowAny])
def get_csrf_token(request):
    """Endpoint para obtener CSRF token si es necesario"""
    from django.middleware.csrf import get_token
    return Response({'csrfToken': get_token(request)})