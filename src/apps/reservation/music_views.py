from rest_framework.views import APIView
from rest_framework.response import Response
from rest_framework import status
from rest_framework.permissions import IsAuthenticated, AllowAny
from asgiref.sync import async_to_sync, sync_to_async
import asyncio
from django.shortcuts import get_object_or_404

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
    
    @async_to_sync
    async def get(self, request):
        try:
            # Obtener propiedades con player_id configurado (usando sync_to_async)
            @sync_to_async
            def get_properties():
                return list(Property.objects.filter(
                    player_id__isnull=False,
                    deleted=False
                ).exclude(player_id='').values('id', 'name', 'player_id'))
            
            properties = await get_properties()
            players_data = []
            
            # Si Music Assistant está disponible, obtener estado en tiempo real
            if MUSIC_ASSISTANT_AVAILABLE:
                try:
                    music_client = await get_music_client()
                    
                    for prop in properties:
                        # Buscar el player en Music Assistant
                        player = next((p for p in music_client.players if p.player_id == prop['player_id']), None)
                        
                        if player:
                            players_data.append({
                                "player_id": player.player_id,
                                "name": player.name,
                                "property_name": prop['name'],
                                "playback_state": player.playback_state.value if player.playback_state else None,
                                "type": player.type.value if player.type else None,
                                "volume_level": player.volume_level,
                                "powered": player.powered,
                                "available": player.available,
                                "current_media": {
                                    "title": player.current_media.title if player.current_media else None
                                } if player.current_media else None
                            })
                        else:
                            # Player configurado pero no encontrado en Music Assistant
                            players_data.append({
                                "player_id": prop['player_id'],
                                "name": f"{prop['name']} (sin conexión)",
                                "property_name": prop['name'],
                                "playback_state": None,
                                "available": False
                            })
                except Exception as e:
                    # Si falla Music Assistant, continuar con datos básicos
                    for prop in properties:
                        players_data.append({
                            "player_id": prop['player_id'],
                            "name": prop['name'],
                            "property_name": prop['name'],
                            "available": False,
                            "error": "No se pudo conectar a Music Assistant"
                        })
            else:
                # Sin Music Assistant, solo listar los configurados
                for prop in properties:
                    players_data.append({
                        "player_id": prop['player_id'],
                        "name": prop['name'],
                        "property_name": prop['name'],
                        "available": None,
                        "note": "Music Assistant no disponible (requiere Python 3.11+)"
                    })
            
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
        
        now = timezone.now()
        now_date = now.date()
        now_time = now.time()
        
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
        
        # Verificar si hay una reserva activa del usuario para esta propiedad
        @sync_to_async
        def get_user_reservations():
            return list(Reservation.objects.filter(
                client=user,
                property=property_obj,
                deleted=False,
                status__in=['approved', 'pending', 'incomplete', 'under_review']
            ))
        
        reservations = await get_user_reservations()
        
        for reservation in reservations:
            if self._is_reservation_active_now(reservation):
                return True
        
        # Verificar si es participante aceptado en alguna reserva activa
        @sync_to_async
        def get_participant():
            return MusicSessionParticipant.objects.filter(
                client=user,
                reservation__property=property_obj,
                status='accepted',
                deleted=False
            ).select_related('reservation').first()
        
        participant = await get_participant()
        
        if participant and self._is_reservation_active_now(participant.reservation):
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
                        "duration": track.duration if hasattr(track, 'duration') else None
                    })
            
            if hasattr(results, 'artists') and results.artists:
                for artist in results.artists:
                    organized_results["artists"].append({
                        "item_id": artist.item_id if hasattr(artist, 'item_id') else artist.uri,
                        "name": artist.name,
                        "uri": artist.uri if hasattr(artist, 'uri') else None
                    })
            
            if hasattr(results, 'albums') and results.albums:
                for album in results.albums:
                    organized_results["albums"].append({
                        "item_id": album.item_id if hasattr(album, 'item_id') else album.uri,
                        "name": album.name,
                        "uri": album.uri if hasattr(album, 'uri') else None
                    })
            
            if hasattr(results, 'playlists') and results.playlists:
                for playlist in results.playlists:
                    organized_results["playlists"].append({
                        "item_id": playlist.item_id if hasattr(playlist, 'item_id') else playlist.uri,
                        "name": playlist.name,
                        "uri": playlist.uri if hasattr(playlist, 'uri') else None
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
            
            # Verificar si ya existe una solicitud
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
            
            # Crear solicitud
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
                participants_data.append({
                    "id": str(participant.id),
                    "client_id": str(participant.client.id),
                    "name": f"{participant.client.first_name} {participant.client.last_name}",
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
