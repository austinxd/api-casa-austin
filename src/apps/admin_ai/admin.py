from django.contrib import admin
from .models import AdminChatSession, AdminChatMessage


class AdminChatMessageInline(admin.TabularInline):
    model = AdminChatMessage
    extra = 0
    readonly_fields = ['created', 'role', 'content', 'tool_calls', 'tokens_used']
    fields = ['role', 'content', 'tokens_used', 'created']


@admin.register(AdminChatSession)
class AdminChatSessionAdmin(admin.ModelAdmin):
    list_display = ['title', 'user', 'model_used', 'message_count', 'total_tokens', 'updated']
    list_filter = ['model_used', 'user']
    search_fields = ['title', 'user__first_name', 'user__last_name']
    readonly_fields = ['created', 'updated']
    inlines = [AdminChatMessageInline]


@admin.register(AdminChatMessage)
class AdminChatMessageAdmin(admin.ModelAdmin):
    list_display = ['session', 'role', 'content_preview', 'tokens_used', 'created']
    list_filter = ['role']
    search_fields = ['content']
    readonly_fields = ['created', 'updated']

    def content_preview(self, obj):
        return obj.content[:80] + '...' if len(obj.content) > 80 else obj.content
    content_preview.short_description = 'Contenido'
