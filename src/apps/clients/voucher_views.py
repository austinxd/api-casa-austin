
from django.utils import timezone
from datetime import timedelta
from rest_framework.views import APIView
from rest_framework.response import Response
from rest_framework.permissions import AllowAny
from rest_framework import status
from django.db import transaction

from .auth_views import ClientJWTAuthentication
from apps.reservation.models import Reservation, RentalReceipt

import logging
logger = logging.getLogger(__name__)


class ClientVoucherUploadView(APIView):
    """Vista para que el cliente suba el voucher de pago"""
    authentication_classes = [ClientJWTAuthentication]
    permission_classes = [AllowAny]

    def post(self, request, reservation_id):
        try:
            # Autenticar cliente
            authenticator = ClientJWTAuthentication()
            client, validated_token = authenticator.authenticate(request)
            
            if not client:
                return Response({'message': 'Token inválido'}, status=401)

            # Obtener la reserva
            try:
                reservation = Reservation.objects.get(
                    id=reservation_id, 
                    client=client, 
                    deleted=False
                )
            except Reservation.DoesNotExist:
                return Response({
                    'message': 'Reserva no encontrada'
                }, status=404)

            # Verificar que la reserva sea de origen CLIENT
            if reservation.origin != 'client':
                return Response({
                    'message': 'Esta reserva no requiere voucher de pago'
                }, status=400)

            # Verificar que no haya expirado el tiempo
            if reservation.payment_voucher_deadline and timezone.now() > reservation.payment_voucher_deadline:
                # Eliminar reserva automáticamente
                reservation.delete()
                return Response({
                    'message': 'El tiempo para subir el voucher ha expirado. La reserva ha sido cancelada.'
                }, status=400)

            # Verificar si ya subió el voucher
            if reservation.payment_voucher_uploaded:
                return Response({
                    'message': 'Ya has subido el voucher para esta reserva'
                }, status=400)

            # Obtener archivo del voucher
            voucher_file = request.FILES.get('voucher')
            if not voucher_file:
                return Response({
                    'message': 'Debe subir un archivo de voucher'
                }, status=400)

            # Obtener confirmación de pago
            payment_confirmed = request.data.get('payment_confirmed', False)

            with transaction.atomic():
                # Crear el RentalReceipt
                RentalReceipt.objects.create(
                    reservation=reservation,
                    file=voucher_file
                )
                
                # Actualizar reserva
                reservation.payment_voucher_uploaded = True
                reservation.payment_confirmed = bool(payment_confirmed)
                
                # Si confirmó el pago, cambiar status a approved
                if payment_confirmed:
                    reservation.status = 'approved'
                    
                reservation.save()

            return Response({
                'message': 'Voucher subido exitosamente',
                'reservation_id': reservation.id,
                'payment_confirmed': reservation.payment_confirmed
            })

        except Exception as e:
            logger.error(f"Error uploading voucher: {str(e)}")
            return Response({
                'message': 'Error interno del servidor'
            }, status=500)


class ClientReservationStatusView(APIView):
    """Vista para verificar el estado de la reserva y tiempo restante"""
    authentication_classes = [ClientJWTAuthentication]
    permission_classes = [AllowAny]

    def get(self, request, reservation_id):
        try:
            # Autenticar cliente
            authenticator = ClientJWTAuthentication()
            client, validated_token = authenticator.authenticate(request)
            
            if not client:
                return Response({'message': 'Token inválido'}, status=401)

            # Obtener la reserva
            try:
                reservation = Reservation.objects.get(
                    id=reservation_id, 
                    client=client, 
                    deleted=False
                )
            except Reservation.DoesNotExist:
                return Response({
                    'message': 'Reserva no encontrada'
                }, status=404)

            # Calcular tiempo restante
            time_remaining = None
            if reservation.payment_voucher_deadline:
                time_remaining = reservation.payment_voucher_deadline - timezone.now()
                time_remaining = max(0, int(time_remaining.total_seconds()))

            return Response({
                'reservation_id': reservation.id,
                'status': reservation.status,
                'payment_voucher_uploaded': reservation.payment_voucher_uploaded,
                'payment_confirmed': reservation.payment_confirmed,
                'time_remaining_seconds': time_remaining,
                'deadline_expired': time_remaining == 0 if time_remaining is not None else None
            })

        except Exception as e:
            logger.error(f"Error getting reservation status: {str(e)}")
            return Response({
                'message': 'Error interno del servidor'
            }, status=500)
