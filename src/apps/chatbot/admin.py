from django.contrib import admin
from .models import (
    ChatSession, ChatMessage, ChatbotConfiguration, ChatAnalytics,
    PropertyVisit, PromoDateConfig, PromoDateSent,
)


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


@admin.register(PropertyVisit)
class PropertyVisitAdmin(admin.ModelAdmin):
    list_display = ['visitor_name', 'property', 'visit_date', 'visit_time', 'status', 'visitor_phone', 'guests_count']
    list_filter = ['status', 'property', 'visit_date']
    search_fields = ['visitor_name', 'visitor_phone']
    readonly_fields = ['created', 'updated']
    date_hierarchy = 'visit_date'


@admin.register(PromoDateConfig)
class PromoDateConfigAdmin(admin.ModelAdmin):
    list_display = ['is_active', 'days_before_checkin', 'discount_config', 'wa_template_name', 'send_hour']


@admin.register(PromoDateSent)
class PromoDateSentAdmin(admin.ModelAdmin):
    list_display = ['client', 'check_in_date', 'check_out_date', 'guests', 'discount_code', 'status', 'created']
    list_filter = ['status', 'check_in_date']
    search_fields = ['client__first_name', 'client__last_name', 'client__tel_number']
    readonly_fields = ['created', 'updated']
    date_hierarchy = 'check_in_date'


@admin.register(ChatAnalytics)
class ChatAnalyticsAdmin(admin.ModelAdmin):
    list_display = ['date', 'total_sessions', 'total_messages_in', 'total_messages_out_ai', 'escalations', 'estimated_cost_usd']
    ordering = ['-date']
