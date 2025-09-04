from rest_framework.views import APIView
from rest_framework.response import Response
from rest_framework import status
from rest_framework.permissions import AllowAny
from django.db import transaction
from django.conf import settings
from .models import Reservation
from apps.clients.auth_views import ClientJWTAuthentication
import requests
import logging
import time
import random
import uuid

logger = logging.getLogger(__name__)

class ProcessPaymentView(APIView):
    """
    Endpoint para procesar pagos con MercadoPago API
    """
    authentication_classes = [ClientJWTAuthentication]
    permission_classes = [AllowAny]

    def __init__(self):
        super().__init__()
        # Configurar MercadoPago API
        self.access_token = settings.MERCADOPAGO_ACCESS_TOKEN
        self.is_sandbox = settings.MERCADOPAGO_SANDBOX

        # URL base según el entorno
        if self.is_sandbox:
            self.base_url = "https://api.mercadopago.com"
        else:
            self.base_url = "https://api.mercadopago.com"

        # Debugging inicial de credenciales
        logger.info(f"🔧 MERCADOPAGO INIT - Access Token length: {len(self.access_token) if self.access_token else 0}")
        logger.info(f"🔧 MERCADOPAGO INIT - Sandbox: {self.is_sandbox}")

    def _get_auth_header(self):
        """Crear header de autenticación para MercadoPago"""
        return f"Bearer {self.access_token}"

    def _format_phone_number(self, phone_number):
        """Formatear número de teléfono para OpenPay"""
        if not phone_number:
            return ""

        # Limpiar el número de espacios, guiones, etc.
        clean_number = ''.join(filter(str.isdigit, str(phone_number)))

        # Si ya tiene código de país +51, no agregarlo de nuevo
        if clean_number.startswith('51') and len(clean_number) >= 11:
            return f"+{clean_number}"
        # Si es un número peruano de 9 dígitos, agregar +51
        elif len(clean_number) == 9:
            return f"+51{clean_number}"
        # Si tiene más de 9 dígitos pero no empieza con 51, asumir que ya tiene código de país
        elif len(clean_number) > 9:
            return f"+{clean_number}"
        else:
            # Para números que no siguen el patrón esperado, intentar agregar +51
            return f"+51{clean_number}"

    def post(self, request, reservation_id):
        try:
            # Debug de credenciales MercadoPago
            logger.info(f"=== DEBUGGING MERCADOPAGO CREDENTIALS ===")
            logger.info(f"Access Token (masked): {self.access_token[:15]}...{self.access_token[-8:]}")
            logger.info(f"Is Sandbox: {self.is_sandbox}")
            logger.info(f"Base URL: {self.base_url}")

            # Autenticar cliente
            authenticator = ClientJWTAuthentication()
            client, validated_token = authenticator.authenticate(request)

            if not client:
                return Response({
                    'success': False,
                    'message': 'Token inválido'
                }, status=401)

            # Obtener la reserva y verificar que pertenece al cliente
            reservation = Reservation.objects.get(
                id=reservation_id,
                client=client,
                deleted=False
            )

            # Datos del pago desde el frontend
            token = request.data.get('token')  # Token de MercadoPago
            amount = float(request.data.get('amount', 0))
            payment_method_id = request.data.get('payment_method_id', 'visa')  # visa, mastercard, etc.
            installments = int(request.data.get('installments', 1))

            logger.info(f"Token recibido: {token}")
            logger.info(f"Amount: {amount}")
            logger.info(f"Payment Method ID: {payment_method_id}")
            logger.info(f"Installments: {installments}")

            # Verificar si el token ya fue usado anteriormente
            logger.info(f"=== VERIFICANDO TOKEN ===")
            logger.info(f"Token length: {len(token) if token else 0}")
            logger.info(f"Token starts with: {token[:10] if token and len(token) >= 10 else token}")

            if not token or amount <= 0:
                return Response({
                    'success': False,
                    'message': 'Token y monto válido son requeridos'
                }, status=400)

            if not payment_method_id:
                return Response({
                    'success': False,
                    'message': 'Método de pago es requerido'
                }, status=400)

            # Verificar si ya existe un pago con este token específico
            from .models import PaymentToken
            try:
                # Buscar si ya se usó este token anteriormente
                from django.utils import timezone
                from datetime import timedelta

                # Verificar si el token ya fue usado en las últimas 24 horas
                twenty_four_hours_ago = timezone.now() - timedelta(hours=24)
                existing_token = PaymentToken.objects.filter(
                    token=token,
                    used_at__gte=twenty_four_hours_ago
                ).first()

                if existing_token:
                    logger.error(f"🚫 TOKEN YA UTILIZADO: {token} fue usado en {existing_token.used_at}")
                    return Response({
                        'success': False,
                        'message': 'Este token de pago ya fue utilizado. Por favor, ingrese nuevamente los datos de la tarjeta.',
                        'error_code': 'TOKEN_ALREADY_USED'
                    }, status=400)

                logger.info(f"✅ Token {token} no ha sido usado anteriormente")

            except Exception as token_check_error:
                logger.warning(f"No se pudo verificar token previo: {token_check_error}")
                # Continuar con el procesamiento


            with transaction.atomic():
                try:
                    # Generar un external_reference único con timestamp y microsegundos
                    import time
                    import random
                    timestamp_micro = str(time.time()).replace('.', '')
                    random_suffix = random.randint(1000, 9999)
                    unique_external_reference = f"RES-{reservation.id}-{timestamp_micro}-{random_suffix}"

                    # Datos del pago para MercadoPago API
                    payment_data = {
                        "transaction_amount": amount,
                        "token": token,
                        "description": f"Pago reserva #{reservation.id} - {reservation.property.name}",
                        "external_reference": unique_external_reference,
                        "payment_method_id": payment_method_id,
                        "installments": installments,
                        "payer": {
                            "email": reservation.client.email if reservation.client else "cliente@casaaustin.pe",
                            "first_name": reservation.client.first_name if reservation.client else "Cliente",
                            "last_name": reservation.client.last_name if reservation.client else "Anónimo",
                            "phone": {
                                "area_code": "51",
                                "number": self._format_phone_number(reservation.client.tel_number) if reservation.client and reservation.client.tel_number else "999888777"
                            },
                            "address": {
                                "zip_code": "15001",
                                "street_name": "Calle Principal",
                                "street_number": 123
                            }
                        },
                        "additional_info": {
                            "items": [
                                {
                                    "id": str(reservation.property.id),
                                    "title": reservation.property.name,
                                    "quantity": 1,
                                    "unit_price": amount
                                }
                            ]
                        }
                    }

                    # Headers para la API
                    headers = {
                        'Content-Type': 'application/json',
                        'Authorization': self._get_auth_header(),
                        'X-Idempotency-Key': str(uuid.uuid4())  # Para evitar pagos duplicados
                    }

                    # Validar credenciales primero con endpoint de MercadoPago
                    logger.info(f"=== VALIDANDO CREDENCIALES MERCADOPAGO ===")
                    auth_header = self._get_auth_header()
                    logger.info(f"Auth header creado: {auth_header[:25]}...")

                    # Validaciones adicionales antes del request
                    logger.info(f"=== VALIDACIONES PRE-REQUEST ===")
                    logger.info(f"Amount validation: {amount} > 0 = {amount > 0}")
                    logger.info(f"Payment Method ID: {payment_data['payment_method_id']}")
                    logger.info(f"Installments: {payment_data['installments']}")
                    logger.info(f"Token length: {len(token)}")
                    logger.info(f"External Reference: {payment_data['external_reference']}")
                    logger.info(f"Payer email: {payment_data['payer']['email']}")
                    logger.info(f"Payer phone: {payment_data['payer']['phone']['number']}")

                    # Procesar pago con MercadoPago API
                    url = f"{self.base_url}/v1/payments"

                    logger.info(f"Procesando pago para reserva {reservation.id} con external_reference: {unique_external_reference}")
                    logger.info(f"DEBUGGING MERCADOPAGO REQUEST:")
                    logger.info(f"URL: {url}")
                    logger.info(f"Headers: {headers}")
                    logger.info(f"Payment Data: {payment_data}")

                    # Reintentar hasta 3 veces en caso de error 500
                    max_retries = 3
                    retry_count = 0
                    
                    while retry_count < max_retries:
                        try:
                            response = requests.post(url, json=payment_data, headers=headers, timeout=30)
                            
                            logger.info(f"MercadoPago Response - Status: {response.status_code} (Intento {retry_count + 1})")
                            logger.info(f"MercadoPago Response Headers: {dict(response.headers)}")
                            
                            # Si es error 500, reintentar
                            if response.status_code == 500:
                                retry_count += 1
                                if retry_count < max_retries:
                                    logger.warning(f"Error 500 de MercadoPago, reintentando... (intento {retry_count + 1}/{max_retries})")
                                    import time
                                    time.sleep(2)  # Esperar 2 segundos antes del reintento
                                    continue
                                else:
                                    logger.error(f"Error 500 persistente después de {max_retries} intentos")
                                    return Response({
                                        'success': False,
                                        'message': 'Error temporal del procesador de pagos. Por favor, intente nuevamente en unos minutos.',
                                        'error_code': 'MERCADOPAGO_SERVER_ERROR'
                                    }, status=503)
                            else:
                                # No es error 500, continuar con el procesamiento normal
                                break
                                
                        except requests.RequestException as e:
                            retry_count += 1
                            if retry_count < max_retries:
                                logger.warning(f"Error de conexión, reintentando... (intento {retry_count + 1}/{max_retries}): {str(e)}")
                                import time
                                time.sleep(2)
                                continue
                            else:
                                logger.error(f"Error de conexión persistente después de {max_retries} intentos: {str(e)}")
                                return Response({
                                    'success': False,
                                    'message': 'Error de conexión con el procesador de pagos'
                                }, status=500)

                    # MercadoPago puede devolver 200 o 201 para pagos exitosos
                    if response.status_code not in [200, 201]:
                        logger.error(f"MercadoPago Error Response: {response.text}")

                        # Intentar parsear el JSON del error para obtener una descripción más clara
                        try:
                            error_details = response.json()
                            error_msg_from_api = error_details.get('message', 'No se pudo obtener descripción del error.')
                            error_cause = error_details.get('cause', [])

                            logger.error(f"   Descripción API: {error_msg_from_api}")
                            logger.error(f"   Causas: {error_cause}")

                            # Errores específicos de MercadoPago
                            if any("already_used" in str(cause) for cause in error_cause):
                                logger.error("   Detectado: El token ya ha sido usado.")
                                return Response({
                                    'success': False,
                                    'message': 'Este token de pago ya fue utilizado. Por favor, ingrese nuevamente los datos de la tarjeta.',
                                    'error_code': 'TOKEN_ALREADY_USED'
                                }, status=400)
                            elif any("invalid_token" in str(cause) for cause in error_cause):
                                logger.error("   Detectado: Token inválido.")
                                return Response({
                                    'success': False,
                                    'message': 'El token de pago proporcionado es inválido.',
                                    'error_code': 'INVALID_TOKEN'
                                }, status=400)
                            else:
                                return Response({
                                    'success': False,
                                    'message': f'Error procesando el pago: {error_msg_from_api}'
                                }, status=400)
                        except ValueError: # Si la respuesta no es JSON
                            logger.error(f"   Respuesta no JSON: {response.text}")
                            return Response({
                                'success': False,
                                'message': f'Error procesando el pago: {response.text}'
                            }, status=400)


                    if response.status_code in [200, 201]:
                        payment = response.json()

                        # Estados exitosos de MercadoPago: approved, authorized
                        if payment.get('status') in ['approved', 'authorized']:
                            # Pago exitoso - actualizar reserva
                            reservation.full_payment = True
                            reservation.status = 'approved'
                            
                            # Actualizar advance_payment para que el frontend calcule resta_pagar = 0
                            # El pago con MercadoPago siempre es en soles (price_sol)
                            reservation.advance_payment = amount  # amount ya viene en soles
                            reservation.advance_payment_currency = 'sol'
                            
                            reservation.save()

                            # Registrar el uso del token
                            try:
                                from .models import PaymentToken
                                from django.utils import timezone
                                PaymentToken.objects.create(
                                    token=token,
                                    reservation=reservation,
                                    amount=amount,
                                    transaction_id=payment.get('id'),
                                    used_at=timezone.now()
                                )
                                logger.info(f"✅ Token {token} registrado como usado para la reserva {reservation.id}")
                            except Exception as token_creation_error:
                                logger.error(f"Error al registrar el uso del token {token}: {token_creation_error}")


                            logger.info(f"Pago exitoso para reserva {reservation.id}. Transaction ID: {payment.get('id')}")

                            return Response({
                                'success': True,
                                'message': 'Pago procesado exitosamente',
                                'reservation_id': reservation.id,
                                'transaction_id': payment.get('id'),
                                'payment_status': payment.get('status'),
                                'amount': amount,
                                'currency': 'SOL'
                            })
                        else:
                            logger.warning(f"Pago no completado para reserva {reservation.id}. Status: {payment.get('status')}")
                            return Response({
                                'success': False,
                                'message': f"Pago no completado. Estado: {payment.get('status')}",
                                'payment_detail': payment.get('status_detail', '')
                            }, status=400)
                    else:
                        # Solo llegar aquí si el status code no es 200 o 201
                        try:
                            error_msg = response.json().get('message', 'Error desconocido') if response.content else 'Error de conexión'
                        except:
                            error_msg = 'Error de conexión'
                        logger.error(f"Error de MercadoPago para reserva {reservation.id}: {error_msg}")
                        return Response({
                            'success': False,
                            'message': f'Error procesando el pago: {error_msg}'
                        }, status=400)

                except requests.RequestException as e:
                    logger.error(f"Error de conexión MercadoPago para reserva {reservation.id}: {str(e)}")
                    return Response({
                        'success': False,
                        'message': 'Error de conexión con el procesador de pagos'
                    }, status=500)
                except Exception as e:
                    logger.error(f"Error general MercadoPago para reserva {reservation.id}: {str(e)}")
                    return Response({
                        'success': False,
                        'message': f'Error procesando el pago: {str(e)}'
                    }, status=400)

        except Reservation.DoesNotExist:
            return Response({
                'success': False,
                'message': 'Reserva no encontrada'
            }, status=404)
        except Exception as e:
            logger.error(f"Error procesando pago MercadoPago para reserva {reservation_id}: {str(e)}")
            return Response({
                'success': False,
                'message': 'Error interno del servidor'
            }, status=500)