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
