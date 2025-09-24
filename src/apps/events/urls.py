from django.urls import path
from .views import (
    # Endpoints públicos
    PublicEventCategoryListView,
    PublicEventListView,
    PastEventsView,
    ComingEventsView,
    PublicEventDetailView,
    EventParticipantsView,
    EventWinnersView,
    
    # Endpoints con autenticación
    EventRegistrationView,
    EventUploadEvidenceView,
    EventCancelRegistrationView,
    ClientEventRegistrationsView,
    check_event_eligibility,
    
    # Activity Feed endpoints
    ActivityFeedView,
    RecentActivitiesView,
    ActivityFeedStatsView,
    ActivityFeedCreateView,
    
    # Analytics endpoints
    UpcomingCheckinsView,
    SearchTrackingStatsView,
    IngresosStatsView,
)

app_name = 'events'

urlpatterns = [
    # === ENDPOINTS PÚBLICOS (sin autenticación) ===
    path('categories/', PublicEventCategoryListView.as_view(), name='public-categories'),
    path('', PublicEventListView.as_view(), name='public-event-list'),
    path('past/', PastEventsView.as_view(), name='past-events'),
    path('coming/', ComingEventsView.as_view(), name='coming-events'), 
    path('<uuid:id>/', PublicEventDetailView.as_view(), name='public-event-detail'),
    path('<uuid:event_id>/participants/', EventParticipantsView.as_view(), name='event-participants'),
    path('<uuid:event_id>/participants/winners/', EventWinnersView.as_view(), name='event-winners'),
    
    # === ENDPOINTS CON AUTENTICACIÓN DE CLIENTE ===
    path('<uuid:event_id>/register/', EventRegistrationView.as_view(), name='event-register'),
    path('<uuid:event_id>/upload-evidence/', EventUploadEvidenceView.as_view(), name='event-upload-evidence'),
    path('<uuid:event_id>/cancel/', EventCancelRegistrationView.as_view(), name='event-cancel'),
    path('my-registrations/', ClientEventRegistrationsView.as_view(), name='my-registrations'),
    path('<uuid:event_id>/check-eligibility/', check_event_eligibility, name='check-eligibility'),
    
    # === ACTIVITY FEED ENDPOINTS ===
    path('activity-feed/', ActivityFeedView.as_view(), name='activity-feed'),
    path('activity-feed/recent/', RecentActivitiesView.as_view(), name='activity-feed-recent'),
    path('activity-feed/stats/', ActivityFeedStatsView.as_view(), name='activity-feed-stats'),
    path('activity-feed/create/', ActivityFeedCreateView.as_view(), name='activity-feed-create'),
    
    # === ANALYTICS ENDPOINTS ===
    path('upcoming-checkins/', UpcomingCheckinsView.as_view(), name='upcoming-checkins'),
    path('stats/search-tracking/', SearchTrackingStatsView.as_view(), name='stats-search-tracking'),
    path('stats/ingresos/', IngresosStatsView.as_view(), name='stats-ingresos'),
]