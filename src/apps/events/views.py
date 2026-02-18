"""
Views para el sistema de eventos, activity feed y analytics de Casa Austin
"""

from rest_framework.views import APIView
from rest_framework.response import Response
from rest_framework.permissions import IsAuthenticated, AllowAny
from rest_framework.decorators import api_view, permission_classes, authentication_classes
from rest_framework import status
from rest_framework.generics import ListAPIView
from rest_framework.pagination import PageNumberPagination
from django.shortcuts import get_object_or_404
from django.utils import timezone
from django.db.models import Q, Count, Avg, Sum, Max, Min
import logging

from .models import EventCategory, Event, EventRegistration, ActivityFeed, ActivityFeedConfig
from .serializers import (
    EventCategorySerializer, 
    EventListSerializer, 
    EventRegistrationSerializer,
    EventRegistrationCreateSerializer,
    ActivityFeedSerializer,
    ActivityFeedCreateSerializer
)
from apps.clients.auth_views import ClientJWTAuthentication

logger = logging.getLogger(__name__)


# ==================== PAGINACIÓN ====================

class EventPagination(PageNumberPagination):
    """Paginación personalizada para eventos"""
    page_size = 10
    page_size_query_param = 'page_size'
    max_page_size = 50


# ==================== ENDPOINTS PÚBLICOS ====================

class PublicEventCategoryListView(APIView):
    """Lista todas las categorías de eventos disponibles"""
    permission_classes = [AllowAny]

    def get(self, request):
        categories = EventCategory.objects.all()
        serializer = EventCategorySerializer(categories, many=True)
        return Response(serializer.data)


class PublicEventListView(APIView):
    """Lista eventos públicos con filtros opcionales"""
    permission_classes = [AllowAny]

    def get(self, request):
        # Filtros de query params
        category = request.GET.get('category')
        location = request.GET.get('location')
        date_from = request.GET.get('date_from')
        
        # Base queryset - solo eventos activos y futuros
        events = Event.objects.filter(
            is_active=True,
            event_date__gte=timezone.now()
        ).order_by('event_date')
        
        # Aplicar filtros
        if category:
            events = events.filter(category__name__icontains=category)
        if location:
            events = events.filter(location__icontains=location)
        if date_from:
            events = events.filter(event_date__gte=date_from)
        
        serializer = EventListSerializer(events, many=True)
        return Response(serializer.data)


class PastEventsView(ListAPIView):
    """Lista eventos pasados con paginación"""
    permission_classes = [AllowAny]
    serializer_class = EventListSerializer
    pagination_class = EventPagination

    def get_queryset(self):
        # Eventos pasados - antes de hoy
        queryset = Event.objects.filter(
            is_active=True,
            event_date__lt=timezone.now()
        ).order_by('-event_date')

        # Filtros opcionales
        category = self.request.GET.get('category')
        location = self.request.GET.get('location')
        
        if category:
            queryset = queryset.filter(category__name__icontains=category)
        if location:
            queryset = queryset.filter(location__icontains=location)
            
        return queryset


class ComingEventsView(ListAPIView):
    """Lista eventos futuros/próximos con paginación"""
    permission_classes = [AllowAny]
    serializer_class = EventListSerializer
    pagination_class = EventPagination

    def get_queryset(self):
        # Eventos futuros - a partir de hoy
        queryset = Event.objects.filter(
            is_active=True,
            event_date__gte=timezone.now()
        ).order_by('event_date')

        # Filtros opcionales
        category = self.request.GET.get('category')
        location = self.request.GET.get('location')
        date_from = self.request.GET.get('date_from')
        
        if category:
            queryset = queryset.filter(category__name__icontains=category)
        if location:
            queryset = queryset.filter(location__icontains=location)
        if date_from:
            queryset = queryset.filter(event_date__gte=date_from)
            
        return queryset


class PublicEventDetailView(APIView):
    """Detalle de un evento específico"""
    permission_classes = [AllowAny]

    def get(self, request, id):
        event = get_object_or_404(Event, id=id, is_active=True)
        
        # Información adicional del evento
        serializer = EventListSerializer(event)
        event_data = serializer.data
        
        # Agregar estadísticas públicas
        registrations = EventRegistration.objects.filter(event=event)
        spots_taken = registrations.filter(
            status__in=['approved', 'pending']
        ).count()
        
        event_data['spots_taken'] = spots_taken
        event_data['spots_available'] = max(0, event.max_participants - spots_taken)
        event_data['is_full'] = spots_taken >= event.max_participants
        
        return Response(event_data)


class EventParticipantsView(APIView):
    """Lista participantes de un evento (información pública limitada)"""
    permission_classes = [AllowAny]

    def get(self, request, event_id):
        from django.utils.timesince import timesince
        
        event = get_object_or_404(Event, id=event_id)
        
        # Solo mostrar participantes aprobados con información limitada
        participants = EventRegistration.objects.filter(
            event=event,
            status='approved'
        ).select_related('client')
        
        # Información limitada por privacidad
        participants_data = []
        contest_leaderboard = []
        
        # Si es concurso, obtener leaderboard para posiciones
        if event.is_contest:
            contest_leaderboard = event.get_contest_leaderboard()
            
        for registration in participants:
            if registration.client:
                client = registration.client
                
                # Primer nombre + primer apellido completo
                first_name_only = client.first_name.strip().split()[0] if client.first_name and client.first_name.strip() else "Usuario"
                first_last_name = client.last_name.strip().split()[0] if client.last_name and client.last_name.strip() else ""
                name = f"{first_name_only} {first_last_name}".strip() if first_last_name else first_name_only
                
                # Tiempo relativo desde el registro (usar fecha más reciente si fue reactivado)
                # Si updated es diferente de created, significa que fue reactivado
                effective_date = registration.updated if registration.updated > registration.created else registration.created
                registration_time_ago = timesince(effective_date)
                
                # Imagen de Facebook
                facebook_image = None
                if client.facebook_profile_data and isinstance(client.facebook_profile_data, dict):
                    facebook_image = client.facebook_profile_data.get('picture', {}).get('data', {}).get('url')
                
                # Estado de Facebook
                facebook_status = client.facebook_linked
                
                participant_info = {
                    'participant_name': name,
                    'registration_date': registration.created.date(),
                    'registration_time_ago': f"hace {registration_time_ago}",
                    'facebook_image': facebook_image,
                    'facebook_status': facebook_status,
                    'status': registration.get_status_display()
                }
                
                # Si es concurso, agregar información de concurso
                if event.is_contest:
                    # Buscar posición en el leaderboard
                    contest_position = None
                    contest_stats = 0
                    
                    for i, entry in enumerate(contest_leaderboard, 1):
                        if entry['client'].id == client.id:
                            contest_position = i
                            contest_stats = entry['stats']
                            break
                    
                    participant_info.update({
                        'contest_position': contest_position,
                        'contest_stats': contest_stats,
                        'contest_stats_label': 'Referidos' if event.contest_type == event.ContestType.REFERRAL_COUNT else 'Reservas de Referidos'
                    })
                
                participants_data.append(participant_info)
        
        # Respuesta base
        response_data = {
            'event_name': event.title,
            'total_participants': len(participants_data),
            'participants': participants_data
        }
        
        # Si es concurso, agregar información adicional
        if event.is_contest:
            response_data.update({
                'is_contest': True,
                'contest_type': event.contest_type,
                'contest_type_display': event.get_contest_type_display(),
                'contest_deadline': event.registration_deadline,
                'contest_description': f"Concurso de {event.get_contest_type_display().lower()}. Los participantes compiten por la mayor cantidad de {'referidos' if event.contest_type == event.ContestType.REFERRAL_COUNT else 'reservas de referidos'}."
            })
        
        return Response(response_data)


class EventWinnersView(APIView):
    """Lista solo los ganadores de un evento específico"""
    permission_classes = [AllowAny]

    def get(self, request, event_id):
        from django.utils.timesince import timesince
        
        event = get_object_or_404(Event, id=event_id)
        
        # Solo mostrar participantes que son ganadores Y cuya fecha de anuncio ya llegó
        from django.utils import timezone
        from django.db.models import Q
        now = timezone.now()
        
        winners = EventRegistration.objects.filter(
            event=event,
            winner_status=EventRegistration.WinnerStatus.WINNER,
        ).filter(
            # Mostrar si: fecha de anuncio llegó O si no tiene fecha pero la fecha del evento ya pasó
            Q(winner_announcement_date__lte=now) | 
            Q(winner_announcement_date__isnull=True, event__event_date__lte=now)
        ).select_related('client').order_by('-winner_announcement_date')
        
        # Información de ganadores
        winners_data = []
        contest_leaderboard = []
        
        # Si es concurso, obtener leaderboard completo
        if event.is_contest:
            contest_leaderboard = event.get_contest_leaderboard()
        
        for registration in winners:
            if registration.client:
                client = registration.client
                
                # Primer nombre + primer apellido completo
                first_name_only = client.first_name.strip().split()[0] if client.first_name and client.first_name.strip() else "Usuario"
                first_last_name = client.last_name.strip().split()[0] if client.last_name and client.last_name.strip() else ""
                name = f"{first_name_only} {first_last_name}".strip() if first_last_name else first_name_only
                
                # Tiempo relativo desde el anuncio del ganador
                announcement_time_ago = None
                if registration.winner_announcement_date:
                    announcement_time_ago = f"hace {timesince(registration.winner_announcement_date)}"
                
                # Imagen de Facebook
                facebook_image = None
                if client.facebook_profile_data and isinstance(client.facebook_profile_data, dict):
                    facebook_image = client.facebook_profile_data.get('picture', {}).get('data', {}).get('url')
                
                # Estado de Facebook
                facebook_status = client.facebook_linked
                
                winner_info = {
                    'participant_name': name,
                    'winner_status': registration.winner_status,
                    'position_name': registration.get_winner_status_display(),
                    'prize_description': registration.prize_description,
                    'winner_announcement_date': registration.winner_announcement_date,
                    'announcement_time_ago': announcement_time_ago,
                    'winner_notified': registration.winner_notified,
                    'facebook_image': facebook_image,
                    'facebook_status': facebook_status,
                    'registration_date': registration.created.date(),
                }
                
                # Si es concurso, agregar estadísticas del concurso
                if event.is_contest:
                    contest_position = None
                    contest_stats = 0
                    
                    for i, entry in enumerate(contest_leaderboard, 1):
                        if entry['client'].id == client.id:
                            contest_position = i
                            contest_stats = entry['stats']
                            break
                    
                    winner_info.update({
                        'contest_position': contest_position,
                        'contest_stats': contest_stats,
                        'contest_stats_label': 'Referidos' if event.contest_type == event.ContestType.REFERRAL_COUNT else 'Reservas de Referidos'
                    })
                
                winners_data.append(winner_info)
        
        # Respuesta base
        response_data = {
            'event_name': event.title,
            'event_date': event.event_date,
            'total_winners': len(winners_data),
            'winners': winners_data
        }
        
        # Si es concurso, agregar ranking completo y información del concurso
        if event.is_contest:
            # Formatear ranking completo
            full_ranking = []
            for i, entry in enumerate(contest_leaderboard, 1):
                client = entry['client']
                
                # Primer nombre + primer apellido completo
                first_name_only = client.first_name.strip().split()[0] if client.first_name and client.first_name.strip() else "Usuario"
                first_last_name = client.last_name.strip().split()[0] if client.last_name and client.last_name.strip() else ""
                participant_name = f"{first_name_only} {first_last_name}".strip() if first_last_name else first_name_only
                
                # Imagen de Facebook
                facebook_image = None
                if client.facebook_profile_data and isinstance(client.facebook_profile_data, dict):
                    facebook_image = client.facebook_profile_data.get('picture', {}).get('data', {}).get('url')
                
                full_ranking.append({
                    'position': i,
                    'participant_name': participant_name,
                    'contest_stats': entry['stats'],
                    'registration_date': entry['registration'].registration_date,
                    'facebook_image': facebook_image,
                    'is_winner': entry['client'].id in [w['participant_name'] for w in winners_data]  # Placeholder para determinar ganadores
                })
            
            response_data.update({
                'is_contest': True,
                'contest_type': event.contest_type,
                'contest_type_display': event.get_contest_type_display(),
                'contest_deadline': event.registration_deadline,
                'contest_description': f"Concurso de {event.get_contest_type_display().lower()}. Los participantes compitieron por la mayor cantidad de {'referidos' if event.contest_type == event.ContestType.REFERRAL_COUNT else 'reservas de referidos'}.",
                'contest_ranking': full_ranking,
                'total_participants': len(contest_leaderboard)
            })
        
        return Response(response_data)


# ==================== ENDPOINTS CON AUTENTICACIÓN ====================

class EventRegistrationView(APIView):
    """Registro de cliente a un evento"""
    authentication_classes = [ClientJWTAuthentication]
    permission_classes = [IsAuthenticated]

    def post(self, request, event_id):
        event = get_object_or_404(Event, id=event_id, is_active=True)
        client = request.user
        
        # Verificar si ya tiene un registro activo
        active_registration = EventRegistration.objects.filter(
            event=event,
            client=client,
            status__in=['incomplete', 'pending', 'approved']
        ).first()
        
        if active_registration:
            return Response({
                'success': False,
                'message': 'Ya estás registrado en este evento',
                'error_code': 'ALREADY_REGISTERED',
                'registration_id': active_registration.id
            }, status=status.HTTP_400_BAD_REQUEST)
        
        # 🔒 VALIDAR RESTRICCIONES DE NIVEL/LOGROS/PUNTOS
        can_register, validation_message = event.client_can_register(client)
        if not can_register:
            return Response({
                'success': False,
                'message': validation_message,
                'error_code': 'REQUIREMENTS_NOT_MET'
            }, status=status.HTTP_400_BAD_REQUEST)
        
        # Verificar si tiene un registro cancelado que podemos reactivar
        cancelled_registration = EventRegistration.objects.filter(
            event=event,
            client=client,
            status='cancelled'
        ).first()
        
        # Verificar capacidad
        current_registrations = EventRegistration.objects.filter(
            event=event,
            status='approved'
        ).count()
        
        if current_registrations >= event.max_participants:
            return Response({
                'success': False,
                'message': 'El evento está lleno',
                'error_code': 'EVENT_FULL'
            }, status=status.HTTP_400_BAD_REQUEST)
        
        # Si existe registro cancelado, reactivarlo
        if cancelled_registration:
            # Determinar estado según si el evento requiere evidencia
            if event.requires_evidence:
                cancelled_registration.status = 'incomplete'  # Necesita subir evidencia
            else:
                cancelled_registration.status = 'approved'  # Flujo normal
            
            cancelled_registration.notes = request.data.get('special_requests', '')
            cancelled_registration.save()
            
            # Log de actividad
            self._log_registration_activity(cancelled_registration)
            
            serializer = EventRegistrationSerializer(cancelled_registration)
            return Response({
                'success': True,
                'message': 'Registro reactivado exitosamente',
                'registration': serializer.data,
                'requires_evidence': event.requires_evidence
            }, status=status.HTTP_200_OK)
        
        # Si no hay registro previo, crear uno nuevo
        # Determinar estado inicial según si requiere evidencia
        initial_status = 'incomplete' if event.requires_evidence else 'approved'
        
        registration_data = {
            'notes': request.data.get('special_requests', '')
        }
        
        # Usar el serializer específico para crear registros
        serializer = EventRegistrationCreateSerializer(
            data=registration_data,
            context={
                'event': event,
                'client': client,
                'status': initial_status
            }
        )
        if serializer.is_valid():
            registration = serializer.save()
            
            # Log de actividad
            self._log_registration_activity(registration)
            
            return Response({
                'success': True,
                'message': 'Registro exitoso',
                'registration': serializer.data,
                'requires_evidence': event.requires_evidence,
                'next_step': 'upload_evidence' if event.requires_evidence else 'wait_approval'
            }, status=status.HTTP_201_CREATED)
        
        return Response({
            'success': False,
            'message': 'Error en los datos proporcionados',
            'errors': serializer.errors
        }, status=status.HTTP_400_BAD_REQUEST)

    def _log_registration_activity(self, registration):
        """Registrar actividad de inscripción"""
        try:
            ActivityFeed.create_activity(
                activity_type=ActivityFeed.ActivityType.EVENT_REGISTRATION,
                title='Inscripción a evento',  # ✅ Título específico para registro
                client=registration.client,
                event=registration.event,
                property_location=registration.event.property_location,
                activity_data={
                    'event_id': str(registration.event.id),
                    'event_name': registration.event.title,
                    'registration_id': str(registration.id),
                    'action': 'registered'
                }
            )
        except Exception as e:
            logger.error(f'Error logging registration activity: {e}')


class EventUploadEvidenceView(APIView):
    """Subir evidencia para eventos que lo requieren"""
    authentication_classes = [ClientJWTAuthentication]
    permission_classes = [IsAuthenticated]
    
    def post(self, request, event_id):
        """Subir evidencia para completar el registro"""
        import logging
        logger = logging.getLogger(__name__)
        
        try:
            event = get_object_or_404(Event, id=event_id)
            client = request.user
            
            # Verificar que el evento requiere evidencia
            if not event.requires_evidence:
                return Response({
                    'error': 'Este evento no requiere evidencia'
                }, status=status.HTTP_400_BAD_REQUEST)
            
            # Buscar registro incompleto del cliente
            registration = EventRegistration.objects.filter(
                event=event,
                client=client,
                status='incomplete'
            ).first()
            
            if not registration:
                return Response({
                    'error': 'No tienes un registro incompleto para este evento'
                }, status=status.HTTP_400_BAD_REQUEST)
            
            # Verificar que se subió una imagen
            if 'evidence_image' not in request.FILES:
                return Response({
                    'error': 'Debes subir una imagen como evidencia'
                }, status=status.HTTP_400_BAD_REQUEST)
            
            # Validar archivo de imagen
            evidence_file = request.FILES['evidence_image']
            
            # Validar tipo de archivo
            allowed_types = ['image/jpeg', 'image/png', 'image/webp', 'image/jpg']
            if evidence_file.content_type not in allowed_types:
                return Response({
                    'error': 'Solo se permiten archivos de imagen (JPEG, PNG, WebP)'
                }, status=status.HTTP_400_BAD_REQUEST)
            
            # Validar tamaño (máximo 10MB)
            if evidence_file.size > 10 * 1024 * 1024:
                return Response({
                    'error': 'El archivo es demasiado grande. Máximo 10MB'
                }, status=status.HTTP_400_BAD_REQUEST)
            
            # Guardar la evidencia y cambiar estado a pending
            registration.evidence_image = request.FILES['evidence_image']
            registration.status = 'pending'  # Ahora espera aprobación del admin
            registration.save()
            
            # Log de actividad
            try:
                ActivityFeed.create_activity(
                    activity_type=ActivityFeed.ActivityType.EVENT_REGISTRATION,
                    title='Evidencia subida',
                    client=registration.client,
                    event=registration.event,
                    property_location=registration.event.property_location,
                    activity_data={
                        'event_id': str(registration.event.id),
                        'event_name': registration.event.title,
                        'registration_id': str(registration.id),
                        'action': 'evidence_uploaded'
                    }
                )
            except Exception as e:
                logger.error(f'Error logging evidence upload activity: {e}')
            
            return Response({
                'message': 'Evidencia subida exitosamente. Tu registro está ahora pendiente de aprobación.',
                'registration_status': registration.status,
                'evidence_uploaded': True
            }, status=status.HTTP_200_OK)
            
        except Exception as e:
            logger.error(f'Error uploading evidence: {e}')
            return Response({
                'error': 'Error interno del servidor'
            }, status=status.HTTP_500_INTERNAL_SERVER_ERROR)


class EventContestLeaderboardView(APIView):
    """Vista para mostrar el ranking del concurso de un evento"""
    
    def get(self, request, event_id):
        """Obtener ranking del concurso"""
        import logging
        logger = logging.getLogger(__name__)
        
        try:
            # Intentar buscar por UUID primero
            try:
                event = get_object_or_404(Event, id=event_id, is_active=True)
            except ValidationError:
                # Si falla, buscar por slug
                event = get_object_or_404(Event, slug=event_id, is_active=True)
            
            # Verificar que es un concurso
            if not event.is_contest:
                return Response({
                    'error': 'Este evento no es un concurso'
                }, status=status.HTTP_400_BAD_REQUEST)
            
            # Obtener leaderboard
            leaderboard = event.get_contest_leaderboard()
            
            # Formatear respuesta
            result = []
            for i, entry in enumerate(leaderboard, 1):
                client = entry['client']
                result.append({
                    'position': i,
                    'client_name': f"{client.first_name} {client.last_name[0]}." if client.last_name else client.first_name,
                    'client_avatar': client.avatar.url if client.avatar else None,
                    'stats': entry['stats'],
                    'registration_date': entry['registration'].registration_date
                })
            
            contest_info = {
                'event_title': event.title,
                'contest_type': event.contest_type,
                'contest_type_display': event.get_contest_type_display(),
                'registration_deadline': event.registration_deadline,
                'total_participants': event.registrations.filter(status='approved').count(),
                'leaderboard': result
            }
            
            return Response(contest_info, status=status.HTTP_200_OK)
            
        except Exception as e:
            logger.error(f'Error fetching contest leaderboard: {e}')
            return Response({
                'error': 'Error interno del servidor'
            }, status=status.HTTP_500_INTERNAL_SERVER_ERROR)


class EventCancelRegistrationView(APIView):
    """Cancelar registro de cliente a un evento"""
    authentication_classes = [ClientJWTAuthentication]
    permission_classes = [IsAuthenticated]

    def delete(self, request, event_id):
        event = get_object_or_404(Event, id=event_id, is_active=True)
        client = request.user
        
        # Buscar registro existente con mejor manejo de errores
        try:
            registration = EventRegistration.objects.get(
                event=event,
                client=client,
                status__in=['pending', 'approved']
            )
        except EventRegistration.DoesNotExist:
            # Debug: verificar si existe registro con cualquier estado
            any_registration = EventRegistration.objects.filter(
                event=event,
                client=client
            ).first()
            
            if any_registration:
                if any_registration.status == 'cancelled':
                    return Response({
                        'error': 'Tu registro ya fue cancelado anteriormente',
                        'status': any_registration.status,
                        'cancelled_date': any_registration.updated.isoformat()
                    }, status=status.HTTP_400_BAD_REQUEST)
                else:
                    return Response({
                        'error': f'Tu registro tiene estado "{any_registration.status}" y no puede ser cancelado',
                        'valid_states': ['pending', 'approved']
                    }, status=status.HTTP_400_BAD_REQUEST)
            else:
                return Response({
                    'error': 'No tienes un registro para este evento',
                    'event_id': str(event_id),
                    'client_id': str(client.id) if hasattr(client, 'id') else str(client)
                }, status=status.HTTP_404_NOT_FOUND)
        
        # Verificar si el evento ya pasó
        if event.event_date < timezone.now():
            return Response({
                'error': 'No puedes cancelar tu registro a un evento que ya ocurrió'
            }, status=status.HTTP_400_BAD_REQUEST)
        
        # Cambiar estado a cancelado (no eliminar para mantener historial)
        registration.status = 'cancelled'
        registration.save()
        
        # Log de actividad
        self._log_cancellation_activity(registration)
        
        return Response({
            'success': True,
            'message': 'Registro cancelado exitosamente',
            'registration': {
                'id': str(registration.id),
                'event_name': event.title,
                'status': registration.get_status_display(),
                'cancelled_at': timezone.now().isoformat()
            }
        }, status=status.HTTP_200_OK)

    def _log_cancellation_activity(self, registration):
        """Registrar actividad de cancelación"""
        try:
            ActivityFeed.create_activity(
                activity_type=ActivityFeed.ActivityType.EVENT_CANCELLATION,  # ✅ Nuevo activity type
                title='Cancelación a evento',
                client=registration.client,
                event=registration.event,
                property_location=registration.event.property_location,
                activity_data={
                    'event_id': str(registration.event.id),
                    'event_name': registration.event.title,
                    'registration_id': str(registration.id),
                    'action': 'cancelled'
                }
            )
        except Exception as e:
            logger.error(f'Error logging cancellation activity: {e}')


class ClientEventRegistrationsView(ListAPIView):
    """Lista las inscripciones del cliente con paginación"""
    authentication_classes = [ClientJWTAuthentication]
    permission_classes = [IsAuthenticated]
    serializer_class = EventRegistrationSerializer
    pagination_class = EventPagination

    def get_queryset(self):
        client = self.request.user
        return EventRegistration.objects.filter(
            client=client
        ).select_related('event').order_by('-created')

    def list(self, request, *args, **kwargs):
        """Override para agregar detalles del evento"""
        queryset = self.filter_queryset(self.get_queryset())
        page = self.paginate_queryset(queryset)
        
        if page is not None:
            registrations_data = []
            for registration in page:
                registration_data = EventRegistrationSerializer(registration).data
                # Agregar información del evento
                registration_data['event_details'] = EventListSerializer(registration.event).data
                registrations_data.append(registration_data)
            
            return self.get_paginated_response(registrations_data)
        
        # Sin paginación (fallback)
        registrations_data = []
        for registration in queryset:
            registration_data = EventRegistrationSerializer(registration).data
            registration_data['event_details'] = EventListSerializer(registration.event).data
            registrations_data.append(registration_data)
        
        return Response(registrations_data)


@api_view(['GET'])
@authentication_classes([ClientJWTAuthentication])
@permission_classes([IsAuthenticated])
def check_event_eligibility(request, event_id):
    """Verificar si el cliente puede inscribirse al evento"""
    event = get_object_or_404(Event, id=event_id, is_active=True)
    client = request.user
    
    # Verificaciones - SOLO considerar registros activos (no cancelados)
    is_registered = EventRegistration.objects.filter(
        event=event,
        client=client,
        status__in=['pending', 'approved']  # ✅ Excluir cancelados
    ).exists()
    
    current_registrations = EventRegistration.objects.filter(
        event=event,
        status='approved'  # ✅ Corregir estado válido
    ).count()
    
    is_full = current_registrations >= event.max_participants
    is_past_event = event.event_date < timezone.now()
    
    return Response({
        'can_register': not (is_registered or is_full or is_past_event),
        'is_registered': is_registered,
        'is_full': is_full,
        'is_past_event': is_past_event,
        'spots_available': max(0, event.max_participants - current_registrations)
    })


# ==================== ACTIVITY FEED ENDPOINTS ====================

from rest_framework.generics import ListAPIView

class ActivityFeedView(ListAPIView):
    """Feed de actividades principal con paginación DRF"""
    permission_classes = [AllowAny]
    serializer_class = ActivityFeedSerializer
    
    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        from apps.core.paginator import CustomPagination
        self.pagination_class = CustomPagination

    def get_queryset(self):
        # Base queryset
        activities = ActivityFeed.objects.all().order_by('-created')
        
        # Parámetros de filtrado
        activity_type = self.request.GET.get('type')
        client_id = self.request.GET.get('client_id')
        importance_level = self.request.GET.get('importance_level')
        is_public = self.request.GET.get('is_public')
        
        # Aplicar filtros
        if activity_type:
            activities = activities.filter(activity_type=activity_type)
        if client_id:
            activities = activities.filter(client_id=client_id)
        if importance_level:
            activities = activities.filter(importance_level=importance_level)
        if is_public is not None:
            is_public_bool = is_public.lower() in ['true', '1', 'yes']
            activities = activities.filter(is_public=is_public_bool)
        
        return activities


class RecentActivitiesView(APIView):
    """Actividades recientes para dashboard"""
    permission_classes = [AllowAny]

    def get(self, request):
        from datetime import timedelta
        
        # Últimas 24 horas por defecto
        hours = int(request.GET.get('hours', 24))
        since = timezone.now() - timedelta(hours=hours)
        
        activities = ActivityFeed.objects.filter(
            created__gte=since
        ).order_by('-created')[:50]
        
        serializer = ActivityFeedSerializer(activities, many=True)
        
        return Response({
            'period_hours': hours,
            'total_activities': activities.count(),
            'activities': serializer.data
        })


class ActivityFeedStatsView(APIView):
    """Estadísticas del activity feed"""
    permission_classes = [AllowAny]

    def get(self, request):
        from datetime import timedelta
        
        # Período de análisis
        days = int(request.GET.get('days', 7))
        since = timezone.now() - timedelta(days=days)
        
        activities = ActivityFeed.objects.filter(created__gte=since)
        
        # Estadísticas por tipo
        stats_by_type = activities.values('activity_type').annotate(
            count=Count('id')
        ).order_by('-count')
        
        # Actividad por día
        daily_stats = []
        for i in range(days):
            day = timezone.now().date() - timedelta(days=i)
            day_activities = activities.filter(created__date=day)
            daily_stats.append({
                'date': day.isoformat(),
                'total_activities': day_activities.count(),
                'by_type': list(day_activities.values('activity_type').annotate(count=Count('id')))
            })
        
        return Response({
            'period_days': days,
            'total_activities': activities.count(),
            'stats_by_type': list(stats_by_type),
            'daily_breakdown': daily_stats
        })


class ActivityFeedCreateView(APIView):
    """Crear nueva actividad en el feed"""
    permission_classes = [IsAuthenticated]

    def post(self, request):
        # Verificar configuración
        config = ActivityFeedConfig.objects.first()
        if not config or not config.is_enabled:
            return Response({
                'error': 'Activity feed está deshabilitado'
            }, status=status.HTTP_403_FORBIDDEN)
        
        # Agregar cliente automáticamente
        data = request.data.copy()
        data['client'] = request.user.id
        
        serializer = ActivityFeedCreateSerializer(data=data)
        if serializer.is_valid():
            activity = serializer.save()
            return Response(
                ActivityFeedSerializer(activity).data,
                status=status.HTTP_201_CREATED
            )
        
        return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)


# ==================== COMPREHENSIVE STATS VIEW ====================

class ComprehensiveStatsView(APIView):
    """
    DEPRECATED: Endpoint monolítico de estadísticas comprehensivas del sistema
    
    ⚠️  Este endpoint está deprecado. Use los endpoints específicos:
    - /api/v1/stats/search-tracking/ - Para análisis de búsquedas
    - /api/v1/stats/ingresos/ - Para análisis de ingresos
    - /api/v1/upcoming-checkins/ - Para check-ins próximos
    
    Parámetros:
    - date_from: fecha inicio análisis (default: hace 30 días)
    - date_to: fecha fin análisis (default: hoy)
    - period: agrupación temporal día/semana/mes (default: week)
    
    Retorna estadísticas completas del sistema:
    - Reservas, ingresos, búsquedas
    - Análisis por propiedades y clientes
    - Tendencias temporales
    """
    
    permission_classes = [IsAuthenticated]  # Restringido por seguridad
    
    def get(self, request):
        """Obtener estadísticas comprehensivas del sistema"""
        from django.utils import timezone
        from datetime import timedelta
        from django.db.models import Sum, Avg, Count, Q
        
        # Parámetros de query con validación segura
        try:
            date_from_str = request.GET.get('date_from')
            if date_from_str:
                date_from = timezone.datetime.strptime(date_from_str, '%Y-%m-%d').date()
            else:
                date_from = timezone.now().date() - timedelta(days=30)
        except ValueError:
            date_from = timezone.now().date() - timedelta(days=30)
            
        try:
            date_to_str = request.GET.get('date_to')
            if date_to_str:
                date_to = timezone.datetime.strptime(date_to_str, '%Y-%m-%d').date()
            else:
                date_to = timezone.now().date()
        except ValueError:
            date_to = timezone.now().date()
            
        period = request.GET.get('period', 'week')
        if period not in ['day', 'week', 'month']:
            period = 'week'
        
        try:
            # Importar modelos necesarios
            from apps.reservation.models import Reservation
            from apps.clients.models import SearchTracking, Clients
            
            # === ANÁLISIS DE RESERVAS ===
            reservations = Reservation.objects.filter(
                check_in_date__gte=date_from,
                check_in_date__lte=date_to
            )
            
            # Métricas básicas de reservas
            total_reservations = reservations.count()
            total_revenue = reservations.aggregate(Sum('price_sol'))['price_sol__sum'] or 0
            
            # Calcular noches y duración promedio de estadía
            total_nights = 0
            durations = []
            for reservation in reservations:
                nights = (reservation.check_out_date - reservation.check_in_date).days
                if nights > 0:
                    total_nights += nights
                    durations.append(nights)
            
            avg_stay_duration = sum(durations) / len(durations) if durations else 0
            
            # === ANÁLISIS DE BÚSQUEDAS ===
            searches = SearchTracking.objects.filter(
                search_timestamp__date__gte=date_from,
                search_timestamp__date__lte=date_to
            )
            
            search_summary = self._analyze_search_tracking(searches)
            
            # === ANÁLISIS POR PROPIEDADES ===
            properties_analysis = self._analyze_properties_performance(reservations, searches)
            
            # === ANÁLISIS DE CLIENTES ===
            guest_distribution = self._analyze_guest_distribution(reservations)
            
            # === TENDENCIAS TEMPORALES ===
            reservations_by_period = self._group_by_period(
                reservations, 'check_in_date', period, date_from, date_to, 'reservations_count'
            )
            
            # === MÉTRICAS DE CRECIMIENTO ===
            growth_metrics = self._calculate_growth_metrics(reservations, searches, date_from, date_to)
            
            return Response({
                'success': True,
                'data': {
                    'period_info': {
                        'date_from': date_from.isoformat(),
                        'date_to': date_to.isoformat(),
                        'period_grouping': period,
                        'total_days_analyzed': (date_to - date_from).days + 1
                    },
                    'reservations_summary': {
                        'total_reservations': total_reservations,
                        'total_revenue': round(total_revenue, 2),
                        'total_nights_booked': total_nights,
                        'average_stay_duration': round(avg_stay_duration, 2),
                        'average_guests_per_reservation': round(reservations.aggregate(Avg('guests'))['guests__avg'] or 0, 1),
                        'occupancy_rate': self._calculate_occupancy_rate(reservations, date_from, date_to)
                    },
                    'reservations_by_period': reservations_by_period,
                    'properties_breakdown': properties_analysis,
                    'guest_distribution': guest_distribution,
                    'search_tracking_analysis': search_summary,
                    'growth_metrics': growth_metrics
                },
                'generated_at': timezone.now().isoformat()
            })
            
        except Exception as e:
            # Log del error para debugging
            import logging
            logger = logging.getLogger(__name__)
            logger.error(f'Comprehensive stats error: {str(e)}')
            
            return Response({
                'error': 'Error al procesar estadísticas comprehensivas',
                'message': 'Error interno del servidor',
                'success': False
            }, status=500)
    
    def _analyze_search_tracking(self, searches):
        """Analizar datos de SearchTracking"""
        from django.db.models import Count
        
        total_searches = searches.count()
        unique_clients = searches.filter(client__isnull=False).values('client').distinct().count()
        anonymous_searches = searches.filter(client__isnull=True).count()
        
        # Propiedades más buscadas
        top_properties = searches.filter(
            property__isnull=False
        ).values(
            'property__name'
        ).annotate(
            searches_count=Count('id')
        ).order_by('-searches_count')[:5]
        
        # Búsquedas por día de la semana
        weekday_patterns = self._analyze_weekday_search_patterns(searches)
        
        # Top clientes que buscan
        top_clients = self._analyze_top_searching_clients(searches)
        
        # Top IPs anónimas
        anonymous_analysis = self._analyze_anonymous_ips_comprehensive(searches)
        
        return {
            'total_searches': total_searches,
            'unique_clients': unique_clients,
            'anonymous_searches': anonymous_searches,
            'conversion_rate': self._calculate_search_conversion_rate(searches),
            'top_searched_properties': [
                {
                    'property_name': prop['property__name'],
                    'searches_count': prop['searches_count'],
                    'percentage': round(prop['searches_count'] / total_searches * 100, 2) if total_searches > 0 else 0
                }
                for prop in top_properties
            ],
            'search_by_day_of_week': weekday_patterns,
            'top_searching_clients': top_clients,
            'anonymous_ips_analysis': anonymous_analysis
        }
    
    def _analyze_properties_performance(self, reservations, searches):
        """Analizar rendimiento por propiedades"""
        from django.db.models import Sum, Count, Avg
        
        # Análisis de reservas por propiedad
        property_reservations = reservations.values(
            'property__name',
            'property__titulo'
        ).annotate(
            total_reservations=Count('id'),
            total_revenue=Sum('price_sol'),
            avg_price=Avg('price_sol')
        ).order_by('-total_revenue')
        
        result = []
        for prop in property_reservations:
            # Búsquedas para esta propiedad
            prop_searches = searches.filter(property__name=prop['property__name']).count()
            
            # Calcular total de noches para esta propiedad
            prop_reservations_list = reservations.filter(property__name=prop['property__name'])
            total_nights = 0
            nights_list = []
            for res in prop_reservations_list:
                nights = (res.check_out_date - res.check_in_date).days
                if nights > 0:
                    total_nights += nights
                    nights_list.append(nights)
            
            avg_nights = sum(nights_list) / len(nights_list) if nights_list else 0
            
            result.append({
                'property_name': prop['property__name'],
                'property_titulo': prop['property__titulo'],
                'total_reservations': prop['total_reservations'],
                'total_revenue': round(prop['total_revenue'] or 0, 2),
                'total_nights': total_nights,
                'average_price_per_night': round((prop['total_revenue'] or 0) / (total_nights or 1), 2),
                'average_stay_duration': round(avg_nights, 2),
                'search_interest': prop_searches,
                'conversion_rate': round(prop['total_reservations'] / prop_searches * 100, 2) if prop_searches > 0 else 0
            })
        
        return result
    
    def _analyze_guest_distribution(self, reservations):
        """Analizar distribución por número de huéspedes"""
        from django.db.models import Count, Sum
        
        distribution = reservations.values('guests').annotate(
            reservations_count=Count('id'),
            total_revenue=Sum('price_sol')
        ).order_by('guests')
        
        total_reservations = reservations.count()
        total_revenue = reservations.aggregate(Sum('price_sol'))['price_sol__sum'] or 0
        
        result = []
        for dist in distribution:
            result.append({
                'guest_count': dist['guests'],
                'count': dist['reservations_count'],
                'percentage': round(dist['reservations_count'] / total_reservations * 100, 2) if total_reservations > 0 else 0,
                'total_revenue': round(dist['total_revenue'] or 0, 2),
                'revenue_percentage': round((dist['total_revenue'] or 0) / total_revenue * 100, 2) if total_revenue > 0 else 0
            })
        
        return result
    
    def _calculate_occupancy_rate(self, reservations, date_from, date_to):
        """Calcular tasa de ocupación simplificada"""
        # Calcular noches manualmente
        total_nights_booked = 0
        for reservation in reservations:
            nights = (reservation.check_out_date - reservation.check_in_date).days
            if nights > 0:
                total_nights_booked += nights
        total_days = (date_to - date_from).days + 1
        
        # Estimación simple: asumiendo 5 propiedades disponibles
        estimated_total_capacity = total_days * 5
        
        return round(total_nights_booked / estimated_total_capacity * 100, 2) if estimated_total_capacity > 0 else 0
    
    def _calculate_search_conversion_rate(self, searches):
        """Calcular tasa de conversión de búsquedas a reservas"""
        # Simplificado: esto requeriría relacionar búsquedas con reservas reales
        return 3.5  # Placeholder
    
    def _group_by_period(self, queryset, date_field, period, date_from, date_to, count_field_name):
        """Agrupar datos por período usando Python-side grouping para evitar timezone issues"""
        from datetime import timedelta
        from django.db.models import Count, Sum
        
        result = []
        current_date = date_from
        
        while current_date <= date_to:
            if period == 'day':
                period_start = current_date
                period_end = current_date
                next_date = current_date + timedelta(days=1)
                period_label = current_date.strftime('%d %b')
            elif period == 'week':
                # Calcular inicio de semana (lunes)
                days_to_monday = current_date.weekday()
                period_start = current_date - timedelta(days=days_to_monday)
                period_end = period_start + timedelta(days=6)
                next_date = period_end + timedelta(days=1)
                period_label = f"Semana del {period_start.strftime('%d %b')}"
            else:  # month
                period_start = current_date.replace(day=1)
                if current_date.month == 12:
                    period_end = current_date.replace(year=current_date.year + 1, month=1, day=1) - timedelta(days=1)
                else:
                    period_end = current_date.replace(month=current_date.month + 1, day=1) - timedelta(days=1)
                next_date = period_end + timedelta(days=1)
                period_label = current_date.strftime('%B %Y')
            
            # Filtrar datos en este período
            period_filter = {
                f'{date_field}__gte': period_start,
                f'{date_field}__lte': min(period_end, date_to)
            }
            
            period_data = {
                'period': current_date.isoformat(),
                'period_label': period_label
            }
            
            if count_field_name == 'reservations_count':
                # Para reservas
                period_queryset = queryset.filter(**period_filter)
                period_data['count'] = period_queryset.count()
                period_data['revenue'] = round(period_queryset.aggregate(Sum('price_sol'))['price_sol__sum'] or 0, 2)
                
                # Calcular noches para el período
                period_nights = 0
                for res in period_queryset:
                    nights = (res.check_out_date - res.check_in_date).days
                    if nights > 0:
                        period_nights += nights
                
                period_data['nights_booked'] = period_nights
                period_data['average_guests'] = round(period_queryset.aggregate(Avg('guests'))['guests__avg'] or 0, 1)
            elif count_field_name == 'searches_count':
                # Para búsquedas
                period_queryset = queryset.filter(**period_filter)
                counts = self._count_client_vs_anonymous_searches(period_queryset)
                period_data['total_searches'] = counts['total']
                period_data['client_searches'] = counts['client']
                period_data['anonymous_searches'] = counts['anonymous']
            elif count_field_name == 'total_activities':
                # Para actividades
                period_data['total_activities'] = counts['total']
            elif count_field_name == 'new_clients':
                # Para clientes
                period_data['new_clients'] = counts['total']
            
            result.append(period_data)
            current_date = next_date
            
            # Evitar loop infinito
            if current_date > date_to:
                break
        
        return result
    
    def _count_client_vs_anonymous_searches(self, searches):
        """Contar búsquedas por clientes vs anónimas"""
        total = searches.count()
        with_client = searches.filter(client__isnull=False).count()
        anonymous = total - with_client
        
        return {
            'total': total,
            'client': with_client,
            'anonymous': anonymous
        }
    
    def _analyze_weekday_search_patterns(self, searches):
        """Analizar patrones de búsqueda por día de la semana"""
        from collections import defaultdict
        
        weekday_counts = defaultdict(int)
        weekday_guests = defaultdict(list)
        
        for search in searches.values('search_timestamp', 'guests'):
            weekday = search['search_timestamp'].strftime('%A')
            weekday_counts[weekday] += 1
            if search['guests']:
                weekday_guests[weekday].append(search['guests'])
        
        result = []
        total_searches = sum(weekday_counts.values())
        
        for day_name in ['Monday', 'Tuesday', 'Wednesday', 'Thursday', 'Friday', 'Saturday', 'Sunday']:
            searches_count = weekday_counts[day_name]
            guests_list = weekday_guests[day_name]
            avg_guests = sum(guests_list) / len(guests_list) if guests_list else 0
            
            result.append({
                'weekday': day_name,
                'day_number': ['Monday', 'Tuesday', 'Wednesday', 'Thursday', 'Friday', 'Saturday', 'Sunday'].index(day_name) + 1,
                'searches_count': searches_count,
                'percentage': round(searches_count / total_searches, 3) if total_searches > 0 else 0,
                'avg_guests_searched': round(avg_guests, 1)
            })
        
        return result
    
    def _analyze_top_searching_clients(self, searches):
        """Analizar top clientes que buscan con privacidad"""
        from django.db.models import Count
        from collections import defaultdict
        
        # Agrupar por cliente
        client_searches = searches.filter(
            client__isnull=False
        ).values(
            'client__id',
            'client__first_name',
            'client__last_name',
            'client__email',
            'property__name',
            'guests',
            'search_timestamp'
        )
        
        # Procesar datos por cliente
        clients_data = {}
        
        for search in client_searches:
            client_id = search['client__id']
            
            if client_id not in clients_data:
                clients_data[client_id] = {
                    'client_id': client_id,
                    'client_first_name': search['client__first_name'],
                    'client_last_name': search['client__last_name'],
                    'client_email': search['client__email'],
                    'searches_count': 0,
                    'properties': set(),
                    'guest_counts': set(),
                    'last_search': None
                }
            
            clients_data[client_id]['searches_count'] += 1
            
            if search['property__name']:
                clients_data[client_id]['properties'].add(search['property__name'])
            if search['guests']:
                clients_data[client_id]['guest_counts'].add(search['guests'])
            
            # Última búsqueda
            if not clients_data[client_id]['last_search'] or search['search_timestamp'] > clients_data[client_id]['last_search']:
                clients_data[client_id]['last_search'] = search['search_timestamp']
        
        # Convertir a lista y aplicar privacidad
        result = []
        for client_data in clients_data.values():
            # Enmascarar datos para privacidad
            first_name = client_data['client_first_name'] or 'Usuario'
            last_name = client_data['client_last_name'] or ''
            masked_name = f"{first_name} {last_name[:1]}.".strip() if last_name else first_name
            
            email = client_data['client_email'] or ''
            masked_email = f"{email[:3]}***@{email.split('@')[1]}" if '@' in email else "***@***.com"
            
            result.append({
                'client_id': client_data['client_id'],
                'client_name': masked_name,
                'client_email': masked_email,
                'searches_count': client_data['searches_count'],
                'last_search_date': client_data['last_search'].isoformat() if client_data['last_search'] else None,
                'converted': False,  # Placeholder
                'favorite_properties': list(client_data['properties']),
                'avg_guests': round(sum(client_data['guest_counts']) / len(client_data['guest_counts']), 1) if client_data['guest_counts'] else 0
            })
        
        # Ordenar por número de búsquedas
        result.sort(key=lambda x: x['searches_count'], reverse=True)
        
        return result[:15]  # Top 15 clientes
    
    def _analyze_anonymous_ips_comprehensive(self, searches):
        """Analizar IPs anónimas con anonimización"""
        from collections import defaultdict
        
        # Agrupar por IP anónima  
        anonymous_searches = searches.filter(
            client__isnull=True,
            ip_address__isnull=False
        ).values(
            'ip_address',
            'property__name',
            'guests',
            'user_agent',
            'search_timestamp'
        )
        
        # Procesar datos por IP
        ips_data = {}
        
        for search in anonymous_searches:
            original_ip = search['ip_address']
            
            # Anonimizar IP
            ip_parts = original_ip.split('.')
            if len(ip_parts) == 4:
                anonymized_ip = f"{ip_parts[0]}.{ip_parts[1]}.{ip_parts[2]}.xxx"
            else:
                anonymized_ip = "xxx.xxx.xxx.xxx"
            
            if anonymized_ip not in ips_data:
                ips_data[anonymized_ip] = {
                    'ip_address': anonymized_ip,
                    'searches_count': 0,
                    'properties': set(),
                    'guest_counts': set(),
                    'user_agents': set(),
                    'last_search': None
                }
            
            ips_data[anonymized_ip]['searches_count'] += 1
            
            if search['property__name']:
                ips_data[anonymized_ip]['properties'].add(search['property__name'])
            if search['guests']:
                ips_data[anonymized_ip]['guest_counts'].add(search['guests'])
            if search['user_agent']:
                ips_data[anonymized_ip]['user_agents'].add(search['user_agent'][:50])  # Truncar user agent
            
            # Última búsqueda
            if not ips_data[anonymized_ip]['last_search'] or search['search_timestamp'] > ips_data[anonymized_ip]['last_search']:
                ips_data[anonymized_ip]['last_search'] = search['search_timestamp']
        
        # Convertir a lista
        ip_details = []
        for ip_data in ips_data.values():
            ip_details.append({
                'ip_address': ip_data['ip_address'],
                'searches_count': ip_data['searches_count'],
                'unique_dates_searched': 0,  # Placeholder
                'avg_guests': round(sum(ip_data['guest_counts']) / len(ip_data['guest_counts']), 1) if ip_data['guest_counts'] else 0,
                'last_search': ip_data['last_search'].isoformat() if ip_data['last_search'] else None,
                'different_devices': len(ip_data['user_agents']),
                'favorite_properties': list(ip_data['properties'])
            })
        
        # Ordenar por número de búsquedas
        ip_details.sort(key=lambda x: x['searches_count'], reverse=True)
        
        return {
            'top_searching_ips': ip_details[:15],
            'total_anonymous_ips': searches.filter(client__isnull=True, ip_address__isnull=False).values('ip_address').distinct().count()
        }
    
    def _calculate_growth_metrics(self, current_reservations, current_searches, date_from, date_to):
        """Calcular métricas de crecimiento vs período anterior"""
        from datetime import timedelta
        from django.db.models import Sum
        
        # Período anterior (mismo número de días)
        period_days = (date_to - date_from).days
        previous_date_to = date_from - timedelta(days=1)
        previous_date_from = previous_date_to - timedelta(days=period_days)
        
        # Reservas período anterior
        from apps.reservation.models import Reservation
        previous_reservations = Reservation.objects.filter(
            check_in_date__gte=previous_date_from,
            check_in_date__lte=previous_date_to
        )
        
        # Búsquedas período anterior
        from apps.clients.models import SearchTracking
        previous_searches = SearchTracking.objects.filter(
            search_timestamp__date__gte=previous_date_from,
            search_timestamp__date__lte=previous_date_to
        )
        
        # Calcular crecimiento
        current_revenue = current_reservations.aggregate(Sum('price_sol'))['price_sol__sum'] or 0
        previous_revenue = previous_reservations.aggregate(Sum('price_sol'))['price_sol__sum'] or 0
        
        current_res_count = current_reservations.count()
        previous_res_count = previous_reservations.count()
        
        current_search_count = current_searches.count()
        previous_search_count = previous_searches.count()
        
        return {
            'reservations_growth': round((current_res_count - previous_res_count) / previous_res_count * 100, 2) if previous_res_count > 0 else 0,
            'revenue_growth': round((current_revenue - previous_revenue) / previous_revenue * 100, 2) if previous_revenue > 0 else 0,
            'searches_growth': round((current_search_count - previous_search_count) / previous_search_count * 100, 2) if previous_search_count > 0 else 0,
            'conversion_growth': 0  # Placeholder
        }


class UpcomingCheckinsView(APIView):
    """
    Endpoint para analizar check-ins próximos más buscados
    
    Parámetros:
    - days_ahead: días hacia adelante para analizar (default: 60)
    - limit: número máximo de fechas a mostrar (default: 20)
    - include_anonymous: incluir búsquedas anónimas (default: true)
    
    Retorna:
    - Fechas de check-in más buscadas que están próximas
    - Usuarios que han buscado cada fecha
    - Detalles de popularidad por fecha
    """
    
    permission_classes = [IsAuthenticated]
    
    def get(self, request):
        """Obtener check-ins próximos más buscados"""
        from django.utils import timezone
        from datetime import timedelta
        from django.db.models import Count, Q
        from collections import defaultdict
        
        # Parámetros de query con validación segura
        try:
            days_ahead = int(request.GET.get('days_ahead', 60))
            if not (1 <= days_ahead <= 180):
                days_ahead = 60
        except (ValueError, TypeError):
            days_ahead = 60
            
        try:
            limit = int(request.GET.get('limit', 20))
            if not (1 <= limit <= 100):
                limit = 20
        except (ValueError, TypeError):
            limit = 20
            
        include_anonymous = request.GET.get('include_anonymous', 'true').lower() == 'true'
        
        # Calcular rango de fechas (desde hoy hasta días hacia adelante)
        today = timezone.now().date()
        future_date = today + timedelta(days=days_ahead)
        
        try:
            # Base queryset: búsquedas con check-in en el futuro próximo
            from apps.clients.models import SearchTracking
            upcoming_searches = SearchTracking.objects.filter(
                check_in_date__gte=today,
                check_in_date__lte=future_date
            )
            
            if not include_anonymous:
                upcoming_searches = upcoming_searches.filter(client__isnull=False)
            
            # 1. Agrupar por fecha de check-in específica
            checkin_popularity = self._analyze_upcoming_checkins_by_date(upcoming_searches)
            
            # 2. Limitar resultados
            top_checkin_dates = checkin_popularity[:limit]
            
            # 3. Métricas generales
            total_upcoming_searches = upcoming_searches.count()
            unique_dates_searched = upcoming_searches.values('check_in_date').distinct().count()
            unique_clients = upcoming_searches.filter(client__isnull=False).values('client').distinct().count()
            unique_ips = upcoming_searches.filter(client__isnull=True, ip_address__isnull=False).values('ip_address').distinct().count()
            
            return Response({
                'success': True,
                'data': {
                    'period_info': {
                        'analysis_from': today.isoformat(),
                        'analysis_to': future_date.isoformat(),
                        'days_ahead': days_ahead
                    },
                    'top_upcoming_checkins': top_checkin_dates,
                    'summary_metrics': {
                        'total_upcoming_searches': total_upcoming_searches,
                        'unique_dates_searched': unique_dates_searched,
                        'unique_clients_searching': unique_clients,
                        'unique_anonymous_ips': unique_ips,
                        'avg_searches_per_date': round(total_upcoming_searches / unique_dates_searched, 2) if unique_dates_searched > 0 else 0
                    }
                },
                'generated_at': timezone.now().isoformat()
            })
            
        except Exception as e:
            # Log del error para debugging
            import logging
            logger = logging.getLogger(__name__)
            logger.error(f'Upcoming checkins processing error: {str(e)}')
            
            return Response({
                'error': 'Error al procesar check-ins próximos',
                'message': 'Error interno del servidor',
                'success': False
            }, status=500)
    
    def _analyze_upcoming_checkins_by_date(self, searches):
        """Analizar check-ins próximos agrupados por fecha específica"""
        from django.db.models import Count
        from collections import defaultdict
        
        # Agrupar búsquedas por fecha de check-in
        checkin_groups = defaultdict(list)
        
        # Obtener todas las búsquedas con detalles
        search_details = searches.values(
            'check_in_date', 'check_out_date', 'guests', 'property__name',
            'client__id', 'client__first_name', 'client__last_name', 'client__email',
            'ip_address', 'user_agent'
        )
        
        for search in search_details:
            checkin_date = search['check_in_date']
            if checkin_date:
                checkin_groups[checkin_date].append(search)
        
        # Procesar cada fecha
        result = []
        for checkin_date, searches_list in checkin_groups.items():
            
            # Separar clientes registrados de anónimos
            client_searches = [s for s in searches_list if s['client__id']]
            anonymous_searches = [s for s in searches_list if not s['client__id']]
            
            # Analizar clientes que buscaron esta fecha (con privacidad)
            clients_details = []
            for search in client_searches:
                # Enmascarar nombre para privacidad: "FirstName L."
                first_name = search['client__first_name'] or 'Usuario'
                last_name = search['client__last_name'] or ''
                masked_name = f"{first_name} {last_name[:1]}.".strip() if last_name else first_name
                
                client_info = {
                    'client_id': search['client__id'],
                    'client_name': masked_name,
                    'client_email': search['client__email'][:3] + "***@" + search['client__email'].split('@')[1] if search['client__email'] else None,  # Email parcialmente enmascarado
                    'checkout_date': search['check_out_date'].isoformat() if search['check_out_date'] else None,
                    'guests': search['guests'],
                    'property': search['property__name']
                }
                clients_details.append(client_info)
            
            # Analizar IPs que buscaron esta fecha (con anonimización)
            ips_details = []
            unique_ips = {}
            for search in anonymous_searches:
                ip = search['ip_address']
                if ip:
                    # Anonimizar IP: mantener solo /24 network (ej: 192.168.1.xxx)
                    ip_parts = ip.split('.')
                    if len(ip_parts) == 4:
                        anonymized_ip = f"{ip_parts[0]}.{ip_parts[1]}.{ip_parts[2]}.xxx"
                    else:
                        anonymized_ip = "xxx.xxx.xxx.xxx"
                    
                    if anonymized_ip not in unique_ips:
                        unique_ips[anonymized_ip] = {
                            'ip_address': anonymized_ip,
                            'searches_count': 0,
                            'checkout_dates': set(),
                            'guests_counts': set(),
                            'properties': set()
                        }
                    
                    unique_ips[anonymized_ip]['searches_count'] += 1
                    if search['check_out_date']:
                        unique_ips[anonymized_ip]['checkout_dates'].add(search['check_out_date'].isoformat())
                    unique_ips[anonymized_ip]['guests_counts'].add(search['guests'])
                    if search['property__name']:
                        unique_ips[anonymized_ip]['properties'].add(search['property__name'])
            
            # Convertir sets a lists para JSON
            for ip_data in unique_ips.values():
                ip_data['checkout_dates'] = list(ip_data['checkout_dates'])
                ip_data['guests_counts'] = list(ip_data['guests_counts'])
                ip_data['properties'] = list(ip_data['properties'])
                ips_details.append(ip_data)
            
            # Calcular duración de estadía más común
            durations = []
            for search in searches_list:
                if search['check_in_date'] and search['check_out_date']:
                    duration = (search['check_out_date'] - search['check_in_date']).days
                    if duration > 0:
                        durations.append(duration)
            
            avg_duration = sum(durations) / len(durations) if durations else 0
            
            # Calcular días hasta la fecha
            from django.utils import timezone
            days_until_checkin = (checkin_date - timezone.now().date()).days
            
            result.append({
                'checkin_date': checkin_date.isoformat(),
                'weekday': checkin_date.strftime('%A'),
                'days_until_checkin': days_until_checkin,
                'total_searches': len(searches_list),
                'client_searches': len(client_searches),
                'anonymous_searches': len(anonymous_searches),
                'avg_stay_duration': round(avg_duration, 1),
                'searching_clients': clients_details,
                'searching_ips': ips_details,
                'unique_clients_count': len(set(s['client__id'] for s in client_searches if s['client__id'])),
                'unique_ips_count': len(unique_ips)
            })
        
        # Ordenar por número total de búsquedas (más popular primero)
        result.sort(key=lambda x: x['total_searches'], reverse=True)
        
        return result


class SearchTrackingStatsView(APIView):
    """
    Endpoint específico para análisis de SearchTracking
    
    Parámetros:
    - date_from: fecha inicio análisis (default: hace 30 días)
    - date_to: fecha fin análisis (default: hoy)
    - include_clients: incluir análisis de clientes registrados (default: true)
    - include_anonymous: incluir análisis de IPs anónimas (default: true)
    
    Retorna:
    - Métricas de búsquedas
    - Top clientes que buscan
    - Top IPs anónimas
    - Análisis por día de la semana
    - Propiedades más buscadas
    """
    
    permission_classes = [IsAuthenticated]
    
    def get(self, request):
        """Obtener estadísticas específicas de SearchTracking"""
        from django.utils import timezone
        from datetime import timedelta
        from django.db.models import Count, Q
        
        # Parámetros de query con validación
        try:
            date_from_str = request.GET.get('date_from')
            if date_from_str:
                date_from = timezone.datetime.strptime(date_from_str, '%Y-%m-%d').date()
            else:
                date_from = timezone.now().date() - timedelta(days=30)
        except ValueError:
            date_from = timezone.now().date() - timedelta(days=30)
            
        try:
            date_to_str = request.GET.get('date_to')
            if date_to_str:
                date_to = timezone.datetime.strptime(date_to_str, '%Y-%m-%d').date()
            else:
                date_to = timezone.now().date()
        except ValueError:
            date_to = timezone.now().date()
            
        include_clients = request.GET.get('include_clients', 'true').lower() == 'true'
        include_anonymous = request.GET.get('include_anonymous', 'true').lower() == 'true'
        
        try:
            # Filtro base de SearchTracking por fechas
            from apps.clients.models import SearchTracking
            searches = SearchTracking.objects.filter(
                search_timestamp__date__gte=date_from,
                search_timestamp__date__lte=date_to
            )
            
            # Métricas generales
            total_searches = searches.count()
            unique_clients = searches.filter(client__isnull=False).values('client').distinct().count()
            anonymous_searches = searches.filter(client__isnull=True).count()
            conversion_rate = self._calculate_conversion_rate(searches, date_from, date_to)
            
            # Análisis específicos según filtros
            result_data = {
                'period_info': {
                    'date_from': date_from.isoformat(),
                    'date_to': date_to.isoformat(),
                    'total_days': (date_to - date_from).days + 1
                },
                'search_summary': {
                    'total_searches': total_searches,
                    'unique_clients_searching': unique_clients,
                    'anonymous_searches': anonymous_searches,
                    'conversion_rate': conversion_rate,
                    'avg_searches_per_day': round(total_searches / ((date_to - date_from).days + 1), 2)
                }
            }
            
            # Análisis por día de la semana
            result_data['searches_by_weekday'] = self._analyze_searches_by_weekday(searches)
            
            # Top propiedades buscadas
            result_data['top_searched_properties'] = self._analyze_top_searched_properties(searches)
            
            # NUEVOS ANÁLISIS ENRIQUECIDOS
            # 1. Fechas más buscadas (check-in dates populares)
            result_data['popular_checkin_dates'] = self._analyze_popular_checkin_dates(searches)
            
            # 2. Análisis de duraciones de estadía
            result_data['stay_duration_analysis'] = self._analyze_stay_durations(searches)
            
            # 3. Análisis de número de huéspedes
            result_data['guest_count_analysis'] = self._analyze_guest_counts(searches)
            
            # 4. Análisis temporal (por hora del día)
            result_data['searches_by_hour'] = self._analyze_searches_by_hour(searches)
            
            # 5. Actividad diaria (búsquedas por día)
            result_data['daily_search_activity'] = self._analyze_daily_activity(searches, date_from, date_to)
            
            # Análisis de clientes (si incluido)
            if include_clients:
                result_data['top_searching_clients'] = self._analyze_top_searching_clients(searches)
                # 6. Búsquedas por cliente único
                result_data['searches_per_client'] = self._analyze_searches_per_client(searches)
            
            # Análisis de IPs anónimas (si incluido)
            if include_anonymous:
                anonymous_data = self._analyze_anonymous_ips(searches)
                result_data['anonymous_ips_analysis'] = anonymous_data['top_searching_ips']
            
            return Response({
                'success': True,
                'data': result_data,
                'generated_at': timezone.now().isoformat()
            })
            
        except Exception as e:
            # Log del error para debugging
            import logging
            logger = logging.getLogger(__name__)
            logger.error(f'SearchTracking stats error: {str(e)}')
            
            return Response({
                'error': 'Error al procesar estadísticas de búsquedas',
                'message': 'Error interno del servidor',
                'success': False
            }, status=500)
    
    def _calculate_conversion_rate(self, searches, date_from, date_to):
        """Calcular tasa de conversión búsquedas -> reservas"""
        try:
            from apps.reservation.models import Reservation
            
            # Reservas en el mismo período
            reservations = Reservation.objects.filter(
                check_in_date__gte=date_from,
                check_in_date__lte=date_to
            ).count()
            
            total_searches = searches.count()
            if total_searches > 0:
                return round(reservations / total_searches, 3)
            return 0.0
        except:
            return 0.0
    
    def _analyze_searches_by_weekday(self, searches):
        """Analizar búsquedas por día de la semana"""
        from collections import defaultdict
        
        weekday_counts = defaultdict(int)
        weekday_guests = defaultdict(list)
        
        for search in searches.values('search_timestamp', 'guests'):
            weekday = search['search_timestamp'].strftime('%A')
            weekday_counts[weekday] += 1
            if search['guests']:
                weekday_guests[weekday].append(search['guests'])
        
        result = []
        total_searches = sum(weekday_counts.values())
        
        for day_name in ['Monday', 'Tuesday', 'Wednesday', 'Thursday', 'Friday', 'Saturday', 'Sunday']:
            searches_count = weekday_counts[day_name]
            guests_list = weekday_guests[day_name]
            avg_guests = sum(guests_list) / len(guests_list) if guests_list else 0
            
            result.append({
                'weekday': day_name,
                'day_number': ['Monday', 'Tuesday', 'Wednesday', 'Thursday', 'Friday', 'Saturday', 'Sunday'].index(day_name) + 1,
                'searches_count': searches_count,
                'percentage': round(searches_count / total_searches, 3) if total_searches > 0 else 0,
                'avg_guests_searched': round(avg_guests, 1)
            })
        
        return result
    
    def _analyze_top_searched_properties(self, searches):
        """Analizar propiedades más buscadas"""
        from django.db.models import Count
        
        property_searches = searches.filter(
            property__isnull=False
        ).values(
            'property__name',
            'property__slug'
        ).annotate(
            searches_count=Count('id')
        ).order_by('-searches_count')[:10]
        
        total_searches = searches.count()
        
        result = []
        for prop in property_searches:
            result.append({
                'property_name': prop['property__name'],
                'property_slug': prop['property__slug'],
                'searches_count': prop['searches_count'],
                'percentage': round(prop['searches_count'] / total_searches, 3) if total_searches > 0 else 0
            })
        
        return result
    
    def _analyze_top_searching_clients(self, searches):
        """Analizar top clientes que buscan (con privacidad)"""
        from django.db.models import Count
        from collections import defaultdict
        
        # Agrupar por cliente
        client_searches = searches.filter(
            client__isnull=False
        ).values(
            'client__id',
            'client__first_name',
            'client__last_name', 
            'client__email',
            'property__name',
            'guests',
            'search_timestamp'
        )
        
        # Procesar datos por cliente
        clients_data = {}
        
        for search in client_searches:
            client_id = search['client__id']
            
            if client_id not in clients_data:
                clients_data[client_id] = {
                    'client_id': client_id,
                    'client_first_name': search['client__first_name'],
                    'client_last_name': search['client__last_name'],
                    'client_email': search['client__email'],
                    'searches_count': 0,
                    'properties': set(),
                    'guest_counts': set(),
                    'last_search': None
                }
            
            clients_data[client_id]['searches_count'] += 1
            
            if search['property__name']:
                clients_data[client_id]['properties'].add(search['property__name'])
            if search['guests']:
                clients_data[client_id]['guest_counts'].add(search['guests'])
            
            # Última búsqueda
            if not clients_data[client_id]['last_search'] or search['search_timestamp'] > clients_data[client_id]['last_search']:
                clients_data[client_id]['last_search'] = search['search_timestamp']
        
        # Convertir a lista y aplicar privacidad
        result = []
        for client_data in clients_data.values():
            # Enmascarar datos para privacidad
            first_name = client_data['client_first_name'] or 'Usuario'
            last_name = client_data['client_last_name'] or ''
            masked_name = f"{first_name} {last_name[:1]}.".strip() if last_name else first_name
            
            email = client_data['client_email'] or ''
            masked_email = f"{email[:3]}***@{email.split('@')[1]}" if '@' in email else "***@***.com"
            
            result.append({
                'client_id': client_data['client_id'],
                'client_name': masked_name,
                'client_email': masked_email,
                'searches_count': client_data['searches_count'],
                'last_search_date': client_data['last_search'].isoformat() if client_data['last_search'] else None,
                'favorite_properties': list(client_data['properties']),
                'guest_counts_searched': list(client_data['guest_counts']),
                'avg_guests': round(sum(client_data['guest_counts']) / len(client_data['guest_counts']), 1) if client_data['guest_counts'] else 0
            })
        
        # Ordenar por número de búsquedas
        result.sort(key=lambda x: x['searches_count'], reverse=True)
        
        return result[:15]  # Top 15 clientes
    
    def _analyze_anonymous_ips(self, searches):
        """Analizar IPs anónimas que buscan (con anonimización)"""
        from collections import defaultdict
        
        # Agrupar por IP anónima
        anonymous_searches = searches.filter(
            client__isnull=True,
            ip_address__isnull=False
        ).values(
            'ip_address',
            'property__name',
            'guests',
            'user_agent',
            'search_timestamp'
        )
        
        # Procesar datos por IP
        ips_data = {}
        
        for search in anonymous_searches:
            original_ip = search['ip_address']
            
            # Anonimizar IP
            ip_parts = original_ip.split('.')
            if len(ip_parts) == 4:
                anonymized_ip = f"{ip_parts[0]}.{ip_parts[1]}.{ip_parts[2]}.xxx"
            else:
                anonymized_ip = "xxx.xxx.xxx.xxx"
            
            if anonymized_ip not in ips_data:
                ips_data[anonymized_ip] = {
                    'ip_address': anonymized_ip,
                    'searches_count': 0,
                    'properties': set(),
                    'guest_counts': set(),
                    'user_agents': set(),
                    'last_search': None
                }
            
            ips_data[anonymized_ip]['searches_count'] += 1
            
            if search['property__name']:
                ips_data[anonymized_ip]['properties'].add(search['property__name'])
            if search['guests']:
                ips_data[anonymized_ip]['guest_counts'].add(search['guests'])
            if search['user_agent']:
                ips_data[anonymized_ip]['user_agents'].add(search['user_agent'][:50])  # Truncar user agent
            
            # Última búsqueda
            if not ips_data[anonymized_ip]['last_search'] or search['search_timestamp'] > ips_data[anonymized_ip]['last_search']:
                ips_data[anonymized_ip]['last_search'] = search['search_timestamp']
        
        # Convertir a lista
        result = []
        for ip_data in ips_data.values():
            result.append({
                'ip_address': ip_data['ip_address'],
                'searches_count': ip_data['searches_count'],
                'last_search': ip_data['last_search'].isoformat() if ip_data['last_search'] else None,
                'favorite_properties': list(ip_data['properties']),
                'guest_counts_searched': list(ip_data['guest_counts']),
                'different_devices': len(ip_data['user_agents']),
                'avg_guests': round(sum(ip_data['guest_counts']) / len(ip_data['guest_counts']), 1) if ip_data['guest_counts'] else 0
            })
        
        # Ordenar por número de búsquedas
        result.sort(key=lambda x: x['searches_count'], reverse=True)
        
        return {
            'top_searching_ips': result[:15],  # Top 15 IPs
            'total_anonymous_ips': len(ips_data)
        }
    
    def _analyze_popular_checkin_dates(self, searches):
        """Analizar fechas de check-in más buscadas"""
        from collections import defaultdict
        from datetime import datetime
        
        checkin_counts = defaultdict(int)
        checkin_guests = defaultdict(list)
        
        for search in searches.values('check_in_date', 'guests'):
            if search['check_in_date']:
                date_str = search['check_in_date'].isoformat()
                checkin_counts[date_str] += 1
                if search['guests']:
                    checkin_guests[date_str].append(search['guests'])
        
        result = []
        for date_str, count in sorted(checkin_counts.items(), key=lambda x: x[1], reverse=True)[:20]:
            guests_list = checkin_guests[date_str]
            avg_guests = sum(guests_list) / len(guests_list) if guests_list else 0
            
            # Convertir fecha para mostrar info adicional
            date_obj = datetime.fromisoformat(date_str).date()
            weekday = date_obj.strftime('%A')
            
            result.append({
                'check_in_date': date_str,
                'searches_count': count,
                'weekday': weekday,
                'avg_guests': round(avg_guests, 1),
                'total_guests_searched': sum(guests_list)
            })
        
        return result
    
    def _analyze_stay_durations(self, searches):
        """Analizar duraciones de estadía buscadas"""
        from collections import defaultdict
        
        duration_counts = defaultdict(int)
        duration_searches = defaultdict(list)
        
        for search in searches.values('check_in_date', 'check_out_date', 'guests'):
            if search['check_in_date'] and search['check_out_date']:
                nights = (search['check_out_date'] - search['check_in_date']).days
                duration_counts[nights] += 1
                duration_searches[nights].append(search)
        
        result = []
        total_searches = sum(duration_counts.values())
        
        for nights, count in sorted(duration_counts.items()):
            if nights > 0:  # Solo estadías válidas
                searches_info = duration_searches[nights]
                avg_guests = sum([s['guests'] for s in searches_info if s['guests']]) / len([s for s in searches_info if s['guests']]) if any(s['guests'] for s in searches_info) else 0
                
                result.append({
                    'nights': nights,
                    'duration_label': f'{nights} noche{"s" if nights != 1 else ""}',
                    'searches_count': count,
                    'percentage': round(count / total_searches * 100, 2) if total_searches > 0 else 0,
                    'avg_guests': round(avg_guests, 1)
                })
        
        return result
    
    def _analyze_guest_counts(self, searches):
        """Analizar número de huéspedes buscados"""
        from collections import defaultdict
        
        guest_counts = defaultdict(int)
        guest_searches = defaultdict(list)
        
        for search in searches.values('guests', 'check_in_date', 'check_out_date'):
            if search['guests']:
                guest_counts[search['guests']] += 1
                guest_searches[search['guests']].append(search)
        
        result = []
        total_searches = sum(guest_counts.values())
        
        for guests, count in sorted(guest_counts.items()):
            searches_info = guest_searches[guests]
            
            # Calcular duración promedio para este número de huéspedes
            valid_durations = []
            for s in searches_info:
                if s['check_in_date'] and s['check_out_date']:
                    nights = (s['check_out_date'] - s['check_in_date']).days
                    if nights > 0:
                        valid_durations.append(nights)
            
            avg_nights = sum(valid_durations) / len(valid_durations) if valid_durations else 0
            
            result.append({
                'guest_count': guests,
                'guest_label': f'{guests} huésped{"es" if guests != 1 else ""}',
                'searches_count': count,
                'percentage': round(count / total_searches * 100, 2) if total_searches > 0 else 0,
                'avg_nights': round(avg_nights, 1)
            })
        
        return result
    
    def _analyze_searches_by_hour(self, searches):
        """Analizar búsquedas por hora del día"""
        from collections import defaultdict
        
        hour_counts = defaultdict(int)
        
        for search in searches.values('search_timestamp'):
            if search['search_timestamp']:
                hour = search['search_timestamp'].hour
                hour_counts[hour] += 1
        
        result = []
        total_searches = sum(hour_counts.values())
        
        for hour in range(24):
            count = hour_counts[hour]
            
            # Determinar período del día
            if 5 <= hour < 12:
                period = 'Mañana'
            elif 12 <= hour < 18:
                period = 'Tarde'
            elif 18 <= hour < 22:
                period = 'Noche'
            else:
                period = 'Madrugada'
            
            result.append({
                'hour': hour,
                'hour_label': f'{hour:02d}:00',
                'period': period,
                'searches_count': count,
                'percentage': round(count / total_searches * 100, 2) if total_searches > 0 else 0
            })
        
        return result
    
    def _analyze_daily_activity(self, searches, date_from, date_to):
        """Analizar actividad diaria de búsquedas"""
        from collections import defaultdict
        from datetime import datetime, timedelta
        
        daily_counts = defaultdict(int)
        daily_clients = defaultdict(set)
        
        for search in searches.values('search_timestamp', 'client', 'ip_address'):
            if search['search_timestamp']:
                date_str = search['search_timestamp'].date().isoformat()
                daily_counts[date_str] += 1
                
                # Contar usuarios únicos por día
                if search['client']:
                    daily_clients[date_str].add(search['client'])
                elif search['ip_address']:
                    daily_clients[date_str].add(f"ip:{search['ip_address']}")
        
        result = []
        current_date = date_from
        
        while current_date <= date_to:
            date_str = current_date.isoformat()
            searches_count = daily_counts[date_str]
            unique_users = len(daily_clients[date_str])
            weekday = current_date.strftime('%A')
            
            result.append({
                'date': date_str,
                'weekday': weekday,
                'searches_count': searches_count,
                'unique_users': unique_users,
                'searches_per_user': round(searches_count / unique_users, 2) if unique_users > 0 else 0
            })
            
            current_date += timedelta(days=1)
        
        return result
    
    def _analyze_searches_per_client(self, searches):
        """Analizar búsquedas por cliente específico"""
        from collections import defaultdict
        
        client_searches = defaultdict(int)
        client_details = {}
        
        # Solo clientes registrados (no anónimos)
        client_search_data = searches.filter(client__isnull=False).values(
            'client', 'client__first_name', 'client__last_name', 'search_timestamp'
        )
        
        for search in client_search_data:
            client_id = search['client']
            client_searches[client_id] += 1
            
            if client_id not in client_details:
                first_name = search['client__first_name'] or ''
                last_name = search['client__last_name'] or ''
                client_details[client_id] = {
                    'name': f"{first_name} {last_name}".strip() or f"Cliente {client_id}",
                    'first_search': search['search_timestamp'],
                    'last_search': search['search_timestamp']
                }
            else:
                # Actualizar primera y última búsqueda
                if search['search_timestamp'] < client_details[client_id]['first_search']:
                    client_details[client_id]['first_search'] = search['search_timestamp']
                if search['search_timestamp'] > client_details[client_id]['last_search']:
                    client_details[client_id]['last_search'] = search['search_timestamp']
        
        result = []
        for client_id, count in sorted(client_searches.items(), key=lambda x: x[1], reverse=True)[:20]:
            details = client_details[client_id]
            
            result.append({
                'client_id': client_id,
                'client_name': details['name'],
                'searches_count': count,
                'first_search': details['first_search'].isoformat(),
                'last_search': details['last_search'].isoformat(),
                'search_frequency': 'Recurrente' if count >= 3 else 'Ocasional'
            })
        
        return result


class IngresosStatsView(APIView):
    """
    Endpoint específico para análisis de ingresos y métricas financieras
    
    Parámetros:
    - date_from: fecha inicio análisis (default: hace 30 días)
    - date_to: fecha fin análisis (default: hoy)
    - period: agrupación temporal día/semana/mes (default: week)
    - currency: moneda de respuesta (default: PEN)
    
    Retorna:
    - Ingresos totales y promedio
    - Evolución temporal de ingresos
    - Distribución por método de pago
    - Análisis de precios y RevPAR
    """
    
    permission_classes = [IsAuthenticated]
    
    def get(self, request):
        """Obtener estadísticas específicas de ingresos"""
        from django.utils import timezone
        from datetime import timedelta
        from django.db.models import Sum, Avg, Count
        
        # Parámetros de query con validación
        try:
            date_from_str = request.GET.get('date_from')
            if date_from_str:
                date_from = timezone.datetime.strptime(date_from_str, '%Y-%m-%d').date()
            else:
                date_from = timezone.now().date() - timedelta(days=30)
        except ValueError:
            date_from = timezone.now().date() - timedelta(days=30)
            
        try:
            date_to_str = request.GET.get('date_to')
            if date_to_str:
                date_to = timezone.datetime.strptime(date_to_str, '%Y-%m-%d').date()
            else:
                date_to = timezone.now().date()
        except ValueError:
            date_to = timezone.now().date()
            
        period = request.GET.get('period', 'week')
        if period not in ['day', 'week', 'month']:
            period = 'week'
            
        currency = request.GET.get('currency', 'PEN')
        
        try:
            from apps.reservation.models import Reservation
            
            # Filtro base de reservas por fechas
            reservations = Reservation.objects.filter(
                check_in_date__gte=date_from,
                check_in_date__lte=date_to,
                status='approved',
                deleted=False,
            )
            
            # Métricas generales de ingresos
            total_revenue = reservations.aggregate(Sum('price_sol'))['price_sol__sum'] or 0
            avg_revenue_per_reservation = reservations.aggregate(Avg('price_sol'))['price_sol__avg'] or 0
            total_reservations = reservations.count()
            
            # Calcular total de noches
            total_nights = 0
            for reservation in reservations:
                nights = (reservation.check_out_date - reservation.check_in_date).days
                if nights > 0:
                    total_nights += nights
            
            # RevPAR (Revenue per Available Room) - simplificado
            revenue_per_night = total_revenue / total_nights if total_nights > 0 else 0
            
            # Análisis temporal de ingresos
            revenue_by_period = self._analyze_revenue_by_period(reservations, period, date_from, date_to)
            
            # Distribución por método de pago
            payment_distribution = self._analyze_payment_methods(reservations)
            
            # Análisis de precios
            price_analysis = self._analyze_pricing_patterns(reservations)
            
            # Comparación con período anterior
            growth_metrics = self._calculate_revenue_growth(reservations, date_from, date_to, period)
            
            return Response({
                'success': True,
                'data': {
                    'period_info': {
                        'date_from': date_from.isoformat(),
                        'date_to': date_to.isoformat(),
                        'period_grouping': period,
                        'currency': currency,
                        'total_days': (date_to - date_from).days + 1
                    },
                    'revenue_summary': {
                        'total_revenue': round(total_revenue, 2),
                        'total_nights': total_nights,
                        'total_reservations': total_reservations,
                        'avg_revenue_per_reservation': round(avg_revenue_per_reservation, 2),
                        'revenue_per_night': round(revenue_per_night, 2),
                        'avg_revenue_per_day': round(total_revenue / ((date_to - date_from).days + 1), 2)
                    },
                    'revenue_by_period': revenue_by_period,
                    'payment_distribution': payment_distribution,
                    'price_analysis': price_analysis,
                    'growth_metrics': growth_metrics
                },
                'generated_at': timezone.now().isoformat()
            })
            
        except Exception as e:
            # Log del error para debugging
            import logging
            logger = logging.getLogger(__name__)
            logger.error(f'Revenue stats error: {str(e)}')
            
            return Response({
                'error': 'Error al procesar estadísticas de ingresos',
                'message': 'Error interno del servidor',
                'success': False
            }, status=500)
    
    def _analyze_revenue_by_period(self, reservations, period, date_from, date_to):
        """Analizar ingresos agrupados por período"""
        from django.db.models import Sum
        from datetime import timedelta
        
        # Agrupar reservas por período
        revenue_periods = []
        current_date = date_from
        
        while current_date <= date_to:
            if period == 'day':
                period_end = current_date
                next_date = current_date + timedelta(days=1)
                period_label = current_date.strftime('%d %b')
            elif period == 'week':
                days_to_monday = current_date.weekday()
                period_start = current_date - timedelta(days=days_to_monday)
                period_end = period_start + timedelta(days=6)
                next_date = period_end + timedelta(days=1)
                period_label = f"Semana del {period_start.strftime('%d %b')}"
            else:  # month
                period_start = current_date.replace(day=1)
                if current_date.month == 12:
                    period_end = current_date.replace(year=current_date.year + 1, month=1, day=1) - timedelta(days=1)
                else:
                    period_end = current_date.replace(month=current_date.month + 1, day=1) - timedelta(days=1)
                next_date = period_end + timedelta(days=1)
                period_label = current_date.strftime('%B %Y')
            
            # Filtrar reservas en este período
            period_reservations = reservations.filter(
                check_in_date__gte=current_date,
                check_in_date__lte=min(period_end, date_to)
            )
            
            period_revenue = period_reservations.aggregate(Sum('price_sol'))['price_sol__sum'] or 0
            period_count = period_reservations.count()
            # Calcular noches para el período
            period_nights = 0
            for res in period_reservations:
                nights = (res.check_out_date - res.check_in_date).days
                if nights > 0:
                    period_nights += nights
            
            revenue_periods.append({
                'period': current_date.isoformat(),
                'period_label': period_label,
                'revenue': round(period_revenue, 2),
                'reservations_count': period_count,
                'nights_count': period_nights,
                'avg_revenue_per_reservation': round(period_revenue / period_count, 2) if period_count > 0 else 0,
                'revenue_per_night': round(period_revenue / period_nights, 2) if period_nights > 0 else 0
            })
            
            current_date = next_date
            
            # Evitar loop infinito
            if current_date > date_to:
                break
        
        return revenue_periods
    
    def _analyze_payment_methods(self, reservations):
        """Analizar distribución por métodos de pago"""
        from django.db.models import Sum, Count
        
        # Agrupar por método de pago (si existe el campo)
        payment_methods = []
        
        # Verificar si el modelo tiene campo payment_method
        if hasattr(reservations.model, 'payment_method'):
            payment_data = reservations.values('payment_method').annotate(
                count=Count('id'),
                total_revenue=Sum('price_sol')
            ).order_by('-total_revenue')
            
            total_revenue = reservations.aggregate(Sum('price_sol'))['price_sol__sum'] or 0
            
            for payment in payment_data:
                payment_methods.append({
                    'payment_method': payment['payment_method'] or 'No especificado',
                    'reservations_count': payment['count'],
                    'total_revenue': round(payment['total_revenue'] or 0, 2),
                    'percentage': round((payment['total_revenue'] or 0) / total_revenue * 100, 2) if total_revenue > 0 else 0
                })
        else:
            # Si no hay campo payment_method, devolver estructura básica
            payment_methods.append({
                'payment_method': 'Todos los métodos',
                'reservations_count': reservations.count(),
                'total_revenue': round(reservations.aggregate(Sum('price_sol'))['price_sol__sum'] or 0, 2),
                'percentage': 100.0
            })
        
        return payment_methods
    
    def _analyze_pricing_patterns(self, reservations):
        """Analizar patrones de precios"""
        from django.db.models import Avg, Min, Max, Sum
        
        # Calcular precio por noche para cada reserva
        price_stats = reservations.aggregate(
            avg_price_sol=Avg('price_sol'),
            min_price_sol=Min('price_sol'),
            max_price_sol=Max('price_sol')
        )
        
        # Calcular duración promedio de estadía
        durations = []
        for reservation in reservations:
            nights = (reservation.check_out_date - reservation.check_in_date).days
            if nights > 0:
                durations.append(nights)
        
        avg_nights = sum(durations) / len(durations) if durations else 0
        
        # Calcular precio promedio por noche
        total_cost_sum = reservations.aggregate(Sum('price_sol'))['price_sol__sum'] or 0
        
        # Calcular total de noches manualmente
        total_nights_sum = 0
        for reservation in reservations:
            nights = (reservation.check_out_date - reservation.check_in_date).days
            if nights > 0:
                total_nights_sum += nights
                
        avg_price_per_night = total_cost_sum / total_nights_sum if total_nights_sum > 0 else 0
        
        # Distribución por rangos de precio
        price_ranges = [
            {'min': 0, 'max': 500, 'label': '0-500 PEN'},
            {'min': 500, 'max': 1000, 'label': '500-1000 PEN'},
            {'min': 1000, 'max': 2000, 'label': '1000-2000 PEN'},
            {'min': 2000, 'max': 5000, 'label': '2000-5000 PEN'},
            {'min': 5000, 'max': 999999, 'label': '5000+ PEN'}
        ]
        
        price_distribution = []
        for price_range in price_ranges:
            count = reservations.filter(
                price_sol__gte=price_range['min'],
                price_sol__lt=price_range['max']
            ).count()
            
            price_distribution.append({
                'price_range': price_range['label'],
                'reservations_count': count,
                'percentage': round(count / reservations.count() * 100, 2) if reservations.count() > 0 else 0
            })
        
        return {
            'avg_total_cost': round(price_stats['avg_price_sol'] or 0, 2),
            'min_total_cost': round(price_stats['min_price_sol'] or 0, 2),
            'max_total_cost': round(price_stats['max_price_sol'] or 0, 2),
            'avg_price_per_night': round(avg_price_per_night, 2),
            'avg_nights_per_reservation': round(avg_nights, 1),
            'price_distribution': price_distribution
        }
    
    def _calculate_revenue_growth(self, current_reservations, date_from, date_to, period):
        """Calcular crecimiento de ingresos vs mismo período del año anterior"""
        from django.db.models import Sum
        from datetime import date as dt_date

        # Calcular ingresos período actual
        current_revenue = current_reservations.aggregate(Sum('price_sol'))['price_sol__sum'] or 0
        current_count = current_reservations.count()

        # Mismo período del año anterior (Ene 1 - Feb 18, 2026 → Ene 1 - Feb 18, 2025)
        try:
            previous_date_from = date_from.replace(year=date_from.year - 1)
            previous_date_to = date_to.replace(year=date_to.year - 1)
        except ValueError:
            # 29 feb → 28 feb
            previous_date_from = dt_date(date_from.year - 1, date_from.month, min(date_from.day, 28))
            previous_date_to = dt_date(date_to.year - 1, date_to.month, min(date_to.day, 28))

        from apps.reservation.models import Reservation
        previous_reservations = Reservation.objects.filter(
            check_in_date__gte=previous_date_from,
            check_in_date__lte=previous_date_to,
            status='approved',
            deleted=False,
        )

        previous_revenue = previous_reservations.aggregate(Sum('price_sol'))['price_sol__sum'] or 0
        previous_count = previous_reservations.count()

        # Calcular crecimiento
        revenue_growth = ((current_revenue - previous_revenue) / previous_revenue * 100) if previous_revenue > 0 else 0
        reservations_growth = ((current_count - previous_count) / previous_count * 100) if previous_count > 0 else 0

        return {
            'revenue_growth_percentage': round(revenue_growth, 2),
            'reservations_growth_percentage': round(reservations_growth, 2),
            'current_period_revenue': round(current_revenue, 2),
            'previous_period_revenue': round(previous_revenue, 2),
            'current_period_reservations': current_count,
            'previous_period_reservations': previous_count,
            'current_period_label': f"{date_from.strftime('%d %b %Y')} - {date_to.strftime('%d %b %Y')}",
            'previous_period_label': f"{previous_date_from.strftime('%d %b %Y')} - {previous_date_to.strftime('%d %b %Y')}",
        }


class MetasIngresosView(APIView):
    """
    Endpoint para comparar metas de ingresos vs ingresos reales por mes.

    Parámetros:
    - year: año a consultar (default: año actual)

    Retorna:
    - Lista de meses con meta, ingreso real y variación porcentual
    - Resumen anual con totales y variación general
    """

    permission_classes = [IsAuthenticated]

    MONTH_NAMES = {
        1: 'Enero', 2: 'Febrero', 3: 'Marzo', 4: 'Abril',
        5: 'Mayo', 6: 'Junio', 7: 'Julio', 8: 'Agosto',
        9: 'Septiembre', 10: 'Octubre', 11: 'Noviembre', 12: 'Diciembre'
    }

    def get(self, request):
        """Obtener comparación de metas vs ingresos reales"""
        from django.db.models import Sum
        from datetime import date
        import calendar

        from apps.reservation.models import Reservation
        from .models import MonthlyRevenueMeta

        # Obtener año del parámetro o usar el actual
        try:
            year = int(request.GET.get('year', timezone.now().year))
        except ValueError:
            year = timezone.now().year

        # Mes actual para saber hasta dónde calcular
        current_date = timezone.now().date()
        current_month = current_date.month if current_date.year == year else 12
        current_year = current_date.year

        monthly_data = []
        total_meta = 0
        total_actual = 0

        for month in range(1, 13):
            # Obtener meta del mes
            meta = MonthlyRevenueMeta.get_meta_for_month(month, year)
            target_amount = float(meta.target_amount) if meta else 0

            # Calcular primer y último día del mes
            first_day = date(year, month, 1)
            last_day = date(year, month, calendar.monthrange(year, month)[1])

            # Obtener ingresos reales del mes (siempre, incluyendo reservas futuras)
            actual_revenue = Reservation.objects.filter(
                check_in_date__gte=first_day,
                check_in_date__lte=last_day,
                status='approved',
                deleted=False
            ).aggregate(total=Sum('price_sol'))['total'] or 0
            actual_revenue = float(actual_revenue)

            # Determinar si es mes futuro (aún no ha terminado)
            is_future_month = year > current_year or (year == current_year and month > current_month)

            # Calcular variación porcentual
            if target_amount > 0 and actual_revenue is not None:
                variation_percentage = ((actual_revenue - target_amount) / target_amount) * 100
                achievement_percentage = (actual_revenue / target_amount) * 100
            else:
                variation_percentage = None
                achievement_percentage = None

            # Determinar estado
            if target_amount == 0:
                status = 'no_target'  # Sin meta definida
            elif is_future_month:
                # Para meses futuros, evaluar basado en lo que ya tienen reservado
                if achievement_percentage >= 100:
                    status = 'achieved'
                elif achievement_percentage >= 75:
                    status = 'on_track'
                else:
                    status = 'pending'  # Aún pendiente de completar
            elif achievement_percentage >= 100:
                status = 'achieved'  # Meta cumplida
            elif achievement_percentage >= 75:
                status = 'on_track'  # En camino
            elif achievement_percentage >= 50:
                status = 'at_risk'  # En riesgo
            else:
                status = 'behind'  # Rezagado

            # Acumular totales (solo meses con meta definida)
            if target_amount > 0:
                total_meta += target_amount
                total_actual += actual_revenue

            monthly_data.append({
                'month': month,
                'month_name': self.MONTH_NAMES[month],
                'target_amount': round(target_amount, 2),
                'actual_revenue': round(actual_revenue, 2),
                'variation_percentage': round(variation_percentage, 2) if variation_percentage is not None else None,
                'achievement_percentage': round(achievement_percentage, 2) if achievement_percentage is not None else None,
                'difference': round(actual_revenue - target_amount, 2),
                'status': status,
                'has_target': target_amount > 0,
                'is_future': is_future_month,
                'notes': meta.notes if meta else None
            })

        # Calcular resumen anual
        if total_meta > 0:
            annual_variation = ((total_actual - total_meta) / total_meta) * 100
            annual_achievement = (total_actual / total_meta) * 100
        else:
            annual_variation = 0
            annual_achievement = 0

        return Response({
            'success': True,
            'data': {
                'year': year,
                'monthly_breakdown': monthly_data,
                'annual_summary': {
                    'total_target': round(total_meta, 2),
                    'total_actual': round(total_actual, 2),
                    'total_difference': round(total_actual - total_meta, 2),
                    'variation_percentage': round(annual_variation, 2),
                    'achievement_percentage': round(annual_achievement, 2),
                    'months_with_target': sum(1 for m in monthly_data if m['has_target']),
                    'months_achieved': sum(1 for m in monthly_data if m['status'] == 'achieved'),
                    'months_on_track': sum(1 for m in monthly_data if m['status'] == 'on_track'),
                    'months_at_risk': sum(1 for m in monthly_data if m['status'] == 'at_risk'),
                    'months_behind': sum(1 for m in monthly_data if m['status'] == 'behind'),
                }
            },
            'generated_at': timezone.now().isoformat()
        })


class IngresosAnalysisView(APIView):
    """
    GET /api/v1/stats/ingresos/analysis/
    Análisis IA de ingresos con datos enriquecidos: comparación interanual,
    crecimiento por mes, métricas de estadía, distribución de precios.
    """
    permission_classes = [IsAuthenticated]

    ANALYSIS_PROMPT = (
        "Eres un analista financiero senior especializado en alquiler vacacional en Perú. "
        "El negocio son departamentos/casas vacacionales en Lima (Casa Austin). "
        "Analiza los datos proporcionados y genera un informe ejecutivo en español con markdown. "
        "Sé directo y concreto — usa cifras exactas, porcentajes y comparaciones. "
        "Las cantidades están en soles peruanos (S/). "
        "NO repitas los datos en tablas — interprétalos, encuentra patrones y da recomendaciones accionables. "
        "El dueño del negocio quiere saber: ¿cómo voy vs el año pasado? ¿qué debo hacer diferente?"
    )

    def get(self, request):
        from django.conf import settings as django_settings
        from datetime import date
        from apps.reservation.models import Reservation
        from .models import MonthlyRevenueMeta
        from apps.property.models import Property
        import calendar
        import openai

        today = timezone.now().date()
        start_date = date(today.year - 2, today.month, 1)

        # --- Recopilar datos mensuales (últimos ~24 meses) ---
        monthly_data = []
        current = start_date
        while current <= today:
            last_day = date(
                current.year, current.month,
                calendar.monthrange(current.year, current.month)[1]
            )
            reservations = Reservation.objects.filter(
                check_in_date__gte=current,
                check_in_date__lte=last_day,
                status='approved',
                deleted=False,
            )
            revenue = float(
                reservations.aggregate(total=Sum('price_sol'))['total'] or 0
            )
            count = reservations.count()

            total_nights = 0
            for r in reservations:
                nights = (r.check_out_date - r.check_in_date).days
                if nights > 0:
                    total_nights += nights

            avg_per_night = round(revenue / total_nights, 2) if total_nights > 0 else 0
            avg_stay = round(total_nights / count, 1) if count > 0 else 0
            avg_per_reservation = round(revenue / count, 2) if count > 0 else 0

            meta = MonthlyRevenueMeta.get_meta_for_month(current.month, current.year)
            target = float(meta.target_amount) if meta else 0

            monthly_data.append({
                'year': current.year,
                'month': current.month,
                'month_name': calendar.month_name[current.month],
                'revenue': round(revenue, 2),
                'reservations': count,
                'nights': total_nights,
                'avg_per_night': avg_per_night,
                'avg_stay': avg_stay,
                'avg_per_reservation': avg_per_reservation,
                'target': round(target, 2),
            })

            if current.month == 12:
                current = date(current.year + 1, 1, 1)
            else:
                current = date(current.year, current.month + 1, 1)

        # --- Contexto actual ---
        days_in_month = calendar.monthrange(today.year, today.month)[1]
        days_elapsed = today.day
        cur_month = next(
            (m for m in monthly_data if m['year'] == today.year and m['month'] == today.month), None
        )
        property_count = Property.objects.count()

        # --- Acumulados año actual vs anterior ---
        cur_year_months = [m for m in monthly_data if m['year'] == today.year]
        prev_year_months = [m for m in monthly_data if m['year'] == today.year - 1]
        # Solo comparar hasta el mes actual
        prev_comparable = [m for m in prev_year_months if m['month'] <= today.month]

        cum_cur = sum(m['revenue'] for m in cur_year_months)
        cum_prev = sum(m['revenue'] for m in prev_comparable)
        cum_growth = round(((cum_cur - cum_prev) / cum_prev) * 100, 1) if cum_prev > 0 else 0

        total_res_cur = sum(m['reservations'] for m in cur_year_months)
        total_res_prev = sum(m['reservations'] for m in prev_comparable)
        total_nights_cur = sum(m['nights'] for m in cur_year_months)
        total_nights_prev = sum(m['nights'] for m in prev_comparable)

        # --- Distribución de precios (año actual) ---
        cur_year_reservations = Reservation.objects.filter(
            check_in_date__gte=date(today.year, 1, 1),
            check_in_date__lte=today,
            status='approved',
            deleted=False,
        )
        price_ranges = {'0-300': 0, '300-600': 0, '600-1000': 0, '1000-2000': 0, '2000+': 0}
        for r in cur_year_reservations:
            p = float(r.price_sol) if r.price_sol else 0
            if p <= 300:
                price_ranges['0-300'] += 1
            elif p <= 600:
                price_ranges['300-600'] += 1
            elif p <= 1000:
                price_ranges['600-1000'] += 1
            elif p <= 2000:
                price_ranges['1000-2000'] += 1
            else:
                price_ranges['2000+'] += 1

        # --- Construir datos para la IA ---
        data_text = "# DATOS DE INGRESOS — CASA AUSTIN\n\n"

        # Tabla principal con comparación interanual
        data_text += "## Tabla Mensual con Comparación Interanual\n\n"
        data_text += "| Mes | Ingreso | Reservas | Noches | Prom/Noche | Prom Estadía | Prom/Reserva | vs Año Ant. | Meta |\n"
        data_text += "|-----|---------|----------|--------|------------|-------------|-------------|------------|------|\n"

        for m in monthly_data:
            # Buscar mismo mes del año anterior
            prev_same = next(
                (p for p in monthly_data if p['year'] == m['year'] - 1 and p['month'] == m['month']),
                None
            )
            if prev_same and prev_same['revenue'] > 0:
                yoy = round(((m['revenue'] - prev_same['revenue']) / prev_same['revenue']) * 100, 1)
                yoy_str = f"{yoy:+.1f}%"
            elif m['revenue'] > 0:
                yoy_str = "nuevo"
            else:
                yoy_str = "—"

            meta_str = f"S/{m['target']:,.0f}" if m['target'] > 0 else "—"
            data_text += (
                f"| {m['month_name'][:3]} {m['year']} "
                f"| S/{m['revenue']:,.0f} "
                f"| {m['reservations']} "
                f"| {m['nights']} "
                f"| S/{m['avg_per_night']:,.0f} "
                f"| {m['avg_stay']} noches "
                f"| S/{m['avg_per_reservation']:,.0f} "
                f"| {yoy_str} "
                f"| {meta_str} |\n"
            )

        # Resumen acumulado
        data_text += f"\n## Acumulado {today.year} vs {today.year - 1} (mismo período ene-{today.strftime('%b')})\n\n"
        data_text += f"| Métrica | {today.year} | {today.year - 1} | Variación |\n"
        data_text += f"|---------|------|------|----------|\n"
        data_text += f"| Ingreso total | S/{cum_cur:,.0f} | S/{cum_prev:,.0f} | {cum_growth:+.1f}% |\n"
        data_text += f"| Reservas | {total_res_cur} | {total_res_prev} | {round(((total_res_cur - total_res_prev) / total_res_prev) * 100, 1) if total_res_prev > 0 else 0:+.1f}% |\n"
        data_text += f"| Noches vendidas | {total_nights_cur} | {total_nights_prev} | {round(((total_nights_cur - total_nights_prev) / total_nights_prev) * 100, 1) if total_nights_prev > 0 else 0:+.1f}% |\n"
        avg_pn_cur = round(cum_cur / total_nights_cur, 0) if total_nights_cur > 0 else 0
        avg_pn_prev = round(cum_prev / total_nights_prev, 0) if total_nights_prev > 0 else 0
        data_text += f"| S/ por noche (prom) | S/{avg_pn_cur:,.0f} | S/{avg_pn_prev:,.0f} | {round(((avg_pn_cur - avg_pn_prev) / avg_pn_prev) * 100, 1) if avg_pn_prev > 0 else 0:+.1f}% |\n"

        # Contexto actual
        data_text += f"\n## Contexto Actual\n\n"
        data_text += f"- Fecha de hoy: {today.isoformat()}\n"
        data_text += f"- Propiedades activas: {property_count}\n"
        data_text += f"- Día {days_elapsed} de {days_in_month} del mes ({round(days_elapsed/days_in_month*100)}% del mes transcurrido)\n"
        if cur_month:
            data_text += f"- Ingreso del mes hasta hoy: S/{cur_month['revenue']:,.0f}\n"
            data_text += f"- Reservas del mes hasta hoy: {cur_month['reservations']}\n"
            data_text += f"- Noches vendidas del mes hasta hoy: {cur_month['nights']}\n"
            # Reservas confirmadas para el resto del mes (check-ins futuros)
            remaining_reservations = Reservation.objects.filter(
                check_in_date__gt=today,
                check_in_date__lte=date(today.year, today.month, days_in_month),
                status='approved',
                deleted=False,
            )
            remaining_count = remaining_reservations.count()
            remaining_revenue = float(
                remaining_reservations.aggregate(total=Sum('price_sol'))['total'] or 0
            )
            data_text += f"- Reservas confirmadas del {today.day + 1} al {days_in_month} de este mes: {remaining_count} (S/{remaining_revenue:,.0f})\n"
            data_text += f"- Total estimado del mes (real + confirmado): S/{cur_month['revenue'] + remaining_revenue:,.0f}\n"
            data_text += f"- Noches libres restantes este mes: {days_in_month - today.day} días del calendario por cubrir\n"
            if cur_month['target'] > 0:
                data_text += f"- Meta del mes: S/{cur_month['target']:,.0f}\n"
                total_month_estimate = cur_month['revenue'] + remaining_revenue
                data_text += f"- Progreso vs meta (real + confirmado): {round(total_month_estimate / cur_month['target'] * 100)}%\n"
            prev_same_month = next(
                (m for m in monthly_data if m['year'] == today.year - 1 and m['month'] == today.month), None
            )
            if prev_same_month:
                data_text += f"- Mismo mes año anterior (completo): S/{prev_same_month['revenue']:,.0f} ({prev_same_month['reservations']} reservas, {prev_same_month['nights']} noches)\n"

        # Distribución de precios
        data_text += f"\n## Distribución de Precios ({today.year})\n\n"
        total_pr = sum(price_ranges.values())
        for rng, cnt in price_ranges.items():
            pct = round(cnt / total_pr * 100) if total_pr > 0 else 0
            data_text += f"- S/{rng}: {cnt} reservas ({pct}%)\n"

        # Mejores y peores meses del año actual
        if cur_year_months:
            best = max(cur_year_months, key=lambda m: m['revenue'])
            worst = min([m for m in cur_year_months if m['revenue'] > 0], key=lambda m: m['revenue'], default=None)
            data_text += f"\n## Extremos {today.year}\n\n"
            data_text += f"- Mejor mes: {best['month_name']} — S/{best['revenue']:,.0f} ({best['reservations']} reservas)\n"
            if worst and worst['month'] != best['month']:
                data_text += f"- Peor mes: {worst['month_name']} — S/{worst['revenue']:,.0f} ({worst['reservations']} reservas)\n"

        # Prompt para la IA
        user_message = (
            f"{data_text}\n\n"
            "---\n\n"
            "Con base en TODOS estos datos, genera este análisis (no repitas tablas de datos, interprétalos):\n\n"
            "## 1. Estado Actual\n"
            "¿Cómo va el negocio hoy? Ingreso acumulado, ritmo vs año pasado, progreso del mes. "
            "Sé específico con números.\n\n"
            "## 2. Comparación Interanual\n"
            "Análisis mes a mes de cómo va el año actual vs el anterior. "
            "¿Qué meses mejoraron? ¿Cuáles cayeron? ¿Por cuánto? "
            "Destaca los cambios más significativos.\n\n"
            "## 3. Cierre del Mes Actual\n"
            "Usa los datos de ingreso real + reservas confirmadas para el resto del mes. "
            "NO hagas proyecciones lineales (dividir entre días transcurridos). "
            "El ingreso real + confirmado es lo que va a entrar. Indica cuánto falta vs la meta "
            "y qué tan factible es cubrirlo con las noches restantes libres.\n\n"
            "## 4. Proyección del Año\n"
            "Basándote en el patrón estacional de años anteriores, ¿cómo cerrará el año? "
            "¿Se alcanzarán las metas anuales?\n\n"
            "## 5. Patrones y Estacionalidad\n"
            "¿Qué meses son fuertes y cuáles débiles? ¿Se repite el patrón entre años? "
            "¿Cambió la duración promedio de estadía? ¿Cambió el precio por noche?\n\n"
            "## 6. Recomendaciones (3-5 accionables)\n"
            "Basadas en los datos concretos. Ejemplo: 'En marzo el ingreso cayó 30% vs 2025 "
            "porque las reservas bajaron de 12 a 8 — considerar promociones de última hora'. "
            "NO des consejos genéricos, solo específicos a estos datos."
        )

        # --- Llamar a OpenAI ---
        try:
            client = openai.OpenAI(api_key=django_settings.OPENAI_API_KEY)
            response = client.chat.completions.create(
                model="gpt-4.1-nano",
                temperature=0.3,
                max_tokens=5000,
                messages=[
                    {"role": "system", "content": self.ANALYSIS_PROMPT},
                    {"role": "user", "content": user_message},
                ],
            )

            analysis_text = response.choices[0].message.content
            tokens_used = response.usage.total_tokens if response.usage else 0

            return Response({
                'analysis': analysis_text,
                'months_analyzed': len(monthly_data),
                'tokens_used': tokens_used,
                'model': 'gpt-4.1-nano',
            })

        except Exception as e:
            logger = logging.getLogger(__name__)
            logger.error(f"Error en análisis IA de ingresos: {e}")
            return Response(
                {'error': f'Error al generar análisis: {str(e)}'},
                status=500
            )