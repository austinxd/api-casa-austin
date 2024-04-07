from django.urls import path
from .views import DashboardApiView


urlpatterns = [
    path("dashboard/", DashboardApiView.as_view()),
]