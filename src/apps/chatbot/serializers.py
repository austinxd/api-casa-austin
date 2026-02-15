from rest_framework import serializers
from .models import ChatSession, ChatMessage, ChatbotConfiguration, ChatAnalytics


class ChatMessageSerializer(serializers.ModelSerializer):
    sent_by_name = serializers.SerializerMethodField()

    class Meta:
        model = ChatMessage
        fields = [
            'id', 'created', 'direction', 'message_type', 'content',
            'media_url', 'wa_message_id', 'wa_status',
            'intent_detected', 'confidence_score', 'ai_model',
            'tokens_used', 'tool_calls', 'sent_by', 'sent_by_name',
        ]

    def get_sent_by_name(self, obj):
        if obj.sent_by:
            return f"{obj.sent_by.first_name} {obj.sent_by.last_name}".strip()
        return None


class ChatSessionListSerializer(serializers.ModelSerializer):
    last_message_preview = serializers.SerializerMethodField()
    unread_count = serializers.IntegerField(read_only=True, default=0)
    client_name = serializers.SerializerMethodField()

    class Meta:
        model = ChatSession
        fields = [
            'id', 'wa_id', 'wa_profile_name', 'client', 'client_name',
            'status', 'ai_enabled', 'current_intent',
            'total_messages', 'ai_messages', 'human_messages',
            'last_message_at', 'last_customer_message_at',
            'last_message_preview', 'unread_count', 'created',
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


class ChatSessionDetailSerializer(serializers.ModelSerializer):
    client_name = serializers.SerializerMethodField()
    client_info = serializers.SerializerMethodField()

    class Meta:
        model = ChatSession
        fields = [
            'id', 'wa_id', 'wa_profile_name', 'client', 'client_name',
            'client_info', 'status', 'ai_enabled', 'ai_paused_at',
            'ai_paused_by', 'ai_resume_at', 'current_intent',
            'conversation_context', 'total_messages', 'ai_messages',
            'human_messages', 'last_message_at',
            'last_customer_message_at', 'created',
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


class ChatAnalyticsSerializer(serializers.ModelSerializer):
    class Meta:
        model = ChatAnalytics
        fields = '__all__'
