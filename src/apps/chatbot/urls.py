from django.urls import path

from .webhook_views import WhatsAppWebhookView
from .admin_views import (
    ChatSessionListView,
    ChatSessionDetailView,
    ChatMessagesView,
    SendManualMessageView,
    ToggleAIView,
    MarkAsReadView,
    ChatSessionPollView,
    ChatAnalyticsView,
    ChatAnalyticsDetailView,
    ChatFunnelView,
    ChatAnalysisView,
    ChatAnalysisCheckpointView,
    PropertyVisitListView,
    PropertyVisitUpdateView,
    FollowupOpportunitiesView,
    PromoConfigView,
    PromoListView,
    PromoPreviewView,
    UnresolvedQuestionListView,
    UnresolvedQuestionUpdateView,
    FrequentQuestionListView,
    ChatSessionsExportView,
    OpportunitiesView,
    MagicLinkListView,
)

urlpatterns = [
    # Webhook de WhatsApp (público, sin auth)
    path('webhook/', WhatsAppWebhookView.as_view(), name='chatbot-webhook'),

    # API Admin (requiere auth)
    path('sessions/', ChatSessionListView.as_view(), name='chatbot-sessions'),
    path('sessions/export/', ChatSessionsExportView.as_view(), name='chatbot-sessions-export'),
    path('sessions/poll/', ChatSessionPollView.as_view(), name='chatbot-poll'),
    path('sessions/<uuid:pk>/', ChatSessionDetailView.as_view(), name='chatbot-session-detail'),
    path('sessions/<uuid:session_id>/messages/', ChatMessagesView.as_view(), name='chatbot-messages'),
    path('sessions/<uuid:session_id>/send/', SendManualMessageView.as_view(), name='chatbot-send'),
    path('sessions/<uuid:session_id>/toggle-ai/', ToggleAIView.as_view(), name='chatbot-toggle-ai'),
    path('sessions/<uuid:session_id>/mark-read/', MarkAsReadView.as_view(), name='chatbot-mark-read'),

    # Visitas
    path('visits/', PropertyVisitListView.as_view(), name='chatbot-visits'),
    path('visits/<uuid:pk>/', PropertyVisitUpdateView.as_view(), name='chatbot-visit-update'),

    # Analytics
    path('analytics/', ChatAnalyticsView.as_view(), name='chatbot-analytics'),
    path('analytics/details/', ChatAnalyticsDetailView.as_view(), name='chatbot-analytics-details'),
    path('funnel/', ChatFunnelView.as_view(), name='chatbot-funnel'),
    path('analysis/', ChatAnalysisView.as_view(), name='chatbot-analysis'),
    path('analysis/checkpoint/', ChatAnalysisCheckpointView.as_view(), name='chatbot-analysis-checkpoint'),
    path('followups/', FollowupOpportunitiesView.as_view(), name='chatbot-followups'),

    # Promos automáticas
    path('promo-config/', PromoConfigView.as_view(), name='chatbot-promo-config'),
    path('promos/', PromoListView.as_view(), name='chatbot-promos'),
    path('promos/preview/', PromoPreviewView.as_view(), name='chatbot-promos-preview'),

    # Preguntas sin resolver
    path('unresolved-questions/', UnresolvedQuestionListView.as_view(), name='chatbot-unresolved-questions'),
    path('unresolved-questions/<uuid:pk>/', UnresolvedQuestionUpdateView.as_view(), name='chatbot-unresolved-question-update'),

    # Preguntas frecuentes (analizadas automáticamente)
    path('frequent-questions/', FrequentQuestionListView.as_view(), name='chatbot-frequent-questions'),

    # Oportunidades por fecha (Fase A read-only)
    path('opportunities/', OpportunitiesView.as_view(), name='chatbot-opportunities'),
    # R4.2 — Listado admin de Magic Links (R4.1 + R4.2)
    path('magic-links/', MagicLinkListView.as_view(), name='chatbot-magic-links'),
]
