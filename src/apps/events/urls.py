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
]