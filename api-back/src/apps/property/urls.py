from .views import PropertyApiView, ProfitPropertyApiView, CheckAvaiblePorperty


from django.urls import include, path
from rest_framework.routers import DefaultRouter

router = DefaultRouter()

router.register("property", PropertyApiView, basename="property")
router.register("profit", ProfitPropertyApiView, basename="profit")

urlpatterns = [
    path("", include(router.urls)),
    path("prop/check-avaible/", CheckAvaiblePorperty.as_view())
]