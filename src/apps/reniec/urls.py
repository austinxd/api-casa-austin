from django.urls import path
from .views import DNILookupView, DNILookupAuthenticatedView, DNILookupPublicView, DNIStatsView

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
]
