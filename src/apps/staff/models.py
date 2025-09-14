
from django.db import models
from django.contrib.auth import get_user_model
from django.conf import settings
from django.utils import timezone
from PIL import Image
import os

from apps.core.models import BaseModel
from apps.property.models import Property
from apps.reservation.models import Reservation


class StaffMember(BaseModel):
    """Modelo para el personal de limpieza y mantenimiento"""
    
    class StaffType(models.TextChoices):
        CLEANING = "cleaning", "Limpieza"
        MAINTENANCE = "maintenance", "Mantenimiento"
        BOTH = "both", "Limpieza y Mantenimiento"
    
    class Status(models.TextChoices):
        ACTIVE = "active", "Activo"
        INACTIVE = "inactive", "Inactivo"
        ON_VACATION = "vacation", "De vacaciones"
        SICK_LEAVE = "sick", "Incapacidad"
    
    user = models.OneToOneField(
        settings.AUTH_USER_MODEL, 
        on_delete=models.CASCADE, 
        null=True, 
        blank=True,
        help_text="Usuario del sistema (opcional)"
    )
    first_name = models.CharField(max_length=100, verbose_name="Nombre")
    last_name = models.CharField(max_length=100, verbose_name="Apellido")
    phone = models.CharField(max_length=20, verbose_name="Teléfono")
    email = models.EmailField(blank=True, null=True, verbose_name="Email")
    staff_type = models.CharField(
        max_length=20, 
        choices=StaffType.choices, 
        default=StaffType.CLEANING,
        verbose_name="Tipo de personal"
    )
    status = models.CharField(
        max_length=20,
        choices=Status.choices,
        default=Status.ACTIVE,
        verbose_name="Estado"
    )
    photo = models.ImageField(
        upload_to="staff_photos/",
        blank=True,
        null=True,
        verbose_name="Foto del personal"
    )
    hire_date = models.DateField(
        blank=True,
        null=True,
        verbose_name="Fecha de contratación"
    )
    daily_rate = models.DecimalField(
        max_digits=10,
        decimal_places=2,
        blank=True,
        null=True,
        verbose_name="Tarifa por día"
    )
    notes = models.TextField(blank=True, verbose_name="Notas adicionales")
    
    # Configuración de trabajo
    can_work_weekends = models.BooleanField(default=True, verbose_name="Puede trabajar fines de semana")
    max_properties_per_day = models.PositiveIntegerField(
        default=3,
        verbose_name="Máximo de propiedades por día"
    )
    preferred_properties = models.ManyToManyField(
        Property,
        blank=True,
        verbose_name="Propiedades preferidas"
    )
    
    class Meta:
        verbose_name = "Personal"
        verbose_name_plural = "Personal"
        ordering = ['first_name', 'last_name']
    
    def __str__(self):
        return f"{self.first_name} {self.last_name} ({self.get_staff_type_display()})"
    
    @property
    def full_name(self):
        return f"{self.first_name} {self.last_name}"
    
    def get_active_tasks_today(self):
        """Obtiene las tareas activas del día de hoy"""
        today = timezone.now().date()
        return self.work_tasks.filter(
            scheduled_date=today,
            status__in=['pending', 'in_progress']
        )


class WorkTask(BaseModel):
    """Modelo para tareas de trabajo asignadas al personal"""
    
    class TaskType(models.TextChoices):
        CHECKOUT_CLEANING = "checkout_cleaning", "Limpieza post-checkout"
        CHECKIN_PREPARATION = "checkin_preparation", "Preparación pre-checkin"
        MAINTENANCE_REPAIR = "maintenance_repair", "Reparación"
        MAINTENANCE_PREVENTIVE = "maintenance_preventive", "Mantenimiento preventivo"
        DEEP_CLEANING = "deep_cleaning", "Limpieza profunda"
        POOL_MAINTENANCE = "pool_maintenance", "Mantenimiento de piscina"
        GARDEN_MAINTENANCE = "garden_maintenance", "Mantenimiento de jardín"
        CUSTOM = "custom", "Tarea personalizada"
    
    class Priority(models.TextChoices):
        LOW = "low", "Baja"
        MEDIUM = "medium", "Media"
        HIGH = "high", "Alta"
        URGENT = "urgent", "Urgente"
    
    class Status(models.TextChoices):
        PENDING = "pending", "Pendiente"
        ASSIGNED = "assigned", "Asignada"
        IN_PROGRESS = "in_progress", "En progreso"
        COMPLETED = "completed", "Completada"
        CANCELLED = "cancelled", "Cancelada"
        NEEDS_REVIEW = "needs_review", "Necesita revisión"
    
    staff_member = models.ForeignKey(
        StaffMember,
        on_delete=models.CASCADE,
        related_name="work_tasks",
        verbose_name="Personal asignado",
        null=True,
        blank=True,
        help_text="Personal asignado a la tarea (puede estar sin asignar)"
    )
    building_property = models.ForeignKey(
        Property,
        on_delete=models.CASCADE,
        verbose_name="Propiedad"
    )
    reservation = models.ForeignKey(
        Reservation,
        on_delete=models.SET_NULL,
        blank=True,
        null=True,
        verbose_name="Reserva relacionada",
        help_text="Solo para tareas de limpieza post-checkout"
    )
    
    task_type = models.CharField(
        max_length=30,
        choices=TaskType.choices,
        verbose_name="Tipo de tarea"
    )
    title = models.CharField(max_length=200, verbose_name="Título de la tarea")
    description = models.TextField(blank=True, verbose_name="Descripción detallada")
    
    scheduled_date = models.DateField(verbose_name="Fecha programada")
    estimated_duration = models.DurationField(
        blank=True,
        null=True,
        verbose_name="Duración estimada",
        help_text="Formato: HH:MM:SS"
    )
    
    priority = models.CharField(
        max_length=10,
        choices=Priority.choices,
        default=Priority.MEDIUM,
        verbose_name="Prioridad"
    )
    status = models.CharField(
        max_length=20,
        choices=Status.choices,
        default=Status.PENDING,
        verbose_name="Estado"
    )
    
    # Tiempos de trabajo
    actual_start_time = models.DateTimeField(
        blank=True,
        null=True,
        verbose_name="Hora real de inicio"
    )
    actual_end_time = models.DateTimeField(
        blank=True,
        null=True,
        verbose_name="Hora real de finalización"
    )
    
    # Validación y evidencia
    requires_photo_evidence = models.BooleanField(
        default=True,
        verbose_name="Requiere evidencia fotográfica"
    )
    completion_notes = models.TextField(
        blank=True,
        verbose_name="Notas de finalización"
    )
    supervisor_approved = models.BooleanField(
        default=False,
        verbose_name="Aprobado por supervisor"
    )
    
    class Meta:
        verbose_name = "Tarea de trabajo"
        verbose_name_plural = "Tareas de trabajo"
        ordering = ['scheduled_date', 'priority']
    
    def __str__(self):
        return f"{self.title} - {self.building_property.name} ({self.scheduled_date})"
    
    @property
    def actual_duration(self):
        """Calcula la duración real de la tarea"""
        if self.actual_start_time and self.actual_end_time:
            return self.actual_end_time - self.actual_start_time
        return None
    
    def can_start_work(self):
        """Verifica si la tarea puede iniciarse"""
        return self.status in ['pending', 'assigned']
    
    def can_complete_work(self):
        """Verifica si la tarea puede completarse"""
        return self.status == 'in_progress'


class TimeTracking(BaseModel):
    """Modelo para control de entrada y salida del personal"""
    
    class ActionType(models.TextChoices):
        CHECK_IN = "check_in", "Entrada"
        CHECK_OUT = "check_out", "Salida"
        BREAK_START = "break_start", "Inicio de descanso"
        BREAK_END = "break_end", "Fin de descanso"
    
    staff_member = models.ForeignKey(
        StaffMember,
        on_delete=models.CASCADE,
        related_name="time_records",
        verbose_name="Personal"
    )
    building_property = models.ForeignKey(
        Property,
        on_delete=models.CASCADE,
        verbose_name="Propiedad"
    )
    work_task = models.ForeignKey(
        WorkTask,
        on_delete=models.CASCADE,
        blank=True,
        null=True,
        verbose_name="Tarea relacionada"
    )
    
    action_type = models.CharField(
        max_length=20,
        choices=ActionType.choices,
        verbose_name="Tipo de acción"
    )
    timestamp = models.DateTimeField(
        default=timezone.now,
        verbose_name="Fecha y hora"
    )
    
    # Validación por ubicación
    latitude = models.DecimalField(
        max_digits=10,
        decimal_places=8,
        blank=True,
        null=True,
        verbose_name="Latitud"
    )
    longitude = models.DecimalField(
        max_digits=11,
        decimal_places=8,
        blank=True,
        null=True,
        verbose_name="Longitud"
    )
    location_verified = models.BooleanField(
        default=False,
        verbose_name="Ubicación verificada"
    )
    
    # Evidencia fotográfica
    photo = models.ImageField(
        upload_to="time_tracking_photos/",
        blank=True,
        null=True,
        verbose_name="Foto de evidencia"
    )
    
    notes = models.TextField(
        blank=True,
        verbose_name="Notas adicionales"
    )
    
    class Meta:
        verbose_name = "Registro de tiempo"
        verbose_name_plural = "Registros de tiempo"
        ordering = ['-timestamp']
    
    def __str__(self):
        return f"{self.staff_member.full_name} - {self.get_action_type_display()} - {self.timestamp.strftime('%d/%m/%Y %H:%M')}"


class WorkSchedule(BaseModel):
    """Modelo para el calendario de trabajo del personal"""
    
    class ScheduleType(models.TextChoices):
        REGULAR = "regular", "Horario regular"
        OVERTIME = "overtime", "Tiempo extra"
        ON_CALL = "on_call", "Disponibilidad"
        VACATION = "vacation", "Vacaciones"
        SICK_LEAVE = "sick_leave", "Incapacidad"
    
    staff_member = models.ForeignKey(
        StaffMember,
        on_delete=models.CASCADE,
        related_name="schedules",
        verbose_name="Personal"
    )
    date = models.DateField(verbose_name="Fecha")
    schedule_type = models.CharField(
        max_length=20,
        choices=ScheduleType.choices,
        default=ScheduleType.REGULAR,
        verbose_name="Tipo de horario"
    )
    
    start_time = models.TimeField(
        blank=True,
        null=True,
        verbose_name="Hora de inicio"
    )
    end_time = models.TimeField(
        blank=True,
        null=True,
        verbose_name="Hora de fin"
    )
    
    is_available = models.BooleanField(
        default=True,
        verbose_name="Disponible"
    )
    
    notes = models.TextField(
        blank=True,
        verbose_name="Notas del día"
    )
    
    class Meta:
        verbose_name = "Horario de trabajo"
        verbose_name_plural = "Horarios de trabajo"
        unique_together = ['staff_member', 'date']
        ordering = ['date']
    
    def __str__(self):
        return f"{self.staff_member.full_name} - {self.date}"


class TaskPhoto(BaseModel):
    """Modelo para fotos de evidencia de tareas"""
    
    work_task = models.ForeignKey(
        WorkTask,
        on_delete=models.CASCADE,
        related_name="photos",
        verbose_name="Tarea"
    )
    photo = models.ImageField(
        upload_to="task_photos/",
        verbose_name="Foto"
    )
    description = models.CharField(
        max_length=200,
        blank=True,
        verbose_name="Descripción"
    )
    uploaded_at = models.DateTimeField(
        default=timezone.now,
        verbose_name="Subida el"
    )
    
    class Meta:
        verbose_name = "Foto de tarea"
        verbose_name_plural = "Fotos de tareas"
        ordering = ['-uploaded_at']
    
    def __str__(self):
        return f"Foto de {self.work_task.title}"


# Señales para auto-asignación de tareas
from django.db.models.signals import post_save
from django.dispatch import receiver


@receiver(post_save, sender=Reservation)
def create_checkout_cleaning_task(sender, instance, **kwargs):
    """Crear automáticamente tarea de limpieza cuando hay un checkout"""
    if instance.status == 'approved':
        # Buscar personal de limpieza disponible
        available_staff = StaffMember.objects.filter(
            status=StaffMember.Status.ACTIVE,
            staff_type__in=[StaffMember.StaffType.CLEANING, StaffMember.StaffType.BOTH]
        )
        
        if available_staff.exists():
            # Asignar al primer disponible (aquí puedes implementar lógica más compleja)
            staff = available_staff.first()
            
            # Crear tarea de limpieza para el día de checkout
            WorkTask.objects.get_or_create(
                staff_member=staff,
                property=instance.property,
                reservation=instance,
                scheduled_date=instance.check_out_date,
                task_type=WorkTask.TaskType.CHECKOUT_CLEANING,
                defaults={
                    'title': f'Limpieza post-checkout - {instance.property.name}',
                    'description': f'Limpieza después del checkout de {instance.client.full_name if instance.client else "Cliente"}',
                    'priority': WorkTask.Priority.HIGH,
                    'status': WorkTask.Status.ASSIGNED,
                }
            )
