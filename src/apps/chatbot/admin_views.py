import logging
from datetime import timedelta

from django.db.models import Count, F, Q, Subquery, OuterRef
from django.utils import timezone
from rest_framework import status
from rest_framework.generics import ListAPIView, RetrieveAPIView
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.core.paginator import CustomPagination
from .models import ChatSession, ChatMessage, ChatbotConfiguration, ChatAnalytics, PropertyVisit
from .serializers import (
    ChatSessionListSerializer, ChatSessionDetailSerializer,
    ChatMessageSerializer, SendMessageSerializer, ToggleAISerializer,
    ChatAnalyticsSerializer, PropertyVisitSerializer,
)
from .channel_sender import get_sender

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

        # Anotar unread_count (mensajes inbound después de last_read_at)
        qs = qs.annotate(
            unread_count=Count(
                'messages',
                filter=Q(messages__direction='inbound') & (
                    Q(last_read_at__isnull=True) |
                    Q(messages__created__gt=F('last_read_at'))
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

        # Enviar por el canal correspondiente (WhatsApp, Instagram, Messenger)
        sender = get_sender(session.channel)
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


class MarkAsReadView(APIView):
    """POST /sessions/{id}/mark-read/ — Marcar conversación como leída"""
    permission_classes = [IsAuthenticated]

    def post(self, request, session_id):
        try:
            session = ChatSession.objects.get(id=session_id, deleted=False)
        except ChatSession.DoesNotExist:
            return Response(
                {'error': 'Sesión no encontrada'},
                status=status.HTTP_404_NOT_FOUND
            )

        session.last_read_at = timezone.now()
        session.save(update_fields=['last_read_at'])

        return Response({'status': 'ok'})


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


class PropertyVisitListView(ListAPIView):
    """GET /visits/ — Visitas futuras programadas"""
    serializer_class = PropertyVisitSerializer
    permission_classes = [IsAuthenticated]
    pagination_class = CustomPagination

    def get_queryset(self):
        from datetime import date
        qs = PropertyVisit.objects.filter(
            deleted=False,
            visit_date__gte=date.today(),
        ).select_related('property', 'client', 'session')

        status_filter = self.request.query_params.get('status')
        if status_filter:
            qs = qs.filter(status=status_filter)

        return qs.order_by('visit_date', 'visit_time')


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


class ChatAnalysisView(APIView):
    """GET /analysis/ — Análisis IA de las últimas 20 conversaciones"""
    permission_classes = [IsAuthenticated]

    ANALYSIS_PROMPT = (
        "Eres un analista experto en optimización de prompts y calidad de chatbots "
        "para Casa Austin, un negocio de alquiler de casas vacacionales en Lima, Perú.\n\n"
        "Se te proporcionará:\n"
        "1. El PROMPT ACTUAL del chatbot (las instrucciones que usa la IA para responder a clientes)\n"
        "2. Las últimas conversaciones reales del chatbot con clientes\n\n"
        "Genera un reporte en español con las siguientes secciones:\n\n"
        "## 1. Resumen General\n"
        "Estado general de las conversaciones, tono, efectividad.\n\n"
        "## 2. Problemas Detectados en las Respuestas\n"
        "Respuestas incorrectas, inconsistencias, información errónea, o momentos "
        "donde la IA no supo responder. Para CADA problema:\n"
        "- Indica la conversación exacta (nombre/número del contacto)\n"
        "- Cita textualmente el fragmento problemático entre comillas\n"
        "- Explica qué estuvo mal y qué debió responder\n\n"
        "## 3. Análisis del Prompt Actual\n"
        "Evalúa el prompt del chatbot:\n"
        "- ¿Qué instrucciones están funcionando bien?\n"
        "- ¿Qué instrucciones faltan o son ambiguas?\n"
        "- ¿Hay contradicciones en el prompt?\n"
        "- ¿El tono indicado en el prompt se refleja en las respuestas?\n\n"
        "## 4. Mejoras Sugeridas al Prompt\n"
        "Sugiere cambios CONCRETOS al prompt del chatbot. Para cada sugerencia:\n"
        "- Explica el problema que resuelve (con ejemplo de la conversación)\n"
        "- Muestra la línea/instrucción ACTUAL del prompt que causa el problema (o indica si falta)\n"
        "- Propón la instrucción NUEVA o MODIFICADA exacta que debería agregarse/cambiarse\n"
        "Formato:\n"
        "**Problema:** [descripción con cita de conversación]\n"
        "**Prompt actual:** \"[línea actual o 'No existe']\" \n"
        "**Prompt sugerido:** \"[nueva instrucción exacta]\"\n\n"
        "## 5. Intenciones Frecuentes\n"
        "Top 5 intenciones de los clientes.\n\n"
        "## 6. Extractos Destacados\n"
        "3-5 extractos textuales de conversaciones que ejemplifiquen "
        "los problemas o aciertos más importantes. Formato:\n"
        "> **Conversación con [nombre]:**\n"
        "> [Cliente]: mensaje del cliente\n"
        "> [IA]: respuesta de la IA\n"
        "> **Veredicto:** explicación\n\n"
        "## 7. Puntuación\n"
        "Del 1 al 10, calidad general. Justifica la nota.\n\n"
        "IMPORTANTE: Sé específico. SIEMPRE cita fragmentos reales. "
        "Las sugerencias al prompt deben ser instrucciones EXACTAS listas para copiar y pegar."
    )

    def get(self, request):
        import openai
        from django.conf import settings as django_settings

        # Obtener el prompt actual del chatbot
        chatbot_config = ChatbotConfiguration.get_config()
        chatbot_prompt = chatbot_config.system_prompt

        # Obtener las últimas 20 sesiones con mensajes
        sessions = ChatSession.objects.filter(
            deleted=False, total_messages__gt=0
        ).order_by('-last_message_at')[:20]

        if not sessions:
            return Response({
                'analysis': 'No hay conversaciones para analizar.',
                'sessions_analyzed': 0,
                'analysis_prompt': self.ANALYSIS_PROMPT,
                'chatbot_prompt': chatbot_prompt,
                'conversations_sent': '',
            })

        # Construir resumen de conversaciones
        conversations_text = []
        for i, session in enumerate(sessions, 1):
            name = session.wa_profile_name or session.wa_id
            client_name = ''
            if session.client:
                client_name = f" — Cliente: {session.client.first_name} {session.client.last_name or ''}"
            msgs = ChatMessage.objects.filter(
                session=session, deleted=False
            ).order_by('created')[:30]

            msg_lines = []
            for msg in msgs:
                direction_label = {
                    'inbound': 'Cliente',
                    'outbound_ai': 'IA',
                    'outbound_human': 'Admin',
                    'system': 'Sistema',
                }.get(msg.direction, msg.direction)
                timestamp = msg.created.strftime('%d/%m %H:%M')
                msg_lines.append(f"  [{timestamp}] [{direction_label}]: {msg.content[:300]}")

            conv_text = (
                f"\n--- Conversación {i}: {name}{client_name} "
                f"(estado: {session.status}, IA: {'activa' if session.ai_enabled else 'pausada'}, "
                f"mensajes: {session.total_messages}) ---\n"
            )
            conv_text += "\n".join(msg_lines)
            conversations_text.append(conv_text)

        all_conversations = "\n".join(conversations_text)

        user_message = (
            f"## PROMPT ACTUAL DEL CHATBOT:\n"
            f"```\n{chatbot_prompt}\n```\n\n"
            f"## CONVERSACIONES RECIENTES ({len(sessions)}):\n\n"
            f"{all_conversations}"
        )

        # Llamar a OpenAI para análisis
        try:
            client = openai.OpenAI(api_key=django_settings.OPENAI_API_KEY)
            response = client.chat.completions.create(
                model="gpt-4.1-nano",
                temperature=0.3,
                max_tokens=3500,
                messages=[
                    {"role": "system", "content": self.ANALYSIS_PROMPT},
                    {"role": "user", "content": user_message},
                ],
            )

            analysis_text = response.choices[0].message.content
            tokens_used = response.usage.total_tokens if response.usage else 0

            return Response({
                'analysis': analysis_text,
                'sessions_analyzed': len(sessions),
                'tokens_used': tokens_used,
                'model': 'gpt-4.1-nano',
                'analysis_prompt': self.ANALYSIS_PROMPT,
                'chatbot_prompt': chatbot_prompt,
                'conversations_sent': all_conversations,
            })

        except Exception as e:
            logger.error(f"Error en análisis IA: {e}")
            return Response(
                {'error': f'Error al generar análisis: {str(e)}'},
                status=status.HTTP_500_INTERNAL_SERVER_ERROR
            )


class FollowupOpportunitiesView(APIView):
    """GET /followups/ — Oportunidades de seguimiento pendientes"""
    permission_classes = [IsAuthenticated]

    def get(self, request):
        now = timezone.now()
        min_age = now - timedelta(hours=22)

        # Sesiones sin cotización (escribieron hace 2-22h)
        no_quote = ChatSession.objects.filter(
            deleted=False,
            status__in=['active', 'ai_paused'],
            quoted_at__isnull=True,
            followup_count=0,
            last_customer_message_at__isnull=False,
            last_customer_message_at__gte=min_age,
            last_customer_message_at__lte=now - timedelta(hours=1),
            total_messages__gte=2,
        ).order_by('-last_customer_message_at')[:20]

        # Sesiones cotizadas sin conversión (cotizadas hace 4-22h)
        quoted_no_conversion = ChatSession.objects.filter(
            deleted=False,
            status__in=['active', 'ai_paused'],
            quoted_at__isnull=False,
            followup_count=0,
            last_customer_message_at__isnull=False,
            last_customer_message_at__gte=min_age,
            quoted_at__lte=now - timedelta(hours=2),
        ).order_by('-quoted_at')[:20]

        # Sesiones que ya recibieron follow-up
        followed_up = ChatSession.objects.filter(
            deleted=False,
            followup_count__gt=0,
            followup_sent_at__gte=now - timedelta(days=3),
        ).order_by('-followup_sent_at')[:10]

        def serialize_session(s, category):
            name = s.wa_profile_name or s.wa_id
            if s.client:
                name = f"{s.client.first_name} {s.client.last_name or ''}".strip()
            last_msg = s.messages.order_by('-created').first()
            hours_since = None
            if s.last_customer_message_at:
                hours_since = round((now - s.last_customer_message_at).total_seconds() / 3600, 1)
            wa_window_remaining = None
            if s.last_customer_message_at:
                remaining = 24 - (now - s.last_customer_message_at).total_seconds() / 3600
                wa_window_remaining = round(max(0, remaining), 1)
            return {
                'id': str(s.id),
                'wa_id': s.wa_id,
                'name': name,
                'category': category,
                'status': s.status,
                'ai_enabled': s.ai_enabled,
                'total_messages': s.total_messages,
                'quoted_at': s.quoted_at.isoformat() if s.quoted_at else None,
                'followup_count': s.followup_count,
                'followup_sent_at': s.followup_sent_at.isoformat() if s.followup_sent_at else None,
                'last_customer_message_at': s.last_customer_message_at.isoformat() if s.last_customer_message_at else None,
                'hours_since_last_message': hours_since,
                'wa_window_remaining_hours': wa_window_remaining,
                'last_message_preview': last_msg.content[:100] if last_msg else None,
            }

        results = (
            [serialize_session(s, 'no_quote') for s in no_quote] +
            [serialize_session(s, 'quoted') for s in quoted_no_conversion] +
            [serialize_session(s, 'followed_up') for s in followed_up]
        )

        return Response({
            'no_quote_count': no_quote.count(),
            'quoted_count': quoted_no_conversion.count(),
            'followed_up_count': followed_up.count(),
            'results': results,
        })
