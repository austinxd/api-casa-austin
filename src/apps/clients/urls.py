from django.urls import path, include
from rest_framework.routers import DefaultRouter

from . import views
from . import auth_views
from . import points_views  # Import the new views

router = DefaultRouter()
router.register(r'clients', views.ClientsApiView, basename='clients')

urlpatterns = [
    # Client Authentication URLs (Must be before router to avoid conflicts)
    path('clients/verify-document/',
         auth_views.ClientVerifyDocumentView.as_view(),
         name='client-verify-document'),

    path('clients/public-register/',
         auth_views.ClientPublicRegisterView.as_view(),
         name='client-public-register'),
    path('clients/complete-register/',
         auth_views.ClientCompleteRegistrationView.as_view(),
         name='complete-register'),

    path('', include(router.urls)),

    # Endpoints originales para compatibilidad
    path('mensaje-fidelidad/',
         views.MensajeFidelidadApiView.as_view(),
         name='mensaje-fidelidad'),
    path('get-api-token-clients/',
         views.TokenApiClientApiView.as_view(),
         name='token-rutificador'),
    path('clients/client-auth/request-otp/',
         auth_views.ClientRequestOTPView.as_view(),
         name='client-request-otp'),
    path('clients/client-auth/request-otp-registration/',
         auth_views.ClientRequestOTPForRegistrationView.as_view(),
         name='client-request-otp-registration'),
    path('clients/client-auth/setup-password/',
         auth_views.ClientSetupPasswordView.as_view(),
         name='client-setup-password'),
    path('clients/client-auth/login/',
         auth_views.ClientLoginView.as_view(),
         name='client-login'),
    path('clients/client-auth/profile/',
         auth_views.ClientProfileView.as_view(),
         name='client-profile'),
    path('clients/client-auth/reservations/',
         auth_views.ClientReservationsView.as_view(),
         name='client-auth-reservations'),
    path('clients/client-auth/points/',
         auth_views.ClientPointsView.as_view(),
         name='client-points'),
    path('clients/client-auth/redeem-points/',
         auth_views.ClientRedeemPointsView.as_view(),
         name='client-redeem-points'),

    # Sistema de puntos (Integrated into the original structure)
    path('clients/points/balance/',
         points_views.ClientPointsBalanceView.as_view(),
         name='client-points-balance'),
    path('clients/points/history/',
         points_views.ClientPointsHistoryView.as_view(),
         name='client-points-history'),
    path('clients/points/redeem/',
         points_views.redeem_points,
         name='redeem-points'),
    
    # Endpoints para reservas de clientes
    path('clients/reservations/create/',
         views.ClientCreateReservationView.as_view(),
         name='client-create-reservation'),
    path('clients/reservations/list/',
         views.ClientReservationsListView.as_view(),
         name='client-reservations-list'),
    
    # Endpoints para sistema de referidos
    path('clients/referral-config/',
         views.ReferralConfigView.as_view(),
         name='client-referral-config'),
    path('clients/referral-stats/',
         views.ReferralStatsView.as_view(),
         name='client-referral-stats'),
    
    path('clients/csrf-token/', auth_views.get_csrf_token, name='csrf-token'),
]