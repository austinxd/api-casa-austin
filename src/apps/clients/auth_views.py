import jwt
from datetime import datetime, timedelta
from django.conf import settings
from django.contrib.auth.hashers import make_password, check_password
from django.utils import timezone
from rest_framework import status
from rest_framework.views import APIView
from rest_framework.response import Response
from rest_framework.permissions import AllowAny, IsAuthenticated
from rest_framework.decorators import api_view, permission_classes
from rest_framework_simplejwt.tokens import RefreshToken
from rest_framework_simplejwt.authentication import JWTAuthentication
from rest_framework_simplejwt.exceptions import InvalidToken, TokenError

from .models import Clients
from .serializers import (ClientAuthVerifySerializer,
                          ClientAuthRequestOTPSerializer,
                          ClientAuthSetPasswordSerializer,
                          ClientAuthLoginSerializer, ClientProfileSerializer,
                          ClientsSerializer)
from .twilio_service import TwilioOTPService
from .whatsapp_service import WhatsAppOTPService
import os
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

                logger.info(
                    f'Nuevo cliente registrado: {client.first_name} {client.last_name} - {client.number_doc}'
                )

                return Response(
                    {
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
                    },
                    status=status.HTTP_201_CREATED)
            else:
                return Response(
                    {
                        'success': False,
                        'message': 'Error en los datos proporcionados',
                        'errors': serializer.errors
                    },
                    status=status.HTTP_400_BAD_REQUEST)

        except Exception as e:
            logger.error(f'Error en registro público de cliente: {str(e)}')
            return Response(
                {
                    'success': False,
                    'message': 'Error interno del servidor'
                },
                status=status.HTTP_500_INTERNAL_SERVER_ERROR)


class ClientPublicRegistrationView(APIView):
    """
    Endpoint para registro público de nuevos clientes
    Puede crear el cliente con o sin contraseña dependiendo de los datos enviados
    """
    permission_classes = [AllowAny]

    def post(self, request):
        try:
            # Validar datos requeridos básicos
            required_fields = [
                'document_type', 'number_doc', 'first_name', 'tel_number'
            ]

            for field in required_fields:
                if not request.data.get(field):
                    return Response(
                        {'message': f'El campo {field} es requerido'},
                        status=400)

            # Verificar que el cliente no exista ya
            existing_client = Clients.objects.filter(
                document_type=request.data.get('document_type'),
                number_doc=request.data.get('number_doc'),
                deleted=False).first()

            if existing_client:
                return Response(
                    {'message': 'Cliente ya existe con este documento'},
                    status=400)

            # Validar contraseña si se proporciona
            password = request.data.get('password')
            confirm_password = request.data.get('confirm_password')

            if password and confirm_password:
                if password != confirm_password:
                    return Response(
                        {'message': 'Las contraseñas no coinciden'},
                        status=400)

                if len(password) < 8:
                    return Response(
                        {'message': 'La contraseña debe tener al menos 8 caracteres'},
                        status=400)

            # Obtener el código de referido del request si existe
            referral_code = request.data.get('referral_code')
            referrer = None
            if referral_code:
                referrer = Clients.get_client_by_referral_code(referral_code)
                if not referrer:
                    logger.warning(f"Código de referido {referral_code} no encontrado")

            # Crear el cliente
            client_data = {
                'document_type': request.data.get('document_type'),
                'number_doc': request.data.get('number_doc'),
                'first_name': request.data.get('first_name'),
                'last_name': request.data.get('last_name', ''),
                'email': request.data.get('email', ''),
                'tel_number': request.data.get('tel_number'),
                'sex': request.data.get('sex', 'm'),
                'date': request.data.get('date'),
            }

            # Agregar referido si existe (usar el ID del referrer)
            if referrer:
                client_data['referred_by'] = referrer.id

            # Configurar contraseña si se proporciona
            if password:
                client_data['password'] = make_password(password)
                client_data['is_password_set'] = True
            else:
                client_data['is_password_set'] = False

            # Crear el cliente usando el serializer
            serializer = ClientsSerializer(data=client_data)
            if serializer.is_valid():
                client = serializer.save()

                logger.info(f"Cliente creado exitosamente: {client.first_name} ({client.number_doc})")

                if referrer:
                    logger.info(f"Cliente referido por: {referrer.first_name} (Código: {referral_code})")

                response_data = {
                    'success': True,
                    'message': 'Cliente registrado exitosamente',
                    'client_id': client.id,
                    'requires_password_setup': not bool(password)
                }

                if password:
                    response_data['message'] = 'Cliente registrado exitosamente con contraseña'
                    logger.info(f"Cliente {client.first_name} registrado con contraseña configurada")

                return Response(response_data, status=201)
            else:
                return Response({
                    'success': False,
                    'message': 'Error en los datos enviados',
                    'errors': serializer.errors
                }, status=400)

        except Exception as e:
            logger.error(f"Error en registro público: {str(e)}")
            return Response({
                'success': False,
                'message': 'Error interno del servidor'
            }, status=500)


class ClientCompleteRegistrationView(APIView):
    """
    Endpoint para registro completo de nuevos clientes con verificación OTP
    Incluye creación del cliente y configuración de contraseña en un solo paso
    """
    permission_classes = [AllowAny]

    def post(self, request):
        try:
            # Validar datos requeridos
            required_fields = [
                'document_type', 'number_doc', 'first_name', 'last_name',
                'email', 'tel_number', 'sex', 'date', 'otp_code',
                'password', 'confirm_password'
            ]

            for field in required_fields:
                if not request.data.get(field):
                    return Response(
                        {'message': f'El campo {field} es requerido'},
                        status=400)

            # Validar que las contraseñas coincidan
            if request.data.get('password') != request.data.get(
                    'confirm_password'):
                return Response({'message': 'Las contraseñas no coinciden'},
                                status=400)

            # Verificar que el cliente no exista ya
            existing_client = Clients.objects.filter(
                document_type=request.data.get('document_type'),
                number_doc=request.data.get('number_doc'),
                deleted=False).first()

            # Obtener el código de referido del request si existe
            referral_code = request.data.get('referral_code')
            referrer = None

            if referral_code:
                try:
                    referrer = Clients.objects.get(referral_code=referral_code,
                                                   deleted=False)
                except Clients.DoesNotExist:
                    return Response({'message': 'Código de referido inválido'},
                                    status=400)

            # Verificar si el cliente existe pero está eliminado
            deleted_client = Clients.objects.filter(
                document_type=request.data.get('document_type'),
                number_doc=request.data.get('number_doc'),
                deleted=True).first()

            if existing_client:
                return Response(
                    {'message': 'Ya existe un cliente con este documento'},
                    status=400)

            # Si existe un cliente eliminado, reactivarlo en lugar de crear uno nuevo
            if deleted_client:
                # Actualizar los datos del cliente eliminado
                deleted_client.first_name = request.data.get('first_name')
                deleted_client.last_name = request.data.get('last_name')
                deleted_client.email = request.data.get('email')
                deleted_client.tel_number = request.data.get('tel_number')
                deleted_client.sex = request.data.get('sex')
                deleted_client.date = request.data.get('date')
                deleted_client.password = make_password(
                    request.data.get('password'))
                deleted_client.is_password_set = True
                deleted_client.deleted = False  # Reactivar el cliente

                # Manejar referido en reactivación
                if referrer:
                    deleted_client.referred_by = referrer
                    logger.info(
                        f'Cliente reactivado con referido: {deleted_client.first_name} {deleted_client.last_name} - Referido por: {referrer.first_name}'
                    )

                deleted_client.save()

                logger.info(
                    f'Cliente reactivado: {deleted_client.first_name} {deleted_client.last_name} - {deleted_client.number_doc}'
                )

                response_data = {
                    'success': True,
                    'message': 'Cuenta reactivada exitosamente',
                    'client': {
                        'id': str(deleted_client.id),
                        'document_type': deleted_client.document_type,
                        'number_doc': deleted_client.number_doc,
                        'first_name': deleted_client.first_name,
                        'last_name': deleted_client.last_name,
                        'email': deleted_client.email
                    }
                }

                # Agregar información del referido si existe
                if referrer:
                    response_data['referrer'] = {
                        'id':
                        str(referrer.id),
                        'name':
                        f"{referrer.first_name} {referrer.last_name or ''}".
                        strip(),
                        'referral_code':
                        referral_code
                    }

                return Response(response_data, status=status.HTTP_201_CREATED)

            # Verificar OTP según el servicio configurado
            otp_service_provider = os.getenv('OTP_SERVICE_PROVIDER', 'twilio').lower()
            tel_number = request.data.get('tel_number')
            otp_code = request.data.get('otp_code')

            if otp_service_provider == 'whatsapp':
                # Verificar OTP almacenado en cache
                from django.core.cache import cache
                cache_key = f"whatsapp_otp_{tel_number}"
                stored_otp = cache.get(cache_key)

                if not stored_otp or stored_otp != otp_code:
                    return Response({'message': 'Código OTP inválido o expirado'},
                                    status=400)

                # Limpiar el código del cache
                cache.delete(cache_key)
            else:
                # Verificar OTP con Twilio
                twilio_service = TwilioOTPService()

                if not twilio_service.verify_otp_code(tel_number, otp_code):
                    return Response({'message': 'Código OTP inválido o expirado'},
                                    status=400)

            # Crear el cliente con todos los datos
            client_data = {
                'document_type': request.data.get('document_type'),
                'number_doc': request.data.get('number_doc'),
                'first_name': request.data.get('first_name'),
                'last_name': request.data.get('last_name'),
                'email': request.data.get('email'),
                'tel_number': tel_number,
                'sex': request.data.get('sex'),
                'date': request.data.get('date'),
                'password': make_password(request.data.get('password')),
                'is_password_set': True
            }

            # Usar el serializer para validar y crear
            serializer = ClientsSerializer(data=client_data)

            if serializer.is_valid():
                client = serializer.save()

                # Asignar el referido si existe
                if referrer:
                    client.referred_by = referrer
                    client.save()
                    logger.info(
                        f'Cliente registrado con referido: {client.first_name} {client.last_name} - Referido por: {referrer.first_name}'
                    )

                logger.info(
                    f'Cliente registrado completamente: {client.first_name} {client.last_name} - {client.number_doc}'
                )

                return Response(
                    {
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
                    },
                    status=status.HTTP_201_CREATED)
            else:
                return Response(
                    {
                        'success': False,
                        'message': 'Error en los datos proporcionados',
                        'errors': serializer.errors
                    },
                    status=status.HTTP_400_BAD_REQUEST)

        except Exception as e:
            logger.error(f'Error en registro completo de cliente: {str(e)}')
            return Response(
                {
                    'success': False,
                    'message': 'Error interno del servidor'
                },
                status=status.HTTP_500_INTERNAL_SERVER_ERROR)


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

        # Validar formato según tipo de documento
        document_type = serializer.validated_data['document_type']
        number_doc = serializer.validated_data['number_doc']

        if document_type == 'dni' and (len(number_doc) != 8 or not number_doc.isdigit()):
            return Response({'message': 'El DNI debe tener exactamente 8 dígitos'}, status=400)
        elif document_type == 'cex' and (len(number_doc) < 9 or len(number_doc) > 12):
            return Response({'message': 'El Carnet de Extranjería debe tener entre 9 y 12 caracteres'}, status=400)
        elif document_type == 'pas' and (len(number_doc) < 8 or len(number_doc) > 9):
            return Response({'message': 'El Pasaporte debe tener entre 8 y 9 caracteres'}, status=400)
        elif document_type == 'ruc' and (len(number_doc) != 11 or not number_doc.isdigit()):
            return Response({'message': 'El RUC debe tener exactamente 11 dígitos'}, status=400)

        try:
            client = Clients.objects.get(
                document_type=serializer.validated_data['document_type'],
                number_doc=serializer.validated_data['number_doc'],
                deleted=False)

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
            return Response(
                {
                    'exists': False,
                    'message': 'Cliente no encontrado en nuestros registros'
                },
                status=404)


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
                deleted=False)

            if not client.tel_number:
                return Response(
                    {
                        'message':
                        'No hay número de teléfono registrado para este cliente'
                    },
                    status=400)

            # Verificar qué servicio usar
            otp_service_provider = os.getenv('OTP_SERVICE_PROVIDER', 'twilio').lower()

            if otp_service_provider == 'whatsapp':
                whatsapp_service = WhatsAppOTPService()
                otp_code = whatsapp_service.generate_otp_code()

                # Almacenar el código OTP temporalmente
                from django.core.cache import cache
                cache_key = f"whatsapp_otp_{client.tel_number}"
                cache.set(cache_key, otp_code, 600)  # 10 minutos

                if whatsapp_service.send_otp_template(client.tel_number, otp_code):
                    return Response({
                        'message': 'Código de verificación enviado por WhatsApp',
                        'phone_masked': f"***{client.tel_number[-4:]}"
                    })
                else:
                    return Response(
                        {'message': 'Error al enviar código de verificación por WhatsApp'},
                        status=500)
            else:
                # Usar Twilio Verify Service
                twilio_service = TwilioOTPService()

                if twilio_service.send_otp_with_verify(client.tel_number):
                    return Response({
                        'message': 'Código de verificación enviado',
                        'phone_masked': f"***{client.tel_number[-4:]}"
                    })
                else:
                    return Response(
                        {'message': 'Error al enviar código de verificación'},
                        status=500)

        except Clients.DoesNotExist:
            return Response({'message': 'Cliente no encontrado'}, status=404)


class ClientRequestOTPForRegistrationView(APIView):
    """
    Endpoint para solicitar OTP durante el registro de nuevos clientes
    No requiere que el cliente exista previamente
    """
    permission_classes = [AllowAny]

    def post(self, request):
        tel_number = request.data.get('tel_number', '').strip()

        if not tel_number:
            return Response({'message': 'Número de teléfono es requerido'},
                            status=400)

        # Validar que el número tenga al menos dígitos
        clean_number = ''.join(filter(str.isdigit, tel_number))
        if len(clean_number) < 9:
            return Response(
                {
                    'message':
                    'El número de teléfono debe tener al menos 9 dígitos'
                },
                status=400)

        # Verificar qué servicio usar
        otp_service_provider = os.getenv('OTP_SERVICE_PROVIDER', 'twilio').lower()

        if otp_service_provider == 'whatsapp':
            whatsapp_service = WhatsAppOTPService()

            # Verificar configuración antes de enviar
            config_ok = whatsapp_service.test_whatsapp_config()
            if not config_ok:
                logger.error("Configuración de WhatsApp no válida")

            otp_code = whatsapp_service.generate_otp_code()

            # Almacenar el código OTP temporalmente
            from django.core.cache import cache
            cache_key = f"whatsapp_otp_{tel_number}"
            cache.set(cache_key, otp_code, 600)  # 10 minutos

            if whatsapp_service.send_otp_template(tel_number, otp_code):
                # Enmascarar el número para mostrar en la respuesta
                masked_number = f"***{tel_number[-4:]}" if len(tel_number) > 4 else tel_number

                return Response({
                    'message': 'Código de verificación enviado por WhatsApp',
                    'phone_masked': masked_number
                })
            else:
                return Response(
                    {
                        'message':
                        'Error al enviar código de verificación por WhatsApp. Verifica que el número sea válido'
                    },
                    status=500)
        else:
            # Usar Twilio Verify Service para enviar OTP (el formateo se hace internamente)
            twilio_service = TwilioOTPService()

            if twilio_service.send_otp_with_verify(tel_number):
                # Enmascarar el número para mostrar en la respuesta
                masked_number = f"***{tel_number[-4:]}" if len(
                    tel_number) > 4 else tel_number

                return Response({
                    'message': 'Código de verificación enviado',
                    'phone_masked': masked_number
                })
            else:
                return Response(
                    {
                        'message':
                        'Error al enviar código de verificación. Verifica que el número sea válido'
                    },
                    status=500)


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
                deleted=False)

            # Verificar OTP según el servicio configurado
            otp_service_provider = os.getenv('OTP_SERVICE_PROVIDER', 'twilio').lower()
            otp_code = serializer.validated_data['otp_code']

            if otp_service_provider == 'whatsapp':
                # Verificar OTP almacenado en cache
                from django.core.cache import cache
                cache_key = f"whatsapp_otp_{client.tel_number}"
                stored_otp = cache.get(cache_key)

                if not stored_otp or stored_otp != otp_code:
                    return Response({'message': 'Código OTP inválido o expirado'},
                                    status=400)

                # Limpiar el código del cache
                cache.delete(cache_key)
            else:
                # Verificar OTP con Twilio
                twilio_service = TwilioOTPService()

                if not twilio_service.verify_otp_code(client.tel_number, otp_code):
                    return Response({'message': 'Código OTP inválido o expirado'},
                                    status=400)

            # Configurar contraseña
            client.password = make_password(
                serializer.validated_data['password'])
            client.is_password_set = True
            client.otp_code = None
            client.otp_expires_at = None
            client.save()

            return Response({'message': 'Contraseña configurada exitosamente'})

        except Clients.DoesNotExist:
            return Response({'message': 'Cliente no encontrado'}, status=404)


class ClientForgotPasswordView(APIView):
    permission_classes = [AllowAny]

    def post(self, request):
        """Enviar código OTP para recuperar contraseña"""
        serializer = ClientAuthRequestOTPSerializer(data=request.data)
        if not serializer.is_valid():
            return Response({'message': 'Datos inválidos'}, status=400)

        try:
            client = Clients.objects.get(
                document_type=serializer.validated_data['document_type'],
                number_doc=serializer.validated_data['number_doc'],
                deleted=False)

            if not client.is_password_set or not client.password:
                return Response(
                    {
                        'message': 'Este cliente no tiene una contraseña configurada. Use el endpoint de configuración inicial.'
                    },
                    status=400)

            # Generar y enviar OTP
            otp_service_provider = os.getenv('OTP_SERVICE_PROVIDER', 'twilio').lower()

            if otp_service_provider == 'whatsapp':
                whatsapp_service = WhatsAppOTPService()
                # Generate OTP code for WhatsApp
                otp_code = whatsapp_service.generate_otp_code()
                
                # Almacenar el código OTP temporalmente
                from django.core.cache import cache
                cache_key = f"whatsapp_otp_{client.tel_number}"
                cache.set(cache_key, otp_code, 600)  # 10 minutos
                
                # Enviar usando el método correcto
                if not whatsapp_service.send_otp_template(client.tel_number, otp_code):
                    return Response({
                        'message': 'Error al enviar código de verificación por WhatsApp'
                    }, status=500)
            else:
                # Usar Twilio SMS
                twilio_service = TwilioOTPService()
                if not twilio_service.send_otp_code(client.tel_number):
                    return Response({
                        'message': 'Error al enviar código de verificación SMS. Verifique que el número sea válido'
                    }, status=500)

            return Response({
                'message': f'Código de verificación enviado a {client.tel_number} para recuperar contraseña'
            })

        except Clients.DoesNotExist:
            return Response({'message': 'Cliente no encontrado'}, status=404)


class ClientResetPasswordView(APIView):
    permission_classes = [AllowAny]

    def post(self, request):
        """Reset password using OTP code"""
        serializer = ClientAuthSetPasswordSerializer(data=request.data)
        if not serializer.is_valid():
            return Response({'message': 'Datos inválidos'}, status=400)

        try:
            client = Clients.objects.get(
                document_type=serializer.validated_data['document_type'],
                number_doc=serializer.validated_data['number_doc'],
                deleted=False)

            if not client.is_password_set or not client.password:
                return Response(
                    {
                        'message': 'Este cliente no tiene una contraseña configurada. Use el endpoint de configuración inicial.'
                    },
                    status=400)

            # Verificar OTP según el servicio configurado
            otp_service_provider = os.getenv('OTP_SERVICE_PROVIDER', 'twilio').lower()
            otp_code = serializer.validated_data['otp_code']

            if otp_service_provider == 'whatsapp':
                # Verificar OTP almacenado en cache
                from django.core.cache import cache
                cache_key = f"whatsapp_otp_{client.tel_number}"
                stored_otp = cache.get(cache_key)

                if not stored_otp or stored_otp != otp_code:
                    return Response({'message': 'Código OTP inválido o expirado'},
                                    status=400)

                # Limpiar el código del cache
                cache.delete(cache_key)
            else:
                # Verificar OTP con Twilio
                twilio_service = TwilioOTPService()

                if not twilio_service.verify_otp_code(client.tel_number, otp_code):
                    return Response({'message': 'Código OTP inválido o expirado'},
                                    status=400)

            # Validar nueva contraseña
            password = serializer.validated_data['password']
            if len(password) < 8:
                return Response(
                    {'message': 'La contraseña debe tener al menos 8 caracteres'},
                    status=400)

            # Actualizar contraseña
            client.password = make_password(password)
            client.otp_code = None
            client.otp_expires_at = None
            client.save()

            logger.info(f"Password reset successful for client {client.id}")

            return Response({'message': 'Contraseña actualizada exitosamente'})

        except Clients.DoesNotExist:
            return Response({'message': 'Cliente no encontrado'}, status=404)


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
                deleted=False)

            if not client.is_password_set or not client.password:
                return Response(
                    {
                        'message':
                        'Este cliente no ha configurado una contraseña'
                    },
                    status=400)

            if not check_password(serializer.validated_data['password'],
                                  client.password):
                return Response({'message': 'Credenciales inválidas'},
                                status=401)

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
            access_token['user_id'] = str(
                client.id)  # Agregar user_id estándar
            access_token['document_type'] = client.document_type
            access_token['number_doc'] = client.number_doc

            return Response({
                'token': str(access_token),
                'refresh': str(refresh),
                'client': ClientProfileSerializer(client).data
            })

        except Clients.DoesNotExist:
            return Response({'message': 'Credenciales inválidas'}, status=401)


class ClientProfileView(APIView):
    authentication_classes = [ClientJWTAuthentication]
    permission_classes = [AllowAny]

    def get(self, request):
        import uuid
        request_id = str(uuid.uuid4())[:8]
        logger.info(
            f"ClientProfileView: Profile request received [ID: {request_id}]")

        # Get client from JWT token
        try:
            authenticator = ClientJWTAuthentication()
            auth_result = authenticator.authenticate(request)

            if auth_result is None:
                logger.error(
                    f"ClientProfileView: Authentication failed [ID: {request_id}]"
                )
                return Response({'message': 'Token inválido'}, status=401)

            user, validated_token = auth_result  # Unpack the result

            logger.info(
                f"ClientProfileView: Returning profile for client {user.id} [ID: {request_id}]"
            )
            return Response(ClientProfileSerializer(user).data)

        except (InvalidToken, TokenError) as e:
            logger.error(
                f"ClientProfileView: Token validation failed: {str(e)}")
            return Response({'message': 'Token inválido'}, status=401)
        except Exception as e:
            logger.error(f"ClientProfileView: Unexpected error: {str(e)}")
            return Response({'message': 'Error interno del servidor'},
                            status=500)


class ClientReservationsView(APIView):
    authentication_classes = [ClientJWTAuthentication]
    permission_classes = [AllowAny]

    def get(self, request):
        import uuid
        request_id = str(uuid.uuid4())[:8]
        logger.info(
            f"ClientReservationsView: Request received [ID: {request_id}]")

        # Get client from JWT token
        try:
            authenticator = ClientJWTAuthentication()
            client, validated_token = authenticator.authenticate(request)

            if not client:
                logger.error("ClientReservationsView: Authentication failed")
                return Response({'message': 'Token inválido'}, status=401)

            from apps.reservation.models import Reservation
            from apps.reservation.serializers import ReservationListSerializer
            from datetime import date, time

            # Filtrar reservaciones del cliente autenticado
            reservations = Reservation.objects.filter(
                client=client, deleted=False).order_by('-check_in_date')

            # Clasificar reservas en próximas y pasadas
            upcoming_reservations = []
            past_reservations = []

            # Obtener la fecha y hora actual en la zona horaria del proyecto
            from django.conf import settings
            import pytz

            # Obtener timezone del proyecto
            project_tz = pytz.timezone(settings.TIME_ZONE)
            now_utc = timezone.now()
            now = now_utc.astimezone(project_tz)
            today = now.date()
            checkout_time = time(11, 0)  # 11 AM

            for reservation in reservations:
                # Si checkout es después de hoy, definitivamente es upcoming
                if reservation.check_out_date > today:
                    upcoming_reservations.append(reservation)
                # Si checkout es hoy, verificar la hora
                elif reservation.check_out_date == today:
                    # Si son antes de las 11 AM, aún es upcoming
                    if now.time() < checkout_time:
                        upcoming_reservations.append(reservation)
                    else:
                        past_reservations.append(reservation)
                else:
                    # Si checkout fue antes de hoy, es pasada
                    past_reservations.append(reservation)

            # Serializar las reservas
            upcoming_serializer = ReservationListSerializer(
                upcoming_reservations, many=True)
            past_serializer = ReservationListSerializer(past_reservations,
                                                        many=True)

            return Response({
                'upcoming_reservations': upcoming_serializer.data,
                'past_reservations': past_serializer.data
            })

        except (InvalidToken, TokenError) as e:
            logger.error(
                f"ClientReservationsView: Token validation failed: {str(e)}")
            return Response({'message': 'Token inválido'}, status=401)
        except Exception as e:
            logger.error(
                f"ClientReservationsView: Error getting reservations: {str(e)}"
            )
            return Response(
                {
                    'success': False,
                    'message': 'Error al obtener las reservaciones'
                },
                status=500)


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

            # Obtener puntos disponibles del cliente
            available_points = client.get_available_points()

            # Obtener historial de transacciones recientes (últimas 10)
            from .models import ClientPoints
            recent_transactions = ClientPoints.objects.filter(
                client=client, 
                deleted=False
            ).order_by('-created')[:10]

            # Serializar las transacciones
            from .serializers import ClientPointsSerializer
            transactions_data = ClientPointsSerializer(recent_transactions, many=True).data

            return Response({
                'total_points': float(available_points), 
                'recent_transactions': transactions_data
            })

        except (InvalidToken, TokenError) as e:
            return Response({'message': 'Token inválido'}, status=401)
        except Exception as e:
            return Response({'message': 'Error obteniendo puntos'}, status=500)


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
            return Response({'message': 'Error interno del servidor'},
                            status=500)


@api_view(['GET'])
@permission_classes([AllowAny])
def get_csrf_token(request):
    """Endpoint para obtener CSRF token si es necesario"""
    from django.middleware.csrf import get_token
    return Response({'csrfToken': get_token(request)})


class ClientLinkFacebookView(APIView):
    """Endpoint para vincular cuenta de Facebook del cliente"""
    authentication_classes = [ClientJWTAuthentication]
    permission_classes = [IsAuthenticated]
    
    def post(self, request):
        try:
            # Cliente ya autenticado por DRF
            client = request.user
            
            # Obtener access token de Facebook del request
            access_token = request.data.get('access_token')
            
            if not access_token:
                return Response({
                    'message': 'access_token es requerido'
                }, status=400)
            
            # Validar access token con Facebook Graph API
            import requests
            from django.conf import settings
            
            # Obtener datos del perfil
            graph_url = f"https://graph.facebook.com/me?fields=id,name,email,picture.type(large)"
            
            try:
                graph_response = requests.get(graph_url, headers={'Authorization': f'Bearer {access_token}'}, timeout=10)
                graph_response.raise_for_status()
                profile_data = graph_response.json()
                facebook_id = profile_data.get('id')
                
                if not facebook_id:
                    return Response({
                        'message': 'No se pudo obtener el ID de Facebook'
                    }, status=400)
                
                # Verificar si ya está vinculado a este cliente (hacer idempotente)
                if client.facebook_id == facebook_id:
                    return Response({
                        'success': True,
                        'message': 'Cuenta de Facebook ya está vinculada',
                        'facebook_linked': True,
                        'profile_data': {
                            'name': client.facebook_profile_data.get('name') if client.facebook_profile_data else None,
                            'picture': client.get_facebook_profile_picture()
                        }
                    })
                
                # Verificar que el Facebook ID no esté ya vinculado a otra cuenta
                existing_client = Clients.get_client_by_facebook_id(facebook_id)
                if existing_client:
                    return Response({
                        'message': 'Esta cuenta de Facebook ya está vinculada a otro usuario'
                    }, status=409)
                
                # Validar el token con debug_token - OBLIGATORIO para seguridad
                app_id = getattr(settings, 'FACEBOOK_APP_ID', None)
                app_secret = getattr(settings, 'FACEBOOK_APP_SECRET', None)
                app_access_token = getattr(settings, 'FACEBOOK_APP_ACCESS_TOKEN', None)
                
                # Generar app access token si no existe
                if not app_access_token and app_id and app_secret:
                    app_access_token = f"{app_id}|{app_secret}"
                
                if not app_access_token or not app_id:
                    return Response({
                        'message': 'Facebook OAuth no está configurado correctamente'
                    }, status=503)
                
                debug_url = f"https://graph.facebook.com/debug_token?input_token={access_token}&access_token={app_access_token}"
                debug_response = requests.get(debug_url, timeout=10)
                debug_response.raise_for_status()
                debug_data = debug_response.json()
                
                token_data = debug_data.get('data', {})
                
                # Validaciones obligatorias
                if not token_data.get('is_valid'):
                    return Response({
                        'message': 'Token de Facebook inválido'
                    }, status=400)
                
                # Verificar que el token sea para nuestra app
                if str(token_data.get('app_id')) != str(app_id):
                    return Response({
                        'message': 'Token no válido para esta aplicación'
                    }, status=400)
                
                # Verificar que el user_id coincida
                if str(token_data.get('user_id')) != str(facebook_id):
                    return Response({
                        'message': 'Token no coincide con el usuario de Facebook'
                    }, status=400)
                
                # Verificar que no esté expirado
                expires_at = token_data.get('expires_at')
                if expires_at and expires_at < int(timezone.now().timestamp()):
                    return Response({
                        'message': 'Token de Facebook expirado'
                    }, status=400)
                
                # Vincular la cuenta de Facebook con transacción atómica
                from django.db import transaction, IntegrityError
                
                try:
                    with transaction.atomic():
                        # Verificar de nuevo dentro de la transacción para evitar race conditions
                        existing_client = Clients.get_client_by_facebook_id(facebook_id)
                        if existing_client:
                            return Response({
                                'message': 'Esta cuenta de Facebook ya está vinculada a otro usuario'
                            }, status=409)
                        
                        client.link_facebook_account(facebook_id, profile_data)
                        
                        logger.info(f'Cliente {client.first_name} (ID: {client.id}) vinculó su cuenta de Facebook (FB ID: {facebook_id})')
                        
                        return Response({
                            'success': True,
                            'message': 'Cuenta de Facebook vinculada exitosamente',
                            'facebook_linked': True,
                            'profile_data': {
                                'name': profile_data.get('name'),
                                'picture': client.get_facebook_profile_picture()
                            }
                        })
                    
                except IntegrityError:
                    logger.warning(f'Intento de vinculación duplicada de Facebook ID {facebook_id}')
                    return Response({
                        'message': 'Esta cuenta de Facebook ya está vinculada a otro usuario'
                    }, status=409)
                except Exception as e:
                    logger.error(f'Error guardando vinculación de Facebook para cliente {client.id}: {str(e)}')
                    return Response({
                        'message': 'Error interno al vincular cuenta'
                    }, status=500)
                
            except requests.exceptions.Timeout:
                logger.error('Timeout conectando con Facebook Graph API')
                return Response({
                    'message': 'Error temporal conectando con Facebook. Intente más tarde.'
                }, status=503)
            except requests.exceptions.RequestException as e:
                logger.error(f'Error validando token de Facebook: {str(e)}')
                return Response({
                    'message': 'Error validando cuenta de Facebook. Servicio no disponible.'
                }, status=503)
            
        except (InvalidToken, TokenError) as e:
            return Response({'message': 'Token inválido'}, status=401)
        except Exception as e:
            logger.error(f'Error vinculando cuenta de Facebook: {str(e)}')
            return Response({
                'message': 'Error interno del servidor'
            }, status=500)


class ClientUnlinkFacebookView(APIView):
    """Endpoint para desvincular cuenta de Facebook del cliente"""
    authentication_classes = [ClientJWTAuthentication]
    permission_classes = [IsAuthenticated]
    
    def delete(self, request):
        try:
            # Cliente ya autenticado por DRF
            client = request.user
            
            # Verificar si tiene Facebook vinculado
            if not client.is_facebook_linked:
                return Response({
                    'message': 'No tienes una cuenta de Facebook vinculada'
                }, status=400)
            
            # Desvincular la cuenta
            client.unlink_facebook_account()
            
            logger.info(f'Cliente {client.first_name} desvinculó su cuenta de Facebook')
            
            return Response({
                'success': True,
                'message': 'Cuenta de Facebook desvinculada exitosamente',
                'facebook_linked': False
            })
            
        except (InvalidToken, TokenError) as e:
            return Response({'message': 'Token inválido'}, status=401)
        except Exception as e:
            logger.error(f'Error desvinculando cuenta de Facebook: {str(e)}')
            return Response({
                'message': 'Error interno del servidor'
            }, status=500)