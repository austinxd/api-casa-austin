from django.utils import timezone
from rest_framework import generics, status
from rest_framework.decorators import api_view, permission_classes, authentication_classes
from rest_framework.permissions import AllowAny
from rest_framework.response import Response
from rest_framework.views import APIView
from rest_framework.pagination import PageNumberPagination
from rest_framework_simplejwt.exceptions import InvalidToken, TokenError
from django.db.models import Q, Count, Sum, Avg
from django.db.models.functions import TruncDate, TruncMonth, TruncWeek
from datetime import datetime, timedelta

from apps.clients.models import Clients, SearchTracking
from apps.clients.auth_views import ClientJWTAuthentication
from .models import EventCategory, Event, EventRegistration, ActivityFeed, ActivityFeedConfig
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
    
    def get_queryset(self):
        return Event.objects.filter(
            deleted=False,
            is_active=True,
            is_public=True,
            status=Event.EventStatus.PUBLISHED
        ).select_related('category')


class EventParticipantsView(generics.ListAPIView):
    """Lista de participantes de un evento específico"""
    
    serializer_class = EventParticipantSerializer
    permission_classes = [AllowAny]
    
    def get_queryset(self):
        event_id = self.kwargs.get('event_id')
        
        # Verificar que el evento sea público
        event = Event.objects.filter(
            id=event_id,
            deleted=False,
            is_active=True,
            is_public=True
        ).first()
        
        if not event:
            return EventRegistration.objects.none()
        
        # Retornar solo los registros aprobados y ganadores
        return EventRegistration.objects.filter(
            event_id=event_id,
            status__in=[
                EventRegistration.RegistrationStatus.APPROVED,
                EventRegistration.RegistrationStatus.WINNER
            ]
        ).select_related('client', 'event').order_by('-registration_date')


# === ENDPOINTS CON AUTENTICACIÓN DE CLIENTE ===

class EventRegistrationView(APIView):
    """Vista para registrarse a un evento"""
    
    authentication_classes = [ClientJWTAuthentication]
    permission_classes = [AllowAny]  # La autenticación es opcional pero se verifica
    
    def post(self, request, event_id):
        """Registrar cliente a un evento"""
        
        # Intentar autenticar al cliente
        authenticator = ClientJWTAuthentication()
        try:
            user, validated_token = authenticator.authenticate(request)
        except (InvalidToken, TokenError):
            return Response({'error': 'Token de autenticación inválido'}, status=401)
        
        if not user:
            return Response({'error': 'Token de autenticación inválido'}, status=401)
        
        # Verificar que el evento existe y esté activo
        try:
            event = Event.objects.get(
                id=event_id,
                deleted=False,
                is_active=True,
                is_public=True,
                status=Event.EventStatus.PUBLISHED
            )
        except Event.DoesNotExist:
            return Response({'error': 'Evento no encontrado o no disponible'}, status=404)
        
        # Verificar que el evento no haya pasado su deadline
        if timezone.now() > event.registration_deadline:
            return Response({'error': 'La fecha límite de registro ha pasado'}, status=400)
        
        # Verificar si el cliente ya está registrado
        existing_registration = EventRegistration.objects.filter(
            event=event,
            client=user
        ).first()
        
        if existing_registration:
            return Response({
                'error': 'Ya estás registrado en este evento',
                'registration': EventRegistrationSerializer(existing_registration).data
            }, status=400)
        
        # Verificar límite de participantes
        if event.max_participants:
            current_count = EventRegistration.objects.filter(
                event=event,
                status__in=[
                    EventRegistration.RegistrationStatus.PENDING,
                    EventRegistration.RegistrationStatus.APPROVED
                ]
            ).count()
            
            if current_count >= event.max_participants:
                return Response({'error': 'El evento ha alcanzado el máximo de participantes'}, status=400)
        
        # Verificar restricciones del evento
        eligibility_error = self._check_event_eligibility(event, user)
        if eligibility_error:
            return Response({'error': eligibility_error}, status=400)
        
        # Crear el registro
        registration_data = {
            'event': event.id,
            'client': user.id,
            'status': EventRegistration.RegistrationStatus.PENDING
        }
        
        serializer = EventRegistrationCreateSerializer(data=registration_data)
        if serializer.is_valid():
            registration = serializer.save()
            
            return Response({
                'success': True,
                'message': 'Te has registrado exitosamente al evento',
                'registration': EventRegistrationSerializer(registration).data
            }, status=status.HTTP_201_CREATED)
        
        return Response({
            'error': 'Error al procesar el registro',
            'details': serializer.errors
        }, status=400)
    
    def _check_event_eligibility(self, event, client):
        """Verificar si el cliente es elegible para el evento"""
        
        # Verificar puntos mínimos
        if event.min_points_required and client.points_balance < event.min_points_required:
            return f"Necesitas al menos {event.min_points_required} puntos para registrarte a este evento"
        
        # Verificar logros requeridos
        if event.required_achievements.exists():
            client_achievements = client.achievements.values_list('id', flat=True)
            required_achievements = event.required_achievements.values_list('id', flat=True)
            
            # El cliente debe tener AL MENOS UNO de los logros requeridos
            if not any(achievement_id in client_achievements for achievement_id in required_achievements):
                required_names = event.required_achievements.values_list('name', flat=True)
                return f"Necesitas tener uno de estos logros para registrarte: {', '.join(required_names)}"
        
        return None


class ClientEventRegistrationsView(generics.ListAPIView):
    """Lista de registros de eventos del cliente autenticado"""
    
    serializer_class = EventRegistrationSerializer
    authentication_classes = [ClientJWTAuthentication]
    permission_classes = [AllowAny]
    
    def get_queryset(self):
        # Autenticar cliente
        authenticator = ClientJWTAuthentication()
        try:
            user, validated_token = authenticator.authenticate(self.request)
        except (InvalidToken, TokenError):
            return EventRegistration.objects.none()
        
        if not user:
            return EventRegistration.objects.none()
        
        return EventRegistration.objects.filter(
            client=user
        ).select_related('event', 'event__category').order_by('-registration_date')


@api_view(['GET'])
@authentication_classes([ClientJWTAuthentication])
@permission_classes([AllowAny])
def check_event_eligibility(request, event_id):
    """Verificar elegibilidad del cliente para un evento"""
    
    # Autenticar cliente
    authenticator = ClientJWTAuthentication()
    try:
        user, validated_token = authenticator.authenticate(request)
    except (InvalidToken, TokenError):
        return Response({'error': 'Token de autenticación inválido'}, status=401)
    
    if not user:
        return Response({'error': 'Token de autenticación inválido'}, status=401)
    
    # Verificar que el evento existe
    try:
        event = Event.objects.get(
            id=event_id,
            deleted=False,
            is_active=True,
            is_public=True,
            status=Event.EventStatus.PUBLISHED
        )
    except Event.DoesNotExist:
        return Response({'error': 'Evento no encontrado'}, status=404)
    
    # Verificar elegibilidad
    eligibility_check = {
        'eligible': True,
        'reasons': []
    }
    
    # Verificar si ya está registrado
    existing_registration = EventRegistration.objects.filter(
        event=event,
        client=user
    ).first()
    
    if existing_registration:
        eligibility_check['eligible'] = False
        eligibility_check['reasons'].append('Ya estás registrado en este evento')
        eligibility_check['existing_registration'] = EventRegistrationSerializer(existing_registration).data
    
    # Verificar deadline
    if timezone.now() > event.registration_deadline:
        eligibility_check['eligible'] = False
        eligibility_check['reasons'].append('La fecha límite de registro ha pasado')
    
    # Verificar límite de participantes
    if event.max_participants:
        current_count = EventRegistration.objects.filter(
            event=event,
            status__in=[
                EventRegistration.RegistrationStatus.PENDING,
                EventRegistration.RegistrationStatus.APPROVED
            ]
        ).count()
        
        if current_count >= event.max_participants:
            eligibility_check['eligible'] = False
            eligibility_check['reasons'].append('El evento ha alcanzado el máximo de participantes')
    
    # Verificar puntos mínimos
    if event.min_points_required and user.points_balance < event.min_points_required:
        eligibility_check['eligible'] = False
        eligibility_check['reasons'].append(f"Necesitas al menos {event.min_points_required} puntos")
    
    # Verificar logros requeridos
    if event.required_achievements.exists():
        user_achievements = user.achievements.values_list('id', flat=True)
        required_achievements = event.required_achievements.values_list('id', flat=True)
        
        if not any(achievement_id in user_achievements for achievement_id in required_achievements):
            required_names = event.required_achievements.values_list('name', flat=True)
            eligibility_check['eligible'] = False
            eligibility_check['reasons'].append(f"Necesitas uno de estos logros: {', '.join(required_names)}")
    
    return Response({
        'event_id': str(event.id),
        'event_title': event.title,
        'eligibility': eligibility_check
    })


# === ACTIVITY FEED ENDPOINTS ===

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
        from .models import ActivityFeedConfig
        
        # Base queryset - solo actividades públicas no eliminadas
        queryset = ActivityFeed.objects.filter(
            deleted=False,
            is_public=True
        ).select_related('client', 'event', 'property_location').order_by('-created')
        
        # ✅ FILTRAR POR ACTIVIDADES HABILITADAS EN CONFIG
        # Obtener todos los tipos de actividad deshabilitados
        disabled_types = ActivityFeedConfig.objects.filter(
            is_enabled=False
        ).values_list('activity_type', flat=True)
        
        # Excluir actividades de tipos deshabilitados
        if disabled_types:
            queryset = queryset.exclude(activity_type__in=disabled_types)
        
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
        """Obtener información de filtros aplicados"""
        filters = {}
        
        if self.request.GET.get('activity_type'):
            filters['activity_type'] = self.request.GET.get('activity_type')
        
        if self.request.GET.get('client_id'):
            filters['client_id'] = self.request.GET.get('client_id')
        
        if self.request.GET.get('importance_level'):
            filters['importance_level'] = self.request.GET.get('importance_level')
        
        if self.request.GET.get('date_from'):
            filters['date_from'] = self.request.GET.get('date_from')
        
        if self.request.GET.get('date_to'):
            filters['date_to'] = self.request.GET.get('date_to')
        
        return filters


class RecentActivitiesView(generics.ListAPIView):
    """Actividades más recientes - versión compacta para widgets"""
    
    serializer_class = ActivityFeedSerializer
    permission_classes = [AllowAny]
    
    def get_queryset(self):
        from .models import ActivityFeedConfig
        
        # Obtener tipos deshabilitados
        disabled_types = ActivityFeedConfig.objects.filter(
            is_enabled=False
        ).values_list('activity_type', flat=True)
        
        queryset = ActivityFeed.objects.filter(
            deleted=False,
            is_public=True
        ).select_related('client', 'event', 'property_location').order_by('-created')
        
        # Excluir tipos deshabilitados
        if disabled_types:
            queryset = queryset.exclude(activity_type__in=disabled_types)
        
        return queryset[:10]  # Solo las 10 más recientes
    
    def list(self, request, *args, **kwargs):
        """Override para respuesta simplificada"""
        queryset = self.get_queryset()
        serializer = self.get_serializer(queryset, many=True)
        
        return Response({
            'success': True,
            'results': serializer.data,
            'count': len(serializer.data),
            'last_updated': timezone.now().isoformat(),
        })


class ComprehensiveStatsView(APIView):
    """
    📊 ENDPOINT COMPREHENSIVO DE ESTADÍSTICAS PARA GRÁFICAS
    
    GET /api/v1/stats/
    
    Query Parameters:
    - period: 'day', 'week', 'month' (default: 'month')
    - days_back: número de días hacia atrás (default: 30)
    - date_from: fecha inicio (YYYY-MM-DD)
    - date_to: fecha fin (YYYY-MM-DD)
    - include_anonymous: incluir datos anónimos (default: true)
    
    Retorna estadísticas comprehensivas para gráficas:
    - Search Analytics (búsquedas por cliente vs IP)
    - Activity Analytics (por tipo, temporales)
    - Client Analytics (nuevos clientes, más activos)
    - Property Analytics (más buscadas)
    """
    
    permission_classes = [AllowAny]
    
    def get(self, request):
        """Obtener estadísticas comprehensivas"""
        
        # Parámetros de query
        period = request.GET.get('period', 'month')  # day, week, month
        days_back = int(request.GET.get('days_back', 30))
        include_anonymous = request.GET.get('include_anonymous', 'true').lower() == 'true'
        
        # Calcular fechas
        end_date = timezone.now()
        
        date_from = request.GET.get('date_from')
        date_to = request.GET.get('date_to')
        
        if date_from and date_to:
            try:
                start_date = datetime.fromisoformat(date_from)
                end_date = datetime.fromisoformat(date_to)
            except ValueError:
                return Response({'error': 'Formato de fecha inválido. Usar YYYY-MM-DD'}, status=400)
        else:
            start_date = end_date - timedelta(days=days_back)
        
        # Determinar función de truncado temporal
        if period == 'day':
            trunc_func = TruncDate
        elif period == 'week':
            trunc_func = TruncWeek
        else:  # month
            trunc_func = TruncMonth
        
        stats = {
            'period_info': {
                'period': period,
                'start_date': start_date.isoformat(),
                'end_date': end_date.isoformat(),
                'days_analyzed': (end_date - start_date).days
            },
            'search_analytics': self._get_search_analytics(start_date, end_date, trunc_func, include_anonymous),
            'activity_analytics': self._get_activity_analytics(start_date, end_date, trunc_func),
            'client_analytics': self._get_client_analytics(start_date, end_date, trunc_func),
            'property_analytics': self._get_property_analytics(start_date, end_date),
            'summary': {}
        }
        
        # Generar resumen
        stats['summary'] = self._generate_summary(stats)
        
        return Response({
            'success': True,
            'stats': stats,
            'generated_at': timezone.now().isoformat()
        })
    
    def _get_search_analytics(self, start_date, end_date, trunc_func, include_anonymous):
        """Análisis de búsquedas con desglose por clientes vs anónimos"""
        
        # Base queryset
        searches = SearchTracking.objects.filter(
            search_timestamp__gte=start_date,
            search_timestamp__lte=end_date
        )
        
        # 1. Total de búsquedas por período
        searches_by_period = searches.annotate(
            period=trunc_func('search_timestamp')
        ).values('period').annotate(
            total_searches=Count('id'),
            client_searches=Count('id', filter=Q(client__isnull=False)),
            anonymous_searches=Count('id', filter=Q(client__isnull=True))
        ).order_by('period')
        
        # 2. Búsquedas por tipo de usuario (cliente vs anónimo)
        user_type_stats = {
            'client_searches': searches.filter(client__isnull=False).count(),
            'anonymous_searches': searches.filter(client__isnull=True).count()
        }
        
        # 3. IPs únicas para búsquedas anónimas
        unique_ips = searches.filter(
            client__isnull=True,
            ip_address__isnull=False
        ).values('ip_address').distinct().count()
        
        # 4. Clientes únicos que buscaron
        unique_clients = searches.filter(
            client__isnull=False
        ).values('client').distinct().count()
        
        # 5. Propiedades más buscadas
        property_searches = searches.filter(
            property__isnull=False
        ).values(
            'property__name'
        ).annotate(
            search_count=Count('id')
        ).order_by('-search_count')[:10]
        
        # 6. Número de huéspedes más común
        guests_stats = searches.values('guests').annotate(
            count=Count('id')
        ).order_by('-count')[:5]
        
        # 7. Patrones de fechas más buscadas (día de la semana)
        day_patterns = searches.annotate(
            weekday=TruncDate('check_in_date')
        ).values('weekday').annotate(
            search_count=Count('id')
        ).order_by('-search_count')[:10]
        
        # 8. Top clientes que más buscan
        top_searching_clients = searches.filter(
            client__isnull=False
        ).values(
            'client__first_name', 
            'client__last_name'
        ).annotate(
            search_count=Count('id')
        ).order_by('-search_count')[:10]
        
        return {
            'searches_by_period': list(searches_by_period),
            'user_type_breakdown': user_type_stats,
            'unique_anonymous_ips': unique_ips,
            'unique_searching_clients': unique_clients,
            'most_searched_properties': list(property_searches),
            'guest_count_patterns': list(guests_stats),
            'popular_checkin_dates': list(day_patterns),
            'top_searching_clients': list(top_searching_clients)
        }
    
    def _get_activity_analytics(self, start_date, end_date, trunc_func):
        """Análisis de actividades del feed"""
        
        # Base queryset (solo actividades habilitadas)
        disabled_types = ActivityFeedConfig.objects.filter(
            is_enabled=False
        ).values_list('activity_type', flat=True)
        
        activities = ActivityFeed.objects.filter(
            created__gte=start_date,
            created__lte=end_date,
            deleted=False
        )
        
        if disabled_types:
            activities = activities.exclude(activity_type__in=disabled_types)
        
        # 1. Actividades por período
        activities_by_period = activities.annotate(
            period=trunc_func('created')
        ).values('period').annotate(
            total_activities=Count('id')
        ).order_by('period')
        
        # 2. Actividades por tipo
        activities_by_type = activities.values(
            'activity_type'
        ).annotate(
            count=Count('id')
        ).order_by('-count')
        
        # 3. Clientes más activos
        most_active_clients = activities.filter(
            client__isnull=False
        ).values(
            'client__first_name',
            'client__last_name'
        ).annotate(
            activity_count=Count('id')
        ).order_by('-activity_count')[:10]
        
        # 4. Actividades por importancia
        importance_breakdown = activities.values('importance_level').annotate(
            count=Count('id')
        ).order_by('importance_level')
        
        return {
            'activities_by_period': list(activities_by_period),
            'activities_by_type': list(activities_by_type),
            'most_active_clients': list(most_active_clients),
            'importance_breakdown': list(importance_breakdown)
        }
    
    def _get_client_analytics(self, start_date, end_date, trunc_func):
        """Análisis de clientes"""
        
        # 1. Nuevos clientes por período
        new_clients = Clients.objects.filter(
            created__gte=start_date,
            created__lte=end_date,
            deleted=False
        ).annotate(
            period=trunc_func('created')
        ).values('period').annotate(
            new_clients=Count('id')
        ).order_by('period')
        
        # 2. Total de clientes activos
        total_clients = Clients.objects.filter(deleted=False).count()
        
        # 3. Clientes con más puntos
        top_clients_by_points = Clients.objects.filter(
            deleted=False
        ).order_by('-points_balance')[:10].values(
            'first_name', 'last_name', 'points_balance'
        )
        
        return {
            'new_clients_by_period': list(new_clients),
            'total_active_clients': total_clients,
            'top_clients_by_points': list(top_clients_by_points)
        }
    
    def _get_property_analytics(self, start_date, end_date):
        """Análisis de propiedades"""
        
        # Propiedades más mencionadas en actividades
        property_mentions = ActivityFeed.objects.filter(
            created__gte=start_date,
            created__lte=end_date,
            property_location__isnull=False,
            deleted=False
        ).values(
            'property_location__name'
        ).annotate(
            mentions=Count('id')
        ).order_by('-mentions')[:10]
        
        return {
            'most_mentioned_properties': list(property_mentions)
        }
    
    def _generate_summary(self, stats):
        """Generar resumen de estadísticas clave"""
        
        search_analytics = stats['search_analytics']
        activity_analytics = stats['activity_analytics']
        client_analytics = stats['client_analytics']
        
        total_searches = (search_analytics['user_type_breakdown']['client_searches'] + 
                         search_analytics['user_type_breakdown']['anonymous_searches'])
        
        total_activities = sum(item['count'] for item in activity_analytics['activities_by_type'])
        
        return {
            'total_searches': total_searches,
            'total_activities': total_activities,
            'unique_searchers': (search_analytics['unique_searching_clients'] + 
                               search_analytics['unique_anonymous_ips']),
            'new_clients': sum(item['new_clients'] for item in client_analytics['new_clients_by_period']),
            'top_activity_type': (activity_analytics['activities_by_type'][0]['activity_type'] 
                                if activity_analytics['activities_by_type'] else None),
            'most_searched_property': (search_analytics['most_searched_properties'][0]['property__name'] 
                                     if search_analytics['most_searched_properties'] else None)
        }


class ActivityFeedStatsView(APIView):
    """Estadísticas básicas del Activity Feed"""
    
    permission_classes = [AllowAny]
    
    def get(self, request):
        """Estadísticas básicas del feed de actividades"""
        
        # Actividades habilitadas
        disabled_types = ActivityFeedConfig.objects.filter(
            is_enabled=False
        ).values_list('activity_type', flat=True)
        
        activities = ActivityFeed.objects.filter(
            deleted=False,
            is_public=True
        )
        
        if disabled_types:
            activities = activities.exclude(activity_type__in=disabled_types)
        
        # Estadísticas básicas
        total_activities = activities.count()
        
        # Por tipo
        by_type = activities.values('activity_type').annotate(
            count=Count('id')
        ).order_by('-count')
        
        # Por importancia
        by_importance = activities.values('importance_level').annotate(
            count=Count('id')
        ).order_by('importance_level')
        
        # Actividades recientes (últimos 7 días)
        week_ago = timezone.now() - timedelta(days=7)
        recent_count = activities.filter(created__gte=week_ago).count()
        
        return Response({
            'success': True,
            'stats': {
                'total_activities': total_activities,
                'recent_activities_7_days': recent_count,
                'by_activity_type': list(by_type),
                'by_importance_level': list(by_importance),
                'generated_at': timezone.now().isoformat()
            }
        })


class ActivityFeedCreateView(generics.CreateAPIView):
    """Crear nueva actividad en el feed (para uso interno/admin)"""
    
    serializer_class = ActivityFeedCreateSerializer
    permission_classes = [AllowAny]  # Cambiar según necesidades de seguridad
    
    def create(self, request, *args, **kwargs):
        """Override para respuesta personalizada"""
        serializer = self.get_serializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        
        activity = serializer.save()
        
        response_serializer = ActivityFeedSerializer(activity)
        
        return Response({
            'success': True,
            'message': 'Actividad creada exitosamente',
            'activity': response_serializer.data
        }, status=status.HTTP_201_CREATED)


class ComprehensiveStatsView(APIView):
    """
    📊 ENDPOINT COMPREHENSIVO DE ESTADÍSTICAS PARA GRÁFICAS
    
    GET /api/v1/stats/
    
    Query Parameters:
    - period: 'day', 'week', 'month' (default: 'month')
    - days_back: número de días hacia atrás (default: 30)
    - date_from: fecha inicio (YYYY-MM-DD)
    - date_to: fecha fin (YYYY-MM-DD)
    - include_anonymous: incluir datos anónimos (default: true)
    
    Retorna estadísticas comprehensivas para gráficas:
    - Search Analytics (búsquedas por cliente vs IP)
    - Activity Analytics (por tipo, temporales)
    - Client Analytics (nuevos clientes, más activos)
    - Property Analytics (más buscadas)
    """
    
    permission_classes = [AllowAny]
    
    def get(self, request):
        """Obtener estadísticas comprehensivas"""
        
        # Parámetros de query
        period = request.GET.get('period', 'month')  # day, week, month
        days_back = int(request.GET.get('days_back', 30))
        include_anonymous = request.GET.get('include_anonymous', 'true').lower() == 'true'
        
        # Calcular fechas
        end_date = timezone.now()
        
        date_from = request.GET.get('date_from')
        date_to = request.GET.get('date_to')
        
        if date_from and date_to:
            try:
                start_date = datetime.fromisoformat(date_from)
                end_date = datetime.fromisoformat(date_to)
            except ValueError:
                return Response({'error': 'Formato de fecha inválido. Usar YYYY-MM-DD'}, status=400)
        else:
            start_date = end_date - timedelta(days=days_back)
        
        # Determinar función de truncado temporal
        if period == 'day':
            trunc_func = TruncDate
        elif period == 'week':
            trunc_func = TruncWeek
        else:  # month
            trunc_func = TruncMonth
        
        stats = {
            'period_info': {
                'period': period,
                'start_date': start_date.isoformat(),
                'end_date': end_date.isoformat(),
                'days_analyzed': (end_date - start_date).days
            },
            'search_analytics': self._get_search_analytics(start_date, end_date, trunc_func, include_anonymous),
            'activity_analytics': self._get_activity_analytics(start_date, end_date, trunc_func),
            'client_analytics': self._get_client_analytics(start_date, end_date, trunc_func),
            'property_analytics': self._get_property_analytics(start_date, end_date),
            'summary': {}
        }
        
        # Generar resumen
        stats['summary'] = self._generate_summary(stats)
        
        return Response({
            'success': True,
            'stats': stats,
            'generated_at': timezone.now().isoformat()
        })
    
    def _get_search_analytics(self, start_date, end_date, trunc_func, include_anonymous):
        """Análisis de búsquedas con desglose por clientes vs anónimos"""
        
        # Base queryset
        searches = SearchTracking.objects.filter(
            search_timestamp__gte=start_date,
            search_timestamp__lte=end_date
        )
        
        # 1. Total de búsquedas por período
        searches_by_period = searches.annotate(
            period=trunc_func('search_timestamp')
        ).values('period').annotate(
            total_searches=Count('id'),
            client_searches=Count('id', filter=Q(client__isnull=False)),
            anonymous_searches=Count('id', filter=Q(client__isnull=True))
        ).order_by('period')
        
        # 2. Búsquedas por tipo de usuario (cliente vs anónimo)
        user_type_stats = {
            'client_searches': searches.filter(client__isnull=False).count(),
            'anonymous_searches': searches.filter(client__isnull=True).count()
        }
        
        # 3. IPs únicas para búsquedas anónimas
        unique_ips = searches.filter(
            client__isnull=True,
            ip_address__isnull=False
        ).values('ip_address').distinct().count()
        
        # 4. Clientes únicos que buscaron
        unique_clients = searches.filter(
            client__isnull=False
        ).values('client').distinct().count()
        
        # 5. Propiedades más buscadas
        property_searches = searches.filter(
            property__isnull=False
        ).values(
            'property__name'
        ).annotate(
            search_count=Count('id')
        ).order_by('-search_count')[:10]
        
        # 6. Número de huéspedes más común
        guests_stats = searches.values('guests').annotate(
            count=Count('id')
        ).order_by('-count')[:5]
        
        # 7. Patrones de fechas más buscadas (día de la semana)
        day_patterns = searches.annotate(
            weekday=TruncDate('check_in_date')
        ).values('weekday').annotate(
            search_count=Count('id')
        ).order_by('-search_count')[:10]
        
        # 8. Top clientes que más buscan
        top_searching_clients = searches.filter(
            client__isnull=False
        ).values(
            'client__first_name', 
            'client__last_name'
        ).annotate(
            search_count=Count('id')
        ).order_by('-search_count')[:10]
        
        return {
            'searches_by_period': list(searches_by_period),
            'user_type_breakdown': user_type_stats,
            'unique_anonymous_ips': unique_ips,
            'unique_searching_clients': unique_clients,
            'most_searched_properties': list(property_searches),
            'guest_count_patterns': list(guests_stats),
            'popular_checkin_dates': list(day_patterns),
            'top_searching_clients': list(top_searching_clients)
        }
    
    def _get_activity_analytics(self, start_date, end_date, trunc_func):
        """Análisis de actividades del feed"""
        
        # Base queryset (solo actividades habilitadas)
        disabled_types = ActivityFeedConfig.objects.filter(
            is_enabled=False
        ).values_list('activity_type', flat=True)
        
        activities = ActivityFeed.objects.filter(
            created__gte=start_date,
            created__lte=end_date,
            deleted=False
        )
        
        if disabled_types:
            activities = activities.exclude(activity_type__in=disabled_types)
        
        # 1. Actividades por período
        activities_by_period = activities.annotate(
            period=trunc_func('created')
        ).values('period').annotate(
            total_activities=Count('id')
        ).order_by('period')
        
        # 2. Actividades por tipo
        activities_by_type = activities.values(
            'activity_type'
        ).annotate(
            count=Count('id')
        ).order_by('-count')
        
        # 3. Clientes más activos
        most_active_clients = activities.filter(
            client__isnull=False
        ).values(
            'client__first_name',
            'client__last_name'
        ).annotate(
            activity_count=Count('id')
        ).order_by('-activity_count')[:10]
        
        # 4. Actividades por importancia
        importance_breakdown = activities.values('importance_level').annotate(
            count=Count('id')
        ).order_by('importance_level')
        
        return {
            'activities_by_period': list(activities_by_period),
            'activities_by_type': list(activities_by_type),
            'most_active_clients': list(most_active_clients),
            'importance_breakdown': list(importance_breakdown)
        }
    
    def _get_client_analytics(self, start_date, end_date, trunc_func):
        """Análisis de clientes"""
        
        # 1. Nuevos clientes por período
        new_clients = Clients.objects.filter(
            created__gte=start_date,
            created__lte=end_date,
            deleted=False
        ).annotate(
            period=trunc_func('created')
        ).values('period').annotate(
            new_clients=Count('id')
        ).order_by('period')
        
        # 2. Total de clientes activos
        total_clients = Clients.objects.filter(deleted=False).count()
        
        # 3. Clientes con más puntos
        top_clients_by_points = Clients.objects.filter(
            deleted=False
        ).order_by('-points_balance')[:10].values(
            'first_name', 'last_name', 'points_balance'
        )
        
        return {
            'new_clients_by_period': list(new_clients),
            'total_active_clients': total_clients,
            'top_clients_by_points': list(top_clients_by_points)
        }
    
    def _get_property_analytics(self, start_date, end_date):
        """Análisis de propiedades"""
        
        # Propiedades más mencionadas en actividades
        property_mentions = ActivityFeed.objects.filter(
            created__gte=start_date,
            created__lte=end_date,
            property_location__isnull=False,
            deleted=False
        ).values(
            'property_location__name'
        ).annotate(
            mentions=Count('id')
        ).order_by('-mentions')[:10]
        
        return {
            'most_mentioned_properties': list(property_mentions)
        }
    
    def _generate_summary(self, stats):
        """Generar resumen de estadísticas clave"""
        
        search_analytics = stats['search_analytics']
        activity_analytics = stats['activity_analytics']
        client_analytics = stats['client_analytics']
        
        total_searches = (search_analytics['user_type_breakdown']['client_searches'] + 
                         search_analytics['user_type_breakdown']['anonymous_searches'])
        
        total_activities = sum(item['count'] for item in activity_analytics['activities_by_type'])
        
        return {
            'total_searches': total_searches,
            'total_activities': total_activities,
            'unique_searchers': (search_analytics['unique_searching_clients'] + 
                               search_analytics['unique_anonymous_ips']),
            'new_clients': sum(item['new_clients'] for item in client_analytics['new_clients_by_period']),
            'top_activity_type': (activity_analytics['activities_by_type'][0]['activity_type'] 
                                if activity_analytics['activities_by_type'] else None),
            'most_searched_property': (search_analytics['most_searched_properties'][0]['property__name'] 
                                     if search_analytics['most_searched_properties'] else None)
        }