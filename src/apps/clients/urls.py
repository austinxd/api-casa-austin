from django.urls import path, include
from rest_framework.routers import DefaultRouter

from . import views
from . import auth_views

router = DefaultRouter()
router.register(r'clients', views.ClientsApiView, basename='clients')

urlpatterns = [
    path('api/v1/clients/', include(router.urls)),
    path('api/v1/clients/mensaje-fidelidad/', views.MensajeFidelidadApiView.as_view(), name='mensaje-fidelidad'),
    path('api/v1/clients/token-rutificador/', views.TokenApiClientApiView.as_view(), name='token-rutificador'),

    # Client Authentication URLs
    path('api/v1/clients/verify-document/', auth_views.ClientVerifyDocumentView.as_view(), name='client-verify-document'),
    path('api/v1/clients/client-auth/request-otp/', auth_views.ClientRequestOTPView.as_view(), name='client-request-otp'),
    path('api/v1/clients/client-auth/setup-password/', auth_views.ClientSetupPasswordView.as_view(), name='client-setup-password'),
    path('api/v1/clients/client-auth/login/', auth_views.ClientLoginView.as_view(), name='client-login'),
    path('api/v1/clients/client-auth/profile/', auth_views.ClientProfileView.as_view(), name='client-profile'),
    path('api/v1/clients/csrf-token/', auth_views.get_csrf_token, name='csrf-token'),
]