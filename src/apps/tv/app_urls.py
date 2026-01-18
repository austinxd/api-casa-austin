from django.urls import path
from .views import TVAppVersionView

urlpatterns = [
    # App version check endpoint
    path('version/', TVAppVersionView.as_view(), name='tv-app-version'),
]
