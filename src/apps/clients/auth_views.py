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
        logger.info("=" * 50)
        logger.info("STARTING TOKEN VALIDATION")
        logger.info("=" * 50)

        # Log all headers for debugging
        logger.info("ALL REQUEST HEADERS:")
        for header_name, header_value in request.headers.items():
            if 'authorization' in header_name.lower():
                logger.info(f"  {header_name}: {header_value[:50]}...")
            else:
                logger.info(f"  {header_name}: {header_value}")

        auth_header = request.headers.get('Authorization')
        logger.info(f"Authorization header: {auth_header}")

        if not auth_header:
            logger.error("NO Authorization header found")
            return None

        if not auth_header.startswith('Bearer '):
            logger.error(f"Invalid Authorization format. Expected 'Bearer <token>', got: {auth_header[:30]}...")
            return None

        token = auth_header.split(' ')[1]
        logger.info(f"Extracted token length: {len(token)}")
        logger.info(f"Token first 30 chars: {token[:30]}...")
        logger.info(f"Token last 30 chars: ...{token[-30:]}")

        try:
            logger.info("Attempting to decode JWT token...")
            logger.info(f"Using SECRET_KEY: {settings.SECRET_KEY[:10]}..." if settings.SECRET_KEY else "NO SECRET_KEY")

            payload = jwt.decode(token, settings.SECRET_KEY, algorithms=['HS256'])
            logger.info(f"JWT Token decoded successfully!")
            logger.info(f"Full payload: {payload}")

            client_id = payload.get('client_id')
            logger.info(f"Client ID from token: {client_id} (type: {type(client_id)})")

            if not client_id:
                logger.error("No client_id found in token payload")
                return None

            logger.info(f"Searching for client in database with ID: {client_id}")

            # Try both string and UUID formats
            try:
                client = Clients.objects.get(id=client_id, deleted=False)
                logger.info(f"Client found by direct ID match: {client.first_name} {client.last_name} (ID: {client.id})")
                return client
            except Clients.DoesNotExist:
                logger.error(f"Client not found with ID: {client_id}")

                # Let's see what clients exist
                all_clients = Clients.objects.filter(deleted=False)[:10]
                logger.info(f"Found {all_clients.count()} active clients in database:")
                for c in all_clients:
                    logger.info(f"  - ID: {c.id} (type: {type(c.id)}), Name: {c.first_name} {c.last_name}")

                return None

        except jwt.ExpiredSignatureError as e:
            logger.error(f"JWT Token has expired: {str(e)}")
            return None
        except jwt.InvalidTokenError as e:
            logger.error(f"Invalid JWT token: {str(e)}")
            logger.error(f"Token that failed: {token}")
            return None
        except Exception as e:
            logger.error(f"Unexpected error during token validation: {str(e)}")
            import traceback
            logger.error(f"Full traceback: {traceback.format_exc()}")
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
        logger.info("=" * 50)
        logger.info("STARTING TOKEN VALIDATION")
        logger.info("=" * 50)

        # Log all headers for debugging
        logger.info("ALL REQUEST HEADERS:")
        for header_name, header_value in request.headers.items():
            if 'authorization' in header_name.lower():
                logger.info(f"  {header_name}: {header_value[:50]}...")
            else:
                logger.info(f"  {header_name}: {header_value}")

        auth_header = request.headers.get('Authorization')
        logger.info(f"Authorization header: {auth_header}")

        if not auth_header:
            logger.error("NO Authorization header found")
            return None

        if not auth_header.startswith('Bearer '):
            logger.error(f"Invalid Authorization format. Expected 'Bearer <token>', got: {auth_header[:30]}...")
            return None

        token = auth_header.split(' ')[1]
        logger.info(f"Extracted token length: {len(token)}")
        logger.info(f"Token first 30 chars: {token[:30]}...")
        logger.info(f"Token last 30 chars: ...{token[-30:]}")

        try:
            logger.info("Attempting to decode JWT token...")
            logger.info(f"Using SECRET_KEY: {settings.SECRET_KEY[:10]}..." if settings.SECRET_KEY else "NO SECRET_KEY")

            payload = jwt.decode(token, settings.SECRET_KEY, algorithms=['HS256'])
            logger.info(f"JWT Token decoded successfully!")
            logger.info(f"Full payload: {payload}")

            client_id = payload.get('client_id')
            logger.info(f"Client ID from token: {client_id} (type: {type(client_id)})")

            if not client_id:
                logger.error("No client_id found in token payload")
                return None

            logger.info(f"Searching for client in database with ID: {client_id}")

            # Try both string and UUID formats
            try:
                client = Clients.objects.get(id=client_id, deleted=False)
                logger.info(f"Client found by direct ID match: {client.first_name} {client.last_name} (ID: {client.id})")
                return client
            except Clients.DoesNotExist:
                logger.error(f"Client not found with ID: {client_id}")

                # Let's see what clients exist
                all_clients = Clients.objects.filter(deleted=False)[:10]
                logger.info(f"Found {all_clients.count()} active clients in database:")
                for c in all_clients:
                    logger.info(f"  - ID: {c.id} (type: {type(c.id)}), Name: {c.first_name} {c.last_name}")

                return None

        except jwt.ExpiredSignatureError as e:
            logger.error(f"JWT Token has expired: {str(e)}")
            return None
        except jwt.InvalidTokenError as e:
            logger.error(f"Invalid JWT token: {str(e)}")
            logger.error(f"Token that failed: {token}")
            return None
        except Exception as e:
            logger.error(f"Unexpected error during token validation: {str(e)}")
            import traceback
            logger.error(f"Full traceback: {traceback.format_exc()}")
            return None


@api_view(['GET'])
@permission_classes([AllowAny])
def get_csrf_token(request):
    """Endpoint para obtener CSRF token si es necesario"""
    from django.middleware.csrf import get_token
    return Response({'csrfToken': get_token(request)})