from rest_framework.views import APIView
from rest_framework.response import Response
from rest_framework import status
from rest_framework.permissions import IsAuthenticated, AllowAny
from asgiref.sync import async_to_sync, sync_to_async
import asyncio
from django.shortcuts import get_object_or_404
from django.utils import timezone

# Importaciones opcionales de Music Assistant (requiere Python 3.11+)
try:
    from music_assistant_models.enums import MediaType, QueueOption
    from apps.reservation.music_client import get_music_client
    MUSIC_ASSISTANT_AVAILABLE = True
except ImportError:
    MUSIC_ASSISTANT_AVAILABLE = False
    MediaType = None
    QueueOption = None

from apps.reservation.music_models import MusicSessionParticipant
from apps.reservation.models import Reservation
from apps.property.models import Property
from apps.clients.auth_views import ClientJWTAuthentication


class PlayersListView(APIView):
    """
    GET /music/players
    Lista todos los reproductores configurados en las propiedades.
    Si Music Assistant está disponible, obtiene estado en tiempo real.
    """
    authentication_classes = [ClientJWTAuthentication]
    permission_classes = [IsAuthenticated]
    
    def _get_active_reservation_for_property(self, property_obj):
        """Obtiene la reserva activa actual para una propiedad."""
        from datetime import time
        
        # Usar hora local del servidor (GMT-5) no UTC
        local_now = timezone.localtime(timezone.now())
        now_date = local_now.date()
        now_time = local_now.time()
        
        checkin_time = time(15, 0)  # 3 PM
        checkout_time = time(11, 0)  # 11 AM
        
        reservations = Reservation.objects.filter(
            property=property_obj,
            deleted=False,
            status__in=['approved', 'pending', 'incomplete', 'under_review']
        ).select_related('client')
        
        for res in reservations:
            # Verificar rango de fechas
            if now_date < res.check_in_date or now_date > res.check_out_date:
                continue
            
            # Si es el día de check-in, debe ser después de las 3 PM
            if now_date == res.check_in_date and now_time < checkin_time:
                continue
            
            # Si es el día de check-out, debe ser antes de las 11 AM
            if now_date == res.check_out_date and now_time >= checkout_time:
                continue
            
            # Esta es la reserva activa actual
            return res
        
        return None
    
    @async_to_sync
    async def get(self, request):
        try:
            # Obtener propiedades con player_id configurado (usando sync_to_async)
            @sync_to_async
            def get_properties_with_details():
                properties = Property.objects.filter(
                    player_id__isnull=False,
                    deleted=False
                ).exclude(player_id='')
                
                result = []
                for prop in properties:
                    prop_data = {
                        'id': prop.id,
                        'name': prop.name,
                        'player_id': prop.player_id,
                        'reservation': None
                    }
                    
                    # Buscar reserva activa
                    active_res = self._get_active_reservation_for_property(prop)
                    if active_res:
                        client = active_res.client
                        # Extraer solo el PRIMER nombre y PRIMER apellido
                        first_name_parts = client.first_name.split() if client.first_name else []
                        last_name_parts = client.last_name.split() if client.last_name else []
                        
                        # Primer nombre y primer apellido - solo primera letra en mayúscula
                        first_name = first_name_parts[0].capitalize() if first_name_parts else ""
                        last_name = last_name_parts[0].capitalize() if last_name_parts else ""
                        
                        prop_data['reservation'] = {
                            'client_name': f"{first_name} {last_name}".strip(),
                            'facebook_linked': client.facebook_linked,
                            'profile_picture': client.get_facebook_profile_picture() if client.facebook_linked else None,
                            'check_in_date': active_res.check_in_date.isoformat(),
                            'check_out_date': active_res.check_out_date.isoformat(),
                        }
                    
                    result.append(prop_data)
                
                return result
            
            properties = await get_properties_with_details()
            players_data = []
            
            # Si Music Assistant está disponible, obtener estado en tiempo real
            if MUSIC_ASSISTANT_AVAILABLE:
                try:
                    music_client = await get_music_client()
                    
                    # Esperar a que los reproductores estén sincronizados
                    max_wait = 20  # Máximo 10 segundos
                    for i in range(max_wait):
                        # Convertir players a lista para verificar
                        players_list = list(music_client.players)
                        if len(players_list) > 0:
                            break
                        await asyncio.sleep(0.5)
                    
                    for prop in properties:
                        # Buscar el player en Music Assistant
                        player = next((p for p in music_client.players if p.player_id == prop['player_id']), None)
                        
                        if player:
                            # Obtener información del media actual
                            current_media_info = None
                            if player.current_media:
                                media_image = None
                                
                                # Intentar obtener la imagen desde la cola activa (más confiable)
                                try:
                                    queue = await music_client.player_queues.get_active_queue(player.player_id)
                                    if queue and queue.current_item:
                                        # El item actual de la cola tiene la metadata completa
                                        if hasattr(queue.current_item, 'image') and queue.current_item.image:
                                            media_image = queue.current_item.image.path
                                except:
                                    pass
                                
                                # Si no se pudo obtener desde la cola, intentar desde current_media
                                if not media_image and hasattr(player.current_media, 'image') and player.current_media.image:
                                    media_image = player.current_media.image.path
                                
                                current_media_info = {
                                    "title": player.current_media.title,
                                    "artist": player.current_media.artist if hasattr(player.current_media, 'artist') else None,
                                    "image": media_image
                                }
                            
                            player_info = {
                                "player_id": player.player_id,
                                "name": player.name,
                                "property_name": prop['name'],
                                "playback_state": player.playback_state.value if player.playback_state else None,
                                "type": player.type.value if player.type else None,
                                "volume_level": player.volume_level,
                                "powered": player.powered,
                                "available": player.available,
                                "current_media": current_media_info
                            }
                            
                            # Agregar información de reserva si existe
                            if prop['reservation']:
                                player_info['reservation'] = prop['reservation']
                            
                            players_data.append(player_info)
                        else:
                            # Player configurado pero no encontrado en Music Assistant
                            player_info = {
                                "player_id": prop['player_id'],
                                "name": f"{prop['name']} (sin conexión)",
                                "property_name": prop['name'],
                                "playback_state": None,
                                "available": False
                            }
                            
                            # Agregar información de reserva si existe
                            if prop['reservation']:
                                player_info['reservation'] = prop['reservation']
                            
                            players_data.append(player_info)
                except Exception as e:
                    # Si falla Music Assistant, continuar con datos básicos
                    for prop in properties:
                        player_info = {
                            "player_id": prop['player_id'],
                            "name": prop['name'],
                            "property_name": prop['name'],
                            "available": False,
                            "error": "No se pudo conectar a Music Assistant"
                        }
                        
                        # Agregar información de reserva si existe
                        if prop['reservation']:
                            player_info['reservation'] = prop['reservation']
                        
                        players_data.append(player_info)
            else:
                # Sin Music Assistant, solo listar los configurados
                for prop in properties:
                    player_info = {
                        "player_id": prop['player_id'],
                        "name": prop['name'],
                        "property_name": prop['name'],
                        "available": None,
                        "note": "Music Assistant no disponible (requiere Python 3.11+)"
                    }
                    
                    # Agregar información de reserva si existe
                    if prop['reservation']:
                        player_info['reservation'] = prop['reservation']
                    
                    players_data.append(player_info)
            
            return Response({
                "success": True,
                "players": players_data,
                "music_assistant_available": MUSIC_ASSISTANT_AVAILABLE
            })
            
        except Exception as e:
            return Response({
                "success": False,
                "error": str(e)
            }, status=status.HTTP_500_INTERNAL_SERVER_ERROR)


class PlayerControlView(APIView):
    """
    Controlador base para comandos de reproductores.
    Verifica permisos de sesión antes de ejecutar comandos.
    """
    authentication_classes = [ClientJWTAuthentication]
    permission_classes = [IsAuthenticated]
    
    def _check_music_available(self):
        """Verifica si Music Assistant está disponible."""
        if not MUSIC_ASSISTANT_AVAILABLE:
            return Response({
                "success": False,
                "error": "Music Assistant no está disponible. Requiere Python 3.11+ y las dependencias music-assistant-client y music-assistant-models."
            }, status=status.HTTP_501_NOT_IMPLEMENTED)
        return None
    
    def _is_reservation_active_now(self, reservation):
        """
        Verifica si la reserva está activa AHORA según los horarios:
        - Check-in: 3 PM del día de llegada
        - Check-out: 11 AM del día de salida
        """
        from datetime import datetime, time
        from django.utils import timezone
        
        # Usar hora local del servidor (GMT-5) no UTC
        local_now = timezone.localtime(timezone.now())
        now_date = local_now.date()
        now_time = local_now.time()
        
        # Horarios configurados
        checkin_time = time(15, 0)  # 3 PM
        checkout_time = time(11, 0)  # 11 AM
        
        # Verificar rango de fechas
        if now_date < reservation.check_in_date or now_date > reservation.check_out_date:
            return False
        
        # Si es el día de check-in, debe ser después de las 3 PM
        if now_date == reservation.check_in_date and now_time < checkin_time:
            return False
        
        # Si es el día de check-out, debe ser antes de las 11 AM
        if now_date == reservation.check_out_date and now_time >= checkout_time:
            return False
        
        return True
    
    async def has_player_permission(self, user, player_id):
        """
        Verifica si el usuario tiene permiso para controlar el reproductor.
        Solo permite acceso a:
        1. El anfitrión (cliente) de LA reserva activa actual en esa propiedad
        2. Participantes aceptados de LA reserva activa actual
        """
        # Obtener la propiedad asociada al player_id
        @sync_to_async
        def get_property():
            try:
                return Property.objects.get(player_id=player_id, deleted=False)
            except Property.DoesNotExist:
                return None
        
        property_obj = await get_property()
        if not property_obj:
            return False
        
        # Buscar LA reserva que está activa AHORA MISMO en esta propiedad
        @sync_to_async
        def get_current_active_reservation():
            # Obtener todas las reservas aprobadas para esta propiedad
            reservations = Reservation.objects.filter(
                property=property_obj,
                deleted=False,
                status__in=['approved', 'pending', 'incomplete', 'under_review']
            )
            
            # Filtrar la que está activa AHORA
            for res in reservations:
                # Usar la función de validación de tiempo
                from datetime import datetime, time
                from django.utils import timezone
                
                # Usar hora local del servidor (GMT-5) no UTC
                local_now = timezone.localtime(timezone.now())
                now_date = local_now.date()
                now_time = local_now.time()
                
                checkin_time = time(15, 0)  # 3 PM
                checkout_time = time(11, 0)  # 11 AM
                
                # Verificar rango de fechas
                if now_date < res.check_in_date or now_date > res.check_out_date:
                    continue
                
                # Si es el día de check-in, debe ser después de las 3 PM
                if now_date == res.check_in_date and now_time < checkin_time:
                    continue
                
                # Si es el día de check-out, debe ser antes de las 11 AM
                if now_date == res.check_out_date and now_time >= checkout_time:
                    continue
                
                # Esta es la reserva activa actual
                return res
            
            return None
        
        active_reservation = await get_current_active_reservation()
        
        # Si no hay ninguna reserva activa, nadie puede controlar
        if not active_reservation:
            return False
        
        # Verificar si el usuario es el anfitrión (owner) de LA reserva activa
        # Usar client_id directamente (sin query) en vez de .client.id
        if active_reservation.client_id == user.id:
            return True
        
        # Verificar si es participante aceptado de LA reserva activa
        @sync_to_async
        def is_accepted_participant():
            return MusicSessionParticipant.objects.filter(
                reservation=active_reservation,
                client=user,
                status='accepted',
                deleted=False
            ).exists()
        
        if await is_accepted_participant():
            return True
        
        return False


class PlayerPlayView(PlayerControlView):
    """
    POST /music/players/{player_id}/play
    Reproduce el contenido actual.
    """
    @async_to_sync
    async def post(self, request, player_id):
        # Verificar disponibilidad de Music Assistant
        error_response = self._check_music_available()
        if error_response:
            return error_response
        
        if not await self.has_player_permission(request.user, player_id):
            return Response({
                "success": False,
                "error": "No tienes permiso para controlar este reproductor"
            }, status=status.HTTP_403_FORBIDDEN)
        
        try:
            music_client = await get_music_client()
            await music_client.players.player_command_play(player_id)
            
            return Response({
                "success": True,
                "message": "Reproducción iniciada"
            })
        except Exception as e:
            return Response({
                "success": False,
                "error": str(e)
            }, status=status.HTTP_500_INTERNAL_SERVER_ERROR)


class PlayerPauseView(PlayerControlView):
    """
    POST /music/players/{player_id}/pause
    Pausa la reproducción actual.
    """
    @async_to_sync
    async def post(self, request, player_id):
        # Verificar disponibilidad de Music Assistant
        error_response = self._check_music_available()
        if error_response:
            return error_response
        
        if not await self.has_player_permission(request.user, player_id):
            return Response({
                "success": False,
                "error": "No tienes permiso para controlar este reproductor"
            }, status=status.HTTP_403_FORBIDDEN)
        
        try:
            music_client = await get_music_client()
            await music_client.players.player_command_pause(player_id)
            
            return Response({
                "success": True,
                "message": "Reproducción pausada"
            })
        except Exception as e:
            return Response({
                "success": False,
                "error": str(e)
            }, status=status.HTTP_500_INTERNAL_SERVER_ERROR)


class PlayerStopView(PlayerControlView):
    """
    POST /music/players/{player_id}/stop
    Detiene la reproducción actual.
    """
    @async_to_sync
    async def post(self, request, player_id):
        # Verificar disponibilidad de Music Assistant
        error_response = self._check_music_available()
        if error_response:
            return error_response
        
        if not await self.has_player_permission(request.user, player_id):
            return Response({
                "success": False,
                "error": "No tienes permiso para controlar este reproductor"
            }, status=status.HTTP_403_FORBIDDEN)
        
        try:
            music_client = await get_music_client()
            await music_client.players.player_command_stop(player_id)
            
            return Response({
                "success": True,
                "message": "Reproducción detenida"
            })
        except Exception as e:
            return Response({
                "success": False,
                "error": str(e)
            }, status=status.HTTP_500_INTERNAL_SERVER_ERROR)


class PlayerNextView(PlayerControlView):
    """
    POST /music/players/{player_id}/next
    Salta a la siguiente pista.
    """
    @async_to_sync
    async def post(self, request, player_id):
        # Verificar disponibilidad de Music Assistant
        error_response = self._check_music_available()
        if error_response:
            return error_response
        
        if not await self.has_player_permission(request.user, player_id):
            return Response({
                "success": False,
                "error": "No tienes permiso para controlar este reproductor"
            }, status=status.HTTP_403_FORBIDDEN)
        
        try:
            music_client = await get_music_client()
            await music_client.players.player_command_next_track(player_id)
            
            return Response({
                "success": True,
                "message": "Pista siguiente"
            })
        except Exception as e:
            return Response({
                "success": False,
                "error": str(e)
            }, status=status.HTTP_500_INTERNAL_SERVER_ERROR)


class PlayerPreviousView(PlayerControlView):
    """
    POST /music/players/{player_id}/previous
    Vuelve a la pista anterior.
    """
    @async_to_sync
    async def post(self, request, player_id):
        # Verificar disponibilidad de Music Assistant
        error_response = self._check_music_available()
        if error_response:
            return error_response
        
        if not await self.has_player_permission(request.user, player_id):
            return Response({
                "success": False,
                "error": "No tienes permiso para controlar este reproductor"
            }, status=status.HTTP_403_FORBIDDEN)
        
        try:
            music_client = await get_music_client()
            await music_client.players.player_command_previous_track(player_id)
            
            return Response({
                "success": True,
                "message": "Pista anterior"
            })
        except Exception as e:
            return Response({
                "success": False,
                "error": str(e)
            }, status=status.HTTP_500_INTERNAL_SERVER_ERROR)


class PlayerVolumeView(PlayerControlView):
    """
    POST /music/players/{player_id}/volume
    Body: {"volume": int} (0-100)
    Ajusta el volumen del reproductor.
    """
    @async_to_sync
    async def post(self, request, player_id):
        # Verificar disponibilidad de Music Assistant
        error_response = self._check_music_available()
        if error_response:
            return error_response
        
        if not await self.has_player_permission(request.user, player_id):
            return Response({
                "success": False,
                "error": "No tienes permiso para controlar este reproductor"
            }, status=status.HTTP_403_FORBIDDEN)
        
        volume = request.data.get('volume')
        
        if volume is None:
            return Response({
                "success": False,
                "error": "El campo 'volume' es requerido"
            }, status=status.HTTP_400_BAD_REQUEST)
        
        try:
            volume = int(volume)
            if volume < 0 or volume > 100:
                return Response({
                    "success": False,
                    "error": "El volumen debe estar entre 0 y 100"
                }, status=status.HTTP_400_BAD_REQUEST)
        except ValueError:
            return Response({
                "success": False,
                "error": "El volumen debe ser un número entero"
            }, status=status.HTTP_400_BAD_REQUEST)
        
        try:
            music_client = await get_music_client()
            await music_client.players.player_command_volume_set(player_id, volume)
            
            return Response({
                "success": True,
                "message": f"Volumen ajustado a {volume}%"
            })
        except Exception as e:
            return Response({
                "success": False,
                "error": str(e)
            }, status=status.HTTP_500_INTERNAL_SERVER_ERROR)


class AutoPowerOnAllView(APIView):
    """
    GET /music/auto-power-on-all
    Revisa TODAS las propiedades, verifica si tienen reserva activa,
    y enciende automáticamente sus reproductores si están apagados.
    Endpoint público para uso en cron jobs.
    """
    authentication_classes = []
    permission_classes = [AllowAny]
    
    @async_to_sync
    async def get(self, request):
        # Verificar disponibilidad de Music Assistant
        if not MUSIC_ASSISTANT_AVAILABLE:
            return Response({
                "success": False,
                "error": "Music Assistant no está disponible"
            }, status=status.HTTP_501_NOT_IMPLEMENTED)
        
        try:
            from apps.property.models import Property
            from django.utils import timezone
            from datetime import time
            
            # Obtener todas las propiedades con reproductor configurado
            @sync_to_async
            def get_properties():
                return list(Property.objects.filter(
                    deleted=False,
                    player_id__isnull=False
                ).exclude(player_id=''))
            
            properties = await get_properties()
            
            if not properties:
                return Response({
                    "success": True,
                    "message": "No hay propiedades con reproductores configurados",
                    "results": []
                })
            
            # Función para verificar reserva activa
            @sync_to_async
            def get_active_reservation(property_obj):
                local_now = timezone.localtime(timezone.now())
                now_date = local_now.date()
                now_time = local_now.time()
                
                reservations = Reservation.objects.filter(
                    property=property_obj,
                    deleted=False,
                    status__in=['approved', 'pending', 'incomplete', 'under_review']
                )
                
                for res in reservations:
                    is_after_checkin = (
                        res.check_in_date < now_date or
                        (res.check_in_date == now_date and now_time >= time(15, 0))
                    )
                    
                    is_before_checkout = (
                        res.check_out_date > now_date or
                        (res.check_out_date == now_date and now_time < time(11, 0))
                    )
                    
                    if is_after_checkin and is_before_checkout:
                        return res
                
                return None
            
            # Obtener cliente de Music Assistant
            music_client = await get_music_client()
            
            results = []
            
            # Procesar cada propiedad
            for property_obj in properties:
                result = {
                    "property_id": str(property_obj.id),
                    "property_name": property_obj.name,
                    "player_id": property_obj.player_id
                }
                
                # Verificar reserva activa
                active_reservation = await get_active_reservation(property_obj)
                
                if not active_reservation:
                    result["action"] = "none"
                    result["reason"] = "No hay reserva activa"
                    result["player_powered"] = None
                    results.append(result)
                    continue
                
                # Hay reserva activa, verificar reproductor
                player = next((p for p in music_client.players if p.player_id == property_obj.player_id), None)
                
                if not player:
                    result["action"] = "error"
                    result["reason"] = "Reproductor no encontrado en Music Assistant"
                    result["player_powered"] = None
                    results.append(result)
                    continue
                
                # Si ya está encendido
                if player.powered:
                    result["action"] = "none"
                    result["reason"] = "Reproductor ya estaba encendido"
                    result["player_powered"] = True
                    results.append(result)
                    continue
                
                # Está apagado y hay reserva activa → ENCENDER
                try:
                    await music_client.players.player_command_power(property_obj.player_id, True)
                    result["action"] = "powered_on"
                    result["reason"] = "Reproductor encendido automáticamente"
                    result["player_powered"] = True
                except Exception as e:
                    result["action"] = "error"
                    result["reason"] = f"Error al encender: {str(e)}"
                    result["player_powered"] = False
                
                results.append(result)
            
            # Contar acciones
            powered_on_count = sum(1 for r in results if r["action"] == "powered_on")
            
            return Response({
                "success": True,
                "message": f"Procesadas {len(results)} propiedades, {powered_on_count} reproductores encendidos",
                "total_properties": len(results),
                "powered_on_count": powered_on_count,
                "results": results
            })
            
        except Exception as e:
            return Response({
                "success": False,
                "error": str(e)
            }, status=status.HTTP_500_INTERNAL_SERVER_ERROR)


class AutoPowerOnView(APIView):
    """
    POST /music/auto-power-on
    Body: {"property_id": str}
    Enciende automáticamente el reproductor si hay una reserva activa y está apagado.
    """
    authentication_classes = [ClientJWTAuthentication]
    permission_classes = [IsAuthenticated]
    
    @async_to_sync
    async def post(self, request):
        # Verificar disponibilidad de Music Assistant
        if not MUSIC_ASSISTANT_AVAILABLE:
            return Response({
                "success": False,
                "error": "Music Assistant no está disponible"
            }, status=status.HTTP_501_NOT_IMPLEMENTED)
        
        property_id = request.data.get('property_id')
        
        if not property_id:
            return Response({
                "success": False,
                "error": "El campo 'property_id' es requerido"
            }, status=status.HTTP_400_BAD_REQUEST)
        
        try:
            # Obtener la propiedad
            from apps.property.models import Property
            from django.utils import timezone
            from datetime import time
            
            property_obj = await sync_to_async(Property.objects.filter(
                id=property_id,
                deleted=False,
                player_id__isnull=False
            ).exclude(player_id='').first)()
            
            if not property_obj:
                return Response({
                    "success": False,
                    "error": "Propiedad no encontrada o sin reproductor configurado"
                }, status=status.HTTP_404_NOT_FOUND)
            
            # Verificar si hay reserva activa
            @sync_to_async
            def get_active_reservation():
                local_now = timezone.localtime(timezone.now())
                now_date = local_now.date()
                now_time = local_now.time()
                
                reservations = Reservation.objects.filter(
                    property=property_obj,
                    deleted=False,
                    status__in=['approved', 'pending', 'incomplete', 'under_review']
                ).select_related('client')
                
                for res in reservations:
                    # Verificar si está activa
                    is_after_checkin = (
                        res.check_in_date < now_date or
                        (res.check_in_date == now_date and now_time >= time(15, 0))
                    )
                    
                    is_before_checkout = (
                        res.check_out_date > now_date or
                        (res.check_out_date == now_date and now_time < time(11, 0))
                    )
                    
                    if is_after_checkin and is_before_checkout:
                        return res
                
                return None
            
            active_reservation = await get_active_reservation()
            
            # Si NO hay reserva activa, no hacer nada
            if not active_reservation:
                return Response({
                    "success": True,
                    "action": "none",
                    "message": "No hay reserva activa, reproductor sin cambios"
                })
            
            # Hay reserva activa, verificar estado del reproductor
            music_client = await get_music_client()
            player = next((p for p in music_client.players if p.player_id == property_obj.player_id), None)
            
            if not player:
                return Response({
                    "success": False,
                    "error": "Reproductor no encontrado en Music Assistant"
                }, status=status.HTTP_404_NOT_FOUND)
            
            # Si ya está encendido, no hacer nada
            if player.powered:
                return Response({
                    "success": True,
                    "action": "none",
                    "message": "Reproductor ya estaba encendido",
                    "player_powered": True
                })
            
            # Está apagado y hay reserva activa → ENCENDER
            await music_client.players.player_command_power(property_obj.player_id, True)
            
            return Response({
                "success": True,
                "action": "powered_on",
                "message": "Reproductor encendido automáticamente",
                "player_powered": True
            })
            
        except Exception as e:
            return Response({
                "success": False,
                "error": str(e)
            }, status=status.HTTP_500_INTERNAL_SERVER_ERROR)


class PlayerPowerView(PlayerControlView):
    """
    POST /music/players/{player_id}/power
    Body: {"powered": bool}
    Enciende (true) o apaga (false) el reproductor.
    """
    @async_to_sync
    async def post(self, request, player_id):
        # Verificar disponibilidad de Music Assistant
        error_response = self._check_music_available()
        if error_response:
            return error_response
        
        if not await self.has_player_permission(request.user, player_id):
            return Response({
                "success": False,
                "error": "No tienes permiso para controlar este reproductor"
            }, status=status.HTTP_403_FORBIDDEN)
        
        powered = request.data.get('powered')
        
        if powered is None:
            return Response({
                "success": False,
                "error": "El campo 'powered' es requerido (true o false)"
            }, status=status.HTTP_400_BAD_REQUEST)
        
        try:
            music_client = await get_music_client()
            await music_client.players.player_command_power(player_id, powered)
            
            action = "encendido" if powered else "apagado"
            return Response({
                "success": True,
                "message": f"Reproductor {action} correctamente"
            })
        except Exception as e:
            return Response({
                "success": False,
                "error": str(e)
            }, status=status.HTTP_500_INTERNAL_SERVER_ERROR)


class PlayerClearQueueView(PlayerControlView):
    """
    POST /music/players/{player_id}/clear-queue
    Limpia toda la cola de reproducción.
    Solo el anfitrión de la reserva activa puede ejecutar este comando.
    """
    @async_to_sync
    async def post(self, request, player_id):
        # Verificar disponibilidad de Music Assistant
        error_response = self._check_music_available()
        if error_response:
            return error_response
        
        # Obtener reservation_id del query param
        reservation_id = request.query_params.get('reservation_id')
        
        if not reservation_id:
            return Response({
                "success": False,
                "error": "El parámetro 'reservation_id' es requerido"
            }, status=status.HTTP_400_BAD_REQUEST)
        
        # Verificar que el usuario es el anfitrión de la reserva (async)
        @sync_to_async
        def check_is_host():
            try:
                reservation = Reservation.objects.select_related('client').get(id=reservation_id, deleted=False)
                # Verificar dentro del contexto sync
                return reservation.client.user_id == request.user.id, True
            except Reservation.DoesNotExist:
                return False, False
        
        is_host, reservation_exists = await check_is_host()
        
        if not reservation_exists:
            return Response({
                "success": False,
                "error": "Reserva no encontrada"
            }, status=status.HTTP_404_NOT_FOUND)
        
        # Solo el anfitrión puede limpiar la cola
        if not is_host:
            return Response({
                "success": False,
                "error": "Solo el anfitrión puede limpiar la cola"
            }, status=status.HTTP_403_FORBIDDEN)
        
        # Verificar que tiene permiso para controlar el reproductor
        if not await self.has_player_permission(request.user, player_id):
            return Response({
                "success": False,
                "error": "No tienes permiso para controlar este reproductor"
            }, status=status.HTTP_403_FORBIDDEN)
        
        try:
            music_client = await get_music_client()
            queue = await music_client.player_queues.get_active_queue(player_id)
            
            if not queue:
                return Response({
                    "success": True,
                    "message": "No hay cola activa para limpiar"
                })
            
            # Limpiar la cola
            await music_client.player_queues.queue_command_clear(queue.queue_id)
            
            return Response({
                "success": True,
                "message": "Cola limpiada correctamente"
            })
        except Exception as e:
            return Response({
                "success": False,
                "error": str(e)
            }, status=status.HTTP_500_INTERNAL_SERVER_ERROR)


class PlayerQueueView(PlayerControlView):
    """
    GET /music/players/{player_id}/queue
    Obtiene la cola de reproducción actual.
    """
    @async_to_sync
    async def get(self, request, player_id):
        # Verificar disponibilidad de Music Assistant
        error_response = self._check_music_available()
        if error_response:
            return error_response
        
        if not self.has_player_permission(request.user, player_id):
            return Response({
                "success": False,
                "error": "No tienes permiso para ver esta cola"
            }, status=status.HTTP_403_FORBIDDEN)
        
        try:
            music_client = await get_music_client()
            queue = await music_client.player_queues.get_active_queue(player_id)
            
            # Si no hay cola activa, devolver cola vacía
            if not queue:
                return Response({
                    "success": True,
                    "queue": {
                        "queue_id": None,
                        "state": None,
                        "current_index": None,
                        "items": []
                    }
                })
            
            items = await music_client.player_queues.get_player_queue_items(queue.queue_id)
            
            # Convertir items a lista y organizarlos
            all_items = []
            for item in items:
                all_items.append({
                    "queue_item_id": item.queue_item_id,
                    "name": item.name,
                    "uri": item.uri,
                    "duration": item.duration,
                    "image": item.image.path if hasattr(item, 'image') and item.image else None
                })
            
            # Separar en pasadas, actual y futuras según current_index
            current_index = queue.current_index if queue.current_index is not None else 0
            
            past_tracks = all_items[:current_index] if current_index > 0 else []
            current_track = all_items[current_index] if current_index < len(all_items) else None
            upcoming_tracks = all_items[current_index + 1:] if current_index < len(all_items) - 1 else []
            
            return Response({
                "success": True,
                "queue": {
                    "queue_id": queue.queue_id,
                    "state": queue.state.value if queue.state else None,
                    "current_index": current_index,
                    "total_items": len(all_items),
                    "past_tracks": past_tracks,
                    "current_track": current_track,
                    "upcoming_tracks": upcoming_tracks,
                    "all_items": all_items  # Mantener compatibilidad con versión anterior
                }
            })
        except Exception as e:
            return Response({
                "success": False,
                "error": str(e)
            }, status=status.HTTP_500_INTERNAL_SERVER_ERROR)


class PlayerPlayMediaView(PlayerControlView):
    """
    POST /music/players/{player_id}/play-media
    Body: {"media_id": str, "media_type": str, "queue_option": str}
    Reproduce un medio específico con opciones de cola.
    """
    @async_to_sync
    async def post(self, request, player_id):
        # Verificar disponibilidad de Music Assistant
        error_response = self._check_music_available()
        if error_response:
            return error_response
        
        if not await self.has_player_permission(request.user, player_id):
            return Response({
                "success": False,
                "error": "No tienes permiso para controlar este reproductor"
            }, status=status.HTTP_403_FORBIDDEN)
        
        media_id = request.data.get('media_id')
        media_type = request.data.get('media_type')
        queue_option_str = request.data.get('queue_option')
        
        if not all([media_id, media_type, queue_option_str]):
            return Response({
                "success": False,
                "error": "Los campos 'media_id', 'media_type' y 'queue_option' son requeridos"
            }, status=status.HTTP_400_BAD_REQUEST)
        
        # Mapear string queue_option al enum QueueOption
        queue_option_map = {
            "play": QueueOption.PLAY,
            "replace": QueueOption.REPLACE,
            "next": QueueOption.NEXT,
            "replace_next": QueueOption.REPLACE_NEXT,
            "add": QueueOption.ADD
        }
        
        queue_option = queue_option_map.get(queue_option_str.lower())
        if queue_option is None:
            return Response({
                "success": False,
                "error": f"queue_option inválido. Opciones válidas: {', '.join(queue_option_map.keys())}"
            }, status=status.HTTP_400_BAD_REQUEST)
        
        try:
            music_client = await get_music_client()
            queue = await music_client.player_queues.get_active_queue(player_id)
            
            # Ejecutar play_media con timeout de 15 segundos
            await asyncio.wait_for(
                music_client.player_queues.play_media(
                    queue_id=queue.queue_id,
                    media=media_id,
                    option=queue_option
                ),
                timeout=15.0
            )
            
            return Response({
                "success": True,
                "message": "Media reproducido correctamente"
            })
        except asyncio.TimeoutError:
            return Response({
                "success": False,
                "error": "Timeout al reproducir el medio. Intenta de nuevo."
            }, status=status.HTTP_504_GATEWAY_TIMEOUT)
        except Exception as e:
            return Response({
                "success": False,
                "error": str(e)
            }, status=status.HTTP_500_INTERNAL_SERVER_ERROR)


class MusicSearchView(APIView):
    """
    POST /music/search
    Body: {"query": str, "media_types": list[str], "limit": int}
    Busca contenido musical.
    """
    authentication_classes = [ClientJWTAuthentication]
    permission_classes = [IsAuthenticated]
    
    @async_to_sync
    async def post(self, request):
        # Verificar disponibilidad de Music Assistant
        if not MUSIC_ASSISTANT_AVAILABLE:
            return Response({
                "success": False,
                "error": "Music Assistant no está disponible. Requiere Python 3.11+ y las dependencias music-assistant-client y music-assistant-models."
            }, status=status.HTTP_501_NOT_IMPLEMENTED)
        
        query = request.data.get('query')
        media_types_str = request.data.get('media_types', [])
        limit = request.data.get('limit', 50)
        
        if not query:
            return Response({
                "success": False,
                "error": "El campo 'query' es requerido"
            }, status=status.HTTP_400_BAD_REQUEST)
        
        # Mapear strings plurales a enums singulares
        media_type_map = {
            "tracks": MediaType.TRACK,
            "artists": MediaType.ARTIST,
            "albums": MediaType.ALBUM,
            "playlists": MediaType.PLAYLIST
        }
        
        media_types_enums = []
        for mt_str in media_types_str:
            mt_enum = media_type_map.get(mt_str.lower())
            if mt_enum:
                media_types_enums.append(mt_enum)
        
        if not media_types_enums:
            # Por defecto buscar en todos
            media_types_enums = list(media_type_map.values())
        
        try:
            music_client = await get_music_client()
            results = await music_client.music.search(
                search_query=query,
                media_types=media_types_enums,
                limit=limit
            )
            
            # Organizar resultados por tipo
            organized_results = {
                "tracks": [],
                "artists": [],
                "albums": [],
                "playlists": []
            }
            
            # SearchResults tiene atributos específicos, no es iterable
            if hasattr(results, 'tracks') and results.tracks:
                for track in results.tracks:
                    organized_results["tracks"].append({
                        "item_id": track.item_id if hasattr(track, 'item_id') else track.uri,
                        "name": track.name,
                        "uri": track.uri if hasattr(track, 'uri') else None,
                        "duration": track.duration if hasattr(track, 'duration') else None,
                        "image": track.image.path if hasattr(track, 'image') and track.image else None
                    })
            
            if hasattr(results, 'artists') and results.artists:
                for artist in results.artists:
                    organized_results["artists"].append({
                        "item_id": artist.item_id if hasattr(artist, 'item_id') else artist.uri,
                        "name": artist.name,
                        "uri": artist.uri if hasattr(artist, 'uri') else None,
                        "image": artist.image.path if hasattr(artist, 'image') and artist.image else None
                    })
            
            if hasattr(results, 'albums') and results.albums:
                for album in results.albums:
                    organized_results["albums"].append({
                        "item_id": album.item_id if hasattr(album, 'item_id') else album.uri,
                        "name": album.name,
                        "uri": album.uri if hasattr(album, 'uri') else None,
                        "image": album.image.path if hasattr(album, 'image') and album.image else None
                    })
            
            if hasattr(results, 'playlists') and results.playlists:
                for playlist in results.playlists:
                    organized_results["playlists"].append({
                        "item_id": playlist.item_id if hasattr(playlist, 'item_id') else playlist.uri,
                        "name": playlist.name,
                        "uri": playlist.uri if hasattr(playlist, 'uri') else None,
                        "image": playlist.image.path if hasattr(playlist, 'image') and playlist.image else None
                    })
            
            return Response({
                "success": True,
                "query": query,
                "results": organized_results
            })
        except Exception as e:
            return Response({
                "success": False,
                "error": str(e)
            }, status=status.HTTP_500_INTERNAL_SERVER_ERROR)


class MusicLibraryTracksView(APIView):
    """
    GET /music/library/tracks
    Obtiene pistas de la biblioteca.
    """
    authentication_classes = [ClientJWTAuthentication]
    permission_classes = [IsAuthenticated]
    
    @async_to_sync
    async def get(self, request):
        # Verificar disponibilidad de Music Assistant
        if not MUSIC_ASSISTANT_AVAILABLE:
            return Response({
                "success": False,
                "error": "Music Assistant no está disponible. Requiere Python 3.11+ y las dependencias music-assistant-client y music-assistant-models."
            }, status=status.HTTP_501_NOT_IMPLEMENTED)
        
        limit = int(request.GET.get('limit', 50))
        offset = int(request.GET.get('offset', 0))
        
        try:
            music_client = await get_music_client()
            tracks = await music_client.music.get_library_tracks(limit=limit, offset=offset)
            
            tracks_data = []
            for track in tracks:
                tracks_data.append({
                    "item_id": track.item_id,
                    "name": track.name,
                    "uri": track.uri if hasattr(track, 'uri') else None,
                    "duration": track.duration if hasattr(track, 'duration') else None
                })
            
            return Response({
                "success": True,
                "tracks": tracks_data,
                "limit": limit,
                "offset": offset
            })
        except Exception as e:
            return Response({
                "success": False,
                "error": str(e)
            }, status=status.HTTP_500_INTERNAL_SERVER_ERROR)


class RequestAccessView(APIView):
    """
    POST /music/sessions/{reservation_id}/request-access/
    Solicita acceso para controlar la música de una reserva.
    """
    authentication_classes = [ClientJWTAuthentication]
    permission_classes = [IsAuthenticated]
    
    def post(self, request, reservation_id):
        try:
            # Verificar que la reserva existe
            reservation = get_object_or_404(
                Reservation,
                id=reservation_id,
                deleted=False,
                status__in=['approved', 'pending', 'incomplete', 'under_review']
            )
            
            # No puede solicitar acceso a su propia reserva
            if reservation.client.id == request.user.id:
                return Response({
                    "success": False,
                    "error": "No puedes solicitar acceso a tu propia reserva"
                }, status=status.HTTP_400_BAD_REQUEST)
            
            # Verificar si ya existe una solicitud activa (no eliminada)
            existing = MusicSessionParticipant.objects.filter(
                reservation=reservation,
                client=request.user,
                deleted=False
            ).first()
            
            if existing:
                return Response({
                    "success": False,
                    "error": f"Ya tienes una solicitud {existing.get_status_display().lower()}",
                    "status": existing.status
                }, status=status.HTTP_400_BAD_REQUEST)
            
            # Verificar si existe una solicitud eliminada (para reutilizarla)
            deleted_participant = MusicSessionParticipant.objects.filter(
                reservation=reservation,
                client=request.user,
                deleted=True
            ).first()
            
            if deleted_participant:
                # Reutilizar el registro eliminado
                deleted_participant.deleted = False
                deleted_participant.status = 'pending'
                deleted_participant.requested_at = timezone.now()
                deleted_participant.accepted_at = None
                deleted_participant.rejected_at = None
                deleted_participant.save()
                participant = deleted_participant
            else:
                # Crear nueva solicitud
                participant = MusicSessionParticipant.objects.create(
                    reservation=reservation,
                    client=request.user,
                    status='pending'
                )
            
            return Response({
                "success": True,
                "request_id": str(participant.id),
                "message": "Solicitud enviada. El anfitrión debe aceptarla."
            }, status=status.HTTP_201_CREATED)
            
        except Exception as e:
            return Response({
                "success": False,
                "error": str(e)
            }, status=status.HTTP_500_INTERNAL_SERVER_ERROR)


class PendingRequestsView(APIView):
    """
    GET /music/sessions/{reservation_id}/requests/
    Lista las solicitudes pendientes (solo anfitrión).
    """
    authentication_classes = [ClientJWTAuthentication]
    permission_classes = [IsAuthenticated]
    
    def get(self, request, reservation_id):
        try:
            # Verificar que la reserva existe y pertenece al usuario
            reservation = get_object_or_404(
                Reservation,
                id=reservation_id,
                client=request.user,
                deleted=False
            )
            
            # Obtener solicitudes pendientes
            requests = MusicSessionParticipant.objects.filter(
                reservation=reservation,
                status='pending',
                deleted=False
            ).select_related('client')
            
            requests_data = []
            for req in requests:
                requests_data.append({
                    "id": str(req.id),
                    "client_id": str(req.client.id),
                    "name": f"{req.client.first_name} {req.client.last_name}",
                    "requested_at": req.requested_at.isoformat()
                })
            
            return Response({
                "success": True,
                "reservation_id": str(reservation.id),
                "property_name": reservation.property.name,
                "pending_requests": requests_data
            })
            
        except Exception as e:
            return Response({
                "success": False,
                "error": str(e)
            }, status=status.HTTP_500_INTERNAL_SERVER_ERROR)


class AcceptRequestView(APIView):
    """
    POST /music/sessions/{reservation_id}/requests/{request_id}/accept/
    Acepta una solicitud (solo anfitrión).
    """
    authentication_classes = [ClientJWTAuthentication]
    permission_classes = [IsAuthenticated]
    
    def post(self, request, reservation_id, request_id):
        try:
            from django.utils import timezone
            
            # Verificar que la reserva existe y pertenece al usuario
            reservation = get_object_or_404(
                Reservation,
                id=reservation_id,
                client=request.user,
                deleted=False
            )
            
            # Buscar la solicitud
            participant = get_object_or_404(
                MusicSessionParticipant,
                id=request_id,
                reservation=reservation,
                deleted=False
            )
            
            if participant.status != 'pending':
                return Response({
                    "success": False,
                    "error": f"La solicitud ya fue {participant.get_status_display().lower()}"
                }, status=status.HTTP_400_BAD_REQUEST)
            
            # Aceptar solicitud
            participant.status = 'accepted'
            participant.accepted_at = timezone.now()
            participant.save()
            
            return Response({
                "success": True,
                "message": f"{participant.client.first_name} puede controlar la música"
            })
            
        except Exception as e:
            return Response({
                "success": False,
                "error": str(e)
            }, status=status.HTTP_500_INTERNAL_SERVER_ERROR)


class RejectRequestView(APIView):
    """
    POST /music/sessions/{reservation_id}/requests/{request_id}/reject/
    Rechaza una solicitud (solo anfitrión).
    """
    authentication_classes = [ClientJWTAuthentication]
    permission_classes = [IsAuthenticated]
    
    def post(self, request, reservation_id, request_id):
        try:
            from django.utils import timezone
            
            # Verificar que la reserva existe y pertenece al usuario
            reservation = get_object_or_404(
                Reservation,
                id=reservation_id,
                client=request.user,
                deleted=False
            )
            
            # Buscar la solicitud
            participant = get_object_or_404(
                MusicSessionParticipant,
                id=request_id,
                reservation=reservation,
                deleted=False
            )
            
            if participant.status != 'pending':
                return Response({
                    "success": False,
                    "error": f"La solicitud ya fue {participant.get_status_display().lower()}"
                }, status=status.HTTP_400_BAD_REQUEST)
            
            # Rechazar solicitud
            participant.status = 'rejected'
            participant.rejected_at = timezone.now()
            participant.save()
            
            return Response({
                "success": True,
                "message": "Solicitud rechazada"
            })
            
        except Exception as e:
            return Response({
                "success": False,
                "error": str(e)
            }, status=status.HTTP_500_INTERNAL_SERVER_ERROR)


class ParticipantsView(APIView):
    """
    GET /music/sessions/{reservation_id}/participants/
    Lista los participantes aceptados.
    """
    authentication_classes = [ClientJWTAuthentication]
    permission_classes = [IsAuthenticated]
    
    def get(self, request, reservation_id):
        try:
            # Verificar que la reserva existe
            reservation = get_object_or_404(
                Reservation,
                id=reservation_id,
                deleted=False
            )
            
            # Verificar que el usuario es el anfitrión o un participante
            is_host = reservation.client.id == request.user.id
            is_participant = MusicSessionParticipant.objects.filter(
                reservation=reservation,
                client=request.user,
                status='accepted',
                deleted=False
            ).exists()
            
            if not is_host and not is_participant:
                return Response({
                    "success": False,
                    "error": "No tienes permiso para ver esta información"
                }, status=status.HTTP_403_FORBIDDEN)
            
            # Obtener participantes aceptados
            participants = MusicSessionParticipant.objects.filter(
                reservation=reservation,
                status='accepted',
                deleted=False
            ).select_related('client')
            
            participants_data = []
            for participant in participants:
                client = participant.client
                # Primer nombre + inicial del apellido
                last_name_initial = client.last_name[0].upper() + "." if client.last_name else ""
                display_name = f"{client.first_name} {last_name_initial}".strip()
                
                participants_data.append({
                    "id": str(participant.id),
                    "client_id": str(client.id),
                    "name": display_name,
                    "facebook_linked": client.facebook_linked,
                    "profile_picture": client.get_facebook_profile_picture() if client.facebook_linked else None,
                    "accepted_at": participant.accepted_at.isoformat() if participant.accepted_at else None
                })
            
            return Response({
                "success": True,
                "reservation_id": str(reservation.id),
                "property_name": reservation.property.name,
                "host": {
                    "id": str(reservation.client.id),
                    "name": f"{reservation.client.first_name} {reservation.client.last_name}"
                },
                "participants": participants_data
            })
            
        except Exception as e:
            return Response({
                "success": False,
                "error": str(e)
            }, status=status.HTTP_500_INTERNAL_SERVER_ERROR)


class RemoveParticipantView(APIView):
    """
    DELETE /music/sessions/{reservation_id}/participants/{participant_id}/
    Expulsa a un participante (solo anfitrión).
    """
    authentication_classes = [ClientJWTAuthentication]
    permission_classes = [IsAuthenticated]
    
    def delete(self, request, reservation_id, participant_id):
        try:
            # Verificar que la reserva existe y pertenece al usuario
            reservation = get_object_or_404(
                Reservation,
                id=reservation_id,
                client=request.user,
                deleted=False
            )
            
            # Buscar participante
            participant = get_object_or_404(
                MusicSessionParticipant,
                id=participant_id,
                reservation=reservation,
                deleted=False
            )
            
            # Eliminar (soft delete)
            participant.deleted = True
            participant.save()
            
            return Response({
                "success": True,
                "message": "Participante expulsado"
            })
            
        except Exception as e:
            return Response({
                "success": False,
                "error": str(e)
            }, status=status.HTTP_500_INTERNAL_SERVER_ERROR)
