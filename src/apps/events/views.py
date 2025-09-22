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
            status__in=['CONFIRMED', 'CHECKED_IN']
        ).count()
        
        event_data['spots_taken'] = spots_taken
        event_data['spots_available'] = max(0, event.max_participants - spots_taken)
        event_data['is_full'] = spots_taken >= event.max_participants
        
        return Response(event_data)


class EventParticipantsView(APIView):
    """Lista participantes de un evento (información pública limitada)"""
    permission_classes = [AllowAny]

    def get(self, request, event_id):
        event = get_object_or_404(Event, id=event_id)
        
        # Solo mostrar participantes confirmados con información limitada
        participants = EventRegistration.objects.filter(
            event=event,
            status='CONFIRMED'
        ).select_related('client')
        
        # Información limitada por privacidad
        participants_data = []
        for registration in participants:
            if registration.client:
                # Solo mostrar nombre y apellido inicial
                name = f"{registration.client.first_name} {registration.client.last_name[0]}." if registration.client.last_name else registration.client.first_name
                participants_data.append({
                    'participant_name': name,
                    'registration_date': registration.created.date(),
                    'status': registration.get_status_display()
                })
        
        return Response({
            'event_name': event.name,
            'total_participants': len(participants_data),
            'participants': participants_data
        })


# ==================== ENDPOINTS CON AUTENTICACIÓN ====================

class EventRegistrationView(APIView):
    """Registro de cliente a un evento"""
    authentication_classes = [ClientJWTAuthentication]
    permission_classes = [IsAuthenticated]

    def post(self, request, event_id):
        event = get_object_or_404(Event, id=event_id, is_active=True)
        client = request.user
        
        # Verificar si ya está registrado
        existing_registration = EventRegistration.objects.filter(
            event=event,
            client=client
        ).first()
        
        if existing_registration:
            return Response({
                'error': 'Ya estás registrado en este evento',
                'registration_id': existing_registration.id
            }, status=status.HTTP_400_BAD_REQUEST)
        
        # Verificar capacidad
        current_registrations = EventRegistration.objects.filter(
            event=event,
            status='CONFIRMED'
        ).count()
        
        if current_registrations >= event.max_participants:
            return Response({
                'error': 'El evento está lleno'
            }, status=status.HTTP_400_BAD_REQUEST)
        
        # Crear registro
        registration_data = {
            'event': event.id,
            'client': client.id,
            'status': 'CONFIRMED',
            'special_requests': request.data.get('special_requests', '')
        }
        
        serializer = EventRegistrationSerializer(data=registration_data)
        if serializer.is_valid():
            registration = serializer.save()
            
            # Log de actividad
            self._log_registration_activity(registration)
            
            return Response({
                'message': 'Registro exitoso',
                'registration': serializer.data
            }, status=status.HTTP_201_CREATED)
        
        return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)

    def _log_registration_activity(self, registration):
        """Registrar actividad de inscripción"""
        try:
            ActivityFeed.objects.create(
                activity_type='registration',
                title='Nueva inscripción a evento',
                description=f'{registration.client.first_name} se inscribió a {registration.event.name}',
                client=registration.client,
                metadata={
                    'event_id': str(registration.event.id),
                    'event_name': registration.event.name,
                    'registration_id': str(registration.id)
                }
            )
        except Exception as e:
            logger.error(f'Error logging registration activity: {e}')


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
    
    # Verificaciones
    is_registered = EventRegistration.objects.filter(
        event=event,
        client=client
    ).exists()
    
    current_registrations = EventRegistration.objects.filter(
        event=event,
        status='CONFIRMED'
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
                status__in=['approved']  # Solo reservas válidas usando el estado correcto
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
                'count': period_count,
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
                    'count': payment['count'],
                    'total_revenue': round(payment['total_revenue'] or 0, 2),
                    'percentage': round((payment['total_revenue'] or 0) / total_revenue * 100, 2) if total_revenue > 0 else 0
                })
        else:
            # Si no hay campo payment_method, devolver estructura básica
            payment_methods.append({
                'payment_method': 'Todos los métodos',
                'count': reservations.count(),
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
                'range': price_range['label'],
                'count': count,
                'percentage': round(count / reservations.count() * 100, 2) if reservations.count() > 0 else 0
            })
        
        return {
            'avg_total_cost': round(price_stats['avg_price_sol'] or 0, 2),
            'min_total_cost': round(price_stats['min_price_sol'] or 0, 2),
            'max_total_cost': round(price_stats['max_price_sol'] or 0, 2),
            'avg_price_per_night': round(avg_price_per_night, 2),
            'avg_nights_per_reservation': round(avg_nights, 1),
            'price_ranges': price_distribution
        }
    
    def _calculate_revenue_growth(self, current_reservations, date_from, date_to, period):
        """Calcular crecimiento de ingresos vs período anterior"""
        from django.db.models import Sum
        from datetime import timedelta
        
        # Calcular ingresos período actual
        current_revenue = current_reservations.aggregate(Sum('price_sol'))['price_sol__sum'] or 0
        current_count = current_reservations.count()
        
        # Calcular período anterior (mismo rango de días)
        period_days = (date_to - date_from).days
        previous_date_to = date_from - timedelta(days=1)
        previous_date_from = previous_date_to - timedelta(days=period_days)
        
        from apps.reservation.models import Reservation
        previous_reservations = Reservation.objects.filter(
            check_in_date__gte=previous_date_from,
            check_in_date__lte=previous_date_to,
            status__in=['approved']  # Usar el estado correcto del modelo
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
            'previous_period_reservations': previous_count
        }