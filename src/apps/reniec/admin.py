from django.contrib import admin
from django.utils.html import format_html
from .models import DNICache, DNIQueryLog, APIKey


@admin.register(DNICache)
class DNICacheAdmin(admin.ModelAdmin):
    list_display = ['dni', 'nombres', 'apellido_paterno', 'apellido_materno', 'sexo', 'source', 'created', 'updated']
    list_filter = ['sexo', 'source', 'created']
    search_fields = ['dni', 'nombres', 'apellido_paterno', 'apellido_materno']
    readonly_fields = ['id', 'created', 'updated', 'raw_data']
    ordering = ['-created']

    fieldsets = (
        ('Identificación', {
            'fields': ('id', 'dni', 'digito_verificacion')
        }),
        ('Datos Personales', {
            'fields': ('nombres', 'apellido_paterno', 'apellido_materno', 'apellido_casada',
                      'fecha_nacimiento', 'sexo', 'estado_civil')
        }),
        ('Lugar de Nacimiento', {
            'fields': ('departamento', 'provincia', 'distrito')
        }),
        ('Dirección Actual', {
            'fields': ('departamento_direccion', 'provincia_direccion', 'distrito_direccion', 'direccion')
        }),
        ('Documento', {
            'fields': ('fecha_emision', 'fecha_caducidad', 'ubigeo_reniec', 'ubigeo_inei')
        }),
        ('Foto', {
            'fields': ('foto',),
            'classes': ('collapse',)
        }),
        ('Datos Técnicos', {
            'fields': ('source', 'raw_data', 'created', 'updated'),
            'classes': ('collapse',)
        }),
    )


@admin.register(DNIQueryLog)
class DNIQueryLogAdmin(admin.ModelAdmin):
    list_display = ['dni', 'source_app', 'success_badge', 'from_cache_badge', 'response_time_ms', 'created']
    list_filter = ['source_app', 'success', 'from_cache', 'created']
    search_fields = ['dni', 'source_app', 'source_ip']
    readonly_fields = ['id', 'created']
    ordering = ['-created']
    date_hierarchy = 'created'

    def success_badge(self, obj):
        if obj.success:
            return format_html('<span style="color: green;">✓ Exitoso</span>')
        return format_html('<span style="color: red;">✗ Error</span>')
    success_badge.short_description = 'Estado'

    def from_cache_badge(self, obj):
        if obj.from_cache:
            return format_html('<span style="color: blue;">📦 Cache</span>')
        return format_html('<span style="color: orange;">🌐 API</span>')
    from_cache_badge.short_description = 'Fuente'


@admin.register(APIKey)
class APIKeyAdmin(admin.ModelAdmin):
    list_display = ['name', 'key_preview', 'is_active_badge', 'rate_limit_per_day', 'rate_limit_per_minute',
                   'can_view_photo', 'can_view_full_data', 'last_used', 'created']
    list_filter = ['is_active', 'can_view_photo', 'can_view_full_data', 'created']
    search_fields = ['name', 'key']
    readonly_fields = ['id', 'key', 'created', 'updated', 'last_used']
    ordering = ['-created']

    fieldsets = (
        ('Identificación', {
            'fields': ('id', 'name', 'key', 'is_active')
        }),
        ('Límites', {
            'fields': ('rate_limit_per_day', 'rate_limit_per_minute')
        }),
        ('Permisos', {
            'fields': ('can_view_photo', 'can_view_full_data')
        }),
        ('Metadatos', {
            'fields': ('notes', 'created', 'updated', 'last_used')
        }),
    )

    def key_preview(self, obj):
        """Muestra solo los primeros y últimos caracteres de la key"""
        if obj.key:
            return f"{obj.key[:8]}...{obj.key[-8:]}"
        return '-'
    key_preview.short_description = 'API Key'

    def is_active_badge(self, obj):
        if obj.is_active:
            return format_html('<span style="color: green;">✓ Activa</span>')
        return format_html('<span style="color: red;">✗ Inactiva</span>')
    is_active_badge.short_description = 'Estado'

    def save_model(self, request, obj, form, change):
        """Al crear, genera una nueva API key automáticamente"""
        if not obj.key:
            obj.key = APIKey.generate_key()
        super().save_model(request, obj, form, change)

    actions = ['regenerate_key', 'activate_keys', 'deactivate_keys']

    @admin.action(description='Regenerar API Key seleccionadas')
    def regenerate_key(self, request, queryset):
        for api_key in queryset:
            api_key.key = APIKey.generate_key()
            api_key.save()
        self.message_user(request, f'Se regeneraron {queryset.count()} API Keys.')

    @admin.action(description='Activar API Keys seleccionadas')
    def activate_keys(self, request, queryset):
        queryset.update(is_active=True)
        self.message_user(request, f'Se activaron {queryset.count()} API Keys.')

    @admin.action(description='Desactivar API Keys seleccionadas')
    def deactivate_keys(self, request, queryset):
        queryset.update(is_active=False)
        self.message_user(request, f'Se desactivaron {queryset.count()} API Keys.')
