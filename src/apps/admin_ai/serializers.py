from rest_framework import serializers
from .models import AdminChatSession, AdminChatMessage


class AdminChatMessageSerializer(serializers.ModelSerializer):
    class Meta:
        model = AdminChatMessage
        fields = [
            'id', 'created', 'role', 'content',
            'tool_calls', 'tokens_used',
        ]


class AdminChatSessionListSerializer(serializers.ModelSerializer):
    last_message_preview = serializers.SerializerMethodField()

    class Meta:
        model = AdminChatSession
        fields = [
            'id', 'title', 'model_used', 'total_tokens',
            'message_count', 'created', 'updated',
            'last_message_preview',
        ]

    def get_last_message_preview(self, obj):
        last_msg = obj.messages.order_by('-created').first()
        if last_msg:
            return {
                'content': last_msg.content[:100],
                'role': last_msg.role,
                'created': last_msg.created.isoformat(),
            }
        return None


class AdminChatSessionDetailSerializer(serializers.ModelSerializer):
    class Meta:
        model = AdminChatSession
        fields = [
            'id', 'title', 'model_used', 'total_tokens',
            'message_count', 'created', 'updated',
        ]


class SendMessageSerializer(serializers.Serializer):
    message = serializers.CharField(max_length=5000)


class UpdateSessionSerializer(serializers.Serializer):
    title = serializers.CharField(max_length=200)
