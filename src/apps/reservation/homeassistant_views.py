
from datetime import datetime, time
from django.db.models import Q
from rest_framework.views import APIView
from rest_framework.response import Response
from rest_framework.permissions import AllowAny, IsAuthenticated, IsAdminUser
from rest_framework.exceptions import PermissionDenied
from rest_framework import status
from drf_spectacular.utils import extend_schema, OpenApiParameter
from drf_spectacular.types import OpenApiTypes

from .models import Reservation
from apps.property.models import Property, HomeAssistantDevice
from .homeassistant_service import HomeAssistantService
from .permissions import HasActiveReservationMixin
from .homeassistant_serializers import (
    ClientDeviceSerializer,
    DeviceActionSerializer,
    DeviceActionResponseSerializer
)
from apps.clients.authentication import ClientJWTAuthentication


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
            OpenApiParameter(
                "unassigned",
                OpenApiTypes.BOOL,
                required=False,
                description="Si es true, muestra solo dispositivos NO asignados a la base de datos",
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
        show_only_unassigned = request.query_params.get('unassigned', 'false').lower() == 'true'
        
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
            
            # Obtener todos los entity_ids que ya están en la BD
            configured_entity_ids = set(
                HomeAssistantDevice.objects.filter(deleted=False)
                .values_list('entity_id', flat=True)
            )
            
            devices_data = []
            for device in devices:
                entity_id = device['entity_id']
                device_type = entity_id.split('.')[0]
                already_configured = entity_id in configured_entity_ids
                
                # Si solo queremos los no asignados, filtrar
                if show_only_unassigned and already_configured:
                    continue
                
                devices_data.append({
                    "entity_id": entity_id,
                    "friendly_name": device.get('attributes', {}).get('friendly_name', entity_id),
                    "state": device.get('state', 'unknown'),
                    "device_type": device_type,
                    "last_changed": device.get('last_changed'),
                    "already_configured": already_configured,
                    "attributes": device.get('attributes', {})
                })
            
            return Response({
                "count": len(devices_data),
                "total_in_ha": len(devices),
                "configured": len(configured_entity_ids),
                "unassigned": len(devices) - len([d for d in devices if d['entity_id'] in configured_entity_ids]),
                "devices": devices_data
            })
            
        except Exception as e:
            return Response(
                {"error": f"Error al descubrir dispositivos: {str(e)}"},
                status=status.HTTP_500_INTERNAL_SERVER_ERROR
            )


class ClientDeviceListView(HasActiveReservationMixin, APIView):
    """
    Endpoint para clientes: Listar dispositivos de Home Assistant accesibles
    durante su reserva activa.
    
    Requiere autenticación y reserva activa.
    Solo muestra dispositivos de la propiedad donde se hospedan,
    marcados como guest_accessible=True.
    """
    authentication_classes = [ClientJWTAuthentication]
    permission_classes = [IsAuthenticated]
    
    @extend_schema(
        responses={
            200: {
                "type": "object",
                "properties": {
                    "property_name": {"type": "string"},
                    "reservation_id": {"type": "string"},
                    "check_in": {"type": "string", "format": "date"},
                    "check_out": {"type": "string", "format": "date"},
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
                                "current_state": {"type": "string"},
                                "supports_brightness": {"type": "boolean"},
                                "supports_temperature": {"type": "boolean"}
                            }
                        }
                    }
                }
            },
            403: {"type": "object", "properties": {"error": {"type": "string"}}}
        },
        tags=['Cliente - Home Assistant']
    )
    def get(self, request, reservation_id):
        """Lista dispositivos accesibles para el cliente en esta reserva"""
        
        # Validar ownership y que la reserva esté activa
        # request.user ya es un objeto Clients gracias a ClientJWTAuthentication
        try:
            active_reservation = self.validate_reservation_ownership_and_active(
                request.user, 
                reservation_id
            )
        except PermissionDenied as e:
            return Response(
                {"error": str(e)},
                status=status.HTTP_403_FORBIDDEN
            )
        
        # Obtener dispositivos de la propiedad que son accesibles para huéspedes
        devices = HomeAssistantDevice.objects.filter(
            property=active_reservation.property,
            guest_accessible=True,
            is_active=True,
            deleted=False
        ).order_by('display_order', 'friendly_name')
        
        # Inicializar servicio de Home Assistant
        try:
            ha_service = HomeAssistantService()
        except ValueError as e:
            return Response(
                {"error": f"Error de configuración: {str(e)}"},
                status=status.HTTP_500_INTERNAL_SERVER_ERROR
            )
        
        # Construir respuesta con estado actual de cada dispositivo
        devices_data = []
        for device in devices:
            try:
                # Obtener estado actual desde Home Assistant
                state_info = ha_service.get_entity_state(device.entity_id)
                current_state = state_info.get('state', 'unknown')
                attributes = state_info.get('attributes', {})
            except Exception:
                current_state = 'unavailable'
                attributes = {}
            
            # Determinar capacidades del dispositivo
            supports_brightness = (
                device.device_type == 'light' and
                'brightness' in attributes
            )
            supports_temperature = device.device_type == 'climate'
            
            devices_data.append({
                "id": str(device.id),
                "entity_id": device.entity_id,
                "friendly_name": device.friendly_name,
                "location": device.location,
                "device_type": device.device_type,
                "icon": device.icon,
                "description": device.description,
                "display_order": device.display_order,
                "current_state": current_state,
                "supports_brightness": supports_brightness,
                "supports_temperature": supports_temperature,
                "attributes": attributes
            })
        
        return Response({
            "property_name": active_reservation.property.name,
            "property_id": str(active_reservation.property.id),
            "reservation_id": str(active_reservation.id),
            "check_in": active_reservation.check_in_date.isoformat(),
            "check_out": active_reservation.check_out_date.isoformat(),
            "devices_count": len(devices_data),
            "devices": devices_data
        })


class ClientDeviceActionView(HasActiveReservationMixin, APIView):
    """
    Endpoint para clientes: Controlar un dispositivo específico de Home Assistant
    durante su reserva activa.
    
    Requiere autenticación y reserva activa.
    Solo permite controlar dispositivos de la propiedad donde se hospedan,
    marcados como guest_accessible=True.
    """
    authentication_classes = [ClientJWTAuthentication]
    permission_classes = [IsAuthenticated]
    
    @extend_schema(
        request=DeviceActionSerializer,
        responses={
            200: DeviceActionResponseSerializer,
            400: {"type": "object", "properties": {"error": {"type": "string"}}},
            403: {"type": "object", "properties": {"error": {"type": "string"}}},
            404: {"type": "object", "properties": {"error": {"type": "string"}}}
        },
        tags=['Cliente - Home Assistant']
    )
    def post(self, request, reservation_id, device_id):
        """Ejecuta una acción de control en un dispositivo"""
        
        # Validar ownership y que la reserva esté activa
        # request.user ya es un objeto Clients gracias a ClientJWTAuthentication
        try:
            active_reservation = self.validate_reservation_ownership_and_active(
                request.user, 
                reservation_id
            )
        except PermissionDenied as e:
            return Response(
                {"error": str(e)},
                status=status.HTTP_403_FORBIDDEN
            )
        
        # Validar datos de entrada
        serializer = DeviceActionSerializer(data=request.data)
        if not serializer.is_valid():
            return Response(
                {"error": serializer.errors},
                status=status.HTTP_400_BAD_REQUEST
            )
        
        action = serializer.validated_data['action']
        value = serializer.validated_data.get('value')
        
        # Buscar el dispositivo
        try:
            device = HomeAssistantDevice.objects.get(
                id=device_id,
                deleted=False
            )
        except HomeAssistantDevice.DoesNotExist:
            return Response(
                {"error": "Dispositivo no encontrado"},
                status=status.HTTP_404_NOT_FOUND
            )
        
        # Verificar que el dispositivo pertenece a la propiedad de la reserva
        if device.property != active_reservation.property:
            return Response(
                {"error": "No tienes permiso para controlar este dispositivo"},
                status=status.HTTP_403_FORBIDDEN
            )
        
        # Verificar que el dispositivo es accesible para huéspedes
        if not device.guest_accessible:
            return Response(
                {"error": "Este dispositivo no está disponible para huéspedes"},
                status=status.HTTP_403_FORBIDDEN
            )
        
        # Verificar que el dispositivo está activo
        if not device.is_active:
            return Response(
                {"error": "Este dispositivo no está activo"},
                status=status.HTTP_400_BAD_REQUEST
            )
        
        # Validar compatibilidad de la acción con el tipo de dispositivo
        try:
            from rest_framework import serializers as drf_serializers
            serializer.validate_device_compatibility(device, action)
        except drf_serializers.ValidationError as e:
            return Response(
                {"error": str(e.detail) if hasattr(e, 'detail') else str(e)},
                status=status.HTTP_400_BAD_REQUEST
            )
        except Exception as e:
            return Response(
                {"error": str(e)},
                status=status.HTTP_400_BAD_REQUEST
            )
        
        # Inicializar servicio de Home Assistant
        try:
            ha_service = HomeAssistantService()
        except ValueError as e:
            return Response(
                {"error": f"Error de configuración: {str(e)}"},
                status=status.HTTP_500_INTERNAL_SERVER_ERROR
            )
        
        # Ejecutar la acción en Home Assistant
        try:
            result = None
            if action == 'turn_on':
                result = ha_service.turn_on(device.entity_id)
                message = f"{device.friendly_name} encendido"
            elif action == 'turn_off':
                result = ha_service.turn_off(device.entity_id)
                message = f"{device.friendly_name} apagado"
            elif action == 'toggle':
                result = ha_service.toggle(device.entity_id)
                message = f"{device.friendly_name} alternado"
            elif action == 'set_brightness':
                result = ha_service.set_light_brightness(device.entity_id, value)
                message = f"Brillo de {device.friendly_name} ajustado a {value}"
            elif action == 'set_temperature':
                result = ha_service.set_climate_temperature(device.entity_id, value)
                message = f"Temperatura de {device.friendly_name} ajustada a {value}°"
            else:
                return Response(
                    {"error": "Acción no soportada"},
                    status=status.HTTP_400_BAD_REQUEST
                )
            
            # Verificar que el resultado incluya la entidad correcta
            # Home Assistant retorna lista de estados de entidades afectadas
            if isinstance(result, list):
                # Verificar que alguna entidad en la respuesta coincide con nuestro device
                entity_found = any(
                    entity.get('entity_id') == device.entity_id 
                    for entity in result 
                    if isinstance(entity, dict)
                )
                if not entity_found and len(result) > 0:
                    # Advertir si la respuesta no incluye nuestra entidad
                    pass  # La acción se ejecutó pero la respuesta puede no incluir la entidad
            
            # Obtener el estado actualizado del dispositivo directamente
            try:
                entity_state = ha_service.get_entity_state(device.entity_id)
            except Exception:
                entity_state = {"state": "unknown", "entity_id": device.entity_id}
            
            # TODO: Registrar la acción en logs de auditoría
            # Almacenar: client_id, reservation_id, device_id, action, timestamp
            
            return Response({
                "status": "success",
                "message": message,
                "device_id": str(device.id),
                "device_name": device.friendly_name,
                "action": action,
                "value": value,
                "entity_state": entity_state
            })
            
        except Exception as e:
            return Response(
                {"error": f"Error al controlar dispositivo: {str(e)}"},
                status=status.HTTP_502_BAD_GATEWAY
            )
