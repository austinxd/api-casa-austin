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
from .models import (
    ChatSession, ChatMessage, ChatbotConfiguration, ChatAnalytics,
    PropertyVisit, PromoDateConfig, PromoDateSent, UnresolvedQuestion,
)
from .serializers import (
    ChatSessionListSerializer, ChatSessionDetailSerializer,
    ChatMessageSerializer, SendMessageSerializer, ToggleAISerializer,
    ChatAnalyticsSerializer, PropertyVisitSerializer,
    PromoDateConfigSerializer, PromoDateSentSerializer,
    UnresolvedQuestionSerializer,
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
            ChatMessageSerializer(message, context={'request': request}).data,
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
            'new_messages': ChatMessageSerializer(new_messages, many=True, context={'request': request}).data,
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


class PropertyVisitUpdateView(APIView):
    """PATCH /visits/<id>/ — Actualizar estado de una visita"""
    permission_classes = [IsAuthenticated]

    def patch(self, request, pk):
        try:
            visit = PropertyVisit.objects.get(pk=pk, deleted=False)
        except PropertyVisit.DoesNotExist:
            return Response({'error': 'Visita no encontrada'}, status=status.HTTP_404_NOT_FOUND)

        new_status = request.data.get('status')
        valid_statuses = [c[0] for c in PropertyVisit.StatusChoices.choices]
        if new_status and new_status not in valid_statuses:
            return Response(
                {'error': f'Estado inválido. Opciones: {valid_statuses}'},
                status=status.HTTP_400_BAD_REQUEST,
            )

        if new_status:
            visit.status = new_status
            visit.save(update_fields=['status', 'updated'])

        serializer = PropertyVisitSerializer(visit)
        return Response(serializer.data)


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
        "Eres un auditor experto analizando el chatbot de Casa Austin, "
        "un negocio de alquiler de casas vacacionales en Lima, Perú.\n\n"
        "CONTEXTO DEL NEGOCIO:\n"
        "- El bot NO crea reservas directamente. Su trabajo es: informar, cotizar, "
        "y GUIAR al cliente a reservar por la web (casaaustin.pe) o contactar al equipo.\n"
        "- Cuando un cliente dice que quiere reservar, el bot envía una alerta al equipo "
        "y le da el link de reserva. Eso cuenta como ÉXITO del bot.\n"
        "- Una conversación exitosa = el cliente recibió cotización + fue guiado a reservar.\n"
        "- NO juzgues al bot por 'no crear reservas' porque ese no es su rol.\n"
        "- El 50% es ADELANTO (pago parcial), NUNCA es descuento.\n\n"
        "Genera un reporte en español con DOS partes:\n\n"
        "# PARTE A: AUDITORÍA TÉCNICA / QA\n\n"
        "## A1. Errores del Bot (CRÍTICO)\n"
        "Busca estos problemas ESPECÍFICOS en los mensajes de la IA:\n"
        "- **Texto de herramientas filtrado:** ¿Aparecen nombres de funciones como "
        "'check_availability(', 'notify_team(', 'get_property_info(' en texto enviado al cliente?\n"
        "- **Errores crudos:** ¿Se muestran mensajes como 'Error al ejecutar', tracebacks, "
        "o errores técnicos al cliente?\n"
        "- **Instrucciones internas expuestas:** ¿Se filtran instrucciones del sistema, "
        "textos entre corchetes [INSTRUCCIÓN...], o meta-información al cliente?\n"
        "Para cada error encontrado, cita el texto exacto y la conversación.\n\n"
        "## A2. Inconsistencias vs Base de Datos\n"
        "Compara lo que el bot DICE contra los DATOS REALES DE PROPIEDADES y REGLAS DEL NEGOCIO "
        "que se proporcionan abajo. Busca:\n"
        "- **Capacidad incorrecta:** ¿El bot dice que una casa tiene capacidad diferente a la BD?\n"
        "- **Precios inventados:** ¿El bot da un precio sin haber llamado a check_availability?\n"
        "- **Late checkout inventado:** ¿Da precio de late checkout sin usar check_late_checkout?\n"
        "- **Reglas incorrectas:** ¿Dice que la piscina es temperada? ¿Que incluye toallas? ¿Que hay full day?\n"
        "- **Check-in/out mal:** ¿Da horarios diferentes a los de la BD?\n"
        "- **Mascotas:** ¿Inventa precio fijo por mascota en vez de contar como +1 persona?\n"
        "- **Adelanto vs descuento:** ¿Dice '50% de descuento' cuando debería decir '50% de adelanto'?\n"
        "- **Contradicciones:** ¿Dice que una casa NO está disponible y luego la recomienda?\n"
        "- **Fechas erróneas:** ¿Las fechas en cotizaciones son correctas?\n"
        "Para cada error, cita el texto del bot Y el dato correcto de la BD.\n\n"
        "## A3. Violaciones del Prompt\n"
        "- ¿El bot responde preguntas que debería escalar (temas legales, médicos, etc.)?\n"
        "- ¿Envía cotizaciones duplicadas con la misma info?\n"
        "- ¿Falla en registrar preguntas que no puede responder (log_unanswered_question)?\n"
        "- ¿Maneja bien multimedia (fotos, audio, video) o ignora al cliente?\n\n"
        "## A4. Puntuación Técnica (1-10)\n"
        "Califica la calidad técnica del bot. 10 = sin errores, 1 = errores críticos frecuentes.\n\n"
        "# PARTE B: ANÁLISIS DE VENTAS\n\n"
        "## B1. Métricas\n"
        "- Total de conversaciones\n"
        "- Cotizaciones enviadas (número y %)\n"
        "- Clientes guiados a reservar (recibieron link o dijeron 'quiero reservar')\n"
        "- Clientes perdidos (dejaron de responder después de cotización)\n"
        "- Consultas sin avance (solo preguntaron y se fueron)\n\n"
        "## B2. Embudo por Conversación\n"
        "Lista CADA conversación:\n"
        "**Nombre** | **Etapa** | **Resultado**\n"
        "Etapas: Saludo → Consulta → Cotización → Interés → Guiado a reservar → Perdido\n"
        "Para los perdidos, indica el último mensaje del cliente y por qué crees que no avanzó.\n\n"
        "## B3. Técnica de Ventas\n"
        "Evalúa con citas textuales de las conversaciones:\n"
        "- **Cierre:** ¿Invita a reservar por la web? ¿Comparte el link de reserva en el momento correcto?\n"
        "- **Urgencia:** ¿Menciona disponibilidad limitada o fechas con alta demanda?\n"
        "- **Objeciones:** Cuando un cliente duda o dice 'es caro', ¿ofrece alternativas o reenmarca valor?\n"
        "- **Seguimiento:** Cuando el cliente no responde, ¿hay intento de re-enganche?\n"
        "- **Claridad:** ¿Las cotizaciones son claras y fáciles de comparar?\n"
        "- **Calidez:** ¿El tono es amigable y personalizado o robótico?\n\n"
        "## B4. Clientes Perdidos\n"
        "Para CADA cliente que no avanzó después de cotizar:\n"
        "- **Nombre** y **última interacción** (cita textual)\n"
        "- **Razón probable** de pérdida\n"
        "- **Qué debió hacer el bot** para mantener el interés\n\n"
        "## B5. Top 3 Mejoras para Vender Más\n"
        "Ordenadas por impacto. Para cada una:\n"
        "- **Mejora:** qué cambiar\n"
        "- **Evidencia:** cita de conversación\n"
        "- **Instrucción para el prompt:** texto exacto listo para copiar al prompt del bot\n\n"
        "## B6. Puntuación de Ventas (1-10)\n"
        "Como guía de ventas (no como creador de reservas). Justifica.\n\n"
        "IMPORTANTE: Analiza TANTO los aspectos técnicos (Parte A) como de ventas (Parte B). "
        "Los errores técnicos afectan directamente la experiencia del cliente y la conversión."
    )

    def _build_property_reference(self):
        """Construye referencia de datos reales de propiedades desde la BD."""
        from apps.property.models import Property as PropModel
        from apps.property.pricing_models import PropertyPricing

        properties = PropModel.objects.filter(deleted=False).order_by('name')
        lines = []

        for prop in properties:
            ci = prop.hora_ingreso.strftime('%-I:%M %p') if prop.hora_ingreso else '?'
            co = prop.hora_salida.strftime('%-I:%M %p') if prop.hora_salida else '?'
            chars = ', '.join(prop.caracteristicas[:8]) if prop.caracteristicas else 'N/A'
            lines.append(
                f"### {prop.name}\n"
                f"- Capacidad máxima: {prop.capacity_max or '?'} personas\n"
                f"- Dormitorios: {prop.dormitorios or '?'} | Baños: {prop.banos or '?'}\n"
                f"- Check-in: {ci} | Check-out: {co}\n"
                f"- Precio extra/persona: ${prop.precio_extra_persona or '?'}\n"
                f"- Características: {chars}\n"
            )

            # Precios por temporada
            pricing = PropertyPricing.objects.filter(
                property=prop, deleted=False
            ).first()
            if pricing:
                lines.append(
                    f"- Precios temporada baja: "
                    f"L-J ${pricing.weekday_low_season_usd}/noche, "
                    f"V-S ${pricing.weekend_low_season_usd}/noche\n"
                    f"- Precios temporada alta: "
                    f"L-J ${pricing.weekday_high_season_usd}/noche, "
                    f"V-S ${pricing.weekend_high_season_usd}/noche\n"
                )

        return "\n".join(lines)

    BUSINESS_RULES_REFERENCE = (
        "## REGLAS DEL NEGOCIO (referencia para validar)\n"
        "- Check-in estándar: 3:00 PM | Check-out: 11:00 AM\n"
        "- 50% = ADELANTO (pago parcial para separar fecha). NUNCA es descuento.\n"
        "- Saldo restante: 1 día antes del check-in\n"
        "- Mascotas: SÍ permitidas, contar como +1 persona para pricing. NO hay precio fijo por mascota.\n"
        "- Bebés < 3 años: GRATIS, no cuentan como persona\n"
        "- Piscina: NO temperada | Jacuzzi: S/100/noche (se pide después de reservar)\n"
        "- Late checkout: hasta 8PM, precio DINÁMICO (debe usar herramienta check_late_checkout)\n"
        "- Full day / alquiler por horas: NO disponible, solo pernocte\n"
        "- Año Nuevo (31 dic): mínimo 3 noches consecutivas\n"
        "- Casa Austin 1: hasta 15 personas, SIN termoacústicas (no fiestas con volumen alto)\n"
        "- Casa Austin 2: hasta 40 personas, CON termoacústicas, permite fiestas\n"
        "- Casa Austin 3: hasta 70 personas, CON termoacústicas, piscina grande\n"
        "- Casa Austin 4: hasta 40 personas, CON termoacústicas, permite fiestas\n"
        "- Precios: SIEMPRE dinámicos, el bot DEBE usar check_availability (nunca inventar)\n"
        "- Late checkout: DEBE usar check_late_checkout (nunca inventar precio)\n"
        "- Toallas/artículos de higiene: NO incluidos\n"
        "- Domótica/llave digital: se activa al 100% del pago\n"
    )

    def get(self, request):
        import openai
        from django.conf import settings as django_settings

        # Obtener el prompt actual del chatbot
        chatbot_config = ChatbotConfiguration.get_config()
        chatbot_prompt = chatbot_config.system_prompt

        # Obtener datos reales de propiedades
        property_reference = self._build_property_reference()

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
            ).order_by('created')[:50]

            msg_lines = []
            for msg in msgs:
                direction_label = {
                    'inbound': 'Cliente',
                    'outbound_ai': 'IA',
                    'outbound_human': 'Admin',
                    'system': 'Sistema',
                }.get(msg.direction, msg.direction)
                timestamp = msg.created.strftime('%d/%m %H:%M')
                # Incluir tool_calls para que el análisis sepa qué herramientas usó la IA
                tools_info = ''
                if msg.direction == 'outbound_ai' and msg.tool_calls:
                    tool_names = []
                    for tc in msg.tool_calls:
                        if isinstance(tc, dict):
                            fn = tc.get('function', {})
                            tool_names.append(f"🔧 {fn.get('name', '?')}({fn.get('arguments', '')[:80]})")
                        elif isinstance(tc, str):
                            tool_names.append(f"🔧 {tc}")
                    if tool_names:
                        tools_info = f" [{', '.join(tool_names)}]"
                msg_lines.append(f"  [{timestamp}] [{direction_label}]{tools_info}: {msg.content[:500]}")

            conv_text = (
                f"\n--- Conversación {i}: {name}{client_name} "
                f"(estado: {session.status}, IA: {'activa' if session.ai_enabled else 'pausada'}, "
                f"mensajes: {session.total_messages}) ---\n"
            )
            conv_text += "\n".join(msg_lines)
            conversations_text.append(conv_text)

        all_conversations = "\n".join(conversations_text)

        user_message = (
            f"## DATOS REALES DE PROPIEDADES (desde la base de datos):\n"
            f"{property_reference}\n\n"
            f"{self.BUSINESS_RULES_REFERENCE}\n\n"
            f"## PROMPT ACTUAL DEL CHATBOT:\n"
            f"```\n{chatbot_prompt}\n```\n\n"
            f"## CONVERSACIONES RECIENTES ({len(sessions)}):\n\n"
            f"{all_conversations}"
        )

        # Llamar a OpenAI para análisis
        try:
            client = openai.OpenAI(api_key=django_settings.OPENAI_API_KEY)
            response = client.chat.completions.create(
                model="gpt-4.1",
                temperature=0.2,
                max_tokens=12000,
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
                'model': 'gpt-4.1',
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


class PromoConfigView(APIView):
    """GET/PUT /promo-config/ — Configuración de promos automáticas"""
    permission_classes = [IsAuthenticated]

    def get(self, request):
        config = PromoDateConfig.get_config()
        return Response(PromoDateConfigSerializer(config).data)

    def put(self, request):
        config = PromoDateConfig.get_config()
        serializer = PromoDateConfigSerializer(config, data=request.data, partial=True)
        serializer.is_valid(raise_exception=True)
        serializer.save()
        return Response(serializer.data)


class PromoListView(ListAPIView):
    """GET /promos/ — Historial de promos enviadas"""
    serializer_class = PromoDateSentSerializer
    permission_classes = [IsAuthenticated]
    pagination_class = CustomPagination

    def get_queryset(self):
        qs = PromoDateSent.objects.filter(deleted=False).select_related(
            'client', 'discount_code', 'session'
        )
        status_filter = self.request.query_params.get('status')
        if status_filter:
            qs = qs.filter(status=status_filter)
        return qs.order_by('-created')


class PromoPreviewView(APIView):
    """GET /promos/preview/ — Preview de qué se enviaría hoy (dry-run)"""
    permission_classes = [IsAuthenticated]

    def get(self, request):
        import re
        from datetime import date as date_cls
        from apps.clients.models import SearchTracking
        from apps.reservation.models import Reservation
        from apps.chatbot.management.commands.send_promo_dates import select_best_search

        config = PromoDateConfig.get_config()
        if not config.is_active:
            return Response({
                'active': False,
                'target_date': None,
                'all_candidates': [],
                'qualified': [],
                'message': 'Promo automática desactivada',
            })

        today = date_cls.today()
        target_date = today + timedelta(days=config.days_before_checkin)

        # --- Clientes registrados ---
        searches = SearchTracking.objects.filter(
            check_in_date=target_date,
            client__isnull=False,
        ).select_related('client')

        client_searches = {}
        for s in searches:
            if s.client_id not in client_searches:
                client_searches[s.client_id] = []
            client_searches[s.client_id].append(s)

        # --- Búsquedas anónimas del chatbot ---
        chatbot_anon = SearchTracking.objects.filter(
            check_in_date=target_date,
            client__isnull=True,
            session_key__startswith='chatbot_',
        )
        anon_searches = {}
        for s in chatbot_anon:
            wa_id = s.session_key.replace('chatbot_', '')
            if wa_id not in anon_searches:
                anon_searches[wa_id] = []
            anon_searches[wa_id].append(s)

        # --- Conjuntos de exclusión ---
        clients_with_reservation = set(
            Reservation.objects.filter(
                deleted=False,
                status__in=['approved', 'pending', 'incomplete', 'under_review'],
                check_in_date__lte=target_date,
                check_out_date__gt=target_date,
            ).values_list('client_id', flat=True)
        )

        clients_already_promo = set(
            PromoDateSent.objects.filter(
                check_in_date=target_date,
                deleted=False,
            ).values_list('client_id', flat=True)
        )

        clients_recent_chat = set()
        if config.exclude_recent_chatters:
            cutoff = timezone.now() - timedelta(hours=24)
            clients_recent_chat = set(
                ChatSession.objects.filter(
                    deleted=False,
                    client__isnull=False,
                    last_customer_message_at__gte=cutoff,
                ).values_list('client_id', flat=True)
            )

        # wa_ids de promos ya enviadas (para anónimos)
        wa_ids_already_promo = set()
        anon_promos = PromoDateSent.objects.filter(
            check_in_date=target_date,
            deleted=False,
            client__isnull=True,
        )
        for p in anon_promos:
            if p.message_content:
                wa_ids_already_promo.add(p.message_content[:20])  # fallback

        # wa_ids de clientes registrados (para dedup cruzado anónimos)
        registered_phones = set()
        for search_list in client_searches.values():
            client = search_list[0].client
            if client.tel_number:
                digits = re.sub(r'\D', '', client.tel_number)
                registered_phones.add(digits)

        # --- Disponibilidad global para target_date ---
        from apps.property.models import Property as PropModel
        all_properties = list(PropModel.objects.filter(deleted=False))

        occupied_property_ids = set(
            Reservation.objects.filter(
                deleted=False,
                status__in=['approved', 'pending', 'under_review'],
                check_in_date__lte=target_date,
                check_out_date__gt=target_date,
            ).values_list('property_id', flat=True)
        )

        available_properties = [p for p in all_properties if p.id not in occupied_property_ids]

        all_candidates = []
        qualified = []

        # --- Procesar clientes registrados ---
        for client_id, search_list in client_searches.items():
            client = search_list[0].client
            check_out_date, guests = select_best_search(search_list)

            candidate = {
                'client_id': str(client.id),
                'client_name': f"{client.first_name} {client.last_name or ''}".strip(),
                'client_phone': client.tel_number or '',
                'check_in_date': str(target_date),
                'check_out_date': str(check_out_date),
                'guests': guests,
                'search_count': len(search_list),
                'source': 'web',
                'exclusion_reason': None,
            }

            if client_id in clients_with_reservation:
                candidate['exclusion_reason'] = 'Tiene reserva activa'
            elif client_id in clients_already_promo:
                candidate['exclusion_reason'] = 'Ya recibió promo'
            elif client_id in clients_recent_chat:
                candidate['exclusion_reason'] = 'Chat activo < 24h'
            elif len(search_list) < config.min_search_count:
                candidate['exclusion_reason'] = f'Solo {len(search_list)} búsqueda(s)'
            elif not client.tel_number:
                candidate['exclusion_reason'] = 'Sin teléfono'

            all_candidates.append(candidate)
            if candidate['exclusion_reason'] is None:
                qualified.append(candidate)

        # --- Procesar búsquedas anónimas del chatbot ---
        for wa_id, search_list in anon_searches.items():
            check_out_date, guests = select_best_search(search_list)

            session = ChatSession.objects.filter(
                wa_id=wa_id, deleted=False,
            ).order_by('-last_message_at').first()
            name = session.wa_profile_name if session else wa_id

            candidate = {
                'client_id': None,
                'client_name': name or wa_id,
                'client_phone': wa_id,
                'check_in_date': str(target_date),
                'check_out_date': str(check_out_date),
                'guests': guests,
                'search_count': len(search_list),
                'source': 'chatbot',
                'exclusion_reason': None,
            }

            digits = re.sub(r'\D', '', wa_id)
            if digits in registered_phones:
                candidate['exclusion_reason'] = 'Ya registrado como cliente'
            elif len(search_list) < config.min_search_count:
                candidate['exclusion_reason'] = f'Solo {len(search_list)} búsqueda(s)'

            all_candidates.append(candidate)
            if candidate['exclusion_reason'] is None:
                qualified.append(candidate)

        return Response({
            'active': True,
            'target_date': str(target_date),
            'discount_config': config.discount_config.name if config.discount_config else None,
            'discount_percentage': float(config.discount_config.discount_percentage) if config.discount_config else None,
            'all_candidates': all_candidates,
            'qualified': qualified,
            'total_candidates': len(all_candidates),
            'total_qualified': len(qualified),
            'available_properties': len(available_properties),
            'available_property_names': [p.name for p in available_properties],
            'total_properties': len(all_properties),
        })


class UnresolvedQuestionListView(ListAPIView):
    """GET /unresolved-questions/ — Preguntas que el bot no pudo responder"""
    serializer_class = UnresolvedQuestionSerializer
    permission_classes = [IsAuthenticated]
    pagination_class = CustomPagination

    def get_queryset(self):
        qs = UnresolvedQuestion.objects.filter(deleted=False).select_related('session')
        status_filter = self.request.query_params.get('status')
        if status_filter:
            qs = qs.filter(status=status_filter)
        category = self.request.query_params.get('category')
        if category:
            qs = qs.filter(category=category)
        return qs.order_by('-created')


class UnresolvedQuestionUpdateView(APIView):
    """PATCH /unresolved-questions/<id>/ — Resolver o ignorar una pregunta"""
    permission_classes = [IsAuthenticated]

    def patch(self, request, pk):
        try:
            question = UnresolvedQuestion.objects.get(pk=pk, deleted=False)
        except UnresolvedQuestion.DoesNotExist:
            return Response({'error': 'Pregunta no encontrada'}, status=status.HTTP_404_NOT_FOUND)

        new_status = request.data.get('status')
        resolution = request.data.get('resolution')

        if new_status:
            valid = [c[0] for c in UnresolvedQuestion.StatusChoices.choices]
            if new_status not in valid:
                return Response({'error': f'Estado inválido. Opciones: {valid}'}, status=status.HTTP_400_BAD_REQUEST)
            question.status = new_status

        if resolution is not None:
            question.resolution = resolution

        question.save(update_fields=['status', 'resolution', 'updated'])
        return Response(UnresolvedQuestionSerializer(question).data)
