
from django.urls import path, include
from rest_framework.routers import DefaultRouter
from .views import StaffMemberViewSet, WorkTaskViewSet, TimeTrackingViewSet, WorkScheduleViewSet, PropertyCleaningGapViewSet

router = DefaultRouter()
router.register(r'staff', StaffMemberViewSet)
router.register(r'tasks', WorkTaskViewSet)
router.register(r'time-tracking', TimeTrackingViewSet)
router.register(r'schedules', WorkScheduleViewSet)
router.register(r'cleaning-gaps', PropertyCleaningGapViewSet)

urlpatterns = [
    path('', include(router.urls)),
]
