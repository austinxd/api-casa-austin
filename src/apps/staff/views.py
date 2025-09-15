
from django.shortcuts import get_object_or_404
from django.utils import timezone
from django.db.models import Count, Q, F
from rest_framework import viewsets, status
from rest_framework.decorators import action
from rest_framework.response import Response
from rest_framework.permissions import IsAuthenticated
from apps.core.permissions import CustomPermissions
from drf_spectacular.utils import extend_schema, OpenApiParameter
from drf_spectacular.types import OpenApiTypes

from .models import StaffMember, WorkTask, TimeTracking, WorkSchedule, TaskPhoto, PropertyCleaningGap
from .serializers import (
    StaffMemberSerializer, WorkTaskSerializer, WorkTaskCreateSerializer,
    TimeTrackingSerializer, TimeTrackingCreateSerializer, WorkScheduleSerializer,
    StaffDashboardSerializer, PropertyTasksSerializer, TaskPhotoSerializer,
    PropertyCleaningGapSerializer, CleaningGapSummarySerializer
)
from apps.property.models import Property


class StaffMemberViewSet(viewsets.ModelViewSet):
    """ViewSet para gestión de personal"""
    queryset = StaffMember.objects.filter(deleted=False)
    serializer_class = StaffMemberSerializer
    permission_classes = [IsAuthenticated, CustomPermissions]
    
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
    permission_classes = [IsAuthenticated, CustomPermissions]
    
    def get_serializer_class(self):
        if self.action == 'create':
            return WorkTaskCreateSerializer
        return WorkTaskSerializer
    
    def _is_maintenance_user(self):
        """Verificar si el usuario pertenece al grupo mantenimiento"""
        return self.request.user.groups.filter(name='mantenimiento').exists()
    
    def _can_maintenance_update_task(self, task, data):
        """Verificar si mantenimiento puede actualizar esta tarea"""
        import logging
        logger = logging.getLogger(__name__)
        
        logger.info(f"🔍 DEBUG MAINTENANCE VALIDATION - Task ID: {task.id}")
        logger.info(f"   User: {self.request.user.username} (ID: {self.request.user.id})")
        
        # Verificar que el usuario tiene StaffMember asociado
        if not hasattr(self.request.user, 'staffmember'):
            logger.error(f"   ❌ FALLA: hasattr(user, 'staffmember') = False")
            return False
        
        logger.info(f"   ✅ hasattr(user, 'staffmember') = True")
        
        try:
            user_staff = self.request.user.staffmember
            logger.info(f"   ✅ user_staff obtenido: {user_staff.id}")
            
            # Verificación más robusta
            if not user_staff:
                logger.error(f"   ❌ FALLA: user_staff es None/False")
                return False
                
            if user_staff.deleted:
                logger.error(f"   ❌ FALLA: user_staff.deleted = True")
                return False
                
            logger.info(f"   Task staff_member_id: {task.staff_member_id}")
            logger.info(f"   User staff_member_id: {user_staff.id}")
            
            # Comparar por ID para evitar problemas de objetos
            if task.staff_member_id != user_staff.id:
                logger.error(f"   ❌ FALLA: task.staff_member_id ({task.staff_member_id}) != user_staff.id ({user_staff.id})")
                return False
                
            logger.info(f"   ✅ IDs coinciden correctamente")
                
        except StaffMember.DoesNotExist:
            logger.error(f"   ❌ FALLA: StaffMember.DoesNotExist exception")
            return False
        
        # Solo pueden cambiar campos específicos
        allowed_fields = {'status', 'completion_notes'}
        provided_fields = set(data.keys())
        
        logger.info(f"   Campos permitidos: {allowed_fields}")
        logger.info(f"   Campos enviados: {provided_fields}")
        
        fields_ok = provided_fields.issubset(allowed_fields)
        if not fields_ok:
            logger.error(f"   ❌ FALLA: Campos no permitidos")
            return False
            
        logger.info(f"   ✅ VALIDACIÓN COMPLETA EXITOSA")
        return True
    
    def update(self, request, *args, **kwargs):
        """Sobrescribir update para manejo especial de mantenimiento"""
        if self._is_maintenance_user():
            task = self.get_object()
            
            if not self._can_maintenance_update_task(task, request.data):
                return Response({
                    'error': 'Personal de mantenimiento solo puede cambiar el status y notas de finalización de sus propias tareas'
                }, status=status.HTTP_403_FORBIDDEN)
        
        return super().update(request, *args, **kwargs)
    
    def partial_update(self, request, *args, **kwargs):
        """Sobrescribir partial_update para manejo especial de mantenimiento"""
        if self._is_maintenance_user():
            task = self.get_object()
            
            if not self._can_maintenance_update_task(task, request.data):
                return Response({
                    'error': 'Personal de mantenimiento solo puede cambiar el status y notas de finalización de sus propias tareas'
                }, status=status.HTTP_403_FORBIDDEN)
        
        return super().partial_update(request, *args, **kwargs)
    
    def destroy(self, request, *args, **kwargs):
        """Sobrescribir destroy para restringir eliminación a mantenimiento"""
        if self._is_maintenance_user():
            return Response({
                'error': 'Personal de mantenimiento no puede eliminar tareas'
            }, status=status.HTTP_403_FORBIDDEN)
        
        return super().destroy(request, *args, **kwargs)
    
    def create(self, request, *args, **kwargs):
        """Sobrescribir create para restringir creación a mantenimiento"""
        if self._is_maintenance_user():
            return Response({
                'error': 'Personal de mantenimiento no puede crear tareas'
            }, status=status.HTTP_403_FORBIDDEN)
        
        return super().create(request, *args, **kwargs)
    
    def get_queryset(self):
        queryset = super().get_queryset()
        
        # Si es usuario de mantenimiento, solo mostrar sus propias tareas
        if self._is_maintenance_user():
            try:
                user_staff = self.request.user.staffmember
                if user_staff and not user_staff.deleted:
                    queryset = queryset.filter(staff_member=user_staff)
                else:
                    queryset = queryset.none()  # No hay tareas si no es staff member
            except StaffMember.DoesNotExist:
                queryset = queryset.none()
        
        # Filtros generales
        staff_member = self.request.query_params.get('staff_member')
        property_id = self.request.query_params.get('property')
        status_param = self.request.query_params.get('status')
        task_type = self.request.query_params.get('task_type')
        date = self.request.query_params.get('date')
        
        if staff_member and not self._is_maintenance_user():  # Mantenimiento no puede filtrar por otro staff
            queryset = queryset.filter(staff_member_id=staff_member)
        if property_id:
            queryset = queryset.filter(building_property_id=property_id)
        if status_param:
            queryset = queryset.filter(status=status_param)
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
    permission_classes = [IsAuthenticated, CustomPermissions]
    
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


class PropertyCleaningGapViewSet(viewsets.ReadOnlyModelViewSet):
    """ViewSet para consultar gaps de limpieza (solo lectura)"""
    queryset = PropertyCleaningGap.objects.filter(deleted=False)
    serializer_class = PropertyCleaningGapSerializer
    permission_classes = [IsAuthenticated]
    
    def get_queryset(self):
        queryset = super().get_queryset()
        
        # Filtros
        property_id = self.request.query_params.get('property')
        resolved = self.request.query_params.get('resolved')
        reason = self.request.query_params.get('reason')
        date_from = self.request.query_params.get('date_from')
        date_to = self.request.query_params.get('date_to')
        
        if property_id:
            queryset = queryset.filter(building_property_id=property_id)
        if resolved is not None:
            queryset = queryset.filter(resolved=resolved.lower() == 'true')
        if reason:
            queryset = queryset.filter(reason=reason)
        if date_from:
            queryset = queryset.filter(gap_date__gte=date_from)
        if date_to:
            queryset = queryset.filter(gap_date__lte=date_to)
        
        return queryset.order_by('-gap_date')
    
    @extend_schema(
        responses={200: CleaningGapSummarySerializer(many=True)},
        description="Resumen de gaps de limpieza por propiedad"
    )
    @action(detail=False, methods=['get'])
    def summary_by_property(self, request):
        """Resumen de gaps de limpieza agrupados por propiedad"""
        from django.db.models import Count, Sum, Max
        
        # Obtener estadísticas agregadas por propiedad
        properties_with_gaps = PropertyCleaningGap.objects.filter(
            deleted=False
        ).values(
            'building_property_id',
            'building_property__name',
            'building_property__background_color'
        ).annotate(
            total_gaps=Count('id'),
            unresolved_gaps=Count('id', filter=Q(resolved=False)),
            total_days_without_cleaning=Sum('days_without_cleaning'),
            most_recent_gap=Max('gap_date')
        )
        
        # Obtener la razón más común para cada propiedad
        results = []
        for prop in properties_with_gaps:
            # Buscar razón más común para esta propiedad
            most_common = PropertyCleaningGap.objects.filter(
                building_property_id=prop['building_property_id'],
                deleted=False
            ).values('reason').annotate(
                count=Count('reason')
            ).order_by('-count').first()
            
            results.append({
                'property_id': prop['building_property_id'],
                'property_name': prop['building_property__name'],
                'property_background_color': prop['building_property__background_color'],
                'total_gaps': prop['total_gaps'],
                'unresolved_gaps': prop['unresolved_gaps'],
                'total_days_without_cleaning': prop['total_days_without_cleaning'] or 0,
                'most_recent_gap': prop['most_recent_gap'],
                'most_common_reason': most_common['reason'] if most_common else None
            })
        
        serializer = CleaningGapSummarySerializer(results, many=True)
        return Response(serializer.data)
    
    @extend_schema(
        responses={200: 'Dashboard statistics'},
        description="Estadísticas generales de gaps de limpieza"
    )
    @action(detail=False, methods=['get'])
    def dashboard_stats(self, request):
        """Estadísticas generales para dashboard"""
        from django.db.models import Count, Avg
        from datetime import timedelta
        
        today = timezone.now().date()
        last_30_days = today - timedelta(days=30)
        
        # Estadísticas generales
        total_gaps = PropertyCleaningGap.objects.filter(deleted=False).count()
        unresolved_gaps = PropertyCleaningGap.objects.filter(deleted=False, resolved=False).count()
        recent_gaps = PropertyCleaningGap.objects.filter(
            deleted=False, 
            gap_date__gte=last_30_days
        ).count()
        
        # Promedio de días sin limpieza
        avg_days_without_cleaning = PropertyCleaningGap.objects.filter(
            deleted=False,
            resolved=True,
            days_without_cleaning__isnull=False
        ).aggregate(avg=Avg('days_without_cleaning'))['avg'] or 0
        
        # Gaps por razón
        gaps_by_reason = list(PropertyCleaningGap.objects.filter(
            deleted=False
        ).values('reason').annotate(
            count=Count('reason'),
            reason_display=F('reason')  # Podrías agregar get_reason_display
        ).order_by('-count'))
        
        # Tendencia por semana (últimas 4 semanas)
        weekly_trends = []
        for week in range(4):
            week_start = today - timedelta(weeks=week+1)
            week_end = today - timedelta(weeks=week)
            week_gaps = PropertyCleaningGap.objects.filter(
                deleted=False,
                gap_date__gte=week_start,
                gap_date__lt=week_end
            ).count()
            weekly_trends.append({
                'week': f"Semana {4-week}",
                'gaps': week_gaps
            })
        
        return Response({
            'total_gaps': total_gaps,
            'unresolved_gaps': unresolved_gaps,
            'recent_gaps_30_days': recent_gaps,
            'avg_days_without_cleaning': round(avg_days_without_cleaning, 1),
            'gaps_by_reason': gaps_by_reason,
            'weekly_trends': weekly_trends
        })
    
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
