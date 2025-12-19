from django.urls import path
from .views import DNILookupView, DNILookupAuthenticatedView, DNIStatsView

app_name = 'reniec'

urlpatterns = [
    # Endpoint principal con autenticación por API Key
    path('lookup/', DNILookupView.as_view(), name='dni-lookup'),

    # Endpoint para admin/staff con JWT
    path('lookup/auth/', DNILookupAuthenticatedView.as_view(), name='dni-lookup-auth'),

    # Estadísticas (solo admin)
    path('stats/', DNIStatsView.as_view(), name='stats'),
]
