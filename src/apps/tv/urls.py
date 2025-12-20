from django.urls import path
from .views import (
    TVSessionView,
    TVHeartbeatView,
    TVCheckoutView,
    TVAppLaunchView
)

urlpatterns = [
    # Main session endpoint
    path('session/<str:room_id>/', TVSessionView.as_view(), name='tv-session'),

    # Heartbeat endpoint
    path('session/<str:room_id>/heartbeat/', TVHeartbeatView.as_view(), name='tv-heartbeat'),

    # Checkout endpoint
    path('session/<str:room_id>/checkout/', TVCheckoutView.as_view(), name='tv-checkout'),

    # App launch tracking
    path('session/<str:room_id>/app-launch/', TVAppLaunchView.as_view(), name='tv-app-launch'),
]
