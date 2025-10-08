from rest_framework.views import APIView
from rest_framework.response import Response
from rest_framework import status
from rest_framework.permissions import IsAuthenticated, AllowAny
from asgiref.sync import async_to_sync
import asyncio
from music_assistant_models.enums import MediaType, QueueOption

from apps.reservation.music_client import get_music_client
from apps.reservation.music_models import MusicSession, MusicSessionParticipant
from apps.reservation.models import Reservation
from apps.property.models import Property
from apps.clients.auth_views import ClientJWTAuthentication
from django.shortcuts import get_object_or_404


class PlayersListView(APIView):
    """
    GET /music/players
    Lista todos los reproductores disponibles en Music Assistant.
    """
    authentication_classes = [ClientJWTAuthentication]
    permission_classes = [IsAuthenticated]
    
    @async_to_sync
    async def get(self, request):
        try:
            music_client = await get_music_client()
            players_data = []
            
            for player in music_client.players:
                player_info = {
                    "player_id": player.player_id,
                    "name": player.name,
                    "playback_state": player.playback_state.value if player.playback_state else None,
                    "type": player.type.value if player.type else None,
                    "volume_level": player.volume_level,
                    "powered": player.powered,
                    "available": player.available,
                    "current_media": {
                        "title": player.current_media.title if player.current_media else None
                    } if player.current_media else None
                }
                players_data.append(player_info)
            
            return Response({
                "success": True,
                "players": players_data
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
    
    def has_player_permission(self, user, player_id):
        """
        Verifica si el usuario tiene permiso para controlar el reproductor.
        """
        # Obtener la propiedad asociada al player_id
        try:
            property_obj = Property.objects.get(player_id=player_id, deleted=False)
        except Property.DoesNotExist:
            return False
        
        # Verificar si hay una reserva activa del usuario para esta propiedad
        from datetime import date
        today = date.today()
        
        active_reservation = Reservation.objects.filter(
            client=user,
            property=property_obj,
            check_in_date__lte=today,
            check_out_date__gte=today,
            deleted=False,
            status__in=['approved', 'pending', 'incomplete', 'under_review']
        ).first()
        
        if active_reservation:
            # Si es el host de la reserva, tiene permiso
            return True
        
        # Verificar si es participante de alguna sesión activa
        participant = MusicSessionParticipant.objects.filter(
            client=user,
            session__reservation__property=property_obj,
            session__is_active=True,
            deleted=False
        ).first()
        
        return participant is not None


class PlayerPlayView(PlayerControlView):
    """
    POST /music/players/{player_id}/play
    Reproduce el contenido actual.
    """
    @async_to_sync
    async def post(self, request, player_id):
        if not self.has_player_permission(request.user, player_id):
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
        if not self.has_player_permission(request.user, player_id):
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
        if not self.has_player_permission(request.user, player_id):
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
        if not self.has_player_permission(request.user, player_id):
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
        if not self.has_player_permission(request.user, player_id):
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
        if not self.has_player_permission(request.user, player_id):
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


class PlayerQueueView(PlayerControlView):
    """
    GET /music/players/{player_id}/queue
    Obtiene la cola de reproducción actual.
    """
    @async_to_sync
    async def get(self, request, player_id):
        if not self.has_player_permission(request.user, player_id):
            return Response({
                "success": False,
                "error": "No tienes permiso para ver esta cola"
            }, status=status.HTTP_403_FORBIDDEN)
        
        try:
            music_client = await get_music_client()
            queue = await music_client.player_queues.get_active_queue(player_id)
            items = await music_client.player_queues.get_player_queue_items(queue.queue_id)
            
            items_data = []
            for item in items:
                items_data.append({
                    "queue_item_id": item.queue_item_id,
                    "name": item.name,
                    "uri": item.uri,
                    "duration": item.duration
                })
            
            return Response({
                "success": True,
                "queue": {
                    "queue_id": queue.queue_id,
                    "state": queue.state.value if queue.state else None,
                    "current_index": queue.current_index,
                    "items": items_data
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
        if not self.has_player_permission(request.user, player_id):
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
            await music_client.player_queues.play_media(
                queue_id=queue.queue_id,
                media=media_id,
                option=queue_option
            )
            
            return Response({
                "success": True,
                "message": "Media reproducido correctamente"
            })
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
            
            for item in results:
                item_data = {
                    "item_id": item.item_id,
                    "name": item.name,
                    "uri": item.uri if hasattr(item, 'uri') else None
                }
                
                if item.media_type == MediaType.TRACK:
                    organized_results["tracks"].append(item_data)
                elif item.media_type == MediaType.ARTIST:
                    organized_results["artists"].append(item_data)
                elif item.media_type == MediaType.ALBUM:
                    organized_results["albums"].append(item_data)
                elif item.media_type == MediaType.PLAYLIST:
                    organized_results["playlists"].append(item_data)
            
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


class MusicSessionCreateView(APIView):
    """
    POST /music/sessions/create
    Body: {"reservation_id": str}
    Crea una sesión de música para la reserva activa.
    """
    authentication_classes = [ClientJWTAuthentication]
    permission_classes = [IsAuthenticated]
    
    def post(self, request):
        reservation_id = request.data.get('reservation_id')
        
        if not reservation_id:
            return Response({
                "success": False,
                "error": "El campo 'reservation_id' es requerido"
            }, status=status.HTTP_400_BAD_REQUEST)
        
        try:
            # Verificar que la reserva existe y pertenece al usuario
            reservation = get_object_or_404(
                Reservation,
                id=reservation_id,
                client=request.user,
                deleted=False
            )
            
            # Verificar que no exista ya una sesión activa
            existing_session = MusicSession.objects.filter(
                reservation=reservation,
                is_active=True,
                deleted=False
            ).first()
            
            if existing_session:
                return Response({
                    "success": False,
                    "error": "Ya existe una sesión activa para esta reserva",
                    "session_id": str(existing_session.id)
                }, status=status.HTTP_400_BAD_REQUEST)
            
            # Crear nueva sesión
            session = MusicSession.objects.create(
                reservation=reservation,
                host_client=request.user,
                is_active=True
            )
            
            return Response({
                "success": True,
                "session_id": str(session.id),
                "message": "Sesión de música creada correctamente"
            }, status=status.HTTP_201_CREATED)
            
        except Exception as e:
            return Response({
                "success": False,
                "error": str(e)
            }, status=status.HTTP_500_INTERNAL_SERVER_ERROR)


class MusicSessionAddParticipantView(APIView):
    """
    POST /music/sessions/{session_id}/add-participant
    Body: {"client_id": str}
    Acepta a un participante en la sesión de música.
    """
    authentication_classes = [ClientJWTAuthentication]
    permission_classes = [IsAuthenticated]
    
    def post(self, request, session_id):
        client_id = request.data.get('client_id')
        
        if not client_id:
            return Response({
                "success": False,
                "error": "El campo 'client_id' es requerido"
            }, status=status.HTTP_400_BAD_REQUEST)
        
        try:
            # Verificar que la sesión existe y pertenece al usuario
            session = get_object_or_404(
                MusicSession,
                id=session_id,
                host_client=request.user,
                is_active=True,
                deleted=False
            )
            
            # Verificar que el cliente a agregar existe
            from apps.clients.models import Clients
            participant_client = get_object_or_404(Clients, id=client_id, deleted=False)
            
            # Verificar que no sea el mismo host
            if participant_client.id == request.user.id:
                return Response({
                    "success": False,
                    "error": "No puedes agregarte a ti mismo como participante"
                }, status=status.HTTP_400_BAD_REQUEST)
            
            # Verificar que no esté ya agregado
            existing_participant = MusicSessionParticipant.objects.filter(
                session=session,
                client=participant_client,
                deleted=False
            ).first()
            
            if existing_participant:
                return Response({
                    "success": False,
                    "error": "Este cliente ya es participante de la sesión"
                }, status=status.HTTP_400_BAD_REQUEST)
            
            # Agregar participante
            participant = MusicSessionParticipant.objects.create(
                session=session,
                client=participant_client
            )
            
            return Response({
                "success": True,
                "participant_id": str(participant.id),
                "message": f"{participant_client.first_name} {participant_client.last_name} agregado como participante"
            }, status=status.HTTP_201_CREATED)
            
        except Exception as e:
            return Response({
                "success": False,
                "error": str(e)
            }, status=status.HTTP_500_INTERNAL_SERVER_ERROR)


class MusicSessionParticipantsView(APIView):
    """
    GET /music/sessions/{session_id}/participants
    Lista los participantes de una sesión.
    """
    authentication_classes = [ClientJWTAuthentication]
    permission_classes = [IsAuthenticated]
    
    def get(self, request, session_id):
        try:
            # Verificar que la sesión existe
            session = get_object_or_404(
                MusicSession,
                id=session_id,
                deleted=False
            )
            
            # Verificar que el usuario es el host o un participante
            is_host = session.host_client.id == request.user.id
            is_participant = MusicSessionParticipant.objects.filter(
                session=session,
                client=request.user,
                deleted=False
            ).exists()
            
            if not is_host and not is_participant:
                return Response({
                    "success": False,
                    "error": "No tienes permiso para ver esta sesión"
                }, status=status.HTTP_403_FORBIDDEN)
            
            # Obtener participantes
            participants = MusicSessionParticipant.objects.filter(
                session=session,
                deleted=False
            ).select_related('client')
            
            participants_data = []
            for participant in participants:
                participants_data.append({
                    "id": str(participant.id),
                    "client_id": str(participant.client.id),
                    "name": f"{participant.client.first_name} {participant.client.last_name}",
                    "accepted_at": participant.accepted_at.isoformat()
                })
            
            return Response({
                "success": True,
                "session_id": str(session.id),
                "host": {
                    "id": str(session.host_client.id),
                    "name": f"{session.host_client.first_name} {session.host_client.last_name}"
                },
                "participants": participants_data,
                "is_active": session.is_active
            })
            
        except Exception as e:
            return Response({
                "success": False,
                "error": str(e)
            }, status=status.HTTP_500_INTERNAL_SERVER_ERROR)


class MusicSessionRemoveParticipantView(APIView):
    """
    DELETE /music/sessions/{session_id}/participants/{participant_id}
    Elimina a un participante de la sesión.
    """
    authentication_classes = [ClientJWTAuthentication]
    permission_classes = [IsAuthenticated]
    
    def delete(self, request, session_id, participant_id):
        try:
            # Verificar que la sesión existe y pertenece al usuario
            session = get_object_or_404(
                MusicSession,
                id=session_id,
                host_client=request.user,
                is_active=True,
                deleted=False
            )
            
            # Buscar participante
            participant = get_object_or_404(
                MusicSessionParticipant,
                id=participant_id,
                session=session,
                deleted=False
            )
            
            # Eliminar (soft delete)
            participant.deleted = True
            participant.save()
            
            return Response({
                "success": True,
                "message": "Participante eliminado de la sesión"
            })
            
        except Exception as e:
            return Response({
                "success": False,
                "error": str(e)
            }, status=status.HTTP_500_INTERNAL_SERVER_ERROR)


class MusicSessionCloseView(APIView):
    """
    POST /music/sessions/{session_id}/close
    Cierra una sesión de música.
    """
    authentication_classes = [ClientJWTAuthentication]
    permission_classes = [IsAuthenticated]
    
    def post(self, request, session_id):
        try:
            # Verificar que la sesión existe y pertenece al usuario
            session = get_object_or_404(
                MusicSession,
                id=session_id,
                host_client=request.user,
                deleted=False
            )
            
            # Desactivar sesión
            session.is_active = False
            session.save()
            
            return Response({
                "success": True,
                "message": "Sesión de música cerrada"
            })
            
        except Exception as e:
            return Response({
                "success": False,
                "error": str(e)
            }, status=status.HTTP_500_INTERNAL_SERVER_ERROR)
