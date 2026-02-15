from django.contrib import admin
from .models import ChatSession, ChatMessage, ChatbotConfiguration, ChatAnalytics


@admin.register(ChatSession)
class ChatSessionAdmin(admin.ModelAdmin):
    list_display = ['wa_profile_name', 'wa_id', 'status', 'ai_enabled', 'client', 'total_messages', 'last_message_at']
    list_filter = ['status', 'ai_enabled']
    search_fields = ['wa_id', 'wa_profile_name']
    readonly_fields = ['created', 'updated']


@admin.register(ChatMessage)
class ChatMessageAdmin(admin.ModelAdmin):
    list_display = ['session', 'direction', 'message_type', 'content_preview', 'wa_status', 'created']
    list_filter = ['direction', 'message_type']
    search_fields = ['content', 'wa_message_id']
    readonly_fields = ['created', 'updated']

    def content_preview(self, obj):
        return obj.content[:60] + '...' if len(obj.content) > 60 else obj.content
    content_preview.short_description = 'Contenido'


@admin.register(ChatbotConfiguration)
class ChatbotConfigurationAdmin(admin.ModelAdmin):
    list_display = ['is_active', 'primary_model', 'temperature', 'ai_auto_resume_minutes']


@admin.register(ChatAnalytics)
class ChatAnalyticsAdmin(admin.ModelAdmin):
    list_display = ['date', 'total_sessions', 'total_messages_in', 'total_messages_out_ai', 'escalations', 'estimated_cost_usd']
    ordering = ['-date']
