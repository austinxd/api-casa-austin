from .views import PropertyApiView


from django.urls import include, path
from rest_framework.routers import DefaultRouter

router = DefaultRouter()

router.register("property", PropertyApiView, basename="property")

urlpatterns = [
    path("", include(router.urls)),
]