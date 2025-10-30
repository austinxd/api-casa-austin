from rest_framework.views import APIView
from rest_framework.response import Response
from rest_framework import status as http_status
from rest_framework.permissions import IsAuthenticated, AllowAny
from django.shortcuts import get_object_or_404
from django.utils import timezone
from datetime import time, datetime
import logging

from apps.reservation.music_client import get_music_client
from apps.reservation.music_models import MusicSessionParticipant
from apps.reservation.models import Reservation
from apps.property.models import Property
from apps.clients.auth_views import ClientJWTAuthentication

logger = logging.getLogger(__name__)


class PlayersListView(APIView):
    """
    GET /music/players
    Lista todos los reproductores configurados en las propiedades.
    Ahora usa la nueva API de música (HTTP).
    """
    authentication_classes = [ClientJWTAuthentication]
    permission_classes = [IsAuthenticated]
    
    def _get_active_reservation_for_property(self, property_obj):
        """Obtiene la reserva activa actual para una propiedad."""
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
    
    def get(self, request):
        try:
            # Buscar reserva activa del usuario autenticado
            local_now = timezone.localtime(timezone.now())
            now_date = local_now.date()
            now_time = local_now.time()
            
            checkin_time = time(15, 0)
            checkout_time = time(11, 0)
            
            # Obtener reservas del usuario
            user_reservations = Reservation.objects.filter(
                client=request.user,
                deleted=False,
                status__in=['approved', 'pending', 'incomplete', 'under_review']
            ).select_related('property')
            
            # Encontrar la reserva activa actual
            active_reservation = None
            for res in user_reservations:
                if now_date < res.check_in_date or now_date > res.check_out_date:
                    continue
                if now_date == res.check_in_date and now_time < checkin_time:
                    continue
                if now_date == res.check_out_date and now_time >= checkout_time:
                    continue
                active_reservation = res
                break
            
            # Si no hay reserva activa, devolver lista vacía
            if not active_reservation:
                return Response({
                    "success": True,
                    "players": []
                })
            
            # Verificar que la propiedad tenga player_id
            prop = active_reservation.property
            if not prop.player_id:
                return Response({
                    "success": True,
                    "players": []
                })
            
            players_data = []
            music_client = get_music_client()
            
            # Obtener estado de todas las casas
            try:
                all_status = music_client.get_all_status()
                houses_status = all_status
            except Exception as e:
                logger.error(f"Error al obtener estado de todas las casas: {e}")
                houses_status = {}
            
            # Obtener estado de esta casa específica
            house_status = houses_status.get(str(prop.player_id), {})
            
            # Mapear campos de la API de música
            is_playing = house_status.get('playing', False)
            is_connected = house_status.get('connected', False)
            
            # Extraer nombre del cliente
            client = active_reservation.client
            first_name_parts = client.first_name.split() if client.first_name else []
            last_name_parts = client.last_name.split() if client.last_name else []
            first_name = first_name_parts[0].capitalize() if first_name_parts else ""
            last_name = last_name_parts[0].capitalize() if last_name_parts else ""
            
            player_info = {
                "player_id": prop.player_id,
                "name": prop.name,
                "property_name": prop.name,
                "available": True,
                "state": "playing" if is_playing else "idle",
                "current_track": house_status.get('current_track'),
                "volume": house_status.get('volume', 0),
                "is_playing": is_playing,
                "power_state": "on" if is_connected else "off",
                "reservation": {
                    'client_name': f"{first_name} {last_name}".strip(),
                    'facebook_linked': client.facebook_linked,
                    'profile_picture': client.get_facebook_profile_picture() if client.facebook_linked else None,
                    'check_in_date': active_reservation.check_in_date.isoformat(),
                    'check_out_date': active_reservation.check_out_date.isoformat(),
                }
            }
            
            players_data.append(player_info)
            
            return Response({
                "success": True,
                "players": players_data
            })
            
        except Exception as e:
            logger.error(f"Error en PlayersListView: {e}", exc_info=True)
            return Response({
                "success": False,
                "error": str(e)
            }, status=http_status.HTTP_500_INTERNAL_SERVER_ERROR)


class PlayerControlView(APIView):
    """
    Controlador base para comandos de reproductores.
    Verifica permisos de sesión antes de ejecutar comandos.
    """
    authentication_classes = [ClientJWTAuthentication]
    permission_classes = [IsAuthenticated]
    
    def _get_house_id_safe(self, player_id):
        """
        Valida que player_id no esté vacío.
        Retorna (house_id, error_response) donde error_response es None si todo está bien.
        player_id se usa directamente como house_id.
        """
        if not player_id:
            logger.error(f"player_id vacío o no configurado")
            error_response = Response({
                "success": False,
                "error": "Reproductor no configurado correctamente"
            }, status=http_status.HTTP_400_BAD_REQUEST)
            return None, error_response
        
        # player_id se usa directamente como house_id
        return player_id, None
    
    def _is_reservation_active_now(self, reservation):
        """
        Verifica si la reserva está activa AHORA según los horarios:
        - Check-in: 3 PM del día de llegada
        - Check-out: 11 AM del día de salida
        """
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
    
    def has_player_permission(self, user, player_id):
        """
        Verifica si el usuario tiene permiso para controlar el reproductor.
        Solo permite acceso a:
        1. El anfitrión (cliente) de LA reserva activa actual en esa propiedad
        2. Participantes aceptados de LA reserva activa actual
        """
        # Obtener la propiedad asociada al player_id
        try:
            property_obj = Property.objects.get(player_id=player_id, deleted=False)
        except Property.DoesNotExist:
            return False
        
        # Buscar LA reserva que está activa AHORA MISMO en esta propiedad
        reservations = Reservation.objects.filter(
            property=property_obj,
            deleted=False,
            status__in=['approved', 'pending', 'incomplete', 'under_review']
        )
        
        # Filtrar la que está activa AHORA
        active_reservation = None
        for res in reservations:
            if self._is_reservation_active_now(res):
                active_reservation = res
                break
        
        # Si no hay ninguna reserva activa, nadie puede controlar
        if not active_reservation:
            return False
        
        # Verificar si el usuario es el anfitrión (owner) de LA reserva activa
        if active_reservation.client_id == user.id:
            return True
        
        # Verificar si es participante aceptado de LA reserva activa
        is_participant = MusicSessionParticipant.objects.filter(
            reservation=active_reservation,
            participant=user,
            status='accepted'
        ).exists()
        
        return is_participant


class PlayerPlayView(PlayerControlView):
    """POST /players/{player_id}/play/"""
    
    def post(self, request, player_id):
        # Verificar permisos
        if not self.has_player_permission(request.user, player_id):
            return Response({
                "success": False,
                "error": "No tienes permiso para controlar este reproductor"
            }, status=http_status.HTTP_403_FORBIDDEN)
        
        # Convertir player_id a house_id con manejo de errores
        house_id, error_response = self._get_house_id_safe(player_id)
        if error_response:
            return error_response
        
        try:
            music_client = get_music_client()
            
            # Obtener track_id si viene en el body
            track_id = request.data.get('track_id')
            
            result = music_client.play(house_id, track_id)
            
            return Response({
                "success": True,
                "message": "Reproducción iniciada",
                "data": result
            })
            
        except Exception as e:
            logger.error(f"Error en PlayerPlayView: {e}", exc_info=True)
            return Response({
                "success": False,
                "error": str(e)
            }, status=http_status.HTTP_500_INTERNAL_SERVER_ERROR)


class PlayerPauseView(PlayerControlView):
    """POST /players/{player_id}/pause/"""
    
    def post(self, request, player_id):
        if not self.has_player_permission(request.user, player_id):
            return Response({
                "success": False,
                "error": "No tienes permiso para controlar este reproductor"
            }, status=http_status.HTTP_403_FORBIDDEN)
        
        house_id, error_response = self._get_house_id_safe(player_id)
        if error_response:
            return error_response
        
        try:
            music_client = get_music_client()
            result = music_client.pause(house_id)
            
            return Response({
                "success": True,
                "message": "Reproducción pausada",
                "data": result
            })
            
        except Exception as e:
            logger.error(f"Error en PlayerPauseView: {e}", exc_info=True)
            return Response({
                "success": False,
                "error": str(e)
            }, status=http_status.HTTP_500_INTERNAL_SERVER_ERROR)


class PlayerStopView(PlayerControlView):
    """POST /players/{player_id}/stop/"""
    
    def post(self, request, player_id):
        if not self.has_player_permission(request.user, player_id):
            return Response({
                "success": False,
                "error": "No tienes permiso para controlar este reproductor"
            }, status=http_status.HTTP_403_FORBIDDEN)
        
        house_id, error_response = self._get_house_id_safe(player_id)
        if error_response:
            return error_response
        
        try:
            music_client = get_music_client()
            result = music_client.stop(house_id)
            
            return Response({
                "success": True,
                "message": "Reproducción detenida",
                "data": result
            })
            
        except Exception as e:
            logger.error(f"Error en PlayerStopView: {e}", exc_info=True)
            return Response({
                "success": False,
                "error": str(e)
            }, status=http_status.HTTP_500_INTERNAL_SERVER_ERROR)


class PlayerNextView(PlayerControlView):
    """POST /players/{player_id}/next/"""
    
    def post(self, request, player_id):
        if not self.has_player_permission(request.user, player_id):
            return Response({
                "success": False,
                "error": "No tienes permiso para controlar este reproductor"
            }, status=http_status.HTTP_403_FORBIDDEN)
        
        house_id, error_response = self._get_house_id_safe(player_id)
        if error_response:
            return error_response
        
        try:
            music_client = get_music_client()
            result = music_client.next_track(house_id)
            
            return Response({
                "success": True,
                "message": "Siguiente canción",
                "data": result
            })
            
        except Exception as e:
            logger.error(f"Error en PlayerNextView: {e}", exc_info=True)
            return Response({
                "success": False,
                "error": str(e)
            }, status=http_status.HTTP_500_INTERNAL_SERVER_ERROR)


class PlayerPreviousView(PlayerControlView):
    """POST /players/{player_id}/previous/"""
    
    def post(self, request, player_id):
        if not self.has_player_permission(request.user, player_id):
            return Response({
                "success": False,
                "error": "No tienes permiso para controlar este reproductor"
            }, status=http_status.HTTP_403_FORBIDDEN)
        
        house_id, error_response = self._get_house_id_safe(player_id)
        if error_response:
            return error_response
        
        try:
            music_client = get_music_client()
            result = music_client.previous_track(house_id)
            
            return Response({
                "success": True,
                "message": "Canción anterior",
                "data": result
            })
            
        except Exception as e:
            logger.error(f"Error en PlayerPreviousView: {e}", exc_info=True)
            return Response({
                "success": False,
                "error": str(e)
            }, status=http_status.HTTP_500_INTERNAL_SERVER_ERROR)


class PlayerVolumeView(PlayerControlView):
    """POST /players/{player_id}/volume/"""
    
    def post(self, request, player_id):
        if not self.has_player_permission(request.user, player_id):
            return Response({
                "success": False,
                "error": "No tienes permiso para controlar este reproductor"
            }, status=http_status.HTTP_403_FORBIDDEN)
        
        house_id, error_response = self._get_house_id_safe(player_id)
        if error_response:
            return error_response
        
        try:
            level = request.data.get('level')
            
            if level is None:
                return Response({
                    "success": False,
                    "error": "Se requiere el parámetro 'level' (0-100)"
                }, status=http_status.HTTP_400_BAD_REQUEST)
            
            music_client = get_music_client()
            result = music_client.set_volume(house_id, int(level))
            
            return Response({
                "success": True,
                "message": f"Volumen ajustado a {level}%",
                "data": result
            })
            
        except Exception as e:
            logger.error(f"Error en PlayerVolumeView: {e}", exc_info=True)
            return Response({
                "success": False,
                "error": str(e)
            }, status=http_status.HTTP_500_INTERNAL_SERVER_ERROR)


class PlayerPowerView(PlayerControlView):
    """POST /players/{player_id}/power/"""
    
    def post(self, request, player_id):
        if not self.has_player_permission(request.user, player_id):
            return Response({
                "success": False,
                "error": "No tienes permiso para controlar este reproductor"
            }, status=http_status.HTTP_403_FORBIDDEN)
        
        house_id, error_response = self._get_house_id_safe(player_id)
        if error_response:
            return error_response
        
        try:
            state = request.data.get('state', 'on')
            
            music_client = get_music_client()
            result = music_client.set_power(house_id, state)
            
            return Response({
                "success": True,
                "message": f"Sistema {'encendido' if state == 'on' else 'apagado'}",
                "data": result
            })
            
        except Exception as e:
            logger.error(f"Error en PlayerPowerView: {e}", exc_info=True)
            return Response({
                "success": False,
                "error": str(e)
            }, status=http_status.HTTP_500_INTERNAL_SERVER_ERROR)


class PlayerQueueView(PlayerControlView):
    """GET /players/{player_id}/queue/"""
    
    def get(self, request, player_id):
        if not self.has_player_permission(request.user, player_id):
            return Response({
                "success": False,
                "error": "No tienes permiso para ver la cola de este reproductor"
            }, status=http_status.HTTP_403_FORBIDDEN)
        
        house_id, error_response = self._get_house_id_safe(player_id)
        if error_response:
            return error_response
        
        try:
            music_client = get_music_client()
            result = music_client.get_queue(house_id)
            
            return Response({
                "success": True,
                "queue": result.get('queue', [])
            })
            
        except Exception as e:
            logger.error(f"Error en PlayerQueueView: {e}", exc_info=True)
            return Response({
                "success": False,
                "error": str(e)
            }, status=http_status.HTTP_500_INTERNAL_SERVER_ERROR)


class PlayerClearQueueView(PlayerControlView):
    """POST /players/{player_id}/clear-queue/"""
    
    def post(self, request, player_id):
        # Solo el host puede limpiar la cola
        try:
            property_obj = Property.objects.get(player_id=player_id, deleted=False)
        except Property.DoesNotExist:
            return Response({
                "success": False,
                "error": "Reproductor no encontrado"
            }, status=http_status.HTTP_404_NOT_FOUND)
        
        # Buscar reserva activa
        reservations = Reservation.objects.filter(
            property=property_obj,
            deleted=False,
            status__in=['approved', 'pending', 'incomplete', 'under_review']
        )
        
        active_reservation = None
        for res in reservations:
            if self._is_reservation_active_now(res):
                active_reservation = res
                break
        
        if not active_reservation:
            return Response({
                "success": False,
                "error": "No hay sesión activa"
            }, status=http_status.HTTP_403_FORBIDDEN)
        
        # Solo el host puede limpiar la cola
        if active_reservation.client_id != request.user.id:
            return Response({
                "success": False,
                "error": "Solo el anfitrión puede limpiar la cola"
            }, status=http_status.HTTP_403_FORBIDDEN)
        
        house_id, error_response = self._get_house_id_safe(player_id)
        if error_response:
            return error_response
        
        try:
            music_client = get_music_client()
            result = music_client.clear_queue(house_id)
            
            return Response({
                "success": True,
                "message": "Cola limpiada",
                "data": result
            })
            
        except Exception as e:
            logger.error(f"Error en PlayerClearQueueView: {e}", exc_info=True)
            return Response({
                "success": False,
                "error": str(e)
            }, status=http_status.HTTP_500_INTERNAL_SERVER_ERROR)


class PlayerPlayMediaView(PlayerControlView):
    """POST /players/{player_id}/play-media/"""
    
    def post(self, request, player_id):
        if not self.has_player_permission(request.user, player_id):
            return Response({
                "success": False,
                "error": "No tienes permiso para controlar este reproductor"
            }, status=http_status.HTTP_403_FORBIDDEN)
        
        house_id, error_response = self._get_house_id_safe(player_id)
        if error_response:
            return error_response
        
        try:
            track_id = request.data.get('track_id')
            track_name = request.data.get('track_name')
            artist = request.data.get('artist')
            
            if not track_id:
                return Response({
                    "success": False,
                    "error": "Se requiere el parámetro 'track_id'"
                }, status=http_status.HTTP_400_BAD_REQUEST)
            
            if not track_name:
                return Response({
                    "success": False,
                    "error": "Se requiere el parámetro 'track_name'"
                }, status=http_status.HTTP_400_BAD_REQUEST)
            
            if not artist:
                return Response({
                    "success": False,
                    "error": "Se requiere el parámetro 'artist'"
                }, status=http_status.HTTP_400_BAD_REQUEST)
            
            music_client = get_music_client()
            
            # Agregar a cola
            result = music_client.add_to_queue(house_id, track_id, track_name, artist)
            
            return Response({
                "success": True,
                "message": "Canción agregada a la cola",
                "data": result
            })
            
        except Exception as e:
            logger.error(f"Error en PlayerPlayMediaView: {e}", exc_info=True)
            return Response({
                "success": False,
                "error": str(e)
            }, status=http_status.HTTP_500_INTERNAL_SERVER_ERROR)


class MusicSearchView(APIView):
    """POST /music/search/"""
    authentication_classes = [ClientJWTAuthentication]
    permission_classes = [IsAuthenticated]
    
    def post(self, request):
        try:
            query = request.data.get('query')
            limit = request.data.get('limit', 20)
            
            if not query:
                return Response({
                    "success": False,
                    "error": "Se requiere el parámetro 'query'"
                }, status=http_status.HTTP_400_BAD_REQUEST)
            
            music_client = get_music_client()
            result = music_client.search_tracks(query, limit)
            
            return Response({
                "success": True,
                "results": result.get('tracks', [])
            })
            
        except Exception as e:
            logger.error(f"Error en MusicSearchView: {e}", exc_info=True)
            return Response({
                "success": False,
                "error": str(e)
            }, status=http_status.HTTP_500_INTERNAL_SERVER_ERROR)


class MusicLibraryTracksView(APIView):
    """GET /music/library/tracks/"""
    authentication_classes = [ClientJWTAuthentication]
    permission_classes = [IsAuthenticated]
    
    def get(self, request):
        try:
            music_client = get_music_client()
            result = music_client.get_charts()
            
            return Response({
                "success": True,
                "tracks": result.get('tracks', [])
            })
            
        except Exception as e:
            logger.error(f"Error en MusicLibraryTracksView: {e}", exc_info=True)
            return Response({
                "success": False,
                "error": str(e)
            }, status=http_status.HTTP_500_INTERNAL_SERVER_ERROR)


class MusicAssistantDebugView(APIView):
    """GET /music/debug/all-players/"""
    permission_classes = [AllowAny]
    
    def get(self, request):
        try:
            music_client = get_music_client()
            all_status = music_client.get_all_status()
            
            return Response({
                "success": True,
                "status": all_status
            })
            
        except Exception as e:
            logger.error(f"Error en MusicAssistantDebugView: {e}", exc_info=True)
            return Response({
                "success": False,
                "error": str(e)
            }, status=http_status.HTTP_500_INTERNAL_SERVER_ERROR)


class MusicAssistantHealthView(APIView):
    """GET /music/health/"""
    permission_classes = [AllowAny]
    
    def get(self, request):
        try:
            music_client = get_music_client()
            all_status = music_client.get_all_status()
            
            return Response({
                "success": True,
                "status": "healthy",
                "houses_count": len(all_status.get('houses', {}))
            })
            
        except Exception as e:
            logger.error(f"Error en MusicAssistantHealthView: {e}", exc_info=True)
            return Response({
                "success": False,
                "status": "unhealthy",
                "error": str(e)
            }, status=http_status.HTTP_503_SERVICE_UNAVAILABLE)


class AutoPowerOnView(APIView):
    """POST /music/auto-power-on/"""
    authentication_classes = [ClientJWTAuthentication]
    permission_classes = [IsAuthenticated]
    
    def post(self, request):
        try:
            property_id = request.data.get('property_id')
            
            if not property_id:
                return Response({
                    "success": False,
                    "error": "Se requiere property_id"
                }, status=http_status.HTTP_400_BAD_REQUEST)
            
            # Obtener propiedad
            try:
                property_obj = Property.objects.get(id=property_id, deleted=False)
            except Property.DoesNotExist:
                return Response({
                    "success": False,
                    "error": "Propiedad no encontrada"
                }, status=http_status.HTTP_404_NOT_FOUND)
            
            if not property_obj.player_id:
                return Response({
                    "success": False,
                    "error": "Esta propiedad no tiene reproductor configurado"
                }, status=http_status.HTTP_400_BAD_REQUEST)
            
            # Verificar si hay reserva activa
            local_now = timezone.localtime(timezone.now())
            now_date = local_now.date()
            now_time = local_now.time()
            
            checkin_time = time(15, 0)
            checkout_time = time(11, 0)
            
            reservations = Reservation.objects.filter(
                property=property_obj,
                deleted=False,
                status__in=['approved', 'pending', 'incomplete', 'under_review']
            )
            
            active_reservation = None
            for res in reservations:
                if now_date < res.check_in_date or now_date > res.check_out_date:
                    continue
                if now_date == res.check_in_date and now_time < checkin_time:
                    continue
                if now_date == res.check_out_date and now_time >= checkout_time:
                    continue
                active_reservation = res
                break
            
            if not active_reservation:
                return Response({
                    "success": False,
                    "error": "No hay reserva activa en esta propiedad"
                }, status=http_status.HTTP_400_BAD_REQUEST)
            
            # Encender el reproductor (player_id se usa directamente como house_id)
            music_client = get_music_client()
            result = music_client.set_power(property_obj.player_id, "on")
            
            return Response({
                "success": True,
                "message": f"Reproductor encendido para {property_obj.name}",
                "data": result
            })
            
        except Exception as e:
            logger.error(f"Error en AutoPowerOnView: {e}", exc_info=True)
            return Response({
                "success": False,
                "error": str(e)
            }, status=http_status.HTTP_500_INTERNAL_SERVER_ERROR)


class AutoPowerOnAllView(APIView):
    """GET /music/auto-power-on-all/"""
    permission_classes = [AllowAny]
    
    def get(self, request):
        try:
            local_now = timezone.localtime(timezone.now())
            now_date = local_now.date()
            now_time = local_now.time()
            
            checkin_time = time(15, 0)
            checkout_time = time(11, 0)
            
            # Obtener todas las propiedades con player_id
            properties = Property.objects.filter(
                player_id__isnull=False,
                deleted=False
            ).exclude(player_id='')
            
            music_client = get_music_client()
            powered_on = []
            
            for prop in properties:
                # Buscar reserva activa
                reservations = Reservation.objects.filter(
                    property=prop,
                    deleted=False,
                    status__in=['approved', 'pending', 'incomplete', 'under_review']
                )
                
                has_active = False
                for res in reservations:
                    if now_date < res.check_in_date or now_date > res.check_out_date:
                        continue
                    if now_date == res.check_in_date and now_time < checkin_time:
                        continue
                    if now_date == res.check_out_date and now_time >= checkout_time:
                        continue
                    has_active = True
                    break
                
                if has_active:
                    try:
                        # player_id se usa directamente como house_id
                        music_client.set_power(prop.player_id, "on")
                        powered_on.append(prop.name)
                    except Exception as e:
                        logger.error(f"Error encendiendo {prop.name}: {e}")
            
            return Response({
                "success": True,
                "message": f"Encendidos: {len(powered_on)} reproductores",
                "powered_on": powered_on
            })
            
        except Exception as e:
            logger.error(f"Error en AutoPowerOnAllView: {e}", exc_info=True)
            return Response({
                "success": False,
                "error": str(e)
            }, status=http_status.HTTP_503_SERVICE_UNAVAILABLE)


# ==================== ENDPOINTS DE SESIONES (sin cambios) ====================

class RequestAccessView(APIView):
    """Solicitar acceso a controlar la música de una sesión"""
    authentication_classes = [ClientJWTAuthentication]
    permission_classes = [IsAuthenticated]

    def post(self, request, reservation_id):
        reservation = get_object_or_404(
            Reservation,
            id=reservation_id,
            deleted=False,
            status__in=['approved', 'pending', 'incomplete', 'under_review']
        )
        
        # Verificar que la reserva esté activa
        local_now = timezone.localtime(timezone.now())
        now_date = local_now.date()
        now_time = local_now.time()
        
        checkin_time = time(15, 0)
        checkout_time = time(11, 0)
        
        if now_date < reservation.check_in_date or now_date > reservation.check_out_date:
            return Response({
                "success": False,
                "error": "La sesión no está activa"
            }, status=http_status.HTTP_400_BAD_REQUEST)
        
        if now_date == reservation.check_in_date and now_time < checkin_time:
            return Response({
                "success": False,
                "error": "La sesión no ha comenzado (inicia a las 3 PM)"
            }, status=http_status.HTTP_400_BAD_REQUEST)
        
        if now_date == reservation.check_out_date and now_time >= checkout_time:
            return Response({
                "success": False,
                "error": "La sesión ya terminó (termina a las 11 AM)"
            }, status=http_status.HTTP_400_BAD_REQUEST)
        
        # Verificar que no sea el host
        if reservation.client == request.user:
            return Response({
                "success": False,
                "error": "Ya eres el anfitrión de esta sesión"
            }, status=http_status.HTTP_400_BAD_REQUEST)
        
        # Verificar si ya tiene una solicitud pendiente o aceptada
        existing = MusicSessionParticipant.objects.filter(
            reservation=reservation,
            participant=request.user,
            status__in=['pending', 'accepted']
        ).first()
        
        if existing:
            if existing.status == 'accepted':
                return Response({
                    "success": False,
                    "error": "Ya tienes acceso a esta sesión"
                }, status=http_status.HTTP_400_BAD_REQUEST)
            else:
                return Response({
                    "success": False,
                    "error": "Ya tienes una solicitud pendiente"
                }, status=http_status.HTTP_400_BAD_REQUEST)
        
        # Crear solicitud
        participant = MusicSessionParticipant.objects.create(
            reservation=reservation,
            participant=request.user,
            status='pending'
        )
        
        return Response({
            "success": True,
            "message": "Solicitud enviada al anfitrión",
            "request_id": str(participant.id)
        })


class PendingRequestsView(APIView):
    """Ver solicitudes pendientes (solo host)"""
    authentication_classes = [ClientJWTAuthentication]
    permission_classes = [IsAuthenticated]

    def get(self, request, reservation_id):
        reservation = get_object_or_404(
            Reservation,
            id=reservation_id,
            deleted=False
        )
        
        # Solo el host puede ver solicitudes
        if reservation.client != request.user:
            return Response({
                "success": False,
                "error": "Solo el anfitrión puede ver solicitudes"
            }, status=http_status.HTTP_403_FORBIDDEN)
        
        # Obtener solicitudes pendientes
        requests_qs = MusicSessionParticipant.objects.filter(
            reservation=reservation,
            status='pending'
        ).select_related('client')
        
        requests_data = []
        for req in requests_qs:
            participant = req.client
            requests_data.append({
                'request_id': str(req.id),
                'id': str(participant.id),
                'name': f"{participant.first_name} {participant.last_name}",
                'facebook_linked': participant.facebook_linked,
                'profile_picture': participant.get_facebook_profile_picture() if participant.facebook_linked else None,
                'created_at': req.created_at.isoformat()
            })
        
        return Response({
            "success": True,
            "requests": requests_data
        })


class AcceptRequestView(APIView):
    """Aceptar solicitud de acceso (solo host)"""
    authentication_classes = [ClientJWTAuthentication]
    permission_classes = [IsAuthenticated]

    def post(self, request, reservation_id, request_id):
        reservation = get_object_or_404(
            Reservation,
            id=reservation_id,
            deleted=False
        )
        
        # Solo el host puede aceptar solicitudes
        if reservation.client != request.user:
            return Response({
                "success": False,
                "error": "Solo el anfitrión puede aceptar solicitudes"
            }, status=http_status.HTTP_403_FORBIDDEN)
        
        # Obtener solicitud
        participant_req = get_object_or_404(
            MusicSessionParticipant,
            id=request_id,
            reservation=reservation,
            status='pending'
        )
        
        # Aceptar
        participant_req.status = 'accepted'
        participant_req.save()
        
        return Response({
            "success": True,
            "message": "Solicitud aceptada"
        })


class RejectRequestView(APIView):
    """Rechazar solicitud de acceso (solo host)"""
    authentication_classes = [ClientJWTAuthentication]
    permission_classes = [IsAuthenticated]

    def post(self, request, reservation_id, request_id):
        reservation = get_object_or_404(
            Reservation,
            id=reservation_id,
            deleted=False
        )
        
        # Solo el host puede rechazar solicitudes
        if reservation.client != request.user:
            return Response({
                "success": False,
                "error": "Solo el anfitrión puede rechazar solicitudes"
            }, status=http_status.HTTP_403_FORBIDDEN)
        
        # Obtener solicitud
        participant_req = get_object_or_404(
            MusicSessionParticipant,
            id=request_id,
            reservation=reservation,
            status='pending'
        )
        
        # Rechazar
        participant_req.status = 'rejected'
        participant_req.save()
        
        return Response({
            "success": True,
            "message": "Solicitud rechazada"
        })


class ParticipantsView(APIView):
    """Ver participantes de una sesión"""
    authentication_classes = [ClientJWTAuthentication]
    permission_classes = [IsAuthenticated]

    def get(self, request, reservation_id):
        reservation = get_object_or_404(
            Reservation,
            id=reservation_id,
            deleted=False
        )
        
        # Verificar estado de la sesión
        from django.conf import settings
        local_now = timezone.localtime(timezone.now())
        now_date = local_now.date()
        now_time = local_now.time()
        
        checkin_time = time(15, 0)
        checkout_time = time(11, 0)
        
        # Determinar estado de la sesión
        if now_date < reservation.check_in_date:
            # Sesión no ha comenzado
            checkin_datetime = timezone.make_aware(
                datetime.combine(reservation.check_in_date, checkin_time)
            ) if settings.USE_TZ else datetime.combine(reservation.check_in_date, checkin_time)
            
            return Response({
                "success": True,
                "session_active": False,
                "status": "not_started",
                "message": "Sesión programada",
                "activation_date": checkin_datetime.isoformat(),
                "host": None,
                "participants": []
            })
        
        if now_date > reservation.check_out_date or (now_date == reservation.check_out_date and now_time >= checkout_time):
            # Sesión terminada
            checkout_datetime = timezone.make_aware(
                datetime.combine(reservation.check_out_date, checkout_time)
            ) if settings.USE_TZ else datetime.combine(reservation.check_out_date, checkout_time)
            
            return Response({
                "success": True,
                "session_active": False,
                "status": "ended",
                "message": "Sesión finalizada",
                "termination_date": checkout_datetime.isoformat(),
                "host": None,
                "participants": []
            })
        
        if now_date == reservation.check_in_date and now_time < checkin_time:
            # Día de check-in pero antes de las 3 PM
            checkin_datetime = timezone.make_aware(
                datetime.combine(reservation.check_in_date, checkin_time)
            ) if settings.USE_TZ else datetime.combine(reservation.check_in_date, checkin_time)
            
            return Response({
                "success": True,
                "session_active": False,
                "status": "not_started",
                "message": "Sesión programada",
                "activation_date": checkin_datetime.isoformat(),
                "host": None,
                "participants": []
            })
        
        # Sesión activa - mostrar host y participantes
        host = reservation.client
        host_data = {
            'id': str(host.id),
            'name': f"{host.first_name} {host.last_name}",
            'facebook_linked': host.facebook_linked,
            'profile_picture': host.get_facebook_profile_picture() if host.facebook_linked else None
        }
        
        # Obtener participantes aceptados
        participants_qs = MusicSessionParticipant.objects.filter(
            reservation=reservation,
            status='accepted'
        ).select_related('client')
        
        participants_data = []
        for p in participants_qs:
            participant = p.client
            participants_data.append({
                'participant_id': str(p.id),
                'id': str(participant.id),
                'name': f"{participant.first_name} {participant.last_name}",
                'facebook_linked': participant.facebook_linked,
                'profile_picture': participant.get_facebook_profile_picture() if participant.facebook_linked else None
            })
        
        return Response({
            "success": True,
            "session_active": True,
            "status": "active",
            "message": "Muestra datos de sesión",
            "host": host_data,
            "participants": participants_data
        })


class RemoveParticipantView(APIView):
    """Remover participante de una sesión (solo host)"""
    authentication_classes = [ClientJWTAuthentication]
    permission_classes = [IsAuthenticated]

    def delete(self, request, reservation_id, participant_id):
        reservation = get_object_or_404(
            Reservation,
            id=reservation_id,
            deleted=False
        )
        
        # Solo el host puede remover participantes
        if reservation.client != request.user:
            return Response({
                "success": False,
                "error": "Solo el anfitrión puede remover participantes"
            }, status=http_status.HTTP_403_FORBIDDEN)
        
        # Obtener participante
        participant = get_object_or_404(
            MusicSessionParticipant,
            id=participant_id,
            reservation=reservation
        )
        
        # Eliminar
        participant.delete()
        
        return Response({
            "success": True,
            "message": "Participante removido"
        })
