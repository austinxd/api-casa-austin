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
    ClientProfileSerializer,
    ClientsSerializer
)
from .twilio_service import TwilioOTPService
import logging

logger = logging.getLogger('apps')


class ClientPublicRegisterView(APIView):
    """
    Endpoint público para registro de nuevos clientes
    No requiere autenticación
    """
    permission_classes = [AllowAny]
    serializer_class = ClientsSerializer
    
    def post(self, request):
        try:
            serializer = self.serializer_class(data=request.data)
            
            if serializer.is_valid():
                # Crear el cliente
                client = serializer.save()
                
                logger.info(f'Nuevo cliente registrado: {client.first_name} {client.last_name} - {client.number_doc}')
                
                return Response({
                    'success': True,
                    'message': 'Cliente registrado exitosamente',
                    'client': {
                        'id': str(client.id),
                        'document_type': client.document_type,
                        'number_doc': client.number_doc,
                        'first_name': client.first_name,
                        'last_name': client.last_name,
                        'email': client.email,
                        'tel_number': client.tel_number
                    }
                }, status=status.HTTP_201_CREATED)
            else:
                return Response({
                    'success': False,
                    'message': 'Error en los datos proporcionados',
                    'errors': serializer.errors
                }, status=status.HTTP_400_BAD_REQUEST)
                
        except Exception as e:
            logger.error(f'Error en registro público de cliente: {str(e)}')
            return Response({
                'success': False,
                'message': 'Error interno del servidor'
            }, status=status.HTTP_500_INTERNAL_SERVER_ERROR)


class ClientCompleteRegistrationView(APIView):
    """
    Endpoint para registro completo de nuevos clientes con verificación OTP
    Incluye creación del cliente y configuración de contraseña en un solo paso
    """
    permission_classes = [AllowAny]
    
    def post(self, request):
        try:
            # Validar datos requeridos
            required_fields = ['document_type', 'number_doc', 'first_name', 'last_name', 
                             'email', 'tel_number', 'sex', 'birth_date', 'otp_code', 
                             'password', 'confirm_password']
            
            for field in required_fields:
                if not request.data.get(field):
                    return Response({
                        'message': f'El campo {field} es requerido'
                    }, status=400)
            
            # Validar que las contraseñas coincidan
            if request.data.get('password') != request.data.get('confirm_password'):
                return Response({
                    'message': 'Las contraseñas no coinciden'
                }, status=400)
            
            # Verificar que el cliente no exista ya
            existing_client = Clients.objects.filter(
                document_type=request.data.get('document_type'),
                number_doc=request.data.get('number_doc'),
                deleted=False
            ).first()
            
            if existing_client:
                return Response({
                    'message': 'Ya existe un cliente con este documento'
                }, status=400)
            
            # Verificar OTP con Twilio
            twilio_service = TwilioOTPService()
            tel_number = request.data.get('tel_number')
            otp_code = request.data.get('otp_code')
            
            if not twilio_service.verify_otp_code(tel_number, otp_code):
                return Response({
                    'message': 'Código OTP inválido o expirado'
                }, status=400)
            
            # Crear el cliente con todos los datos
            client_data = {
                'document_type': request.data.get('document_type'),
                'number_doc': request.data.get('number_doc'),
                'first_name': request.data.get('first_name'),
                'last_name': request.data.get('last_name'),
                'email': request.data.get('email'),
                'tel_number': tel_number,
                'sex': request.data.get('sex'),
                'birth_date': request.data.get('birth_date'),
                'password': make_password(request.data.get('password')),
                'is_password_set': True
            }
            
            # Usar el serializer para validar y crear
            serializer = ClientsSerializer(data=client_data)
            
            if serializer.is_valid():
                client = serializer.save()
                
                logger.info(f'Cliente registrado completamente: {client.first_name} {client.last_name} - {client.number_doc}')
                
                return Response({
                    'success': True,
                    'message': 'Cuenta creada exitosamente',
                    'client': {
                        'id': str(client.id),
                        'document_type': client.document_type,
                        'number_doc': client.number_doc,
                        'first_name': client.first_name,
                        'last_name': client.last_name,
                        'email': client.email
                    }
                }, status=status.HTTP_201_CREATED)
            else:
                return Response({
                    'success': False,
                    'message': 'Error en los datos proporcionados',
                    'errors': serializer.errors
                }, status=status.HTTP_400_BAD_REQUEST)
                
        except Exception as e:
            logger.error(f'Error en registro completo de cliente: {str(e)}')
            return Response({
                'success': False,
                'message': 'Error interno del servidor'
            }, status=status.HTTP_500_INTERNAL_SERVER_ERROR)


# Custom JWT Authentication for Clients
class ClientJWTAuthentication(JWTAuthentication):
    def get_user(self, validated_token):
        """
        Override to get client instead of user
        """
        try:
            # Intentar primero con client_id (nuestro claim personalizado)
            client_id = validated_token.get('client_id')
            if not client_id:
                # Si no hay client_id, intentar con user_id (claim estándar)
                client_id = validated_token.get('user_id')
            
            if client_id:
                return Clients.objects.get(id=client_id, deleted=False)
        except Clients.DoesNotExist:
            pass
        return None

class ClientVerifyDocumentView(APIView):
    permission_classes = [AllowAny]
    authentication_classes = []  # Deshabilitar autenticación completamente
    http_method_names = ['post']  # Explicitly allow POST method

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


class ClientRequestOTPForRegistrationView(APIView):
    """
    Endpoint para solicitar OTP durante el registro de nuevos clientes
    No requiere que el cliente exista previamente
    """
    permission_classes = [AllowAny]

    def post(self, request):
        tel_number = request.data.get('tel_number', '').strip()
        
        if not tel_number:
            return Response({'message': 'Número de teléfono es requerido'}, status=400)

        # Validar que el número tenga al menos dígitos
        clean_number = ''.join(filter(str.isdigit, tel_number))
        if len(clean_number) < 9:
            return Response({'message': 'El número de teléfono debe tener al menos 9 dígitos'}, status=400)

        # Usar Twilio Verify Service para enviar OTP (el formateo se hace internamente)
        twilio_service = TwilioOTPService()

        if twilio_service.send_otp_with_verify(tel_number):
            # Enmascarar el número para mostrar en la respuesta
            masked_number = f"***{tel_number[-4:]}" if len(tel_number) > 4 else tel_number
            
            return Response({
                'message': 'Código de verificación enviado',
                'phone_masked': masked_number
            })
        else:
            return Response({
                'message': 'Error al enviar código de verificación. Verifica que el número sea válido'
            }, status=500)


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

            # Actualizar último login sin disparar la audiencia de Meta
            client.last_login = timezone.now()
            client.save(update_fields=['last_login'])

            # Generar tokens using Simple JWT
            refresh = RefreshToken()
            refresh['client_id'] = str(client.id)
            refresh['user_id'] = str(client.id)  # Agregar user_id estándar
            refresh['document_type'] = client.document_type
            refresh['number_doc'] = client.number_doc

            access_token = refresh.access_token
            access_token['client_id'] = str(client.id)
            access_token['user_id'] = str(client.id)  # Agregar user_id estándar
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
        import uuid
        request_id = str(uuid.uuid4())[:8]
        logger.info(f"ClientProfileView: Profile request received [ID: {request_id}]")

        # Get client from JWT token
        try:
            authenticator = ClientJWTAuthentication()
            auth_result = authenticator.authenticate(request)

            if auth_result is None:
                logger.error(f"ClientProfileView: Authentication failed [ID: {request_id}]")
                return Response({'message': 'Token inválido'}, status=401)

            user, validated_token = auth_result  # Unpack the result

            logger.info(f"ClientProfileView: Returning profile for client {user.id} [ID: {request_id}]")
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
        import uuid
        request_id = str(uuid.uuid4())[:8]
        logger.info(f"ClientReservationsView: Request received [ID: {request_id}]")

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


class ClientPointsView(APIView):
    authentication_classes = [ClientJWTAuthentication]
    permission_classes = [AllowAny]

    def get(self, request):
        try:
            authenticator = ClientJWTAuthentication()
            auth_result = authenticator.authenticate(request)

            if auth_result is None:
                return Response({'message': 'Token requerido'}, status=401)

            client, validated_token = auth_result

            if not client:
                return Response({'message': 'Token inválido'}, status=401)

            # Por ahora devolvemos datos mock, luego puedes implementar tu lógica real
            return Response({
                'total_points': 0.0,
                'recent_transactions': []
            })

        except (InvalidToken, TokenError) as e:
            return Response({'message': 'Token inválido'}, status=401)
        except Exception as e:
            return Response({'message': 'Error interno del servidor'}, status=500)


class ClientRedeemPointsView(APIView):
    authentication_classes = [ClientJWTAuthentication]
    permission_classes = [AllowAny]

    def post(self, request):
        try:
            authenticator = ClientJWTAuthentication()
            auth_result = authenticator.authenticate(request)

            if auth_result is None:
                return Response({'message': 'Token requerido'}, status=401)

            client, validated_token = auth_result

            if not client:
                return Response({'message': 'Token inválido'}, status=401)

            points_to_redeem = request.data.get('points_to_redeem', 0)

            # Por ahora devolvemos éxito, luego implementas tu lógica real
            return Response({
                'message': 'Puntos canjeados exitosamente',
                'points_redeemed': points_to_redeem,
                'new_balance': 0.0
            })

        except (InvalidToken, TokenError) as e:
            return Response({'message': 'Token inválido'}, status=401)
        except Exception as e:
            return Response({'message': 'Error interno del servidor'}, status=500)


@api_view(['GET'])
@permission_classes([AllowAny])
def get_csrf_token(request):
    """Endpoint para obtener CSRF token si es necesario"""
    from django.middleware.csrf import get_token
    return Response({'csrfToken': get_token(request)})