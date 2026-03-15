from django.urls import path
from .views import (
    SessionListView,
    SessionDetailView,
    SessionMessagesView,
    ChatView,
)

urlpatterns = [
    path('sessions/', SessionListView.as_view(), name='admin-ai-sessions'),
    path('sessions/<uuid:pk>/', SessionDetailView.as_view(), name='admin-ai-session-detail'),
    path('sessions/<uuid:pk>/messages/', SessionMessagesView.as_view(), name='admin-ai-messages'),
    path('sessions/<uuid:pk>/chat/', ChatView.as_view(), name='admin-ai-chat'),
]
