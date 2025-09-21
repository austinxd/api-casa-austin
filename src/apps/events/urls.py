from django.urls import path
from .views import (
    # Endpoints públicos
    PublicEventCategoryListView,
    PublicEventListView,
    PublicEventDetailView,
    EventParticipantsView,
    
    # Endpoints con autenticación
    EventRegistrationView,
    ClientEventRegistrationsView,
    check_event_eligibility,
    
    # Activity Feed endpoints
    ActivityFeedView,
    RecentActivitiesView,
    ActivityFeedStatsView,
    ActivityFeedCreateView,
    
    # Analytics endpoints
    UpcomingCheckinsView,
)

app_name = 'events'

urlpatterns = [
    # === ENDPOINTS PÚBLICOS (sin autenticación) ===
    path('categories/', PublicEventCategoryListView.as_view(), name='public-categories'),
    path('', PublicEventListView.as_view(), name='public-event-list'),
    path('<uuid:id>/', PublicEventDetailView.as_view(), name='public-event-detail'),
    path('<uuid:event_id>/participants/', EventParticipantsView.as_view(), name='event-participants'),
    
    # === ENDPOINTS CON AUTENTICACIÓN DE CLIENTE ===
    path('<uuid:event_id>/register/', EventRegistrationView.as_view(), name='event-register'),
    path('my-registrations/', ClientEventRegistrationsView.as_view(), name='my-registrations'),
    path('<uuid:event_id>/check-eligibility/', check_event_eligibility, name='check-eligibility'),
    
    # === ACTIVITY FEED ENDPOINTS ===
    path('activity-feed/', ActivityFeedView.as_view(), name='activity-feed'),
    path('activity-feed/recent/', RecentActivitiesView.as_view(), name='activity-feed-recent'),
    path('activity-feed/stats/', ActivityFeedStatsView.as_view(), name='activity-feed-stats'),
    path('activity-feed/create/', ActivityFeedCreateView.as_view(), name='activity-feed-create'),
    
    # === ANALYTICS ENDPOINTS ===
    path('upcoming-checkins/', UpcomingCheckinsView.as_view(), name='upcoming-checkins'),
]