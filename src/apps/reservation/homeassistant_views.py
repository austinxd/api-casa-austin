
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


        # Buscar reservas que cumplan criterios básicos
        basic_reservations = Reservation.objects.filter(
            property=property_obj,
            deleted=False,
            status='approved'
        ).select_related('client')
        
        
        # Buscar reserva activa considerando los horarios
        # Prioridad: 1) Reservas que inician hoy, 2) Reservas en curso, 3) Reservas que terminan hoy
        active_reservation = None
        
        # PRIMERA PRIORIDAD: Reserva que inicia hoy
        reservations_starting_today = basic_reservations.filter(
            check_in_date=today,
            check_out_date__gt=today
        )
        if reservations_starting_today.exists():
            active_reservation = reservations_starting_today.first()
        
        # SEGUNDA PRIORIDAD: Reserva en curso (entre fechas)
        if not active_reservation:
            reservations_in_progress = basic_reservations.filter(
                check_in_date__lt=today,
                check_out_date__gt=today
            )
            if reservations_in_progress.exists():
                active_reservation = reservations_in_progress.first()
        
        # TERCERA PRIORIDAD: Reserva que termina hoy
        if not active_reservation:
            reservations_ending_today = basic_reservations.filter(
                check_out_date=today,
                check_in_date__lt=today
            )
            if reservations_ending_today.exists():
                active_reservation = reservations_ending_today.first()


        # Validar horarios específicos
        if active_reservation:
            original_reservation = active_reservation
            
            # Si la reserva inicia hoy, verificar que ya sea después de las 15:00
            if active_reservation.check_in_date == today and current_time < check_in_time:
                active_reservation = None
            # Si la reserva termina hoy (y no inicia hoy), verificar que no sea después de las 11:00
            elif active_reservation.check_out_date == today and active_reservation.check_in_date < today and current_time >= check_out_time:
                active_reservation = None
            else:
                pass  # Reserva pasa validación de tiempo

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

            # Obtener reservas futuras del cliente (incluyendo la actual si termina después de hoy)
            from datetime import date
            upcoming_reservations_data = []
            
            if active_reservation.client:
                upcoming_reservations = Reservation.objects.filter(
                    client=active_reservation.client,
                    deleted=False,
                    status='approved',
                    check_out_date__gt=today  # Reservas que terminan después de hoy
                ).order_by('check_in_date')
                
                for reservation in upcoming_reservations:
                    # Formatear fechas para cada reserva
                    check_in_formatted_res = reservation.check_in_date.strftime('%d de %B')
                    check_out_formatted_res = reservation.check_out_date.strftime('%d de %B')
                    
                    upcoming_reservations_data.append({
                        "id": str(reservation.id),
                        "property_name": reservation.property.name if reservation.property else 'Sin propiedad',
                        "check_in_date": check_in_formatted_res,
                        "check_out_date": check_out_formatted_res,
                        "guests": reservation.guests,
                        "nights": (reservation.check_out_date - reservation.check_in_date).days,
                        "price_sol": float(reservation.price_sol) if reservation.price_sol else 0,
                        "status": "Aprobada",
                        "payment_full": reservation.full_payment,
                        "temperature_pool": reservation.temperature_pool
                    })

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
                "points_balance": int(available_points),
                "upcoming_reservations": upcoming_reservations_data
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
                "points_balance": 0,
                "upcoming_reservations": []
            })
