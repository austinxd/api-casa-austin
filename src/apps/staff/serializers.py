
from rest_framework import serializers
from .models import StaffMember, TaskType, Task, WorkSession, AutomaticTaskRule
from apps.property.serializers import PropertySerializer


class StaffMemberSerializer(serializers.ModelSerializer):
    class Meta:
        model = StaffMember
        fields = '__all__'


class TaskTypeSerializer(serializers.ModelSerializer):
    class Meta:
        model = TaskType
        fields = '__all__'


class TaskSerializer(serializers.ModelSerializer):
    property_detail = PropertySerializer(source='property', read_only=True)
    assigned_to_detail = StaffMemberSerializer(source='assigned_to', read_only=True)
    task_type_detail = TaskTypeSerializer(source='task_type', read_only=True)
    duration_minutes = serializers.ReadOnlyField()

    class Meta:
        model = Task
        fields = '__all__'


class WorkSessionSerializer(serializers.ModelSerializer):
    staff_member_detail = StaffMemberSerializer(source='staff_member', read_only=True)
    property_detail = PropertySerializer(source='property', read_only=True)
    duration_hours = serializers.ReadOnlyField()

    class Meta:
        model = WorkSession
        fields = '__all__'


class CheckInSerializer(serializers.Serializer):
    staff_member_id = serializers.IntegerField()
    property_id = serializers.IntegerField()
    task_id = serializers.IntegerField(required=False)
    latitude = serializers.DecimalField(max_digits=10, decimal_places=8, required=False)
    longitude = serializers.DecimalField(max_digits=11, decimal_places=8, required=False)
    notes = serializers.CharField(required=False, allow_blank=True)


class CheckOutSerializer(serializers.Serializer):
    work_session_id = serializers.IntegerField()
    latitude = serializers.DecimalField(max_digits=10, decimal_places=8, required=False)
    longitude = serializers.DecimalField(max_digits=11, decimal_places=8, required=False)
    notes = serializers.CharField(required=False, allow_blank=True)
