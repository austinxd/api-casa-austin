from datetime import time
from django.utils import timezone
from rest_framework.permissions import BasePermission
from rest_framework.exceptions import PermissionDenied
from django.db.models import Q
import pytz

from .models import Reservation


class HasActiveReservationMixin:
    """
    Mixin para vistas que requieren que el cliente tenga una reserva activa.
    Proporciona el método get_active_reservation() que valida y retorna la reserva.
    """
    
    def validate_reservation_ownership_and_active(self, client, reservation_id):
        """
        Valida que una reserva específica pertenece al cliente y está activa.
        Reutiliza la lógica de validación de get_active_reservation().
        
        Args:
            client: Cliente autenticado
            reservation_id: UUID de la reserva a validar
            
        Returns:
            Reservation: La reserva activa validada
            
        Raises:
            Reservation.DoesNotExist: Si la reserva no existe
            PermissionDenied: Si la reserva no pertenece al cliente o no está activa
        """
        # Obtener la reserva
        try:
            reservation = Reservation.objects.select_related('property', 'client').get(
                id=reservation_id,
                deleted=False
            )
        except Reservation.DoesNotExist:
            raise PermissionDenied("Reserva no encontrada")
        
        # Validar ownership
        if reservation.client.id != client.id:
            raise PermissionDenied("No tienes acceso a esta reserva")
        
        # Validar status
        if reservation.status != 'approved':
            raise PermissionDenied(
                "Esta reserva no está aprobada. "
                "Solo puedes controlar dispositivos de reservas aprobadas."
            )
        
        # Validar que esté activa según horarios (convertir a hora de Perú)
        lima_tz = pytz.timezone('America/Lima')
        now_lima = timezone.now().astimezone(lima_tz)
        today = now_lima.date()
        current_time = now_lima.time()
        
        check_in_time = time(12, 0)  # 12:00 PM
        check_out_time = time(10, 59)  # 10:59 AM
        
        # Si la reserva inicia hoy, verificar que ya sea después de las 12:00 PM
        if reservation.check_in_date == today and current_time < check_in_time:
            raise PermissionDenied(
                f"Esta reserva inicia hoy pero el acceso está disponible desde las 12:00 PM. "
                f"Hora actual: {current_time.strftime('%H:%M')}"
            )
        
        # Si la reserva termina hoy (y no inicia hoy), verificar que no sea después de las 10:59 AM
        if reservation.check_out_date == today and reservation.check_in_date < today and current_time > check_out_time:
            raise PermissionDenied(
                "Esta reserva terminó hoy a las 10:59 AM. El acceso ya no está disponible."
            )
        
        # Verificar que la fecha actual esté dentro del rango de la reserva
        if today < reservation.check_in_date:
            raise PermissionDenied(
                f"Esta reserva aún no ha iniciado. "
                f"Check-in disponible desde las 12:00 PM del {reservation.check_in_date.strftime('%d/%m/%Y')}"
            )
        
        if today > reservation.check_out_date:
            raise PermissionDenied(
                f"Esta reserva ya finalizó el {reservation.check_out_date.strftime('%d/%m/%Y')}"
            )
        
        return reservation
    
    def get_active_reservation(self, client):
        """
        Obtiene la reserva activa del cliente basándose en la lógica de negocio:
        - Check-in: disponible desde las 12:00 PM del día de entrada
        - Check-out: disponible hasta las 10:59 AM del día de salida
        
        Args:
            client: Cliente autenticado
            
        Returns:
            Reservation: Reserva activa del cliente
            
        Raises:
            PermissionDenied: Si no hay reserva activa
        """
        # Convertir a hora de Perú
        lima_tz = pytz.timezone('America/Lima')
        now_lima = timezone.now().astimezone(lima_tz)
        today = now_lima.date()
        current_time = now_lima.time()
        
        # Horarios de check-in y check-out
        check_in_time = time(12, 0)  # 12:00 PM
        check_out_time = time(10, 59)  # 10:59 AM
        
        # Buscar reservas potencialmente activas
        potential_reservations = Reservation.objects.filter(
            client=client,
            deleted=False,
            status='approved'
        ).filter(
            Q(check_in_date=today, check_out_date__gt=today) |  # Inicia hoy
            Q(check_in_date__lt=today, check_out_date__gt=today) |  # En curso
            Q(check_out_date=today, check_in_date__lt=today)  # Termina hoy
        ).select_related('property').order_by('check_in_date')
        
        for reservation in potential_reservations:
            # Si la reserva inicia hoy, verificar que ya sea después de las 12:00 PM
            if reservation.check_in_date == today and current_time < check_in_time:
                continue
            
            # Si la reserva termina hoy (y no inicia hoy), verificar que no sea después de las 10:59 AM
            if reservation.check_out_date == today and reservation.check_in_date < today and current_time >= check_out_time:
                continue
            
            # Esta reserva pasa todas las validaciones
            return reservation
        
        # No se encontró ninguna reserva activa
        raise PermissionDenied(
            "No tienes una reserva activa en este momento. "
            "Las reservas están disponibles desde las 12:00 PM del día de check-in "
            "hasta las 10:59 AM del día de check-out."
        )


class HasActiveReservation(BasePermission):
    """
    Permission class que verifica si el usuario tiene una reserva activa.
    """
    
    def has_permission(self, request, view):
        if not request.user or not request.user.is_authenticated:
            return False
        
        # Verificar que el usuario tenga un cliente asociado
        if not hasattr(request.user, 'client'):
            return False
        
        # Intentar obtener la reserva activa (lanzará PermissionDenied si no existe)
        try:
            mixin = HasActiveReservationMixin()
            mixin.get_active_reservation(request.user.client)
            return True
        except PermissionDenied:
            return False
