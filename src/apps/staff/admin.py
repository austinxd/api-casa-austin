
from django.contrib import admin
from .models import StaffMember, TaskType, Task, WorkSession, AutomaticTaskRule


@admin.register(StaffMember)
class StaffMemberAdmin(admin.ModelAdmin):
    list_display = ['full_name', 'role', 'phone', 'is_active']
    list_filter = ['role', 'is_active']
    search_fields = ['first_name', 'last_name', 'phone', 'email']


@admin.register(TaskType)
class TaskTypeAdmin(admin.ModelAdmin):
    list_display = ['name', 'estimated_duration_minutes', 'is_cleaning', 'is_maintenance']
    list_filter = ['is_cleaning', 'is_maintenance']


@admin.register(Task)
class TaskAdmin(admin.ModelAdmin):
    list_display = ['title', 'property', 'assigned_to', 'status', 'priority', 'scheduled_date']
    list_filter = ['status', 'priority', 'task_type', 'assigned_to', 'property']
    search_fields = ['title', 'description']
    date_hierarchy = 'scheduled_date'


@admin.register(WorkSession)
class WorkSessionAdmin(admin.ModelAdmin):
    list_display = ['staff_member', 'property', 'check_in_time', 'check_out_time', 'duration_hours']
    list_filter = ['staff_member', 'property']
    date_hierarchy = 'check_in_time'


@admin.register(AutomaticTaskRule)
class AutomaticTaskRuleAdmin(admin.ModelAdmin):
    list_display = ['name', 'task_type', 'trigger_on_checkout', 'trigger_on_checkin', 'is_active']
    list_filter = ['trigger_on_checkout', 'trigger_on_checkin', 'is_active']
