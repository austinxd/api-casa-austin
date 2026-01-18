from django.contrib import admin
from django.utils.html import format_html
from .models import TVDevice, TVSession, TVAppVersion


@admin.register(TVDevice)
class TVDeviceAdmin(admin.ModelAdmin):
    list_display = ['room_id', 'property', 'room_name', 'is_active', 'last_heartbeat', 'created']
    list_filter = ['is_active', 'property']
    search_fields = ['room_id', 'room_name', 'property__name']
    readonly_fields = ['created', 'updated', 'last_heartbeat']

    fieldsets = (
        (None, {
            'fields': ('property', 'room_id', 'room_name', 'is_active')
        }),
        ('📺 Mensaje de Bienvenida', {
            'fields': ('welcome_message',),
            'description': 'Mensaje que se muestra en la TV cuando hay un huésped. Si está vacío, se usa la descripción de la propiedad.'
        }),
        ('Status', {
            'fields': ('last_heartbeat',),
            'classes': ('collapse',)
        }),
        ('Timestamps', {
            'fields': ('created', 'updated'),
            'classes': ('collapse',)
        }),
    )


@admin.register(TVSession)
class TVSessionAdmin(admin.ModelAdmin):
    list_display = ['tv_device', 'event_type', 'reservation', 'created']
    list_filter = ['event_type', 'tv_device__property', 'created']
    search_fields = ['tv_device__room_id', 'tv_device__property__name']
    readonly_fields = ['created', 'updated']
    date_hierarchy = 'created'

    def has_add_permission(self, request):
        return False  # Sessions are created automatically

    def has_change_permission(self, request, obj=None):
        return False  # Sessions should not be edited


@admin.register(TVAppVersion)
class TVAppVersionAdmin(admin.ModelAdmin):
    list_display = ['version_display', 'version_code', 'is_current_display', 'force_update', 'apk_link', 'created']
    list_filter = ['is_current', 'force_update']
    search_fields = ['version_name', 'release_notes']
    readonly_fields = ['created', 'updated', 'apk_preview']
    ordering = ['-version_code']

    fieldsets = (
        ('📱 Versión', {
            'fields': ('version_code', 'version_name', 'is_current', 'force_update')
        }),
        ('📦 APK', {
            'fields': ('apk_file', 'apk_preview', 'min_version_code'),
        }),
        ('📝 Notas', {
            'fields': ('release_notes',),
        }),
        ('Timestamps', {
            'fields': ('created', 'updated'),
            'classes': ('collapse',)
        }),
    )

    def version_display(self, obj):
        return f"v{obj.version_name}"
    version_display.short_description = 'Versión'

    def is_current_display(self, obj):
        if obj.is_current:
            return format_html('<span style="color: #28a745; font-weight: bold;">✓ ACTUAL</span>')
        return format_html('<span style="color: #6c757d;">-</span>')
    is_current_display.short_description = 'Estado'

    def apk_link(self, obj):
        if obj.apk_file:
            return format_html('<a href="{}" target="_blank">📥 Descargar</a>', obj.apk_file.url)
        return '-'
    apk_link.short_description = 'APK'

    def apk_preview(self, obj):
        if obj.apk_file:
            size_mb = obj.apk_file.size / (1024 * 1024)
            return format_html(
                '<strong>Archivo:</strong> {}<br>'
                '<strong>Tamaño:</strong> {:.2f} MB<br>'
                '<a href="{}" target="_blank">📥 Descargar APK</a>',
                obj.apk_file.name,
                size_mb,
                obj.apk_file.url
            )
        return 'No hay archivo APK'
    apk_preview.short_description = 'Vista previa'
