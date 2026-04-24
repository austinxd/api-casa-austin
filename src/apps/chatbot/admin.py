from django.contrib import admin
from .models import (
    ChatSession, ChatMessage, ChatbotConfiguration, ChatAnalytics,
    ChatAnalysisCheckpoint,
    PropertyVisit, PromoDateConfig, PromoDateSent,
    PromoBirthdayConfig, PromoBirthdaySent,
    ReviewRequestConfig, ReviewRequest,
    FrequentQuestion, FrequentQuestionCheckpoint,
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


@admin.register(PromoBirthdayConfig)
class PromoBirthdayConfigAdmin(admin.ModelAdmin):
    list_display = ['is_active', 'days_before_birthday', 'birthday_discount_percentage', 'wa_template_name', 'send_hour']


@admin.register(PromoBirthdaySent)
class PromoBirthdaySentAdmin(admin.ModelAdmin):
    list_display = ['client', 'year', 'status', 'created']
    list_filter = ['status', 'year']
    search_fields = ['client__first_name', 'client__last_name', 'client__tel_number']
    readonly_fields = ['created', 'updated']


@admin.register(ReviewRequestConfig)
class ReviewRequestConfigAdmin(admin.ModelAdmin):
    list_display = ['is_active', 'google_review_url', 'wa_template_name']


@admin.register(ReviewRequest)
class ReviewRequestAdmin(admin.ModelAdmin):
    list_display = ['client', 'reservation', 'status', 'rating', 'achievement_at_send', 'created']
    list_filter = ['status', 'rating']
    search_fields = ['client__first_name', 'client__last_name', 'client__tel_number']
    readonly_fields = ['created', 'updated']
    date_hierarchy = 'created'


@admin.register(ChatAnalysisCheckpoint)
class ChatAnalysisCheckpointAdmin(admin.ModelAdmin):
    list_display = ['last_analyzed_at', 'total_sessions_analyzed', 'total_messages_analyzed', 'notes']
    readonly_fields = ['created', 'updated']
    ordering = ['-last_analyzed_at']


@admin.register(FrequentQuestion)
class FrequentQuestionAdmin(admin.ModelAdmin):
    list_display = ['count', 'category_label', 'label_short', 'last_seen_at', 'first_seen_at']
    list_filter = ['category']
    search_fields = ['label', 'category']
    readonly_fields = ['created', 'updated', 'first_seen_at', 'last_seen_at', 'count', 'sample_messages']
    ordering = ['-count', '-last_seen_at']
    list_per_page = 50

    def label_short(self, obj):
        return (obj.label[:120] + '…') if len(obj.label) > 120 else obj.label
    label_short.short_description = 'Pregunta'


@admin.register(FrequentQuestionCheckpoint)
class FrequentQuestionCheckpointAdmin(admin.ModelAdmin):
    list_display = ['last_analyzed_message_created', 'total_messages_analyzed', 'last_run_at']
    readonly_fields = ['created', 'updated', 'last_run_at']


@admin.register(ChatAnalytics)
class ChatAnalyticsAdmin(admin.ModelAdmin):
    list_display = ['date', 'total_sessions', 'total_messages_in', 'total_messages_out_ai', 'escalations', 'estimated_cost_usd']
    ordering = ['-date']
