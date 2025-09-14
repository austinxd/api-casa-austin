
from rest_framework import viewsets, status
from rest_framework.decorators import action
from rest_framework.response import Response
from rest_framework.permissions import IsAuthenticated
from django.utils import timezone
from django.db.models import Q, Count, Avg
from datetime import datetime, date, timedelta
from .models import StaffMember, TaskType, Task, WorkSession, AutomaticTaskRule
from .serializers import (
    StaffMemberSerializer, TaskTypeSerializer, TaskSerializer, 
    WorkSessionSerializer, CheckInSerializer, CheckOutSerializer
)


class StaffMemberViewSet(viewsets.ModelViewSet):
    queryset = StaffMember.objects.filter(deleted=False, is_active=True)
    serializer_class = StaffMemberSerializer
    permission_classes = [IsAuthenticated]

    @action(detail=True, methods=['get'])
    def tasks(self, request, pk=None):
        """Obtener tareas de un staff member"""
        staff_member = self.get_object()
        date_from = request.query_params.get('date_from')
        date_to = request.query_params.get('date_to')
        
        tasks = Task.objects.filter(
            assigned_to=staff_member,
            deleted=False
        )
        
        if date_from:
            tasks = tasks.filter(scheduled_date__gte=date_from)
        if date_to:
            tasks = tasks.filter(scheduled_date__lte=date_to)
            
        serializer = TaskSerializer(tasks, many=True)
        return Response(serializer.data)

    @action(detail=True, methods=['get'])
    def work_sessions(self, request, pk=None):
        """Obtener sesiones de trabajo de un staff member"""
        staff_member = self.get_object()
        date_from = request.query_params.get('date_from')
        date_to = request.query_params.get('date_to')
        
        sessions = WorkSession.objects.filter(
            staff_member=staff_member,
            deleted=False
        )
        
        if date_from:
            sessions = sessions.filter(check_in_time__date__gte=date_from)
        if date_to:
            sessions = sessions.filter(check_in_time__date__lte=date_to)
            
        serializer = WorkSessionSerializer(sessions, many=True)
        return Response(serializer.data)


class TaskViewSet(viewsets.ModelViewSet):
    queryset = Task.objects.filter(deleted=False)
    serializer_class = TaskSerializer
    permission_classes = [IsAuthenticated]

    def get_queryset(self):
        queryset = super().get_queryset()
        
        # Filtros
        staff_id = self.request.query_params.get('staff_id')
        property_id = self.request.query_params.get('property_id')
        status_filter = self.request.query_params.get('status')
        date_from = self.request.query_params.get('date_from')
        date_to = self.request.query_params.get('date_to')
        
        if staff_id:
            queryset = queryset.filter(assigned_to_id=staff_id)
        if property_id:
            queryset = queryset.filter(property_id=property_id)
        if status_filter:
            queryset = queryset.filter(status=status_filter)
        if date_from:
            queryset = queryset.filter(scheduled_date__gte=date_from)
        if date_to:
            queryset = queryset.filter(scheduled_date__lte=date_to)
            
        return queryset

    @action(detail=True, methods=['post'])
    def start_task(self, request, pk=None):
        """Iniciar una tarea"""
        task = self.get_object()
        task.status = Task.TaskStatus.IN_PROGRESS
        task.actual_start_time = timezone.now()
        task.save()
        
        serializer = TaskSerializer(task)
        return Response(serializer.data)

    @action(detail=True, methods=['post'])
    def complete_task(self, request, pk=None):
        """Completar una tarea"""
        task = self.get_object()
        task.status = Task.TaskStatus.COMPLETED
        task.actual_end_time = timezone.now()
        task.notes = request.data.get('notes', task.notes)
        task.save()
        
        serializer = TaskSerializer(task)
        return Response(serializer.data)

    @action(detail=False, methods=['get'])
    def calendar(self, request):
        """Vista de calendario para tareas"""
        date_param = request.query_params.get('date', str(date.today()))
        view_type = request.query_params.get('view', 'week')  # day, week, month
        
        try:
            target_date = datetime.strptime(date_param, '%Y-%m-%d').date()
        except:
            target_date = date.today()
        
        if view_type == 'day':
            start_date = target_date
            end_date = target_date
        elif view_type == 'week':
            start_date = target_date - timedelta(days=target_date.weekday())
            end_date = start_date + timedelta(days=6)
        else:  # month
            start_date = target_date.replace(day=1)
            next_month = start_date.replace(month=start_date.month + 1) if start_date.month < 12 else start_date.replace(year=start_date.year + 1, month=1)
            end_date = next_month - timedelta(days=1)
        
        tasks = Task.objects.filter(
            deleted=False,
            scheduled_date__range=[start_date, end_date]
        ).select_related('assigned_to', 'property', 'task_type')
        
        serializer = TaskSerializer(tasks, many=True)
        return Response({
            'start_date': start_date,
            'end_date': end_date,
            'view_type': view_type,
            'tasks': serializer.data
        })


class WorkSessionViewSet(viewsets.ModelViewSet):
    queryset = WorkSession.objects.filter(deleted=False)
    serializer_class = WorkSessionSerializer
    permission_classes = [IsAuthenticated]

    @action(detail=False, methods=['post'])
    def check_in(self, request):
        """Registrar entrada del personal"""
        serializer = CheckInSerializer(data=request.data)
        
        if serializer.is_valid():
            data = serializer.validated_data
            
            # Verificar que no hay sesión activa
            active_session = WorkSession.objects.filter(
                staff_member_id=data['staff_member_id'],
                check_out_time__isnull=True,
                deleted=False
            ).first()
            
            if active_session:
                return Response(
                    {'error': 'Ya hay una sesión de trabajo activa para este empleado'},
                    status=status.HTTP_400_BAD_REQUEST
                )
            
            # Crear nueva sesión
            work_session = WorkSession.objects.create(
                staff_member_id=data['staff_member_id'],
                property_id=data['property_id'],
                task_id=data.get('task_id'),
                check_in_time=timezone.now(),
                check_in_latitude=data.get('latitude'),
                check_in_longitude=data.get('longitude'),
                notes=data.get('notes', '')
            )
            
            # Si hay una tarea asociada, marcarla como en progreso
            if work_session.task:
                work_session.task.status = Task.TaskStatus.IN_PROGRESS
                work_session.task.actual_start_time = work_session.check_in_time
                work_session.task.save()
            
            return Response(WorkSessionSerializer(work_session).data)
        
        return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)

    @action(detail=False, methods=['post'])
    def check_out(self, request):
        """Registrar salida del personal"""
        serializer = CheckOutSerializer(data=request.data)
        
        if serializer.is_valid():
            data = serializer.validated_data
            
            try:
                work_session = WorkSession.objects.get(
                    id=data['work_session_id'],
                    check_out_time__isnull=True,
                    deleted=False
                )
            except WorkSession.DoesNotExist:
                return Response(
                    {'error': 'Sesión de trabajo no encontrada o ya finalizada'},
                    status=status.HTTP_404_NOT_FOUND
                )
            
            # Actualizar sesión
            work_session.check_out_time = timezone.now()
            work_session.check_out_latitude = data.get('latitude')
            work_session.check_out_longitude = data.get('longitude')
            work_session.notes = data.get('notes', work_session.notes)
            work_session.save()
            
            # Si hay una tarea asociada, marcarla como completada
            if work_session.task:
                work_session.task.actual_end_time = work_session.check_out_time
                if work_session.task.status == Task.TaskStatus.IN_PROGRESS:
                    work_session.task.status = Task.TaskStatus.COMPLETED
                work_session.task.save()
            
            return Response(WorkSessionSerializer(work_session).data)
        
        return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)

    @action(detail=False, methods=['get'])
    def active_sessions(self, request):
        """Obtener sesiones activas"""
        active_sessions = WorkSession.objects.filter(
            check_out_time__isnull=True,
            deleted=False
        ).select_related('staff_member', 'property', 'task')
        
        serializer = WorkSessionSerializer(active_sessions, many=True)
        return Response(serializer.data)


class StaffDashboardView(viewsets.ViewSet):
    permission_classes = [IsAuthenticated]

    @action(detail=False, methods=['get'])
    def stats(self, request):
        """Estadísticas del personal"""
        today = date.today()
        week_start = today - timedelta(days=today.weekday())
        month_start = today.replace(day=1)
        
        stats = {
            'active_staff': StaffMember.objects.filter(is_active=True, deleted=False).count(),
            'tasks_today': Task.objects.filter(scheduled_date=today, deleted=False).count(),
            'tasks_pending': Task.objects.filter(status=Task.TaskStatus.PENDING, deleted=False).count(),
            'tasks_in_progress': Task.objects.filter(status=Task.TaskStatus.IN_PROGRESS, deleted=False).count(),
            'active_work_sessions': WorkSession.objects.filter(check_out_time__isnull=True, deleted=False).count(),
            'tasks_this_week': Task.objects.filter(scheduled_date__gte=week_start, deleted=False).count(),
            'tasks_this_month': Task.objects.filter(scheduled_date__gte=month_start, deleted=False).count(),
        }
        
        return Response(stats)
