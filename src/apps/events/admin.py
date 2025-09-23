from django.contrib import admin
from django.utils.html import format_html
from django.utils.safestring import mark_safe
from .models import EventCategory, Event, EventRegistration, ActivityFeed, ActivityFeedConfig


@admin.register(EventCategory)
class EventCategoryAdmin(admin.ModelAdmin):
    list_display = ['name', 'description', 'icon', 'color']
    search_fields = ['name']
    list_per_page = 20


@admin.register(Event)
class EventAdmin(admin.ModelAdmin):
    list_display = ['title', 'category', 'property_location', 'status', 'event_date', 'registration_deadline', 'max_participants', 'is_public', 'is_active']
    list_filter = ['category', 'status', 'is_public', 'is_active', 'event_date']
    search_fields = ['title', 'description']
    filter_horizontal = ['required_achievements']
    readonly_fields = ['created', 'updated']
    list_per_page = 20
    
    fieldsets = (
        ('Información Básica', {
            'fields': ('title', 'description', 'category', 'image')
        }),
        ('Fechas y Ubicación', {
            'fields': ('event_date', 'registration_deadline', 'location')
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
    list_display = ['event', 'client', 'registration_date', 'status', 'winner_display', 'prize_description']
    list_filter = [
        'status', 
        'winner_status',
        ('event', admin.RelatedOnlyFieldListFilter),  # Filtrar por evento específico
        'registration_date', 
        'event__category'
    ]
    search_fields = ['event__title', 'client__first_name', 'client__last_name']
    readonly_fields = ['registration_date', 'created', 'updated']
    list_per_page = 20
    
    # Acciones personalizadas para marcar ganadores
    actions = ['mark_as_winner', 'mark_as_not_winner']
    
    fieldsets = (
        ('Información del Registro', {
            'fields': ('event', 'client', 'status')
        }),
        ('🏆 Sistema de Ganadores', {
            'fields': ('winner_status', 'prize_description', 'winner_announcement_date', 'winner_notified'),
            'classes': ('collapse',)
        }),
        ('Notas', {
            'fields': ('notes', 'admin_notes'),
            'classes': ('collapse',)
        }),
        ('Timestamps', {
            'fields': ('registration_date', 'created', 'updated'),
            'classes': ('collapse',)
        })
    )
    
    def winner_display(self, obj):
        """Mostrar estado de ganador con emoji"""
        if obj.winner_status == EventRegistration.WinnerStatus.WINNER:
            return "🏆 Ganador"
        return "❌ No ganador"
    winner_display.short_description = "Estado Ganador"
    
    def mark_as_winner(self, request, queryset):
        """Marcar registros seleccionados como ganadores"""
        updated = 0
        for registration in queryset:
            if registration.status == EventRegistration.RegistrationStatus.APPROVED:
                registration.mark_as_winner(
                    winner_status=EventRegistration.WinnerStatus.WINNER,
                    prize_description="Premio del sorteo",
                    notify=True
                )
                updated += 1
        
        if updated:
            self.message_user(request, f"✅ {updated} participantes marcados como ganadores y notificados")
        else:
            self.message_user(request, "⚠️ Solo se pueden marcar como ganadores los participantes aprobados")
    
    mark_as_winner.short_description = "🏆 Marcar como ganador y notificar"
    
    def mark_as_not_winner(self, request, queryset):
        """Quitar estado de ganador a registros seleccionados"""
        updated = queryset.update(winner_status=EventRegistration.WinnerStatus.NOT_WINNER)
        self.message_user(request, f"❌ {updated} participantes ya no son ganadores")
    
    mark_as_not_winner.short_description = "❌ Quitar estado de ganador"


@admin.register(ActivityFeed)
class ActivityFeedAdmin(admin.ModelAdmin):
    """
    Administración completa del Feed de Actividades
    Permite controlar qué actividades aparecen, ocultarlas, editarlas, etc.
    """
    
    # === VISTA DE LISTA ===
    list_display = [
        'activity_icon_display', 
        'get_activity_type_display', 
        'formatted_title_display',
        'client_display',
        'visibility_status',
        'importance_display',
        'time_ago_display',
        'created'
    ]
    
    list_filter = [
        'activity_type',
        'is_public',
        'importance_level',
        'created',
        ('client', admin.RelatedOnlyFieldListFilter),
        ('event', admin.RelatedOnlyFieldListFilter),
        ('property_location', admin.RelatedOnlyFieldListFilter)
    ]
    
    search_fields = [
        'title',
        'description', 
        'client__first_name',
        'client__last_name',
        'event__title',
        'property_location__name'
    ]
    
    readonly_fields = ['created', 'updated', 'formatted_message_preview', 'time_ago']
    
    list_per_page = 25
    # date_hierarchy = 'created'  # Temporalmente desactivado por error de timezone
    ordering = ['-created']
    
    # === ACCIONES EN MASA ===
    actions = [
        'make_public',
        'make_private', 
        'set_high_importance',
        'set_low_importance',
        'mark_as_deleted'
    ]
    
    # === ORGANIZACIÓN DEL FORMULARIO ===
    fieldsets = (
        ('🎯 Información Principal', {
            'fields': ('activity_type', 'title', 'description')
        }),
        ('🔗 Relaciones', {
            'fields': ('client', 'event', 'property_location'),
            'description': 'Conectar con cliente, evento o propiedad específica'
        }),
        ('⚙️ Configuración de Visibilidad', {
            'fields': ('is_public', 'importance_level'),
            'description': 'Controlar si aparece en el feed público y su importancia'
        }),
        ('📄 Datos Adicionales (JSON)', {
            'fields': ('activity_data',),
            'classes': ('collapse',),
            'description': 'Datos específicos del tipo de actividad en formato JSON'
        }),
        ('📝 Vista Previa', {
            'fields': ('formatted_message_preview',),
            'description': 'Cómo se verá en el feed público'
        }),
        ('🕒 Información de Tiempo', {
            'fields': ('time_ago', 'created', 'updated'),
            'classes': ('collapse',)
        })
    )
    
    # === MÉTODOS PERSONALIZADOS PARA LA VISTA ===
    
    def activity_icon_display(self, obj):
        """Mostrar icono de la actividad"""
        icon = obj.get_icon()
        return format_html('<span style="font-size: 1.5em;">{}</span>', icon)
    activity_icon_display.short_description = '🎯'
    
    def formatted_title_display(self, obj):
        """Título formateado con vista previa del mensaje"""
        if len(obj.title) > 50:
            title = obj.title[:47] + "..."
        else:
            title = obj.title
        return format_html(
            '<strong>{}</strong><br><small style="color: #666;">{}</small>', 
            title, 
            obj.get_formatted_message()[:100]
        )
    formatted_title_display.short_description = 'Actividad'
    
    def client_display(self, obj):
        """Mostrar cliente si existe"""
        if obj.client:
            return format_html(
                '<strong>{}</strong><br><small>{}</small>', 
                obj.client.first_name,
                obj.client.last_name
            )
        return format_html('<span style="color: #ccc;">Sin cliente</span>')
    client_display.short_description = 'Cliente'
    
    def visibility_status(self, obj):
        """Estado de visibilidad con colores"""
        if obj.is_public:
            return format_html(
                '<span style="color: green; font-weight: bold;">✅ Público</span>'
            )
        else:
            return format_html(
                '<span style="color: red; font-weight: bold;">❌ Privado</span>'
            )
    visibility_status.short_description = 'Visibilidad'
    
    def importance_display(self, obj):
        """Nivel de importancia con barras"""
        level = obj.importance_level
        bars = '█' * level + '░' * (5 - level)
        color = '#ff4444' if level >= 4 else '#ffaa00' if level >= 3 else '#00aa00'
        return format_html(
            '<span style="color: {}; font-family: monospace;">{}</span> {}', 
            color, bars, level
        )
    importance_display.short_description = 'Importancia'
    
    def time_ago_display(self, obj):
        """Tiempo transcurrido"""
        return obj.time_ago
    time_ago_display.short_description = 'Hace'
    
    def formatted_message_preview(self, obj):
        """Vista previa del mensaje formateado"""
        return format_html(
            '<div style="padding: 10px; background: #f8f9fa; border-radius: 5px; border-left: 4px solid #007bff;">'
            '<strong>{}</strong> {}<br>'
            '<small style="color: #666;">Así se verá en el feed público</small>'
            '</div>',
            obj.get_icon(),
            obj.get_formatted_message()
        )
    formatted_message_preview.short_description = 'Vista Previa del Mensaje'
    
    # === ACCIONES EN MASA ===
    
    def make_public(self, request, queryset):
        """Hacer actividades públicas"""
        updated = queryset.update(is_public=True)
        self.message_user(request, f'{updated} actividades marcadas como públicas.')
    make_public.short_description = '✅ Hacer público'
    
    def make_private(self, request, queryset):
        """Hacer actividades privadas"""
        updated = queryset.update(is_public=False)
        self.message_user(request, f'{updated} actividades marcadas como privadas.')
    make_private.short_description = '❌ Hacer privado'
    
    def set_high_importance(self, request, queryset):
        """Marcar como alta importancia"""
        updated = queryset.update(importance_level=4)
        self.message_user(request, f'{updated} actividades marcadas con alta importancia.')
    set_high_importance.short_description = '🔥 Alta importancia'
    
    def set_low_importance(self, request, queryset):
        """Marcar como baja importancia"""
        updated = queryset.update(importance_level=1)
        self.message_user(request, f'{updated} actividades marcadas con baja importancia.')
    set_low_importance.short_description = '🔽 Baja importancia'
    
    def mark_as_deleted(self, request, queryset):
        """Marcar como eliminadas (soft delete)"""
        updated = queryset.update(deleted=True)
        self.message_user(request, f'{updated} actividades marcadas como eliminadas.')
    mark_as_deleted.short_description = '🗑️ Marcar como eliminado'


@admin.register(ActivityFeedConfig)
class ActivityFeedConfigAdmin(admin.ModelAdmin):
    """
    Configuración Global de Tipos de Actividad
    Controla qué tipos aparecen automáticamente y cómo
    """
    
    list_display = [
        'activity_type_icon_display',
        'activity_type_display',
        'status_display',
        'visibility_display',
        'importance_display',
        'description_short'
    ]
    
    list_filter = [
        'is_enabled',
        'is_public_by_default', 
        'default_importance_level'
    ]
    
    search_fields = ['description']
    
    fieldsets = (
        ('🎯 Tipo de Actividad', {
            'fields': ('activity_type',),
            'description': 'Selecciona el tipo de actividad a configurar'
        }),
        ('⚙️ Configuración de Comportamiento', {
            'fields': ('is_enabled', 'is_public_by_default', 'default_importance_level', 'default_icon', 'default_reason'),
            'description': 'Controla cómo se comportan automáticamente las actividades de este tipo'
        }),
        ('📝 Información Adicional', {
            'fields': ('description',),
            'description': 'Descripción opcional para recordar qué incluye este tipo'
        })
    )
    
    actions = [
        'enable_all_types',
        'disable_all_types',
        'make_all_public',
        'make_all_private'
    ]
    
    def activity_type_icon_display(self, obj):
        """Icono del tipo de actividad"""
        # Usar el icono configurado por el usuario o fallback
        if obj.default_icon:
            icon = obj.default_icon
        else:
            # Mapeo de iconos por defecto solo si no hay configurado
            icon_map = {
                'points_earned': "⭐",
                'reservation_made': "📅",
                'event_created': "🎉",
                'event_registration': "✅",
                'event_winner': "🏆",
                'achievement_earned': "🏅",
                'property_visited': "🏠",
                'payment_completed': "💰",
                'discount_used': "🎫",
                'review_posted': "📝",
                'staff_assigned': "👥",
                'milestone_reached': "🎯",
                'system_update': "📢"
            }
            icon = icon_map.get(obj.activity_type, "📌")
        
        return format_html('<span style="font-size: 1.5em;">{}</span>', icon)
    activity_type_icon_display.short_description = '🎯'
    
    def activity_type_display(self, obj):
        """Nombre del tipo de actividad"""
        return obj.get_activity_type_display()
    activity_type_display.short_description = 'Tipo de Actividad'
    
    def status_display(self, obj):
        """Estado habilitado/deshabilitado"""
        if obj.is_enabled:
            return format_html('<span style="color: green; font-weight: bold;">✅ Habilitado</span>')
        else:
            return format_html('<span style="color: red; font-weight: bold;">❌ Deshabilitado</span>')
    status_display.short_description = 'Estado'
    
    def visibility_display(self, obj):
        """Visibilidad por defecto"""
        if obj.is_public_by_default:
            return format_html('<span style="color: blue;">🌐 Público</span>')
        else:
            return format_html('<span style="color: orange;">🔒 Privado</span>')
    visibility_display.short_description = 'Visibilidad'
    
    def importance_display(self, obj):
        """Nivel de importancia con barras"""
        level = obj.default_importance_level
        bars = '█' * level + '░' * (5 - level)
        color = '#ff4444' if level >= 4 else '#ffaa00' if level >= 3 else '#00aa00'
        return format_html(
            '<span style="color: {}; font-family: monospace;">{}</span> {}', 
            color, bars, level
        )
    importance_display.short_description = 'Importancia'
    
    def description_short(self, obj):
        """Descripción corta"""
        if obj.description:
            return obj.description[:50] + "..." if len(obj.description) > 50 else obj.description
        return format_html('<span style="color: #ccc;">Sin descripción</span>')
    description_short.short_description = 'Descripción'
    
    # === ACCIONES EN MASA ===
    
    def enable_all_types(self, request, queryset):
        """Habilitar todos los tipos seleccionados"""
        updated = queryset.update(is_enabled=True)
        self.message_user(request, f'{updated} tipos de actividad habilitados.')
    enable_all_types.short_description = '✅ Habilitar tipos'
    
    def disable_all_types(self, request, queryset):
        """Deshabilitar todos los tipos seleccionados"""
        updated = queryset.update(is_enabled=False)
        self.message_user(request, f'{updated} tipos de actividad deshabilitados.')
    disable_all_types.short_description = '❌ Deshabilitar tipos'
    
    def make_all_public(self, request, queryset):
        """Hacer públicos por defecto"""
        updated = queryset.update(is_public_by_default=True)
        self.message_user(request, f'{updated} tipos configurados como públicos por defecto.')
    make_all_public.short_description = '🌐 Público por defecto'
    
    def make_all_private(self, request, queryset):
        """Hacer privados por defecto"""
        updated = queryset.update(is_public_by_default=False)
        self.message_user(request, f'{updated} tipos configurados como privados por defecto.')
    make_all_private.short_description = '🔒 Privado por defecto'