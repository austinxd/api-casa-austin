from django.urls import path, include
from rest_framework.routers import DefaultRouter

from . import views
from . import auth_views

router = DefaultRouter()
router.register(r'clients', views.ClientsApiView, basename='clients')

urlpatterns = [
    path('clients/', include(router.urls)),

    # Endpoints originales para compatibilidad
    path('mensaje-fidelidad/', views.MensajeFidelidadApiView.as_view(), name='mensaje-fidelidad-original'),
    path('get-api-token-clients/', views.TokenApiClientApiView.as_view(), name='token-rutificador-original'),

    # Endpoints nuevos
    path('clients/mensaje-fidelidad/', views.MensajeFidelidadApiView.as_view(), name='mensaje-fidelidad'),
    path('clients/token-rutificador/', views.TokenApiClientApiView.as_view(), name='token-rutificador'),

    # Client Authentication URLs
    path('clients/verify-document/', auth_views.ClientVerifyDocumentView.as_view(), name='client-verify-document'),
    path('clients/client-auth/request-otp/', auth_views.ClientRequestOTPView.as_view(), name='client-request-otp'),
    path('clients/client-auth/setup-password/', auth_views.ClientSetupPasswordView.as_view(), name='client-setup-password'),
    path('clients/client-auth/login/', auth_views.ClientLoginView.as_view(), name='client-login'),
    path('clients/client-auth/profile/', auth_views.ClientProfileView.as_view(), name='client-profile'),
    path('clients/client-auth/reservations/', auth_views.ClientReservationsView.as_view(), name='client-auth-reservations'),
    path('clients/client-auth/points/', auth_views.ClientPointsView.as_view(), name='client-points'),
    path('clients/client-auth/redeem-points/', auth_views.ClientRedeemPointsView.as_view(), name='client-redeem-points'),
    
    path('clients/csrf-token/', auth_views.get_csrf_token, name='csrf-token'),
]