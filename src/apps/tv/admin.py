from django.contrib import admin
from .models import TVDevice, TVSession


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
