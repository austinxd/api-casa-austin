
from rest_framework import serializers
from django.utils import timezone
from .models import StaffMember, WorkTask, TimeTracking, WorkSchedule, TaskPhoto, PropertyCleaningGap


class StaffMemberSerializer(serializers.ModelSerializer):
    full_name = serializers.ReadOnlyField()
    tasks_today = serializers.SerializerMethodField()
    
    class Meta:
        model = StaffMember
        fields = [
            'id', 'full_name', 'first_name', 'last_name', 'phone', 'email',
            'staff_type', 'status', 'photo', 'hire_date', 'daily_rate',
            'can_work_weekends', 'max_properties_per_day', 'tasks_today'
        ]
    
    def get_tasks_today(self, obj):
        today = timezone.now().date()
        return obj.work_tasks.filter(scheduled_date=today).count()


class TaskPhotoSerializer(serializers.ModelSerializer):
    class Meta:
        model = TaskPhoto
        fields = ['id', 'photo', 'description', 'uploaded_at']


class WorkTaskSerializer(serializers.ModelSerializer):
    staff_member_name = serializers.CharField(source='staff_member.full_name', read_only=True)
    property_name = serializers.CharField(source='building_property.name', read_only=True)
    property_background_color = serializers.CharField(source='building_property.background_color', read_only=True)
    check_out_date = serializers.SerializerMethodField()
    actual_duration_display = serializers.SerializerMethodField()
    estimated_duration = serializers.SerializerMethodField()
    scheduled_date = serializers.DateField(input_formats=['%Y-%m-%d', '%Y-%m-%dT%H:%M:%S%z', '%Y-%m-%dT%H:%M:%SZ'])
    photos = TaskPhotoSerializer(many=True, read_only=True)
    
    class Meta:
        model = WorkTask
        fields = [
            'id', 'staff_member', 'staff_member_name', 'building_property', 'property_name',
            'property_background_color', 'reservation', 'check_out_date', 'task_type', 'title', 'description', 'scheduled_date',
            'estimated_duration', 'priority', 'status', 'actual_start_time',
            'actual_end_time', 'actual_duration_display', 'requires_photo_evidence',
            'completion_notes', 'supervisor_approved', 'photos'
        ]
    
    def get_actual_duration_display(self, obj):
        if obj.actual_duration:
            total_seconds = int(obj.actual_duration.total_seconds())
            hours = total_seconds // 3600
            minutes = (total_seconds % 3600) // 60
            return f"{hours}h {minutes}m"
        return None
    
    def get_estimated_duration(self, obj):
        """Formatear estimated_duration para evitar NaN"""
        if obj.estimated_duration:
            total_seconds = int(obj.estimated_duration.total_seconds())
            hours = total_seconds // 3600
            minutes = (total_seconds % 3600) // 60
            return f"{hours}h {minutes}m"
        return "No definida"
    
    def get_check_out_date(self, obj):
        """Obtener fecha de checkout de la reserva asociada"""
        if obj.reservation:
            return obj.reservation.check_out_date
        return None


class WorkTaskCreateSerializer(serializers.ModelSerializer):
    scheduled_date = serializers.DateField(input_formats=['%Y-%m-%d', '%Y-%m-%dT%H:%M:%S%z', '%Y-%m-%dT%H:%M:%SZ'])
    estimated_duration = serializers.DurationField()
    
    class Meta:
        model = WorkTask
        fields = [
            'staff_member', 'building_property', 'reservation', 'task_type',
            'title', 'description', 'scheduled_date', 'estimated_duration',
            'priority', 'requires_photo_evidence'
        ]


class TimeTrackingSerializer(serializers.ModelSerializer):
    staff_member_name = serializers.CharField(source='staff_member.full_name', read_only=True)
    property_name = serializers.CharField(source='building_property.name', read_only=True)
    
    class Meta:
        model = TimeTracking
        fields = [
            'id', 'staff_member', 'staff_member_name', 'building_property', 'property_name',
            'work_task', 'action_type', 'timestamp', 'latitude', 'longitude',
            'location_verified', 'photo', 'notes'
        ]


class TimeTrackingCreateSerializer(serializers.ModelSerializer):
    class Meta:
        model = TimeTracking
        fields = [
            'staff_member', 'building_property', 'work_task', 'action_type',
            'latitude', 'longitude', 'photo', 'notes'
        ]
    
    def create(self, validated_data):
        # Validar ubicación automáticamente si se proporcionan coordenadas
        if validated_data.get('latitude') and validated_data.get('longitude'):
            # Aquí puedes implementar lógica para verificar si está cerca de la propiedad
            validated_data['location_verified'] = True
        
        return super().create(validated_data)


class WorkScheduleSerializer(serializers.ModelSerializer):
    staff_member_name = serializers.CharField(source='staff_member.full_name', read_only=True)
    work_hours_display = serializers.SerializerMethodField()
    
    class Meta:
        model = WorkSchedule
        fields = [
            'id', 'staff_member', 'staff_member_name', 'date', 'schedule_type',
            'start_time', 'end_time', 'work_hours_display', 'is_available', 'notes'
        ]
    
    def get_work_hours_display(self, obj):
        if obj.start_time and obj.end_time:
            return f"{obj.start_time.strftime('%H:%M')} - {obj.end_time.strftime('%H:%M')}"
        return None


# Serializers específicos para dashboard
class StaffDashboardSerializer(serializers.ModelSerializer):
    tasks_pending = serializers.SerializerMethodField()
    tasks_completed_today = serializers.SerializerMethodField()
    current_task = serializers.SerializerMethodField()
    
    class Meta:
        model = StaffMember
        fields = [
            'id', 'full_name', 'staff_type', 'status', 'photo',
            'tasks_pending', 'tasks_completed_today', 'current_task'
        ]
    
    def get_tasks_pending(self, obj):
        return obj.work_tasks.filter(
            status__in=['pending', 'assigned', 'in_progress']
        ).count()
    
    def get_tasks_completed_today(self, obj):
        today = timezone.now().date()
        return obj.work_tasks.filter(
            scheduled_date=today,
            status='completed'
        ).count()
    
    def get_current_task(self, obj):
        current = obj.work_tasks.filter(status='in_progress').first()
        if current:
            return {
                'id': current.id,
                'title': current.title,
                'property': current.building_property.name
            }
        return None


class PropertyTasksSerializer(serializers.Serializer):
    property_id = serializers.UUIDField()
    property_name = serializers.CharField()
    pending_tasks = serializers.IntegerField()
    tasks_today = serializers.IntegerField()
    last_cleaning = serializers.DateField(allow_null=True)


class PropertyCleaningGapSerializer(serializers.ModelSerializer):
    property_name = serializers.CharField(source='building_property.name', read_only=True)
    property_background_color = serializers.CharField(source='building_property.background_color', read_only=True)
    client_name = serializers.SerializerMethodField()
    check_out_date = serializers.SerializerMethodField()
    days_without_cleaning = serializers.ReadOnlyField()
    reason_display = serializers.CharField(source='get_reason_display', read_only=True)
    
    class Meta:
        model = PropertyCleaningGap
        fields = [
            'id', 'building_property', 'property_name', 'property_background_color',
            'reservation', 'client_name', 'check_out_date', 'gap_date', 'reason', 'reason_display',
            'original_required_date', 'rescheduled_date', 'resolved', 
            'days_without_cleaning', 'notes', 'created', 'updated'
        ]
    
    def get_client_name(self, obj):
        if obj.reservation and obj.reservation.client:
            return f"{obj.reservation.client.first_name} {obj.reservation.client.last_name}".strip()
        return None
    
    def get_check_out_date(self, obj):
        if obj.reservation:
            return obj.reservation.check_out_date
        return None


class CleaningGapSummarySerializer(serializers.Serializer):
    property_id = serializers.UUIDField()
    property_name = serializers.CharField()
    property_background_color = serializers.CharField()
    total_gaps = serializers.IntegerField()
    unresolved_gaps = serializers.IntegerField()
    total_days_without_cleaning = serializers.IntegerField()
    most_recent_gap = serializers.DateField(allow_null=True)
    most_common_reason = serializers.CharField(allow_null=True)
