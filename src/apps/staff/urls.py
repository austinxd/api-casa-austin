
from django.urls import path, include
from rest_framework.routers import DefaultRouter
from .views import StaffMemberViewSet, TaskViewSet, WorkSessionViewSet, StaffDashboardView

router = DefaultRouter()
router.register(r'staff', StaffMemberViewSet)
router.register(r'tasks', TaskViewSet)
router.register(r'work-sessions', WorkSessionViewSet)
router.register(r'dashboard', StaffDashboardView, basename='staff-dashboard')

urlpatterns = [
    path('staff/', include(router.urls)),
]
