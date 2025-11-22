
from datetime import datetime, time
from django.db.models import Q
from rest_framework.views import APIView
from rest_framework.response import Response
from rest_framework.permissions import AllowAny, IsAuthenticated, IsAdminUser
from rest_framework import status
from drf_spectacular.utils import extend_schema, OpenApiParameter
from drf_spectacular.types import OpenApiTypes

from .models import Reservation
from apps.property.models import Property, HomeAssistantDevice
from .homeassistant_service import HomeAssistantService


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
                    "referral_code": {"type": "string"},
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


        # Buscar reservas que cumplan criterios básicos - OPTIMIZADO
        # Solo traer reservas que terminan hoy o después (check_out_date >= today)
        # Las reservas pasadas nunca serán válidas para el análisis actual
        basic_reservations = Reservation.objects.filter(
            property=property_obj,
            deleted=False,
            status='approved',
            check_out_date__gte=today  # ← OPTIMIZACIÓN: Solo reservas actuales/futuras
        ).select_related('client')
        
        
        # Buscar reserva activa con una sola consulta optimizada
        # Usar CASE WHEN para priorizar en SQL en lugar de múltiples consultas
        from django.db.models import Q, Case, When, IntegerField
        
        potential_reservations = basic_reservations.filter(
            Q(check_in_date=today, check_out_date__gt=today) |  # Inicia hoy
            Q(check_in_date__lt=today, check_out_date__gt=today) |  # En curso
            Q(check_out_date=today, check_in_date__lt=today)  # Termina hoy
        ).annotate(
            priority=Case(
                When(check_in_date=today, check_out_date__gt=today, then=1),  # Primera prioridad
                When(check_in_date__lt=today, check_out_date__gt=today, then=2),  # Segunda prioridad  
                When(check_out_date=today, check_in_date__lt=today, then=3),  # Tercera prioridad
                default=4,
                output_field=IntegerField()
            )
        ).order_by('priority', 'check_in_date')
        
        active_reservation = potential_reservations.first()


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

            # Obtener el nivel más alto (logro más importante) del cliente - OPTIMIZADO
            from apps.clients.models import ClientAchievement
            highest_achievement = None
            highest_achievement_name = ""
            
            # Optimización: Usar prefetch_related y obtener solo el primer resultado
            earned_achievements = ClientAchievement.objects.filter(
                client=active_reservation.client,
                deleted=False
            ).select_related('achievement').order_by(
                '-achievement__required_reservations',
                '-achievement__required_referrals',
                '-achievement__required_referral_reservations'
            )[:1]  # Solo necesitamos el más alto

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
                ).select_related('property').order_by('check_in_date')  # OPTIMIZACIÓN: select_related
                
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

            # Obtener referral code del cliente
            referral_code = active_reservation.client.get_referral_code() if hasattr(active_reservation.client, 'get_referral_code') else active_reservation.client.referral_code
            
            return Response({
                "client_id": str(active_reservation.client.id),
                "first_name": first_name,
                "last_name": last_name,
                "referral_code": referral_code,
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
                "referral_code": "Reserva no activa",
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


class AdminHADeviceListView(APIView):
    """
    Endpoint administrativo para listar dispositivos de Home Assistant
    Puede filtrar por propiedad o tipo de dispositivo
    """
    permission_classes = [IsAdminUser]
    
    @extend_schema(
        parameters=[
            OpenApiParameter(
                "property_id",
                OpenApiTypes.STR,
                required=False,
                description="UUID de la propiedad para filtrar dispositivos",
                location=OpenApiParameter.QUERY
            ),
            OpenApiParameter(
                "device_type",
                OpenApiTypes.STR,
                required=False,
                description="Tipo de dispositivo (light, switch, climate, etc.)",
                location=OpenApiParameter.QUERY
            ),
        ],
        responses={200: {
            "type": "object",
            "properties": {
                "count": {"type": "integer"},
                "devices": {
                    "type": "array",
                    "items": {
                        "type": "object",
                        "properties": {
                            "id": {"type": "string"},
                            "entity_id": {"type": "string"},
                            "friendly_name": {"type": "string"},
                            "device_type": {"type": "string"},
                            "icon": {"type": "string"},
                            "property_name": {"type": "string"},
                            "guest_accessible": {"type": "boolean"},
                            "is_active": {"type": "boolean"},
                            "current_state": {"type": "string"}
                        }
                    }
                }
            }
        }}
    )
    def get(self, request):
        """Lista todos los dispositivos configurados"""
        property_id = request.query_params.get('property_id')
        device_type = request.query_params.get('device_type')
        
        queryset = HomeAssistantDevice.objects.filter(deleted=False).select_related('property')
        
        if property_id:
            queryset = queryset.filter(property_id=property_id)
        
        if device_type:
            queryset = queryset.filter(device_type=device_type)
        
        try:
            ha_service = HomeAssistantService()
        except ValueError as e:
            return Response(
                {"error": f"Error de configuración de Home Assistant: {str(e)}"},
                status=status.HTTP_500_INTERNAL_SERVER_ERROR
            )
        
        devices_data = []
        
        for device in queryset:
            try:
                state_info = ha_service.get_entity_state(device.entity_id)
                current_state = state_info.get('state', 'unknown')
            except Exception:
                current_state = 'unavailable'
            
            devices_data.append({
                "id": str(device.id),
                "entity_id": device.entity_id,
                "friendly_name": device.friendly_name,
                "device_type": device.device_type,
                "icon": device.icon,
                "property_name": device.property.name if device.property else None,
                "guest_accessible": device.guest_accessible,
                "is_active": device.is_active,
                "display_order": device.display_order,
                "current_state": current_state
            })
        
        return Response({
            "count": len(devices_data),
            "devices": devices_data
        })


class AdminHADeviceControlView(APIView):
    """
    Endpoint administrativo para controlar dispositivos de Home Assistant
    Permite turn_on, turn_off, toggle
    """
    permission_classes = [IsAdminUser]
    
    @extend_schema(
        request={
            "type": "object",
            "properties": {
                "device_id": {"type": "string", "description": "UUID del dispositivo en la base de datos"},
                "action": {"type": "string", "enum": ["turn_on", "turn_off", "toggle"], "description": "Acción a realizar"},
                "brightness": {"type": "integer", "description": "Brillo para luces (0-255, opcional)"},
                "temperature": {"type": "number", "description": "Temperatura para clima (opcional)"}
            },
            "required": ["device_id", "action"]
        },
        responses={
            200: {
                "type": "object",
                "properties": {
                    "success": {"type": "boolean"},
                    "message": {"type": "string"},
                    "new_state": {"type": "object"}
                }
            },
            400: {"type": "object", "properties": {"error": {"type": "string"}}},
            404: {"type": "object", "properties": {"error": {"type": "string"}}}
        }
    )
    def post(self, request):
        """Controla un dispositivo específico"""
        device_id = request.data.get('device_id')
        action = request.data.get('action')
        brightness = request.data.get('brightness')
        temperature = request.data.get('temperature')
        
        if not device_id or not action:
            return Response(
                {"error": "device_id y action son requeridos"},
                status=status.HTTP_400_BAD_REQUEST
            )
        
        if action not in ['turn_on', 'turn_off', 'toggle']:
            return Response(
                {"error": "action debe ser: turn_on, turn_off o toggle"},
                status=status.HTTP_400_BAD_REQUEST
            )
        
        try:
            device = HomeAssistantDevice.objects.get(id=device_id, deleted=False)
        except HomeAssistantDevice.DoesNotExist:
            return Response(
                {"error": "Dispositivo no encontrado"},
                status=status.HTTP_404_NOT_FOUND
            )
        
        if not device.is_active:
            return Response(
                {"error": "Dispositivo no está activo y no puede ser controlado"},
                status=status.HTTP_400_BAD_REQUEST
            )
        
        if brightness is not None:
            if device.device_type != 'light':
                return Response(
                    {"error": "El parámetro brightness solo es válido para dispositivos de tipo 'light'"},
                    status=status.HTTP_400_BAD_REQUEST
                )
            if not isinstance(brightness, int) or brightness < 0 or brightness > 255:
                return Response(
                    {"error": "brightness debe ser un número entero entre 0 y 255"},
                    status=status.HTTP_400_BAD_REQUEST
                )
        
        if temperature is not None:
            if device.device_type != 'climate':
                return Response(
                    {"error": "El parámetro temperature solo es válido para dispositivos de tipo 'climate'"},
                    status=status.HTTP_400_BAD_REQUEST
                )
        
        try:
            ha_service = HomeAssistantService()
        except ValueError as e:
            return Response(
                {"error": f"Error de configuración de Home Assistant: {str(e)}"},
                status=status.HTTP_500_INTERNAL_SERVER_ERROR
            )
        
        try:
            if action == 'turn_on':
                if brightness is not None and device.device_type == 'light':
                    result = ha_service.set_light_brightness(device.entity_id, brightness)
                elif temperature is not None and device.device_type == 'climate':
                    result = ha_service.set_climate_temperature(device.entity_id, temperature)
                else:
                    result = ha_service.turn_on(device.entity_id)
            elif action == 'turn_off':
                result = ha_service.turn_off(device.entity_id)
            else:
                result = ha_service.toggle(device.entity_id)
            
            new_state = ha_service.get_entity_state(device.entity_id)
            
            return Response({
                "success": True,
                "message": f"Dispositivo {device.friendly_name} controlado exitosamente",
                "action": action,
                "new_state": new_state
            })
            
        except Exception as e:
            return Response(
                {"error": f"Error al controlar dispositivo: {str(e)}"},
                status=status.HTTP_500_INTERNAL_SERVER_ERROR
            )


class AdminHAConnectionTestView(APIView):
    """
    Endpoint administrativo para probar la conexión con Home Assistant
    """
    permission_classes = [IsAdminUser]
    
    @extend_schema(
        responses={
            200: {
                "type": "object",
                "properties": {
                    "connected": {"type": "boolean"},
                    "message": {"type": "string"},
                    "total_entities": {"type": "integer"}
                }
            }
        }
    )
    def get(self, request):
        """Prueba la conexión con Home Assistant"""
        try:
            ha_service = HomeAssistantService()
        except ValueError as e:
            return Response(
                {"error": f"Error de configuración de Home Assistant: {str(e)}"},
                status=status.HTTP_500_INTERNAL_SERVER_ERROR
            )
        
        try:
            api_info = ha_service.test_connection()
            all_states = ha_service.get_all_states()
            
            return Response({
                "connected": True,
                "message": api_info.get('message', 'API running'),
                "total_entities": len(all_states),
                "base_url": ha_service.base_url
            })
            
        except Exception as e:
            return Response({
                "connected": False,
                "error": str(e),
                "base_url": ha_service.base_url
            }, status=status.HTTP_500_INTERNAL_SERVER_ERROR)


class AdminHADiscoverDevicesView(APIView):
    """
    Endpoint administrativo para descubrir todos los dispositivos disponibles en Home Assistant
    Útil para agregar nuevos dispositivos a la base de datos
    """
    permission_classes = [IsAdminUser]
    
    @extend_schema(
        parameters=[
            OpenApiParameter(
                "filter_type",
                OpenApiTypes.STR,
                required=False,
                description="Filtrar por tipo: light, switch, climate, sensor, etc.",
                location=OpenApiParameter.QUERY
            ),
            OpenApiParameter(
                "search",
                OpenApiTypes.STR,
                required=False,
                description="Buscar en entity_id o friendly_name",
                location=OpenApiParameter.QUERY
            ),
        ],
        responses={
            200: {
                "type": "object",
                "properties": {
                    "count": {"type": "integer"},
                    "devices": {
                        "type": "array",
                        "items": {
                            "type": "object",
                            "properties": {
                                "entity_id": {"type": "string"},
                                "friendly_name": {"type": "string"},
                                "state": {"type": "string"},
                                "device_type": {"type": "string"}
                            }
                        }
                    }
                }
            }
        }
    )
    def get(self, request):
        """Descubre todos los dispositivos disponibles en Home Assistant"""
        filter_type = request.query_params.get('filter_type')
        search_term = request.query_params.get('search')
        
        try:
            ha_service = HomeAssistantService()
        except ValueError as e:
            return Response(
                {"error": f"Error de configuración de Home Assistant: {str(e)}"},
                status=status.HTTP_500_INTERNAL_SERVER_ERROR
            )
        
        try:
            if filter_type:
                devices = ha_service.get_devices_by_type(filter_type)
            elif search_term:
                devices = ha_service.search_devices(search_term)
            else:
                devices = ha_service.get_all_states()
            
            devices_data = []
            for device in devices:
                device_type = device['entity_id'].split('.')[0]
                devices_data.append({
                    "entity_id": device['entity_id'],
                    "friendly_name": device.get('attributes', {}).get('friendly_name', device['entity_id']),
                    "state": device.get('state', 'unknown'),
                    "device_type": device_type,
                    "last_changed": device.get('last_changed'),
                    "attributes": device.get('attributes', {})
                })
            
            return Response({
                "count": len(devices_data),
                "devices": devices_data
            })
            
        except Exception as e:
            return Response(
                {"error": f"Error al descubrir dispositivos: {str(e)}"},
                status=status.HTTP_500_INTERNAL_SERVER_ERROR
            )
