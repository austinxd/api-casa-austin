from rest_framework.views import APIView
from rest_framework.response import Response
from rest_framework import status
from rest_framework.permissions import AllowAny
from django.db import transaction
from django.conf import settings
from .models import Reservation
from apps.clients.auth_views import ClientJWTAuthentication
import requests
import base64
import logging
import time
import random

logger = logging.getLogger(__name__)

class ProcessPaymentView(APIView):
    """
    Endpoint para procesar pagos con OpenPay
    """
    authentication_classes = [ClientJWTAuthentication]
    permission_classes = [AllowAny]

    def __init__(self):
        super().__init__()
        # Configurar OpenPay API
        self.merchant_id = settings.OPENPAY_MERCHANT_ID
        self.private_key = settings.OPENPAY_PRIVATE_KEY
        self.is_sandbox = settings.OPENPAY_SANDBOX

        # URL base según el entorno
        if self.is_sandbox:
            self.base_url = "https://sandbox-api.openpay.pe/v1"
        else:
            self.base_url = "https://api.openpay.pe/v1"

    def _get_auth_header(self):
        """Crear header de autenticación para OpenPay"""
        credentials = f"{self.private_key}:"
        encoded_credentials = base64.b64encode(credentials.encode()).decode()
        return f"Basic {encoded_credentials}"

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
            token = request.data.get('token')  # Token de OpenPay
            amount = float(request.data.get('amount', 0))
            device_session_id = request.data.get('device_session_id')

            logger.info(f"Token recibido: {token}")
            logger.info(f"Amount: {amount}")
            logger.info(f"Device Session ID: {device_session_id}")

            if not token or amount <= 0:
                return Response({
                    'success': False,
                    'message': 'Token y monto válido son requeridos'
                }, status=400)

            if not device_session_id:
                return Response({
                    'success': False,
                    'message': 'Device session ID es requerido'
                }, status=400)

            with transaction.atomic():
                try:
                    # Generar un order_id verdaderamente único con timestamp y microsegundos
                    import time
                    import random
                    timestamp_micro = str(time.time()).replace('.', '')
                    random_suffix = random.randint(1000, 9999)
                    unique_order_id = f"RES-{reservation.id}-{timestamp_micro}-{random_suffix}"

                    charge_data = {
                        "source_id": token,
                        "method": "card",
                        "amount": amount,
                        "currency": "PEN",
                        "description": f"Pago reserva #{reservation.id} - {reservation.property.name}",
                        "order_id": unique_order_id,
                        "device_session_id": device_session_id,
                        "customer": {
                            "name": reservation.client.first_name if reservation.client else "Cliente",
                            "last_name": reservation.client.last_name if reservation.client else "",
                            "email": reservation.client.email if reservation.client else "",
                            "phone_number": self._format_phone_number(reservation.client.tel_number) if reservation.client and reservation.client.tel_number else ""
                        }
                    }

                    # Headers para la API
                    headers = {
                        'Content-Type': 'application/json',
                        'Authorization': self._get_auth_header()
                    }

                    # Procesar pago con OpenPay API
                    url = f"{self.base_url}/{self.merchant_id}/charges"

                    logger.info(f"Procesando pago para reserva {reservation.id} con order_id: {unique_order_id}")
                    logger.info(f"DEBUGGING OPENPAY REQUEST:")
                    logger.info(f"URL: {url}")
                    logger.info(f"Headers: {headers}")
                    logger.info(f"Charge Data: {charge_data}")

                    response = requests.post(url, json=charge_data, headers=headers)

                    logger.info(f"OpenPay Response - Status: {response.status_code}")
                    if response.status_code != 201:
                        logger.error(f"OpenPay Error Response: {response.text}")

                    if response.status_code == 201:
                        charge = response.json()

                        if charge.get('status') == 'completed':
                            # Pago exitoso - actualizar reserva
                            reservation.full_payment = True
                            reservation.status = 'approved'
                            reservation.save()

                            logger.info(f"Pago exitoso para reserva {reservation.id}. Transaction ID: {charge.get('id')}")

                            return Response({
                                'success': True,
                                'message': 'Pago procesado exitosamente',
                                'reservation_id': reservation.id,
                                'transaction_id': charge.get('id')
                            })
                        else:
                            logger.warning(f"Pago no completado para reserva {reservation.id}. Status: {charge.get('status')}")
                            return Response({
                                'success': False,
                                'message': f"Pago no completado. Estado: {charge.get('status')}"
                            }, status=400)
                    else:
                        error_msg = response.json().get('description', 'Error desconocido') if response.content else 'Error de conexión'
                        logger.error(f"Error de OpenPay para reserva {reservation.id}: {error_msg}")
                        return Response({
                            'success': False,
                            'message': f'Error procesando el pago: {error_msg}'
                        }, status=400)

                except requests.RequestException as e:
                    logger.error(f"Error de conexión OpenPay para reserva {reservation.id}: {str(e)}")
                    return Response({
                        'success': False,
                        'message': 'Error de conexión con el procesador de pagos'
                    }, status=500)
                except Exception as e:
                    logger.error(f"Error general OpenPay para reserva {reservation.id}: {str(e)}")
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
            logger.error(f"Error procesando pago para reserva {reservation_id}: {str(e)}")
            return Response({
                'success': False,
                'message': 'Error interno del servidor'
            }, status=500)