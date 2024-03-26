from .views import ClientsApiView


from django.urls import include, path
from rest_framework.routers import DefaultRouter

router = DefaultRouter()

router.register("clients", ClientsApiView, basename="clients")

urlpatterns = [
    path("", include(router.urls)),
]
