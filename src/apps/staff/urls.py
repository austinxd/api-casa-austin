
from django.urls import path, include
from rest_framework.routers import DefaultRouter
from .views import StaffMemberViewSet, WorkTaskViewSet, TimeTrackingViewSet, WorkScheduleViewSet

router = DefaultRouter()
router.register(r'staff', StaffMemberViewSet)
router.register(r'tasks', WorkTaskViewSet)
router.register(r'time-tracking', TimeTrackingViewSet)
router.register(r'schedules', WorkScheduleViewSet)

urlpatterns = [
    path('api/v1/', include(router.urls)),
]
