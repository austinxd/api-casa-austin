import logging
from datetime import timedelta

from django.db.models import Count, Q, Subquery, OuterRef
from django.utils import timezone
from rest_framework import status
from rest_framework.generics import ListAPIView, RetrieveAPIView
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.core.paginator import CustomPagination
from .models import ChatSession, ChatMessage, ChatbotConfiguration, ChatAnalytics
from .serializers import (
    ChatSessionListSerializer, ChatSessionDetailSerializer,
    ChatMessageSerializer, SendMessageSerializer, ToggleAISerializer,
    ChatAnalyticsSerializer,
)
from .whatsapp_sender import WhatsAppSender

logger = logging.getLogger(__name__)


class ChatSessionListView(ListAPIView):
    """GET /sessions/ — Lista de sesiones de chat con filtros"""
    serializer_class = ChatSessionListSerializer
    permission_classes = [IsAuthenticated]
    pagination_class = CustomPagination

    def get_queryset(self):
        qs = ChatSession.objects.filter(deleted=False)

        # Filtro por status
        status_filter = self.request.query_params.get('status')
        if status_filter:
            qs = qs.filter(status=status_filter)

        # Búsqueda por nombre/teléfono
        search = self.request.query_params.get('search', '').strip()
        if search:
            qs = qs.filter(
                Q(wa_profile_name__icontains=search) |
                Q(wa_id__icontains=search) |
                Q(client__first_name__icontains=search) |
                Q(client__last_name__icontains=search) |
                Q(client__tel_number__icontains=search)
            )

        # Anotar unread_count (mensajes inbound sin respuesta desde la última respuesta)
        last_outbound = ChatMessage.objects.filter(
            session=OuterRef('pk'),
            direction__in=['outbound_ai', 'outbound_human'],
        ).order_by('-created').values('created')[:1]

        qs = qs.annotate(
            unread_count=Count(
                'messages',
                filter=Q(
                    messages__direction='inbound',
                    messages__created__gt=Subquery(last_outbound),
                ) | Q(
                    messages__direction='inbound',
                ) & ~Q(
                    messages__session__messages__direction__in=['outbound_ai', 'outbound_human'],
                ),
                distinct=True,
            )
        )

        return qs.order_by('-last_message_at')


class ChatSessionDetailView(RetrieveAPIView):
    """GET /sessions/{id}/ — Detalle de una sesión"""
    serializer_class = ChatSessionDetailSerializer
    permission_classes = [IsAuthenticated]
    queryset = ChatSession.objects.filter(deleted=False)


class ChatMessagesView(ListAPIView):
    """GET /sessions/{id}/messages/ — Mensajes de una sesión"""
    serializer_class = ChatMessageSerializer
    permission_classes = [IsAuthenticated]

    def get_queryset(self):
        session_id = self.kwargs['session_id']
        qs = ChatMessage.objects.filter(
            session_id=session_id, deleted=False
        ).order_by('-created')

        # Cursor pagination por timestamp
        before = self.request.query_params.get('before')
        if before:
            qs = qs.filter(created__lt=before)

        limit = int(self.request.query_params.get('limit', 50))
        return qs[:limit]

    def list(self, request, *args, **kwargs):
        queryset = self.get_queryset()
        serializer = self.get_serializer(queryset, many=True)
        return Response(serializer.data)


class SendManualMessageView(APIView):
    """POST /sessions/{id}/send/ — Enviar mensaje manual (admin)"""
    permission_classes = [IsAuthenticated]

    def post(self, request, session_id):
        serializer = SendMessageSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        content = serializer.validated_data['content']

        try:
            session = ChatSession.objects.get(id=session_id, deleted=False)
        except ChatSession.DoesNotExist:
            return Response(
                {'error': 'Sesión no encontrada'},
                status=status.HTTP_404_NOT_FOUND
            )

        # Enviar por WhatsApp
        sender = WhatsAppSender()
        wa_message_id = sender.send_text_message(session.wa_id, content)

        # Crear mensaje
        message = ChatMessage.objects.create(
            session=session,
            direction=ChatMessage.DirectionChoices.OUTBOUND_HUMAN,
            message_type=ChatMessage.MessageTypeChoices.TEXT,
            content=content,
            wa_message_id=wa_message_id,
            sent_by=request.user,
        )

        # Pausar IA automáticamente
        config = ChatbotConfiguration.get_config()
        now = timezone.now()
        session.ai_enabled = False
        session.status = ChatSession.StatusChoices.AI_PAUSED
        session.ai_paused_at = now
        session.ai_paused_by = request.user
        session.ai_resume_at = now + timedelta(minutes=config.ai_auto_resume_minutes)
        session.total_messages += 1
        session.human_messages += 1
        session.last_message_at = now
        session.save(update_fields=[
            'ai_enabled', 'status', 'ai_paused_at', 'ai_paused_by',
            'ai_resume_at', 'total_messages', 'human_messages', 'last_message_at',
        ])

        return Response(
            ChatMessageSerializer(message).data,
            status=status.HTTP_201_CREATED
        )


class ToggleAIView(APIView):
    """POST /sessions/{id}/toggle-ai/ — Pausar/reactivar IA"""
    permission_classes = [IsAuthenticated]

    def post(self, request, session_id):
        serializer = ToggleAISerializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        ai_enabled = serializer.validated_data['ai_enabled']

        try:
            session = ChatSession.objects.get(id=session_id, deleted=False)
        except ChatSession.DoesNotExist:
            return Response(
                {'error': 'Sesión no encontrada'},
                status=status.HTTP_404_NOT_FOUND
            )

        session.ai_enabled = ai_enabled
        now = timezone.now()

        if ai_enabled:
            session.status = ChatSession.StatusChoices.ACTIVE
            session.ai_paused_at = None
            session.ai_paused_by = None
            session.ai_resume_at = None
        else:
            session.status = ChatSession.StatusChoices.AI_PAUSED
            session.ai_paused_at = now
            session.ai_paused_by = request.user
            config = ChatbotConfiguration.get_config()
            session.ai_resume_at = now + timedelta(minutes=config.ai_auto_resume_minutes)

        session.save(update_fields=[
            'ai_enabled', 'status', 'ai_paused_at', 'ai_paused_by', 'ai_resume_at',
        ])

        return Response(
            ChatSessionDetailSerializer(session).data,
            status=status.HTTP_200_OK
        )


class ChatSessionPollView(APIView):
    """GET /sessions/poll/?since=ISO_timestamp — Polling eficiente"""
    permission_classes = [IsAuthenticated]

    def get(self, request):
        since = request.query_params.get('since')
        if not since:
            return Response(
                {'error': 'Parámetro since requerido'},
                status=status.HTTP_400_BAD_REQUEST
            )

        # Sesiones actualizadas desde 'since'
        sessions = ChatSession.objects.filter(
            deleted=False, last_message_at__gt=since
        ).order_by('-last_message_at')[:20]

        # Mensajes nuevos de esas sesiones
        new_messages = ChatMessage.objects.filter(
            session__in=sessions,
            created__gt=since,
            deleted=False,
        ).order_by('created')

        return Response({
            'sessions': ChatSessionListSerializer(sessions, many=True).data,
            'new_messages': ChatMessageSerializer(new_messages, many=True).data,
            'server_time': timezone.now().isoformat(),
        })


class ChatAnalyticsView(APIView):
    """GET /analytics/?from=date&to=date — Métricas agregadas"""
    permission_classes = [IsAuthenticated]

    def get(self, request):
        from_date = request.query_params.get('from')
        to_date = request.query_params.get('to')

        qs = ChatAnalytics.objects.filter(deleted=False)

        if from_date:
            qs = qs.filter(date__gte=from_date)
        if to_date:
            qs = qs.filter(date__lte=to_date)

        analytics = qs.order_by('-date')[:30]

        return Response(
            ChatAnalyticsSerializer(analytics, many=True).data
        )
