
from django.db import models
from django.utils import timezone
from apps.core.models import BaseModel
from apps.property.models import Property
from apps.reservation.models import Reservation


class StaffMember(BaseModel):
    class StaffRole(models.TextChoices):
        CLEANING = "cleaning", "Limpieza"
        MAINTENANCE = "maintenance", "Mantenimiento"
        BOTH = "both", "Limpieza y Mantenimiento"

    first_name = models.CharField(max_length=100)
    last_name = models.CharField(max_length=100)
    phone = models.CharField(max_length=20, unique=True)
    email = models.EmailField(blank=True, null=True)
    role = models.CharField(max_length=20, choices=StaffRole.choices)
    is_active = models.BooleanField(default=True)
    profile_photo = models.ImageField(upload_to='staff_photos/', blank=True, null=True)

    def __str__(self):
        return f"{self.first_name} {self.last_name} ({self.get_role_display()})"

    @property
    def full_name(self):
        return f"{self.first_name} {self.last_name}"


class TaskType(BaseModel):
    name = models.CharField(max_length=100)
    description = models.TextField(blank=True)
    estimated_duration_minutes = models.PositiveIntegerField(default=60)
    is_cleaning = models.BooleanField(default=False)
    is_maintenance = models.BooleanField(default=False)

    def __str__(self):
        return self.name


class Task(BaseModel):
    class TaskStatus(models.TextChoices):
        PENDING = "pending", "Pendiente"
        IN_PROGRESS = "in_progress", "En Progreso"
        COMPLETED = "completed", "Completada"
        CANCELLED = "cancelled", "Cancelada"

    class Priority(models.TextChoices):
        LOW = "low", "Baja"
        MEDIUM = "medium", "Media"
        HIGH = "high", "Alta"
        URGENT = "urgent", "Urgente"

    task_type = models.ForeignKey(TaskType, on_delete=models.CASCADE)
    property = models.ForeignKey(Property, on_delete=models.CASCADE)
    assigned_to = models.ForeignKey(StaffMember, on_delete=models.CASCADE, related_name='assigned_tasks')
    reservation = models.ForeignKey(Reservation, on_delete=models.CASCADE, blank=True, null=True, 
                                  help_text="Reserva asociada si es tarea de limpieza post-checkout")
    
    title = models.CharField(max_length=200)
    description = models.TextField(blank=True)
    priority = models.CharField(max_length=10, choices=Priority.choices, default=Priority.MEDIUM)
    status = models.CharField(max_length=15, choices=TaskStatus.choices, default=TaskStatus.PENDING)
    
    scheduled_date = models.DateField()
    scheduled_start_time = models.TimeField(blank=True, null=True)
    scheduled_end_time = models.TimeField(blank=True, null=True)
    
    actual_start_time = models.DateTimeField(blank=True, null=True)
    actual_end_time = models.DateTimeField(blank=True, null=True)
    
    notes = models.TextField(blank=True, help_text="Notas del trabajador")
    admin_notes = models.TextField(blank=True, help_text="Notas administrativas")
    
    created_by = models.ForeignKey('accounts.CustomUser', on_delete=models.SET_NULL, null=True, blank=True)

    class Meta:
        ordering = ['scheduled_date', 'priority', 'scheduled_start_time']

    def __str__(self):
        return f"{self.title} - {self.property.name} ({self.scheduled_date})"

    @property
    def duration_minutes(self):
        if self.actual_start_time and self.actual_end_time:
            delta = self.actual_end_time - self.actual_start_time
            return int(delta.total_seconds() / 60)
        return None


class WorkSession(BaseModel):
    """Registro de entrada y salida del personal"""
    staff_member = models.ForeignKey(StaffMember, on_delete=models.CASCADE, related_name='work_sessions')
    property = models.ForeignKey(Property, on_delete=models.CASCADE)
    task = models.ForeignKey(Task, on_delete=models.CASCADE, blank=True, null=True)
    
    check_in_time = models.DateTimeField()
    check_out_time = models.DateTimeField(blank=True, null=True)
    
    # Ubicación GPS para validar que está en la propiedad
    check_in_latitude = models.DecimalField(max_digits=10, decimal_places=8, blank=True, null=True)
    check_in_longitude = models.DecimalField(max_digits=11, decimal_places=8, blank=True, null=True)
    check_out_latitude = models.DecimalField(max_digits=10, decimal_places=8, blank=True, null=True)
    check_out_longitude = models.DecimalField(max_digits=11, decimal_places=8, blank=True, null=True)
    
    notes = models.TextField(blank=True)

    class Meta:
        ordering = ['-check_in_time']

    def __str__(self):
        return f"{self.staff_member.full_name} - {self.property.name} ({self.check_in_time.date()})"

    @property
    def duration_hours(self):
        if self.check_in_time and self.check_out_time:
            delta = self.check_out_time - self.check_in_time
            return round(delta.total_seconds() / 3600, 2)
        return None


class AutomaticTaskRule(BaseModel):
    """Reglas para crear tareas automáticamente"""
    name = models.CharField(max_length=100)
    task_type = models.ForeignKey(TaskType, on_delete=models.CASCADE)
    trigger_on_checkout = models.BooleanField(default=False)
    trigger_on_checkin = models.BooleanField(default=False)
    days_before_checkin = models.PositiveIntegerField(default=0)
    days_after_checkout = models.PositiveIntegerField(default=0)
    
    properties = models.ManyToManyField(Property, blank=True, 
                                      help_text="Si está vacío, aplica a todas las propiedades")
    
    auto_assign_to = models.ForeignKey(StaffMember, on_delete=models.SET_NULL, null=True, blank=True,
                                     help_text="Staff member para auto-asignar, si está vacío requiere asignación manual")
    
    is_active = models.BooleanField(default=True)

    def __str__(self):
        return self.name
