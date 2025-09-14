
from django.contrib import admin
from django.utils.html import format_html
from django.urls import reverse
from django.db.models import Count, Q
from django.utils import timezone

from .models import StaffMember, WorkTask, TimeTracking, WorkSchedule, TaskPhoto


@admin.register(StaffMember)
class StaffMemberAdmin(admin.ModelAdmin):
    list_display = (
        'full_name',
        'staff_type',
        'status',
        'phone',
        'get_tasks_today',
        'get_active_status',
        'hire_date'
    )
    list_filter = ('staff_type', 'status', 'can_work_weekends', 'hire_date')
    search_fields = ('first_name', 'last_name', 'phone', 'email')
    filter_horizontal = ('preferred_properties',)
    
    fieldsets = (
        ('Información Personal', {
            'fields': ('first_name', 'last_name', 'phone', 'email', 'photo')
        }),
        ('Información Laboral', {
            'fields': ('staff_type', 'status', 'hire_date', 'daily_rate')
        }),
        ('Configuración de Trabajo', {
            'fields': ('can_work_weekends', 'max_properties_per_day', 'preferred_properties')
        }),
        ('Usuario del Sistema', {
            'fields': ('user',),
            'classes': ('collapse',)
        }),
        ('Notas', {
            'fields': ('notes',),
            'classes': ('collapse',)
        })
    )
    
    def get_tasks_today(self, obj):
        today = timezone.now().date()
        tasks = obj.work_tasks.filter(scheduled_date=today).count()
        if tasks > 0:
            url = reverse('admin:staff_worktask_changelist') + f'?staff_member={obj.id}&scheduled_date={today}'
            return format_html('<a href="{}">{} tareas</a>', url, tasks)
        return '0 tareas'
    get_tasks_today.short_description = 'Tareas hoy'
    
    def get_active_status(self, obj):
        if obj.status == StaffMember.Status.ACTIVE:
            return format_html('<span style="color: green;">●</span> Activo')
        elif obj.status == StaffMember.Status.INACTIVE:
            return format_html('<span style="color: red;">●</span> Inactivo')
        elif obj.status == StaffMember.Status.ON_VACATION:
            return format_html('<span style="color: orange;">●</span> Vacaciones')
        else:
            return format_html('<span style="color: gray;">●</span> Incapacidad')
    get_active_status.short_description = 'Estado'


class TaskPhotoInline(admin.TabularInline):
    model = TaskPhoto
    extra = 1
    readonly_fields = ('uploaded_at',)


@admin.register(WorkTask)
class WorkTaskAdmin(admin.ModelAdmin):
    list_display = (
        'title',
        'staff_member',
        'building_property',
        'scheduled_date',
        'get_priority_display',
        'get_status_display',
        'get_duration',
        'supervisor_approved'
    )
    list_filter = (
        'task_type',
        'priority',
        'status',
        'scheduled_date',
        'supervisor_approved',
        'staff_member__staff_type'
    )
    search_fields = (
        'title',
        'description',
        'staff_member__first_name',
        'staff_member__last_name',
        'building_property__name'
    )
    date_hierarchy = 'scheduled_date'
    inlines = [TaskPhotoInline]
    
    fieldsets = (
        ('Información de la Tarea', {
            'fields': ('title', 'description', 'task_type', 'priority', 'status')
        }),
        ('Asignación', {
            'fields': ('staff_member', 'building_property', 'reservation')
        }),
        ('Programación', {
            'fields': ('scheduled_date', 'estimated_duration')
        }),
        ('Tiempos Reales', {
            'fields': ('actual_start_time', 'actual_end_time'),
            'classes': ('collapse',)
        }),
        ('Validación', {
            'fields': ('requires_photo_evidence', 'completion_notes', 'supervisor_approved'),
            'classes': ('collapse',)
        })
    )
    
    def get_priority_display(self, obj):
        colors = {
            'low': 'green',
            'medium': 'orange',
            'high': 'red',
            'urgent': 'darkred'
        }
        color = colors.get(obj.priority, 'black')
        return format_html(
            '<span style="color: {}; font-weight: bold;">●</span> {}',
            color,
            obj.get_priority_display()
        )
    get_priority_display.short_description = 'Prioridad'
    
    def get_status_display(self, obj):
        colors = {
            'pending': 'gray',
            'assigned': 'blue',
            'in_progress': 'orange',
            'completed': 'green',
            'cancelled': 'red',
            'needs_review': 'purple'
        }
        color = colors.get(obj.status, 'black')
        return format_html(
            '<span style="color: {};">●</span> {}',
            color,
            obj.get_status_display()
        )
    get_status_display.short_description = 'Estado'
    
    def get_duration(self, obj):
        if obj.actual_duration:
            total_seconds = int(obj.actual_duration.total_seconds())
            hours = total_seconds // 3600
            minutes = (total_seconds % 3600) // 60
            return f"{hours}h {minutes}m"
        return "-"
    get_duration.short_description = 'Duración real'
    
    actions = ['mark_as_completed', 'mark_as_approved']
    
    def mark_as_completed(self, request, queryset):
        queryset.update(status=WorkTask.Status.COMPLETED)
        self.message_user(request, f'{queryset.count()} tareas marcadas como completadas.')
    mark_as_completed.short_description = "Marcar como completadas"
    
    def mark_as_approved(self, request, queryset):
        queryset.update(supervisor_approved=True)
        self.message_user(request, f'{queryset.count()} tareas aprobadas por supervisor.')
    mark_as_approved.short_description = "Aprobar por supervisor"


@admin.register(TimeTracking)
class TimeTrackingAdmin(admin.ModelAdmin):
    list_display = (
        'staff_member',
        'building_property',
        'get_action_display',
        'timestamp',
        'get_location_status',
        'get_photo_status'
    )
    list_filter = (
        'action_type',
        'timestamp',
        'location_verified',
        'staff_member'
    )
    search_fields = (
        'staff_member__first_name',
        'staff_member__last_name',
        'building_property__name'
    )
    date_hierarchy = 'timestamp'
    readonly_fields = ('timestamp',)
    
    fieldsets = (
        ('Información Básica', {
            'fields': ('staff_member', 'building_property', 'work_task', 'action_type', 'timestamp')
        }),
        ('Validación de Ubicación', {
            'fields': ('latitude', 'longitude', 'location_verified'),
            'classes': ('collapse',)
        }),
        ('Evidencia', {
            'fields': ('photo', 'notes'),
            'classes': ('collapse',)
        })
    )
    
    def get_action_display(self, obj):
        colors = {
            'check_in': 'green',
            'check_out': 'red',
            'break_start': 'orange',
            'break_end': 'blue'
        }
        color = colors.get(obj.action_type, 'black')
        return format_html(
            '<span style="color: {};">●</span> {}',
            color,
            obj.get_action_type_display()
        )
    get_action_display.short_description = 'Acción'
    
    def get_location_status(self, obj):
        if obj.latitude and obj.longitude:
            if obj.location_verified:
                return format_html('<span style="color: green;">📍 Verificada</span>')
            else:
                return format_html('<span style="color: orange;">📍 Sin verificar</span>')
        return format_html('<span style="color: gray;">📍 Sin ubicación</span>')
    get_location_status.short_description = 'Ubicación'
    
    def get_photo_status(self, obj):
        if obj.photo:
            return format_html('<span style="color: green;">📷 Sí</span>')
        return format_html('<span style="color: gray;">📷 No</span>')
    get_photo_status.short_description = 'Foto'


@admin.register(WorkSchedule)
class WorkScheduleAdmin(admin.ModelAdmin):
    list_display = (
        'staff_member',
        'date',
        'schedule_type',
        'get_work_hours',
        'is_available'
    )
    list_filter = (
        'schedule_type',
        'is_available',
        'date',
        'staff_member'
    )
    search_fields = (
        'staff_member__first_name',
        'staff_member__last_name'
    )
    date_hierarchy = 'date'
    
    def get_work_hours(self, obj):
        if obj.start_time and obj.end_time:
            return f"{obj.start_time.strftime('%H:%M')} - {obj.end_time.strftime('%H:%M')}"
        return "-"
    get_work_hours.short_description = 'Horario'


@admin.register(TaskPhoto)
class TaskPhotoAdmin(admin.ModelAdmin):
    list_display = (
        'work_task',
        'description',
        'uploaded_at',
        'get_photo_preview'
    )
    list_filter = ('uploaded_at', 'work_task__task_type')
    search_fields = (
        'work_task__title',
        'description'
    )
    readonly_fields = ('uploaded_at',)
    
    def get_photo_preview(self, obj):
        if obj.photo:
            return format_html(
                '<img src="{}" width="50" height="50" style="object-fit: cover; border-radius: 4px;"/>',
                obj.photo.url
            )
        return "Sin foto"
    get_photo_preview.short_description = 'Vista previa'


# Configuración del admin
admin.site.site_header = "Casa Austin - Gestión de Staff"
admin.site.site_title = "Staff Admin"
admin.site.index_title = "Panel de Administración de Personal"
