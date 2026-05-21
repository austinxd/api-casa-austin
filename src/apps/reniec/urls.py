from django.urls import path
from .views import DNILookupView, DNILookupAuthenticatedView, DNILookupPublicView, DNIStatsView
from .expediente_views import (
    AdminFullExpedienteView,
    AdminPhoneByNumberView,
    AdminFamilyView,
    AdminSalariesView,
    AdminMarriagesView,
    AdminAddressesView,
    AdminPoliceView,
)

app_name = 'reniec'

urlpatterns = [
    # Endpoint principal con autenticación por API Key (para apps externas)
    path('lookup/', DNILookupView.as_view(), name='dni-lookup'),

    # Endpoint para admin/staff con JWT (panel de administración)
    path('lookup/auth/', DNILookupAuthenticatedView.as_view(), name='dni-lookup-auth'),

    # Endpoint PÚBLICO para registro de clientes (rate limited por IP)
    path('lookup/public/', DNILookupPublicView.as_view(), name='dni-lookup-public'),

    # Estadísticas (solo admin)
    path('stats/', DNIStatsView.as_view(), name='stats'),

    # ─── Expediente extendido (admin-only) ───────────────────────────
    # Orquestador: dispara los 7 endpoints de Leder en paralelo
    path('full/<str:dni>/', AdminFullExpedienteView.as_view(), name='expediente-full'),

    # Búsqueda inversa por teléfono
    path('phones/by-number/', AdminPhoneByNumberView.as_view(), name='expediente-phones'),

    # Sub-endpoints individuales (acepta ?refresh=1 para forzar Leder)
    path('<str:dni>/family/', AdminFamilyView.as_view(), name='expediente-family'),
    path('<str:dni>/salaries/', AdminSalariesView.as_view(), name='expediente-salaries'),
    path('<str:dni>/marriages/', AdminMarriagesView.as_view(), name='expediente-marriages'),
    path('<str:dni>/addresses/', AdminAddressesView.as_view(), name='expediente-addresses'),
    path('<str:dni>/police/', AdminPoliceView.as_view(), name='expediente-police'),
]
