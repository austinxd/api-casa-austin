from rest_framework import serializers
from .models import (
    ChatSession, ChatMessage, ChatbotConfiguration, ChatAnalytics,
    PropertyVisit, PromoDateConfig, PromoDateSent, UnresolvedQuestion,
)


def _get_client_level(client):
    """Retorna el nivel más alto del cliente basado en sus achievements."""
    from apps.clients.models import ClientAchievement
    earned = ClientAchievement.objects.filter(
        client=client, deleted=False
    ).select_related('achievement').order_by(
        '-achievement__required_reservations',
        '-achievement__required_referrals',
    ).first()
    if earned:
        return {
            'name': earned.achievement.name,
            'icon': earned.achievement.icon,
        }
    return None


class ChatMessageSerializer(serializers.ModelSerializer):
    sent_by_name = serializers.SerializerMethodField()
    media_url = serializers.SerializerMethodField()

    class Meta:
        model = ChatMessage
        fields = [
            'id', 'created', 'direction', 'message_type', 'content',
            'media_url', 'wa_message_id', 'wa_status',
            'intent_detected', 'confidence_score', 'ai_model',
            'tokens_used', 'tool_calls', 'sent_by', 'sent_by_name',
        ]

    def get_media_url(self, obj):
        if not obj.media_url:
            return None
        # Si ya es URL absoluta, devolverla tal cual
        if obj.media_url.startswith('http'):
            return obj.media_url
        # Convertir path relativo a URL absoluta
        request = self.context.get('request')
        if request:
            return request.build_absolute_uri(obj.media_url)
        return obj.media_url

    def get_sent_by_name(self, obj):
        if obj.sent_by:
            return f"{obj.sent_by.first_name} {obj.sent_by.last_name}".strip()
        return None


class ChatSessionListSerializer(serializers.ModelSerializer):
    last_message_preview = serializers.SerializerMethodField()
    unread_count = serializers.IntegerField(read_only=True, default=0)
    client_name = serializers.SerializerMethodField()
    client_level = serializers.SerializerMethodField()

    class Meta:
        model = ChatSession
        fields = [
            'id', 'wa_id', 'wa_profile_name', 'channel', 'client',
            'client_name', 'client_level', 'status', 'ai_enabled',
            'current_intent', 'total_messages', 'ai_messages',
            'human_messages', 'last_message_at',
            'last_customer_message_at', 'last_message_preview',
            'unread_count', 'created',
        ]

    def get_last_message_preview(self, obj):
        last_msg = obj.messages.order_by('-created').first()
        if last_msg:
            preview = last_msg.content[:80]
            if len(last_msg.content) > 80:
                preview += '...'
            return {
                'content': preview,
                'direction': last_msg.direction,
                'created': last_msg.created,
            }
        return None

    def get_client_name(self, obj):
        if obj.client:
            return f"{obj.client.first_name} {obj.client.last_name or ''}".strip()
        return obj.wa_profile_name

    def get_client_level(self, obj):
        if not obj.client:
            return None
        return _get_client_level(obj.client)


class ChatSessionDetailSerializer(serializers.ModelSerializer):
    client_name = serializers.SerializerMethodField()
    client_info = serializers.SerializerMethodField()

    class Meta:
        model = ChatSession
        fields = [
            'id', 'wa_id', 'wa_profile_name', 'channel', 'client',
            'client_name', 'client_info', 'status', 'ai_enabled',
            'ai_paused_at', 'ai_paused_by', 'ai_resume_at',
            'current_intent', 'conversation_context',
            'total_messages', 'ai_messages', 'human_messages',
            'last_message_at', 'last_customer_message_at', 'created',
        ]

    def get_client_name(self, obj):
        if obj.client:
            return f"{obj.client.first_name} {obj.client.last_name or ''}".strip()
        return obj.wa_profile_name

    def get_client_info(self, obj):
        if obj.client:
            return {
                'id': str(obj.client.id),
                'first_name': obj.client.first_name,
                'last_name': obj.client.last_name or '',
                'tel_number': obj.client.tel_number,
                'email': obj.client.email,
                'number_doc': obj.client.number_doc,
                'points_balance': float(obj.client.points_balance),
                'level': _get_client_level(obj.client),
            }
        return None


class SendMessageSerializer(serializers.Serializer):
    content = serializers.CharField(max_length=4096)


class ToggleAISerializer(serializers.Serializer):
    ai_enabled = serializers.BooleanField()


class ChatbotConfigurationSerializer(serializers.ModelSerializer):
    class Meta:
        model = ChatbotConfiguration
        fields = '__all__'


class PropertyVisitSerializer(serializers.ModelSerializer):
    property_name = serializers.CharField(source='property.name', read_only=True)
    client_name = serializers.SerializerMethodField()
    session_wa_profile = serializers.CharField(
        source='session.wa_profile_name', read_only=True
    )

    class Meta:
        model = PropertyVisit
        fields = [
            'id', 'created', 'session', 'property', 'property_name',
            'client', 'client_name', 'session_wa_profile',
            'visit_date', 'visit_time', 'visitor_name', 'visitor_phone',
            'guests_count', 'notes', 'status',
        ]

    def get_client_name(self, obj):
        if obj.client:
            return f"{obj.client.first_name} {obj.client.last_name or ''}".strip()
        return None


class ChatAnalyticsSerializer(serializers.ModelSerializer):
    class Meta:
        model = ChatAnalytics
        fields = '__all__'


class PromoDateConfigSerializer(serializers.ModelSerializer):
    discount_config_name = serializers.CharField(
        source='discount_config.name', read_only=True, default=None
    )
    discount_percentage = serializers.DecimalField(
        source='discount_config.discount_percentage',
        max_digits=5, decimal_places=2,
        read_only=True, default=None
    )

    class Meta:
        model = PromoDateConfig
        fields = [
            'id', 'is_active', 'days_before_checkin', 'discount_config',
            'discount_config_name', 'discount_percentage',
            'wa_template_name', 'wa_template_language',
            'max_promos_per_client', 'min_search_count',
            'send_hour', 'exclude_recent_chatters',
            'created', 'updated',
        ]


class PromoDateSentSerializer(serializers.ModelSerializer):
    client_name = serializers.SerializerMethodField()
    client_phone = serializers.CharField(source='client.tel_number', read_only=True)
    discount_code_str = serializers.CharField(
        source='discount_code.code', read_only=True, default=None
    )

    class Meta:
        model = PromoDateSent
        fields = [
            'id', 'client', 'client_name', 'client_phone',
            'check_in_date', 'check_out_date', 'guests',
            'discount_code', 'discount_code_str',
            'wa_message_id', 'message_content', 'pricing_snapshot',
            'status', 'created',
        ]

    def get_client_name(self, obj):
        if obj.client:
            return f"{obj.client.first_name} {obj.client.last_name or ''}".strip()
        return None


class UnresolvedQuestionSerializer(serializers.ModelSerializer):
    session_name = serializers.SerializerMethodField()

    class Meta:
        model = UnresolvedQuestion
        fields = [
            'id', 'session', 'session_name', 'question', 'context',
            'category', 'status', 'resolution', 'created',
        ]
        read_only_fields = ['session', 'question', 'context', 'category', 'created']

    def get_session_name(self, obj):
        s = obj.session
        if s.client:
            return f"{s.client.first_name} {s.client.last_name or ''}".strip()
        return s.wa_profile_name or s.wa_id
