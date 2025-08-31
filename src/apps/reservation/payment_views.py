
from rest_framework.views import APIView
from rest_framework.response import Response
from rest_framework import status
from django.db import transaction
from django.conf import settings
from .models import Reservation
import openpay
import logging

logger = logging.getLogger(__name__)

class ProcessPaymentView(APIView):
    """
    Endpoint para procesar pagos con OpenPay
    """
    
    def __init__(self):
        super().__init__()
        # Configurar OpenPay
        self.openpay = openpay.Openpay(
            merchant_id=settings.OPENPAY_MERCHANT_ID,
            private_key=settings.OPENPAY_PRIVATE_KEY,
            production=not settings.OPENPAY_SANDBOX
        )
    
    def post(self, request, reservation_id):
        try:
            # Obtener la reserva
            reservation = Reservation.objects.get(id=reservation_id, deleted=False)
            
            # Datos del pago desde el frontend
            token = request.data.get('token')  # Token de OpenPay
            amount = float(request.data.get('amount', 0))
            
            if not token or amount <= 0:
                return Response({
                    'success': False,
                    'message': 'Token y monto válido son requeridos'
                }, status=400)
            
            with transaction.atomic():
                try:
                    # Crear el cargo con OpenPay
                    charge_data = {
                        "source_id": token,
                        "method": "card",
                        "amount": amount,
                        "currency": "PEN",
                        "description": f"Pago reserva #{reservation.id} - {reservation.property.name}",
                        "order_id": f"RES-{reservation.id}",
                        "customer": {
                            "name": reservation.client.first_name if reservation.client else "Cliente",
                            "last_name": reservation.client.last_name if reservation.client else "",
                            "email": reservation.client.email if reservation.client else "",
                            "phone_number": f"+51{reservation.client.tel_number}" if reservation.client and reservation.client.tel_number else ""
                        }
                    }
                    
                    # Procesar pago con OpenPay
                    charge = self.openpay.Charge.create(charge_data)
                    
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
                        
                except openpay.exceptions.OpenpayError as e:
                    logger.error(f"Error de OpenPay para reserva {reservation.id}: {str(e)}")
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
