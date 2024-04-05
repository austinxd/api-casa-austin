from .views import DashboardApiView


from django.urls import include, path
from rest_framework.routers import DefaultRouter

router = DefaultRouter()

router.register("dashboard", DashboardApiView, basename="dashboard")

urlpatterns = [
    path("", include(router.urls)),
]