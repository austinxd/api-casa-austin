from django.utils import timezone
from rest_framework import generics, status
from rest_framework.decorators import api_view, permission_classes, authentication_classes
from rest_framework.permissions import AllowAny
from rest_framework.response import Response
from rest_framework.views import APIView
from rest_framework.pagination import PageNumberPagination
from rest_framework_simplejwt.exceptions import InvalidToken, TokenError
from django.db.models import Q

from apps.clients.models import Clients
from apps.clients.auth_views import ClientJWTAuthentication
from .models import EventCategory, Event, EventRegistration, ActivityFeed
from .serializers import (
    EventCategorySerializer, EventListSerializer, EventDetailSerializer,
    EventRegistrationSerializer, EventRegistrationCreateSerializer, EventParticipantSerializer,
    ActivityFeedSerializer, ActivityFeedCreateSerializer, ActivityFeedFilterSerializer
)


# === ENDPOINTS PÚBLICOS (sin autenticación) ===

class PublicEventCategoryListView(generics.ListAPIView):
    """Lista pública de categorías de eventos"""
    
    queryset = EventCategory.objects.filter(deleted=False)
    serializer_class = EventCategorySerializer
    permission_classes = [AllowAny]


class PublicEventListView(generics.ListAPIView):
    """Lista pública de eventos activos con filtros opcionales"""
    
    serializer_class = EventListSerializer
    permission_classes = [AllowAny]
    
    def get_queryset(self):
        from django.utils import timezone
        now = timezone.now()
        
        # Base queryset - todos los eventos publicados
        queryset = Event.objects.filter(
            deleted=False,
            is_active=True,
            is_public=True,
            status=Event.EventStatus.PUBLISHED
        ).select_related('category')
        
        # Filtrar por status si se proporciona
        status_filter = self.request.GET.get('status', None)
        
        if status_filter == 'upcoming':
            # Eventos próximos: que no hayan ocurrido
            queryset = queryset.filter(event_date__gte=now)
            
        elif status_filter == 'past':
            # Solo eventos que ya terminaron
            queryset = queryset.filter(event_date__lt=now)
        
        # Filtrar por categoría si se proporciona
        category_filter = self.request.GET.get('category', None)
        if category_filter:
            queryset = queryset.filter(category__name__icontains=category_filter)
        
        # Ordenar: eventos próximos por fecha ASC, pasados por fecha DESC
        if status_filter == 'upcoming':
            return queryset.order_by('event_date')  # Próximos primero
        else:
            return queryset.order_by('-event_date')  # Más recientes primero


class PublicEventDetailView(generics.RetrieveAPIView):
    """Detalle público de un evento específico"""
    
    serializer_class = EventDetailSerializer
    permission_classes = [AllowAny]
    lookup_field = 'id'
    
    def get_queryset(self):
        return Event.objects.filter(
            deleted=False,
            is_active=True,
            is_public=True,
            status=Event.EventStatus.PUBLISHED
        ).select_related('category').prefetch_related('required_achievements')


# === ENDPOINTS CON AUTENTICACIÓN DE CLIENTE ===

class EventRegistrationView(APIView):
    """Registrarse o cancelar registro de un evento"""
    
    authentication_classes = [ClientJWTAuthentication]
    permission_classes = [AllowAny]
    
    def post(self, request, event_id):
        """Registrarse a un evento"""
        try:
            # Autenticar cliente
            authenticator = ClientJWTAuthentication()
            auth_result = authenticator.authenticate(request)
            
            if auth_result is None:
                return Response({
                    'success': False,
                    'message': 'Token inválido'
                }, status=status.HTTP_401_UNAUTHORIZED)
            
            client, validated_token = auth_result
            
            # Obtener evento
            event = Event.objects.get(
                id=event_id,
                deleted=False,
                is_active=True,
                status=Event.EventStatus.PUBLISHED
            )
            
            # Verificar si el cliente puede registrarse
            can_register, message = event.client_can_register(client)
            if not can_register:
                return Response({
                    'success': False,
                    'message': message
                }, status=status.HTTP_400_BAD_REQUEST)
            
            # Verificar si ya existe un registro (incluyendo cancelados)
            existing_registration = EventRegistration.objects.filter(
                event=event,
                client=client,
                deleted=False
            ).first()
            
            if existing_registration:
                # Reutilizar registro existente si está cancelado o rechazado
                if existing_registration.status in ['cancelled', 'rejected']:
                    existing_registration.status = EventRegistration.RegistrationStatus.APPROVED
                    existing_registration.registration_date = timezone.now()
                    existing_registration.save()
                    
                    # 📊 ACTIVITY FEED: Crear actividad para reactivación de registro
                    try:
                        from apps.events.models import ActivityFeedConfig
                        
                        # ✅ VERIFICAR CONFIGURACIÓN: ¿Está habilitado este tipo de actividad?
                        if ActivityFeedConfig.is_type_enabled(ActivityFeed.ActivityType.EVENT_REGISTRATION):
                            # Usar configuración por defecto para visibilidad e importancia
                            is_public = ActivityFeedConfig.should_be_public(ActivityFeed.ActivityType.EVENT_REGISTRATION)
                            importance = ActivityFeedConfig.get_default_importance(ActivityFeed.ActivityType.EVENT_REGISTRATION)
                            
                            ActivityFeed.create_activity(
                                activity_type=ActivityFeed.ActivityType.EVENT_REGISTRATION,
                                client=client,
                                event=event,
                                property_location=event.property_location,
                                is_public=is_public,
                                importance_level=importance,
                                activity_data={
                                    'event_name': event.title,
                                    'event_id': str(event.id),
                                    'registration_id': str(existing_registration.id),
                                    'event_date': event.event_date.isoformat(),
                                    'category': event.category.name if event.category else 'General',
                                    'reactivated': True
                                }
                            )
                        print(f"Actividad de reactivación de registro creada para cliente {client.id}")
                    except Exception as e:
                        print(f"Error creando actividad de reactivación de registro: {str(e)}")

                    return Response({
                        'success': True,
                        'message': 'Registro reactivado exitosamente',
                        'registration_id': existing_registration.id
                    }, status=status.HTTP_201_CREATED)
                else:
                    # Si está pending o approved, no debería llegar aquí por client_can_register
                    return Response({
                        'success': False,
                        'message': 'Ya tienes un registro activo para este evento'
                    }, status=status.HTTP_400_BAD_REQUEST)
            
            # Crear nuevo registro si no existe
            serializer = EventRegistrationCreateSerializer(
                data=request.data,
                context={'event': event, 'client': client}
            )
            if serializer.is_valid():
                registration = serializer.save()
                
                # Aprobar automáticamente si no hay restricciones especiales
                registration.status = EventRegistration.RegistrationStatus.APPROVED
                registration.save()
                
                # 📊 ACTIVITY FEED: Crear actividad para registro a evento
                try:
                    from apps.events.models import ActivityFeedConfig
                    
                    # ✅ VERIFICAR CONFIGURACIÓN: ¿Está habilitado este tipo de actividad?
                    if ActivityFeedConfig.is_type_enabled(ActivityFeed.ActivityType.EVENT_REGISTRATION):
                        # Usar configuración por defecto para visibilidad e importancia
                        is_public = ActivityFeedConfig.should_be_public(ActivityFeed.ActivityType.EVENT_REGISTRATION)
                        importance = ActivityFeedConfig.get_default_importance(ActivityFeed.ActivityType.EVENT_REGISTRATION)
                        
                        ActivityFeed.create_activity(
                            activity_type=ActivityFeed.ActivityType.EVENT_REGISTRATION,
                            client=client,
                            event=event,
                            property_location=event.property_location,
                            is_public=is_public,
                            importance_level=importance,
                            activity_data={
                                'event_name': event.title,
                                'event_id': str(event.id),
                                'registration_id': str(registration.id),
                                'event_date': event.event_date.isoformat(),
                                'category': event.category.name if event.category else 'General'
                            }
                        )
                    print(f"Actividad de registro a evento creada para cliente {client.id}")
                except Exception as e:
                    print(f"Error creando actividad de registro a evento: {str(e)}")

                return Response({
                    'success': True,
                    'message': 'Registro exitoso al evento',
                    'registration_id': registration.id
                }, status=status.HTTP_201_CREATED)
            else:
                return Response({
                    'success': False,
                    'errors': serializer.errors
                }, status=status.HTTP_400_BAD_REQUEST)
                
        except Event.DoesNotExist:
            return Response({
                'success': False,
                'message': 'Evento no encontrado'
            }, status=status.HTTP_404_NOT_FOUND)
        except (InvalidToken, TokenError):
            return Response({
                'success': False,
                'message': 'Token inválido'
            }, status=status.HTTP_401_UNAUTHORIZED)
        except Exception as e:
            return Response({
                'success': False,
                'message': f'Error al registrarse: {str(e)}'
            }, status=status.HTTP_500_INTERNAL_SERVER_ERROR)
    
    def delete(self, request, event_id):
        """Cancelar registro de un evento"""
        try:
            # Autenticar cliente
            authenticator = ClientJWTAuthentication()
            auth_result = authenticator.authenticate(request)
            
            if auth_result is None:
                return Response({
                    'success': False,
                    'message': 'Token inválido'
                }, status=status.HTTP_401_UNAUTHORIZED)
            
            client, validated_token = auth_result
            
            registration = EventRegistration.objects.get(
                event_id=event_id,
                client=client,
                deleted=False
            )
            
            # Solo permitir cancelar si está aprobado o pendiente
            if registration.status in [EventRegistration.RegistrationStatus.APPROVED, 
                                     EventRegistration.RegistrationStatus.PENDING]:
                registration.status = EventRegistration.RegistrationStatus.CANCELLED
                registration.save()
                
                return Response({
                    'success': True,
                    'message': 'Registro cancelado exitosamente'
                })
            else:
                return Response({
                    'success': False,
                    'message': 'No puedes cancelar este registro'
                }, status=status.HTTP_400_BAD_REQUEST)
                
        except EventRegistration.DoesNotExist:
            return Response({
                'success': False,
                'message': 'No estás registrado en este evento'
            }, status=status.HTTP_404_NOT_FOUND)
        except (InvalidToken, TokenError):
            return Response({
                'success': False,
                'message': 'Token inválido'
            }, status=status.HTTP_401_UNAUTHORIZED)


class ClientEventRegistrationsView(APIView):
    """Lista de registros del cliente autenticado"""
    
    authentication_classes = [ClientJWTAuthentication]
    permission_classes = [AllowAny]
    
    def get(self, request):
        """Obtener registros del cliente autenticado"""
        try:
            # Autenticar cliente
            authenticator = ClientJWTAuthentication()
            auth_result = authenticator.authenticate(request)
            
            if auth_result is None:
                return Response({
                    'success': False,
                    'message': 'Token inválido'
                }, status=status.HTTP_401_UNAUTHORIZED)
            
            client, validated_token = auth_result
            
            # Obtener registros del cliente
            registrations = EventRegistration.objects.filter(
                client=client,
                deleted=False
            ).select_related('event', 'event__category').order_by('-registration_date')
            
            serializer = EventRegistrationSerializer(registrations, many=True)
            
            return Response({
                'success': True,
                'registrations': serializer.data
            })
            
        except (InvalidToken, TokenError):
            return Response({
                'success': False,
                'message': 'Token inválido'
            }, status=status.HTTP_401_UNAUTHORIZED)


# === ENDPOINT PARA VERIFICAR ELEGIBILIDAD ===

@api_view(['GET'])
@permission_classes([AllowAny])
@authentication_classes([])  # Deshabilita autenticación automática de DRF
def check_event_eligibility(request, event_id):
    """Verificar si el cliente puede registrarse a un evento específico"""
    try:
        # Autenticar cliente
        authenticator = ClientJWTAuthentication()
        auth_result = authenticator.authenticate(request)
        
        if auth_result is None:
            return Response({
                'success': False,
                'message': 'Token inválido'
            }, status=status.HTTP_401_UNAUTHORIZED)
        
        client, validated_token = auth_result
        
        event = Event.objects.get(
            id=event_id,
            deleted=False,
            is_active=True,
            status=Event.EventStatus.PUBLISHED
        )
        
        can_register, message = event.client_can_register(client)
        
        return Response({
            'event_id': event_id,
            'event_title': event.title,
            'can_register': can_register,
            'message': message,
            'client_requirements': {
                'current_points': float(client.points_balance),
                'required_points': float(event.min_points_required),
                'client_achievements': [
                    {'id': ach.achievement.id, 'name': ach.achievement.name} 
                    for ach in client.achievements.filter(deleted=False).select_related('achievement')
                ],
                'required_achievements': [
                    {'id': ach.id, 'name': ach.name}
                    for ach in event.required_achievements.all()
                ]
            }
        })
        
    except Event.DoesNotExist:
        return Response({
            'success': False,
            'message': 'Evento no encontrado'
        }, status=status.HTTP_404_NOT_FOUND)
    except (InvalidToken, TokenError):
        return Response({
            'success': False,
            'message': 'Token inválido'
        }, status=status.HTTP_401_UNAUTHORIZED)
    except Exception as e:
        return Response({
            'success': False,
            'message': f'Error interno: {str(e)}'
        }, status=status.HTTP_500_INTERNAL_SERVER_ERROR)


class EventParticipantsView(APIView):
    """Endpoint para mostrar participantes de un evento"""
    
    permission_classes = [AllowAny]  # Público para mostrar participantes
    
    def get(self, request, event_id):
        """
        GET /api/v1/events/{event_id}/participants/
        
        Muestra todos los participantes aprobados de un evento con:
        - Foto de perfil (prioriza Facebook, luego custom)
        - Nombre formateado (Augusto T.)
        - Nivel más alto con icono
        """
        try:
            # Obtener evento
            event = Event.objects.get(id=event_id, deleted=False)
            
            # Obtener solo participantes aprobados
            participants = EventRegistration.objects.filter(
                event=event,
                status=EventRegistration.RegistrationStatus.APPROVED,
                deleted=False
            ).select_related('client').prefetch_related(
                'client__achievements__achievement',
                'client__event_registrations'
            ).order_by('-registration_date')
            
            # Serializar datos
            serializer = EventParticipantSerializer(
                participants, 
                many=True, 
                context={'request': request}
            )
            
            return Response({
                'success': True,
                'event': {
                    'id': event.id,
                    'title': event.title,
                    'registered_users': participants.count(),
                    'max_allowed_users': event.max_participants,
                    'available_spots': event.available_spots,
                    'event_status': self._get_event_status(event)
                },
                'participants': serializer.data
            })
            
        except Event.DoesNotExist:
            return Response({
                'success': False,
                'message': 'Evento no encontrado'
            }, status=status.HTTP_404_NOT_FOUND)
        except Exception as e:
            return Response({
                'success': False,
                'message': f'Error interno: {str(e)}'
            }, status=status.HTTP_500_INTERNAL_SERVER_ERROR)
    
    def _get_event_status(self, event):
        """Helper para obtener el estado del evento"""
        from django.utils import timezone
        now = timezone.now()
        
        if event.event_date > now:
            return 'upcoming'  # Próximo
        else:
            return 'past'      # Pasado


# === FEED DE ACTIVIDADES DE CASA AUSTIN ===

class ActivityFeedPagination(PageNumberPagination):
    """Paginación personalizada para el feed de actividades"""
    page_size = 20
    page_size_query_param = 'page_size'
    max_page_size = 100


class ActivityFeedView(generics.ListAPIView):
    """
    Feed público de actividades de Casa Austin
    
    GET /api/v1/activity-feed/
    
    Query Parameters:
    - activity_type: Filtrar por tipo (points_earned, reservation_made, event_created, etc.)
    - client_id: Filtrar por cliente específico
    - importance_level: Filtrar por nivel de importancia (1-4)
    - date_from: Actividades desde fecha (YYYY-MM-DD)
    - date_to: Actividades hasta fecha (YYYY-MM-DD)
    - page: Número de página
    - page_size: Elementos por página (máx 100)
    """
    
    serializer_class = ActivityFeedSerializer
    permission_classes = [AllowAny]
    pagination_class = ActivityFeedPagination
    
    def get_queryset(self):
        """Obtener actividades con filtros aplicados"""
        
        # Base queryset - solo actividades públicas no eliminadas
        queryset = ActivityFeed.objects.filter(
            deleted=False,
            is_public=True
        ).select_related('client', 'event', 'property_location').order_by('-created')
        
        # Aplicar filtros de query parameters
        activity_type = self.request.GET.get('activity_type')
        if activity_type:
            queryset = queryset.filter(activity_type=activity_type)
        
        client_id = self.request.GET.get('client_id')
        if client_id:
            try:
                queryset = queryset.filter(client_id=client_id)
            except ValueError:
                # ID inválido, retornar queryset vacío
                return ActivityFeed.objects.none()
        
        importance_level = self.request.GET.get('importance_level')
        if importance_level:
            try:
                importance_level = int(importance_level)
                if 1 <= importance_level <= 4:
                    queryset = queryset.filter(importance_level=importance_level)
            except (ValueError, TypeError):
                pass
        
        date_from = self.request.GET.get('date_from')
        if date_from:
            try:
                from datetime import datetime
                date_from_parsed = datetime.fromisoformat(date_from)
                queryset = queryset.filter(created__gte=date_from_parsed)
            except ValueError:
                pass
        
        date_to = self.request.GET.get('date_to')
        if date_to:
            try:
                from datetime import datetime
                date_to_parsed = datetime.fromisoformat(date_to)
                queryset = queryset.filter(created__lte=date_to_parsed)
            except ValueError:
                pass
        
        return queryset
    
    def list(self, request, *args, **kwargs):
        """Override para formato de respuesta personalizado"""
        queryset = self.filter_queryset(self.get_queryset())
        
        page = self.paginate_queryset(queryset)
        if page is not None:
            serializer = self.get_serializer(page, many=True)
            response_data = self.get_paginated_response(serializer.data)
            
            # Agregar metadatos del feed
            response_data.data.update({
                'success': True,
                'feed_info': {
                    'total_activities': queryset.count(),
                    'filters_applied': self._get_applied_filters(),
                    'last_updated': timezone.now().isoformat(),
                }
            })
            
            return response_data
        
        serializer = self.get_serializer(queryset, many=True)
        return Response({
            'success': True,
            'results': serializer.data,
            'count': queryset.count(),
            'feed_info': {
                'total_activities': queryset.count(),
                'filters_applied': self._get_applied_filters(),
                'last_updated': timezone.now().isoformat(),
            }
        })
    
    def _get_applied_filters(self):
        """Helper para mostrar filtros aplicados en la respuesta"""
        filters = {}
        
        for param in ['activity_type', 'client_id', 'importance_level', 'date_from', 'date_to']:
            value = self.request.GET.get(param)
            if value:
                filters[param] = value
        
        return filters


class RecentActivitiesView(APIView):
    """
    Endpoint rápido para obtener las actividades más recientes
    
    GET /api/v1/activity-feed/recent/
    
    Query Parameters:
    - limit: Número de actividades a retornar (default: 10, max: 50)
    - activity_type: Filtrar por tipo específico
    """
    
    permission_classes = [AllowAny]
    
    def get(self, request):
        """Obtener las actividades más recientes"""
        try:
            # Parámetros
            limit = int(request.GET.get('limit', 10))
            if limit > 50:
                limit = 50
            
            activity_type = request.GET.get('activity_type')
            
            # Queryset base
            queryset = ActivityFeed.objects.filter(
                deleted=False,
                is_public=True
            ).select_related('client', 'event', 'property_location').order_by('-created')
            
            # Filtrar por tipo si se especifica
            if activity_type:
                queryset = queryset.filter(activity_type=activity_type)
            
            # Limitar resultados
            activities = queryset[:limit]
            
            # Serializar
            serializer = ActivityFeedSerializer(activities, many=True)
            
            return Response({
                'success': True,
                'activities': serializer.data,
                'count': len(activities),
                'limit_applied': limit,
                'last_updated': timezone.now().isoformat()
            })
            
        except Exception as e:
            return Response({
                'success': False,
                'message': f'Error obteniendo actividades recientes: {str(e)}'
            }, status=status.HTTP_500_INTERNAL_SERVER_ERROR)


class ActivityFeedStatsView(APIView):
    """
    Estadísticas del feed de actividades
    
    GET /api/v1/activity-feed/stats/
    """
    
    permission_classes = [AllowAny]
    
    def get(self, request):
        """Obtener estadísticas del feed de actividades"""
        try:
            from django.db.models import Count
            from datetime import datetime, timedelta
            
            now = timezone.now()
            
            # Estadísticas generales
            total_activities = ActivityFeed.objects.filter(deleted=False, is_public=True).count()
            
            # Actividades por tipo
            activities_by_type = ActivityFeed.objects.filter(
                deleted=False, 
                is_public=True
            ).values('activity_type').annotate(
                count=Count('id')
            ).order_by('-count')
            
            # Actividades de las últimas 24 horas
            yesterday = now - timedelta(days=1)
            recent_activities = ActivityFeed.objects.filter(
                deleted=False,
                is_public=True,
                created__gte=yesterday
            ).count()
            
            # Actividades de la última semana
            last_week = now - timedelta(days=7)
            weekly_activities = ActivityFeed.objects.filter(
                deleted=False,
                is_public=True,
                created__gte=last_week
            ).count()
            
            # Clientes más activos (último mes)
            last_month = now - timedelta(days=30)
            top_clients = ActivityFeed.objects.filter(
                deleted=False,
                is_public=True,
                created__gte=last_month,
                client__isnull=False
            ).values(
                'client__first_name', 'client__last_name', 'client_id'
            ).annotate(
                activity_count=Count('id')
            ).order_by('-activity_count')[:5]
            
            return Response({
                'success': True,
                'stats': {
                    'total_activities': total_activities,
                    'recent_24h': recent_activities,
                    'recent_week': weekly_activities,
                    'activities_by_type': [
                        {
                            'type': item['activity_type'],
                            'type_display': dict(ActivityFeed.ActivityType.choices).get(
                                item['activity_type'], item['activity_type']
                            ),
                            'count': item['count']
                        }
                        for item in activities_by_type
                    ],
                    'top_clients_month': [
                        {
                            'client_id': client['client_id'],
                            'name': f"{client['client__first_name']} {client['client__last_name'][0].upper() if client['client__last_name'] else ''}.",
                            'activity_count': client['activity_count']
                        }
                        for client in top_clients
                    ]
                },
                'generated_at': now.isoformat()
            })
            
        except Exception as e:
            return Response({
                'success': False,
                'message': f'Error obteniendo estadísticas: {str(e)}'
            }, status=status.HTTP_500_INTERNAL_SERVER_ERROR)


# === ENDPOINTS PARA ADMINISTRADORES (crear actividades manualmente) ===

class ActivityFeedCreateView(APIView):
    """
    Crear actividades manualmente (solo para administradores o sistema interno)
    
    POST /api/v1/activity-feed/create/
    
    SEGURIDAD: Requiere clave secreta del sistema para prevenir spam/manipulación
    """
    
    permission_classes = [AllowAny]  # Controlado por validación de clave secreta
    
    def post(self, request):
        """Crear nueva actividad en el feed"""
        try:
            # 🔐 VALIDACIÓN DE SEGURIDAD: Verificar clave secreta del sistema
            admin_key = request.headers.get('X-Admin-Key') or request.data.get('admin_key')
            expected_key = "casa_austin_feed_admin_2025"  # TODO: Mover a settings/environment
            
            if admin_key != expected_key:
                return Response({
                    'success': False,
                    'message': 'Acceso denegado: clave de administrador requerida'
                }, status=status.HTTP_401_UNAUTHORIZED)
            
            # Remover admin_key de los datos antes de validar
            request_data = request.data.copy()
            request_data.pop('admin_key', None)
            
            serializer = ActivityFeedCreateSerializer(data=request_data)
            if serializer.is_valid():
                activity = serializer.save()
                
                # Serializar respuesta
                response_serializer = ActivityFeedSerializer(activity)
                
                return Response({
                    'success': True,
                    'message': 'Actividad creada exitosamente',
                    'activity': response_serializer.data
                }, status=status.HTTP_201_CREATED)
            else:
                return Response({
                    'success': False,
                    'errors': serializer.errors
                }, status=status.HTTP_400_BAD_REQUEST)
                
        except Exception as e:
            return Response({
                'success': False,
                'message': f'Error creando actividad: {str(e)}'
            }, status=status.HTTP_500_INTERNAL_SERVER_ERROR)