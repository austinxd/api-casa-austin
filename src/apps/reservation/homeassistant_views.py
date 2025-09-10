
from datetime import datetime, time
from django.db.models import Q
from rest_framework.views import APIView
from rest_framework.response import Response
from rest_framework.permissions import AllowAny
from drf_spectacular.utils import extend_schema, OpenApiParameter, OpenApiTypes

from .models import Reservation
from apps.property.models import Property


class HomeAssistantReservationView(APIView):
    """
    Endpoint público para HomeAssistant - obtener datos de reserva activa
    """
    permission_classes = [AllowAny]

    @extend_schema(
        parameters=[
            OpenApiParameter(
                "property_uuid",
                OpenApiTypes.STR,
                required=True,
                description="UUID de la propiedad",
                location=OpenApiParameter.QUERY
            ),
        ],
        responses={
            200: {
                "type": "object",
                "properties": {
                    "client_id": {"type": "string"},
                    "first_name": {"type": "string"},
                    "last_name": {"type": "string"},
                    "check_in_date": {"type": "string"},
                    "check_out_date": {"type": "string"},
                    "temperature_pool": {"type": "integer"},
                    "full_payment": {"type": "integer"},
                    "property_name": {"type": "string"},
                    "highest_achievement": {"type": "string"},
                    "points_balance": {"type": "integer"}
                }
            },
            400: {
                "type": "object",
                "properties": {
                    "error": {"type": "string"}
                }
            }
        }
    )
    def get(self, request):
        property_uuid = request.query_params.get('property_uuid')
        
        if not property_uuid:
            return Response({
                "error": "El parámetro 'property_uuid' es requerido"
            }, status=400)

        try:
            # Buscar la propiedad por UUID
            property_obj = Property.objects.get(id=property_uuid, deleted=False)
        except Property.DoesNotExist:
            return Response({
                "error": "Propiedad no encontrada"
            }, status=404)

        # Obtener fecha y hora actual
        now = datetime.now()
        today = now.date()
        current_time = now.time()
        
        # Definir horarios de check-in y check-out
        check_in_time = time(15, 0)  # 3:00 PM
        check_out_time = time(11, 0)  # 11:00 AM

        # DEBUG: Buscar TODAS las reservas para esta propiedad (SIN FILTRAR deleted)
        import logging
        logger = logging.getLogger(__name__)
        
        all_reservations = Reservation.objects.filter(property=property_obj).select_related('client')
        logger.error(f"HomeAssistant DEBUG - Total reservations for property (ALL): {all_reservations.count()}")
        
        # Mostrar TODAS las reservas (incluyendo deleted)
        for res in all_reservations:
            logger.error(f"HomeAssistant DEBUG - ALL RESERVATIONS - ID: {res.id}, "
                        f"Status: {res.status}, Deleted: {res.deleted}, "
                        f"Check-in: {res.check_in_date}, Check-out: {res.check_out_date}, "
                        f"Client: {res.client_id if res.client else 'None'}")

        # Ahora filtrar por deleted=False
        non_deleted_reservations = all_reservations.filter(deleted=False)
        logger.error(f"HomeAssistant DEBUG - Non-deleted reservations: {non_deleted_reservations.count()}")
        
        for res in non_deleted_reservations:
            logger.error(f"HomeAssistant DEBUG - NON-DELETED - ID: {res.id}, "
                        f"Status: {res.status}, Check-in: {res.check_in_date}, Check-out: {res.check_out_date}")

        # Buscar reservas que cumplan criterios básicos
        basic_reservations = Reservation.objects.filter(
            property=property_obj,
            deleted=False,
            status='approved'
        ).select_related('client')
        
        logger.error(f"HomeAssistant DEBUG - Approved non-deleted reservations: {basic_reservations.count()}")
        
        # Buscar reserva activa considerando los horarios
        # Una reserva está activa si:
        # - Es hoy y ya pasó la hora de check-in (15:00)
        # - O es antes del check-out de hoy (11:00) si checkout es hoy
        # - O estamos entre las fechas de la reserva
        active_reservation = basic_reservations.filter(
            Q(
                # Reserva que inicia hoy y ya pasó la hora de check-in
                (Q(check_in_date=today) & Q(check_out_date__gt=today)) |
                # Reserva que termina hoy pero aún no es hora de check-out
                (Q(check_out_date=today) & Q(check_in_date__lt=today)) |
                # Reserva en curso (entre fechas)
                (Q(check_in_date__lt=today) & Q(check_out_date__gt=today))
            )
        ).first()

        logger.error(f"HomeAssistant DEBUG - Active reservation found: {active_reservation.id if active_reservation else 'None'}")
        logger.error(f"HomeAssistant DEBUG - Current date: {today}, Current time: {current_time}")
        logger.error(f"HomeAssistant DEBUG - Check-in time: {check_in_time}, Check-out time: {check_out_time}")

        # Validar horarios específicos
        if active_reservation:
            original_reservation = active_reservation
            logger.error(f"HomeAssistant DEBUG - Found reservation {original_reservation.id} - checking time constraints...")
            
            # Si la reserva inicia hoy, verificar que ya sea después de las 15:00
            if active_reservation.check_in_date == today and current_time < check_in_time:
                logger.error(f"HomeAssistant DEBUG - Reservation starts today but current time {current_time} < check-in time {check_in_time}")
                active_reservation = None
            # Si la reserva termina hoy, verificar que no sea después de las 11:00
            elif active_reservation.check_out_date == today and current_time >= check_out_time:
                logger.error(f"HomeAssistant DEBUG - Reservation ends today but current time {current_time} >= check-out time {check_out_time}")
                active_reservation = None
            else:
                logger.error(f"HomeAssistant DEBUG - Reservation {original_reservation.id} passes time validation!")
        else:
            logger.error(f"HomeAssistant DEBUG - No active reservation found after date filtering")

        if active_reservation and active_reservation.client:
            # Formatear nombres (solo primer nombre y primer apellido)
            first_name = active_reservation.client.first_name.split()[0] if active_reservation.client.first_name else ""
            last_name = active_reservation.client.last_name.split()[0] if active_reservation.client.last_name else ""
            
            # Formatear fechas en español
            import locale
            try:
                locale.setlocale(locale.LC_TIME, 'es_ES.UTF-8')
            except:
                pass  # Si no está disponible el locale, usar formato por defecto
            
            check_in_formatted = active_reservation.check_in_date.strftime('%d de %B')
            check_out_formatted = active_reservation.check_out_date.strftime('%d de %B')

            # Obtener el nivel más alto (logro más importante) del cliente
            from apps.clients.models import ClientAchievement
            highest_achievement = None
            highest_achievement_name = ""
            
            earned_achievements = ClientAchievement.objects.filter(
                client=active_reservation.client,
                deleted=False
            ).select_related('achievement').order_by(
                '-achievement__required_reservations',
                '-achievement__required_referrals',
                '-achievement__required_referral_reservations'
            )

            if earned_achievements.exists():
                highest_achievement_obj = earned_achievements.first()
                icon = highest_achievement_obj.achievement.icon or ""
                name = highest_achievement_obj.achievement.name
                highest_achievement_name = f"{icon} {name}" if icon else name

            # Obtener puntos disponibles del cliente
            available_points = active_reservation.client.get_available_points()

            return Response({
                "client_id": str(active_reservation.client.id),
                "first_name": first_name,
                "last_name": last_name,
                "check_in_date": check_in_formatted,
                "check_out_date": check_out_formatted,
                "temperature_pool": 1 if active_reservation.temperature_pool else 0,
                "full_payment": 1 if active_reservation.full_payment else 0,
                "property_name": property_obj.name,
                "reservation_id": str(active_reservation.id),
                "highest_achievement": highest_achievement_name,
                "points_balance": int(available_points)
            })
        else:
            # No hay reserva activa
            return Response({
                "client_id": "Reserva no activa",
                "first_name": "Reserva no activa", 
                "last_name": "Reserva no activa",
                "check_in_date": "Reserva no activa",
                "check_out_date": "Reserva no activa",
                "temperature_pool": 0,
                "full_payment": 0,
                "property_name": property_obj.name,
                "reservation_id": "none",
                "highest_achievement": "Sin reserva activa",
                "points_balance": 0
            })
