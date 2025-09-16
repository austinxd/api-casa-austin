from django.urls import path
from .views import (
    # Endpoints públicos
    PublicEventCategoryListView,
    PublicEventListView,
    PublicEventDetailView,
    
    # Endpoints con autenticación
    EventRegistrationView,
    ClientEventRegistrationsView,
    check_event_eligibility,
)

# 🏆 Importar vistas de ganadores
from .winners_views import PublicEventWinnersView, draw_winners, mark_manual_winner

app_name = 'events'

urlpatterns = [
    # === ENDPOINTS PÚBLICOS (sin autenticación) ===
    path('categories/', PublicEventCategoryListView.as_view(), name='public-categories'),
    path('', PublicEventListView.as_view(), name='public-event-list'),
    path('<uuid:id>/', PublicEventDetailView.as_view(), name='public-event-detail'),
    
    # 🏆 ENDPOINTS PARA GANADORES (públicos)
    path('<uuid:id>/winners/', PublicEventWinnersView.as_view(), name='event-winners'),
    
    # === ENDPOINTS CON AUTENTICACIÓN DE CLIENTE ===
    path('<uuid:event_id>/register/', EventRegistrationView.as_view(), name='event-register'),
    path('my-registrations/', ClientEventRegistrationsView.as_view(), name='my-registrations'),
    path('<uuid:event_id>/check-eligibility/', check_event_eligibility, name='check-eligibility'),
    
    # 🎲 ENDPOINTS PARA SORTEOS (admin - cambiar permisos en producción)
    path('<uuid:event_id>/draw-winners/', draw_winners, name='draw-winners'),
    path('<uuid:event_id>/registrations/<uuid:registration_id>/mark-winner/', mark_manual_winner, name='mark-winner'),
]