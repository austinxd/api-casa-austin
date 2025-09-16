from django.contrib import admin
from .models import EventCategory, Event, EventRegistration


@admin.register(EventCategory)
class EventCategoryAdmin(admin.ModelAdmin):
    list_display = ['name', 'description', 'icon', 'color']
    search_fields = ['name']
    list_per_page = 20


@admin.register(Event)
class EventAdmin(admin.ModelAdmin):
    list_display = ['title', 'category', 'property_location', 'status', 'start_date', 'end_date', 'max_participants', 'is_public', 'is_active']
    list_filter = ['category', 'status', 'is_public', 'is_active', 'start_date']
    search_fields = ['title', 'description']
    filter_horizontal = ['required_achievements']
    readonly_fields = ['created', 'updated']
    list_per_page = 20
    
    fieldsets = (
        ('Información Básica', {
            'fields': ('title', 'description', 'category', 'image')
        }),
        ('Fechas y Ubicación', {
            'fields': ('start_date', 'end_date', 'registration_deadline', 'location')
        }),
        ('Configuración', {
            'fields': ('status', 'max_participants', 'is_public', 'is_active')
        }),
        ('Restricciones', {
            'fields': ('min_points_required', 'required_achievements')
        }),
        ('Propiedad (solo para estadías)', {
            'fields': ('property_location',),
            'description': 'Seleccionar propiedad solo cuando el evento sea sorteo de estadía/noche gratis'
        }),
        ('Timestamps', {
            'fields': ('created', 'updated'),
            'classes': ('collapse',)
        })
    )


@admin.register(EventRegistration)
class EventRegistrationAdmin(admin.ModelAdmin):
    list_display = ['event', 'client', 'registration_date', 'status']
    list_filter = ['status', 'registration_date', 'event__category']
    search_fields = ['event__title', 'client__first_name', 'client__last_name']
    readonly_fields = ['registration_date', 'created', 'updated']
    list_per_page = 20
    
    fieldsets = (
        ('Información del Registro', {
            'fields': ('event', 'client', 'status')
        }),
        ('Timestamps', {
            'fields': ('registration_date', 'created', 'updated'),
            'classes': ('collapse',)
        })
    )