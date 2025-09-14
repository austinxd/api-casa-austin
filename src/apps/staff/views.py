
from django.shortcuts import get_object_or_404
from django.utils import timezone
from django.db.models import Count, Q
from rest_framework import viewsets, status
from rest_framework.decorators import action
from rest_framework.response import Response
from rest_framework.permissions import IsAuthenticated
from drf_spectacular.utils import extend_schema, OpenApiParameter
from drf_spectacular.types import OpenApiTypes

from .models import StaffMember, WorkTask, TimeTracking, WorkSchedule, TaskPhoto
from .serializers import (
    StaffMemberSerializer, WorkTaskSerializer, WorkTaskCreateSerializer,
    TimeTrackingSerializer, TimeTrackingCreateSerializer, WorkScheduleSerializer,
    StaffDashboardSerializer, PropertyTasksSerializer, TaskPhotoSerializer
)
from apps.property.models import Property


class StaffMemberViewSet(viewsets.ModelViewSet):
    """ViewSet para gestión de personal"""
    queryset = StaffMember.objects.filter(deleted=False)
    serializer_class = StaffMemberSerializer
    permission_classes = [IsAuthenticated]
    
    def get_queryset(self):
        queryset = super().get_queryset()
        staff_type = self.request.query_params.get('staff_type')
        status = self.request.query_params.get('status')
        
        if staff_type:
            queryset = queryset.filter(staff_type=staff_type)
        if status:
            queryset = queryset.filter(status=status)
            
        return queryset.order_by('first_name', 'last_name')
    
    @extend_schema(
        responses={200: StaffDashboardSerializer(many=True)},
        description="Dashboard del personal con estadísticas del día"
    )
    @action(detail=False, methods=['get'])
    def dashboard(self, request):
        """Dashboard con estadísticas del personal"""
        staff_members = self.get_queryset().filter(status=StaffMember.Status.ACTIVE)
        serializer = StaffDashboardSerializer(staff_members, many=True)
        return Response(serializer.data)
    
    @extend_schema(
        parameters=[
            OpenApiParameter('date', OpenApiTypes.DATE, description='Fecha para obtener tareas (YYYY-MM-DD)')
        ],
        responses={200: WorkTaskSerializer(many=True)}
    )
    @action(detail=True, methods=['get'])
    def tasks(self, request, pk=None):
        """Obtener tareas de un miembro del staff"""
        staff_member = self.get_object()
        date_param = request.query_params.get('date')
        
        tasks = staff_member.work_tasks.filter(deleted=False)
        
        if date_param:
            tasks = tasks.filter(scheduled_date=date_param)
        else:
            # Por defecto, mostrar tareas de hoy
            today = timezone.now().date()
            tasks = tasks.filter(scheduled_date=today)
        
        serializer = WorkTaskSerializer(tasks, many=True)
        return Response(serializer.data)


class WorkTaskViewSet(viewsets.ModelViewSet):
    """ViewSet para gestión de tareas de trabajo"""
    queryset = WorkTask.objects.filter(deleted=False)
    permission_classes = [IsAuthenticated]
    
    def get_serializer_class(self):
        if self.action == 'create':
            return WorkTaskCreateSerializer
        return WorkTaskSerializer
    
    def get_queryset(self):
        queryset = super().get_queryset()
        
        # Filtros
        staff_member = self.request.query_params.get('staff_member')
        property_id = self.request.query_params.get('property')
        status = self.request.query_params.get('status')
        task_type = self.request.query_params.get('task_type')
        date = self.request.query_params.get('date')
        
        if staff_member:
            queryset = queryset.filter(staff_member_id=staff_member)
        if property_id:
            queryset = queryset.filter(building_property_id=property_id)
        if status:
            queryset = queryset.filter(status=status)
        if task_type:
            queryset = queryset.filter(task_type=task_type)
        if date:
            queryset = queryset.filter(scheduled_date=date)
        
        return queryset.order_by('scheduled_date', 'priority')
    
    @action(detail=True, methods=['post'])
    def start_work(self, request, pk=None):
        """Iniciar trabajo en una tarea"""
        task = self.get_object()
        
        if not task.can_start_work():
            return Response(
                {'error': 'La tarea no puede iniciarse en su estado actual'},
                status=status.HTTP_400_BAD_REQUEST
            )
        
        task.status = WorkTask.Status.IN_PROGRESS
        task.actual_start_time = timezone.now()
        task.save()
        
        # Crear registro de tiempo
        TimeTracking.objects.create(
            staff_member=task.staff_member,
            building_property=task.building_property,
            work_task=task,
            action_type=TimeTracking.ActionType.CHECK_IN,
            latitude=request.data.get('latitude'),
            longitude=request.data.get('longitude')
        )
        
        serializer = self.get_serializer(task)
        return Response(serializer.data)
    
    @action(detail=True, methods=['post'])
    def complete_work(self, request, pk=None):
        """Completar trabajo de una tarea"""
        task = self.get_object()
        
        if not task.can_complete_work():
            return Response(
                {'error': 'La tarea no puede completarse en su estado actual'},
                status=status.HTTP_400_BAD_REQUEST
            )
        
        task.status = WorkTask.Status.COMPLETED
        task.actual_end_time = timezone.now()
        task.completion_notes = request.data.get('completion_notes', '')
        task.save()
        
        # Crear registro de tiempo
        TimeTracking.objects.create(
            staff_member=task.staff_member,
            building_property=task.building_property,
            work_task=task,
            action_type=TimeTracking.ActionType.CHECK_OUT,
            latitude=request.data.get('latitude'),
            longitude=request.data.get('longitude'),
            notes=task.completion_notes
        )
        
        serializer = self.get_serializer(task)
        return Response(serializer.data)
    
    @action(detail=True, methods=['post'], url_path='upload-photo')
    def upload_photo(self, request, pk=None):
        """Subir foto de evidencia a una tarea"""
        task = self.get_object()
        
        if 'photo' not in request.FILES:
            return Response(
                {'error': 'No se proporcionó ninguna foto'},
                status=status.HTTP_400_BAD_REQUEST
            )
        
        photo = TaskPhoto.objects.create(
            work_task=task,
            photo=request.FILES['photo'],
            description=request.data.get('description', '')
        )
        
        serializer = TaskPhotoSerializer(photo)
        return Response(serializer.data, status=status.HTTP_201_CREATED)
    
    @extend_schema(
        responses={200: PropertyTasksSerializer(many=True)},
        description="Resumen de tareas por propiedad"
    )
    @action(detail=False, methods=['get'])
    def property_summary(self, request):
        """Resumen de tareas por propiedad"""
        today = timezone.now().date()
        
        properties = Property.objects.filter(deleted=False).annotate(
            pending_tasks=Count(
                'worktask',
                filter=Q(worktask__status__in=['pending', 'assigned', 'in_progress'])
            ),
            tasks_today=Count(
                'worktask',
                filter=Q(worktask__scheduled_date=today)
            )
        )
        
        results = []
        for prop in properties:
            # Buscar última limpieza
            last_cleaning = WorkTask.objects.filter(
                building_property=prop,
                task_type=WorkTask.TaskType.CHECKOUT_CLEANING,
                status=WorkTask.Status.COMPLETED
            ).order_by('-scheduled_date').first()
            
            results.append({
                'property_id': prop.id,
                'property_name': prop.name,
                'pending_tasks': prop.pending_tasks,
                'tasks_today': prop.tasks_today,
                'last_cleaning': last_cleaning.scheduled_date if last_cleaning else None
            })
        
        serializer = PropertyTasksSerializer(results, many=True)
        return Response(serializer.data)


class TimeTrackingViewSet(viewsets.ModelViewSet):
    """ViewSet para registros de tiempo"""
    queryset = TimeTracking.objects.filter(deleted=False)
    permission_classes = [IsAuthenticated]
    
    def get_serializer_class(self):
        if self.action == 'create':
            return TimeTrackingCreateSerializer
        return TimeTrackingSerializer
    
    def get_queryset(self):
        queryset = super().get_queryset()
        
        staff_member = self.request.query_params.get('staff_member')
        date = self.request.query_params.get('date')
        action_type = self.request.query_params.get('action_type')
        
        if staff_member:
            queryset = queryset.filter(staff_member_id=staff_member)
        if date:
            queryset = queryset.filter(timestamp__date=date)
        if action_type:
            queryset = queryset.filter(action_type=action_type)
        
        return queryset.order_by('-timestamp')


class WorkScheduleViewSet(viewsets.ModelViewSet):
    """ViewSet para horarios de trabajo"""
    queryset = WorkSchedule.objects.filter(deleted=False)
    serializer_class = WorkScheduleSerializer
    permission_classes = [IsAuthenticated]
    
    def get_queryset(self):
        queryset = super().get_queryset()
        
        staff_member = self.request.query_params.get('staff_member')
        date = self.request.query_params.get('date')
        month = self.request.query_params.get('month')
        year = self.request.query_params.get('year')
        
        if staff_member:
            queryset = queryset.filter(staff_member_id=staff_member)
        if date:
            queryset = queryset.filter(date=date)
        if month and year:
            queryset = queryset.filter(date__month=month, date__year=year)
        
        return queryset.order_by('date')
    
    @extend_schema(
        parameters=[
            OpenApiParameter('month', OpenApiTypes.INT, description='Mes (1-12)'),
            OpenApiParameter('year', OpenApiTypes.INT, description='Año')
        ]
    )
    @action(detail=False, methods=['get'])
    def calendar(self, request):
        """Vista de calendario mensual para todo el personal"""
        month = request.query_params.get('month')
        year = request.query_params.get('year')
        
        if not month or not year:
            today = timezone.now().date()
            month = today.month
            year = today.year
        
        schedules = self.get_queryset().filter(
            date__month=month,
            date__year=year
        ).select_related('staff_member')
        
        # Agrupar por staff member
        calendar_data = {}
        for schedule in schedules:
            staff_id = schedule.staff_member.id
            if staff_id not in calendar_data:
                calendar_data[staff_id] = {
                    'staff_member': StaffMemberSerializer(schedule.staff_member).data,
                    'schedules': []
                }
            calendar_data[staff_id]['schedules'].append(
                WorkScheduleSerializer(schedule).data
            )
        
        return Response(list(calendar_data.values()))
