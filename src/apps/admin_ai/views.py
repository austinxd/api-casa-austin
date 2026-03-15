import logging

from rest_framework import status
from rest_framework.permissions import IsAuthenticated, IsAdminUser
from rest_framework.response import Response
from rest_framework.views import APIView

from .models import AdminChatSession, AdminChatMessage
from .orchestrator import AdminAIOrchestrator
from .serializers import (
    AdminChatSessionListSerializer,
    AdminChatSessionDetailSerializer,
    AdminChatMessageSerializer,
    SendMessageSerializer,
    UpdateSessionSerializer,
)

logger = logging.getLogger(__name__)


class SessionListView(APIView):
    """GET: Listar sesiones del usuario. POST: Crear nueva sesión."""
    permission_classes = [IsAuthenticated, IsAdminUser]

    def get(self, request):
        sessions = AdminChatSession.objects.filter(
            user=request.user,
            deleted=False,
        ).order_by('-updated')

        serializer = AdminChatSessionListSerializer(sessions, many=True)
        return Response(serializer.data)

    def post(self, request):
        session = AdminChatSession.objects.create(user=request.user)
        serializer = AdminChatSessionDetailSerializer(session)
        return Response(serializer.data, status=status.HTTP_201_CREATED)


class SessionDetailView(APIView):
    """GET/PATCH/DELETE para una sesión específica."""
    permission_classes = [IsAuthenticated, IsAdminUser]

    def _get_session(self, request, pk):
        try:
            return AdminChatSession.objects.get(
                pk=pk, user=request.user, deleted=False
            )
        except AdminChatSession.DoesNotExist:
            return None

    def get(self, request, pk):
        session = self._get_session(request, pk)
        if not session:
            return Response(
                {'error': 'Sesión no encontrada'},
                status=status.HTTP_404_NOT_FOUND,
            )
        serializer = AdminChatSessionDetailSerializer(session)
        return Response(serializer.data)

    def patch(self, request, pk):
        session = self._get_session(request, pk)
        if not session:
            return Response(
                {'error': 'Sesión no encontrada'},
                status=status.HTTP_404_NOT_FOUND,
            )

        serializer = UpdateSessionSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        session.title = serializer.validated_data['title']
        session.save(update_fields=['title', 'updated'])

        return Response(AdminChatSessionDetailSerializer(session).data)

    def delete(self, request, pk):
        session = self._get_session(request, pk)
        if not session:
            return Response(
                {'error': 'Sesión no encontrada'},
                status=status.HTTP_404_NOT_FOUND,
            )
        session.deleted = True
        session.save(update_fields=['deleted', 'updated'])
        return Response(status=status.HTTP_204_NO_CONTENT)


class SessionMessagesView(APIView):
    """GET: Historial de mensajes de una sesión."""
    permission_classes = [IsAuthenticated, IsAdminUser]

    def get(self, request, pk):
        try:
            session = AdminChatSession.objects.get(
                pk=pk, user=request.user, deleted=False
            )
        except AdminChatSession.DoesNotExist:
            return Response(
                {'error': 'Sesión no encontrada'},
                status=status.HTTP_404_NOT_FOUND,
            )

        messages = AdminChatMessage.objects.filter(
            session=session,
            deleted=False,
        ).order_by('created')

        serializer = AdminChatMessageSerializer(messages, many=True)
        return Response(serializer.data)


class ChatView(APIView):
    """POST: Enviar mensaje y recibir respuesta de la IA."""
    permission_classes = [IsAuthenticated, IsAdminUser]

    def post(self, request, pk):
        try:
            session = AdminChatSession.objects.get(
                pk=pk, user=request.user, deleted=False
            )
        except AdminChatSession.DoesNotExist:
            return Response(
                {'error': 'Sesión no encontrada'},
                status=status.HTTP_404_NOT_FOUND,
            )

        serializer = SendMessageSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        user_message = serializer.validated_data['message']

        orchestrator = AdminAIOrchestrator()
        response_text = orchestrator.process_message(session, user_message)

        # Obtener el último mensaje guardado (la respuesta de la IA)
        ai_message = session.messages.order_by('-created').first()

        return Response({
            'response': response_text,
            'message': AdminChatMessageSerializer(ai_message).data,
            'session': AdminChatSessionDetailSerializer(session).data,
        })
