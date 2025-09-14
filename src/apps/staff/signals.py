
from django.db.models.signals import post_save
from django.dispatch import receiver
from datetime import timedelta
from apps.reservation.models import Reservation
from .models import Task, TaskType, AutomaticTaskRule, StaffMember
import logging

logger = logging.getLogger('apps')


@receiver(post_save, sender=Reservation)
def create_automatic_tasks(sender, instance, created, **kwargs):
    """Crear tareas automáticamente basadas en reservas"""
    
    # Solo procesar reservas aprobadas de Austin o Cliente Web
    if instance.status != 'approved' or instance.origin not in ['aus', 'client']:
        return
    
    # Obtener reglas activas
    rules = AutomaticTaskRule.objects.filter(
        is_active=True,
        deleted=False
    )
    
    for rule in rules:
        # Verificar si la regla aplica a esta propiedad
        if rule.properties.exists() and instance.property not in rule.properties.all():
            continue
        
        # Verificar triggers
        should_create = False
        scheduled_date = None
        
        if rule.trigger_on_checkout and rule.days_after_checkout >= 0:
            scheduled_date = instance.check_out_date + timedelta(days=rule.days_after_checkout)
            should_create = True
        elif rule.trigger_on_checkin and rule.days_before_checkin >= 0:
            scheduled_date = instance.check_in_date - timedelta(days=rule.days_before_checkin)
            should_create = True
        
        if should_create and scheduled_date:
            # Verificar que no existe ya una tarea similar
            existing_task = Task.objects.filter(
                task_type=rule.task_type,
                property=instance.property,
                reservation=instance,
                scheduled_date=scheduled_date,
                deleted=False
            ).first()
            
            if not existing_task:
                # Crear la tarea
                task_title = f"{rule.task_type.name} - {instance.property.name}"
                if rule.trigger_on_checkout:
                    task_title += f" (Post check-out {instance.check_out_date})"
                else:
                    task_title += f" (Pre check-in {instance.check_in_date})"
                
                task = Task.objects.create(
                    task_type=rule.task_type,
                    property=instance.property,
                    reservation=instance,
                    assigned_to=rule.auto_assign_to,
                    title=task_title,
                    description=f"Tarea automática creada por regla: {rule.name}",
                    scheduled_date=scheduled_date,
                    priority=Task.Priority.MEDIUM if rule.trigger_on_checkout else Task.Priority.HIGH
                )
                
                logger.info(f"Tarea automática creada: {task.title} para {scheduled_date}")
