from .views import MensajeFidelidadApiView, TokenApiClientApiView, ClientsApiView


from django.urls import include, path
from rest_framework.routers import DefaultRouter

router = DefaultRouter()

router.register("clients", ClientsApiView, basename="clients")

urlpatterns = [
    path("", include(router.urls)),
    path("mensaje-fidelidad/", MensajeFidelidadApiView.as_view(), name="mensaje_fidelidad"),
    path("get-api-token-clients/", TokenApiClientApiView.as_view(), name="token_rutificador")
]
from django.urls import path, include
from rest_framework.routers import DefaultRouter
from .views import (
    ClientsApiView, MensajeFidelidadApiView, TokenApiClientApiView,
    ClientAuthRequestView, ClientPasswordSetupView, ClientLoginView,
    ClientProfileView, ClientReservationsView,ClientDocumentVerifyView
)

router = DefaultRouter()
router.register(r'clients', ClientsApiView, basename='clients')

urlpatterns = [
    path('', include(router.urls)),
    path('mensaje-fidelidad/', MensajeFidelidadApiView.as_view(), name='mensaje-fidelidad'),
    path('token-api-cliente/', TokenApiClientApiView.as_view(), name='token-api-cliente'),

    # Autenticación de clientes
    path('verify-document/', ClientDocumentVerifyView.as_view(), name='client-document-verify'),
    path('client-auth/request-otp/', ClientAuthRequestView.as_view(), name='client-auth-request'),
    path('client-auth/setup-password/', ClientPasswordSetupView.as_view(), name='client-password-setup'),
    path('client-auth/login/', ClientLoginView.as_view(), name='client-login'),
    path('client-auth/profile/', ClientProfileView.as_view(), name='client-profile'),
    path('client-auth/reservations/', ClientReservationsView.as_view(), name='client-reservations'),
]