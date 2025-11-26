import logging
from django.db.models.signals import post_save, pre_save, pre_delete
from django.dispatch import receiver
from django.utils import timezone
from .models import Reservation, RentalReceipt
from ..core.telegram_notifier import send_telegram_message
from django.conf import settings
from .points_signals import check_and_assign_achievements
from datetime import datetime, date
import hashlib
import requests
import json

logger = logging.getLogger('apps')

# Import staff models for task updating
try:
    from ..staff.models import WorkTask, StaffMember, PropertyCleaningGap
except ImportError:
    # Fallback in case staff app is not installed
    WorkTask = None
    StaffMember = None
    PropertyCleaningGap = None

# Diccionarios para fechas en español
MONTHS_ES = {
    1: "enero",
    2: "febrero",
    3: "marzo",
    4: "abril",
    5: "mayo",
    6: "junio",
    7: "julio",
    8: "agosto",
    9: "septiembre",
    10: "octubre",
    11: "noviembre",
    12: "diciembre"
}

DAYS_ES = {
    0: "Lunes",
    1: "Martes",
    2: "Miércoles",
    3: "Jueves",
    4: "Viernes",
    5: "Sábado",
    6: "Domingo"
}

# CONSTANTES PARA SISTEMA DE PRIORIDADES
URGENT_BOOST = 1000  # Puntos extra para check-in el mismo día del check-out
BASE_PROXIMITY = 200  # Puntos base para proximidad
DECAY_PER_DAY = 20    # Penalización por cada día de diferencia
HIGH_THRESHOLD = 1    # ≤1 día = prioridad ALTA
MEDIUM_THRESHOLD = 3  # ≤3 días = prioridad MEDIA

def get_next_checkin(property_id, from_date):
    """
    Encuentra la próxima reserva aprobada en una propiedad desde una fecha dada.
    
    Args:
        property_id: ID de la propiedad
        from_date: Fecha desde la cual buscar (date object)
    
    Returns:
        tuple: (next_check_in_date, gap_days) o (None, None) si no hay próxima reserva
    """
    if not property_id or not from_date:
        return None, None
    
    try:
        next_reservation = Reservation.objects.filter(
            property_id=property_id,
            status='approved',
            check_in_date__gte=from_date,
            deleted=False
        ).order_by('check_in_date').first()
        
        if next_reservation:
            next_check_in = next_reservation.check_in_date
            if isinstance(next_check_in, datetime):
                next_check_in = next_check_in.date()
            if isinstance(from_date, datetime):
                from_date = from_date.date()
            
            gap_days = (next_check_in - from_date).days
            return next_check_in, gap_days
        
        return None, None
    except Exception as e:
        logger.error(f"Error buscando próximo check-in para propiedad {property_id}: {e}")
        return None, None

def compute_task_priority(task):
    """
    Calcula la prioridad de una tarea de limpieza basada en la proximidad del próximo check-in.
    
    Args:
        task: Instancia de WorkTask
    
    Returns:
        tuple: (priority_label, priority_score, gap_days)
    """
    if not task or not task.building_property or not task.scheduled_date:
        return 'low', 0, None
    
    # Convertir scheduled_date a date si es datetime
    scheduled_date = task.scheduled_date
    if isinstance(scheduled_date, datetime):
        scheduled_date = scheduled_date.date()
    
    # Usar función centralizada para calcular prioridad
    priority_label, gap_days = get_priority_from_property(
        task.building_property.id,
        scheduled_date
    )
    
    # Calcular puntuación según prioridad
    if priority_label == 'urgent':
        priority_score = URGENT_BOOST
        logger.info(f"🚨 TAREA URGENTE: {task.title} - Check-in MISMO DÍA")
    elif priority_label == 'high':
        priority_score = max(0, BASE_PROXIMITY - DECAY_PER_DAY * (gap_days or 1))
        logger.info(f"🔥 TAREA ALTA PRIORIDAD: {task.title} - Check-in en {gap_days} día(s)")
    elif priority_label == 'medium':
        priority_score = max(0, BASE_PROXIMITY - DECAY_PER_DAY * (gap_days or 2))
        logger.debug(f"📅 TAREA MEDIA PRIORIDAD: {task.title} - Check-in en {gap_days} día(s)")
    else:
        priority_score = max(0, BASE_PROXIMITY - DECAY_PER_DAY * (gap_days or 10))
        logger.debug(f"📋 TAREA BAJA PRIORIDAD: {task.title} - {f'Check-in en {gap_days} día(s)' if gap_days else 'Sin próximo check-in'}")
    
    return priority_label, priority_score, gap_days

def get_priority_from_property(property_id, from_date):
    """
    Función centralizada para calcular prioridad basada en próximo check-in.
    Retorna (priority_label, gap_days) según las mismas reglas que compute_task_priority.
    """
    try:
        next_check_in, gap_days = get_next_checkin(property_id, from_date)
        
        if next_check_in is None:
            return ('low', None)
        
        # Misma lógica que compute_task_priority
        if gap_days == 0:
            return ('urgent', gap_days)
        elif gap_days <= HIGH_THRESHOLD:  # ≤1 día
            return ('high', gap_days)
        elif gap_days <= MEDIUM_THRESHOLD:  # ≤3 días
            return ('medium', gap_days)
        else:
            return ('low', gap_days)
            
    except Exception as e:
        logger.error(f"Error en get_priority_from_property({property_id}, {from_date}): {e}")
        return ('low', None)

def find_affected_tasks_by_new_reservation(new_reservation):
    """
    Encuentra tareas existentes que puedan ser afectadas por una nueva reserva.
    Busca tareas de checkout ANTES del nuevo check-in en la misma propiedad.
    """
    if not WorkTask or not new_reservation:
        return []
    
    try:
        # Buscar tareas de checkout existentes en la misma propiedad
        # que estén programadas ANTES del nuevo check-in
        affected_tasks = WorkTask.objects.filter(
            building_property=new_reservation.property,
            task_type='checkout_cleaning',
            scheduled_date__lt=new_reservation.check_in_date,  # Antes del nuevo check-in
            scheduled_date__gte=timezone.now().date(),  # Solo futuras
            status__in=['pending', 'assigned'],  # Solo no completadas
            deleted=False
        ).exclude(
            scheduled_date=timezone.now().date()  # Excluir tareas de hoy (no reorganizar)
        ).order_by('scheduled_date')
        
        logger.info(f"🔍 Nueva reserva {new_reservation.id} (check-in {new_reservation.check_in_date})")
        logger.info(f"   Encontradas {affected_tasks.count()} tareas potencialmente afectadas en {new_reservation.property.name}")
        
        return list(affected_tasks)
        
    except Exception as e:
        logger.error(f"Error buscando tareas afectadas por reserva {new_reservation.id}: {e}")
        return []


def find_preemptable_tasks_for_date(target_date, minimum_priority_level='urgent'):
    """
    Encuentra tareas de menor prioridad que puedan ser preemptadas para liberar personal.
    Busca tareas asignadas en la misma fecha con prioridad menor que la requerida.
    """
    if not WorkTask:
        return []
    
    try:
        # Definir orden de prioridades
        priority_order = {'low': 1, 'medium': 2, 'high': 3, 'urgent': 4}
        min_priority_value = priority_order.get(minimum_priority_level, 4)
        
        # Buscar tareas asignadas con prioridad menor en la misma fecha (cross-property)
        preemptable_tasks = WorkTask.objects.filter(
            scheduled_date=target_date,
            task_type='checkout_cleaning',
            status='assigned',  # Solo tareas ya asignadas
            staff_member__isnull=False,  # Que tengan personal asignado
            deleted=False
        ).exclude(
            priority__in=[k for k, v in priority_order.items() if v >= min_priority_value]
        ).order_by('priority')  # Comenzar por las de menor prioridad
        
        # Filtrar por prioridad numérica para mayor precisión
        filtered_tasks = []
        for task in preemptable_tasks:
            task_priority_value = priority_order.get(task.priority, 0)
            if task_priority_value < min_priority_value:
                filtered_tasks.append(task)
        
        logger.info(f"🎯 Búsqueda de preemption para {target_date}: {len(filtered_tasks)} tareas candidatas")
        for task in filtered_tasks[:3]:  # Log primeras 3 como muestra
            logger.info(f"   📋 {task.building_property.name} - {task.priority} - {task.staff_member.first_name if task.staff_member else 'Sin personal'}")
        
        return filtered_tasks
        
    except Exception as e:
        logger.error(f"Error buscando tareas preemptables para {target_date}: {e}")
        return []


def preempt_task_for_urgent(urgent_task, target_task):
    """
    Reasigna personal de una tarea de menor prioridad a una tarea urgente.
    La tarea preemptada queda pendiente de reasignación.
    """
    if not urgent_task or not target_task or not target_task.staff_member:
        return False
    
    try:
        # Capturar información antes del cambio
        freed_staff = target_task.staff_member
        target_property = target_task.building_property.name
        urgent_property = urgent_task.building_property.name
        
        logger.info(f"🔄 PREEMPTION INICIADA:")
        logger.info(f"   De: {target_property} ({target_task.priority}) → {urgent_property} ({urgent_task.priority})")
        logger.info(f"   Personal: {freed_staff.first_name} {freed_staff.last_name}")
        
        # Reasignar personal a la tarea urgente
        urgent_task.staff_member = freed_staff
        urgent_task.status = 'assigned'
        urgent_task.save()
        
        # Liberar la tarea preemptada
        target_task.staff_member = None
        target_task.status = 'pending'
        target_task.save()
        
        logger.info(f"✅ PREEMPTION EXITOSA: {freed_staff.first_name} reasignado de {target_property} a {urgent_property}")
        logger.info(f"⏳ Tarea {target_property} marcada como pendiente de reasignación")
        
        return True
        
    except Exception as e:
        logger.error(f"Error en preemption entre tareas {urgent_task.id} y {target_task.id}: {e}")
        return False

def reorganize_affected_tasks(affected_tasks):
    """
    Reorganiza automáticamente las tareas afectadas por cambios de prioridad.
    Solo reorganiza si hay mejora significativa en la eficiencia.
    """
    if not affected_tasks:
        return
    
    try:
        reorganized_count = 0
        
        for task in affected_tasks:
            # Calcular nueva prioridad
            old_priority = task.priority
            new_priority_label, new_priority_score, gap_days = compute_task_priority(task)
            
            # Solo reorganizar si la prioridad cambió significativamente
            priority_order = {'low': 1, 'medium': 2, 'high': 3, 'urgent': 4}
            old_order = priority_order.get(old_priority, 1)
            new_order = priority_order.get(new_priority_label, 1)
            
            if new_order > old_order:  # Prioridad aumentó
                logger.info(f"🔄 REORGANIZANDO tarea {task.id}: {old_priority} → {new_priority_label}")
                logger.info(f"   Tarea: {task.title} en {task.scheduled_date}")
                
                # Actualizar prioridad de la tarea
                task.priority = new_priority_label
                if gap_days is not None and gap_days <= 1:
                    if gap_days == 0:
                        task.description += f"\n🚨 ACTUALIZADO: Check-in MISMO DÍA"
                    else:
                        task.description += f"\n🔥 ACTUALIZADO: Check-in en {gap_days} día(s)"
                task.save()
                
                # Buscar nueva asignación óptima
                current_staff = task.staff_member
                best_staff = find_best_cleaning_staff(
                    task.scheduled_date, 
                    task.building_property, 
                    task.reservation, 
                    task
                )
                
                # Solo reasignar si encontramos mejor personal
                if best_staff and best_staff != current_staff:
                    old_staff_name = f"{current_staff.first_name} {current_staff.last_name}" if current_staff else "Sin asignar"
                    new_staff_name = f"{best_staff.first_name} {best_staff.last_name}"
                    
                    task.staff_member = best_staff
                    task.status = 'assigned'
                    task.save()
                    
                    logger.info(f"   ✅ REASIGNADO: {old_staff_name} → {new_staff_name}")
                    reorganized_count += 1
                else:
                    logger.info(f"   ➡️ MANTIENE asignación actual (óptima)")
            else:
                logger.debug(f"⏸️ Tarea {task.id} mantiene prioridad {old_priority}")
        
        if reorganized_count > 0:
            logger.info(f"🎯 REORGANIZACIÓN COMPLETADA: {reorganized_count} tareas reasignadas")
        else:
            logger.info(f"✅ REORGANIZACIÓN EVALUADA: No se requieren cambios")
            
    except Exception as e:
        logger.error(f"Error reorganizando tareas: {e}")

def trigger_smart_reorganization(new_reservation):
    """
    Función principal que detecta y ejecuta reorganización inteligente
    cuando una nueva reserva afecta prioridades existentes.
    """
    try:
        logger.info(f"🧠 EVALUANDO reorganización por nueva reserva {new_reservation.id}")
        
        # Encontrar tareas potencialmente afectadas
        affected_tasks = find_affected_tasks_by_new_reservation(new_reservation)
        
        if affected_tasks:
            logger.info(f"🔄 INICIANDO reorganización automática...")
            reorganize_affected_tasks(affected_tasks)
        else:
            logger.info(f"✅ No hay tareas que requieran reorganización")
            
    except Exception as e:
        logger.error(f"Error en reorganización inteligente: {e}")


def reorganize_all_existing_tasks():
    """
    NUEVA FUNCIÓN: Reorganización completa de TODAS las tareas de limpieza existentes.
    Esta función evalúa todas las tareas futuras y las reorganiza usando la lógica completa.
    """
    try:
        from apps.staff.models import WorkTask
        from django.utils import timezone
        
        logger.info(f"🧠 INICIANDO reorganización completa de todas las tareas existentes...")
        
        # Buscar TODAS las tareas de limpieza futuras
        all_cleaning_tasks = WorkTask.objects.filter(
            task_type='checkout_cleaning',
            scheduled_date__gte=timezone.now().date(),
            status__in=['pending', 'assigned'],
            deleted=False
        ).select_related('staff_member', 'building_property', 'reservation').order_by('scheduled_date', '-priority')
        
        stats = {
            'total_evaluated': all_cleaning_tasks.count(),
            'reassigned': 0,
            'priority_changed': 0,
            'preemptions': 0
        }
        
        logger.info(f"📊 Evaluando {stats['total_evaluated']} tareas existentes...")
        
        # PASO 1: Actualizar todas las prioridades usando la lógica centralizada
        for task in all_cleaning_tasks:
            try:
                old_priority = task.priority
                new_priority_label, priority_score, gap_days = compute_task_priority(task)
                
                if new_priority_label != old_priority:
                    task.priority = new_priority_label
                    task.save()
                    stats['priority_changed'] += 1
                    logger.info(f"🔄 Prioridad actualizada: Tarea {task.id} → {new_priority_label.upper()}")
                    
            except Exception as e:
                logger.error(f"Error actualizando prioridad de tarea {task.id}: {e}")
        
        # PASO 2: Reorganizar tareas por fecha, priorizando urgentes y altas
        # IMPORTANTE: Re-consultar tareas después de actualizar prioridades
        urgent_and_high_tasks = WorkTask.objects.filter(
            task_type='checkout_cleaning',
            scheduled_date__gte=timezone.now().date(),
            status__in=['pending', 'assigned'],
            deleted=False,
            priority__in=['urgent', 'high']  # Con prioridades ACTUALIZADAS
        ).select_related('staff_member', 'building_property', 'reservation').order_by('scheduled_date')
        
        for task in urgent_and_high_tasks:
            try:
                # Si la tarea no tiene staff asignado, intentar preemption
                if not task.staff_member:
                    logger.info(f"🚨 Tarea {task.priority.upper()} sin asignar: {task.building_property.name} ({task.scheduled_date})")
                    
                    # Buscar tareas de menor prioridad en la misma fecha
                    preemptable_tasks = find_preemptable_tasks_for_date(
                        task.scheduled_date, 
                        task.priority
                    )
                    
                    if preemptable_tasks:
                        # Seleccionar el mejor candidato (menor prioridad)
                        target_task = preemptable_tasks[0]  # Ya ordenado por prioridad
                        
                        if preempt_task_for_urgent(task, target_task):
                            stats['preemptions'] += 1
                            logger.info(f"✅ PREEMPTION exitosa: {task.building_property.name} obtuvo personal")
                        else:
                            logger.warning(f"❌ PREEMPTION falló para {task.building_property.name}")
                    else:
                        logger.warning(f"⚠️ No hay tareas preemptables para {task.scheduled_date}")
                
                # Si la tarea tiene staff pero podemos encontrar mejor asignación
                elif task.staff_member:
                    # NUEVO: Verificar si tarea urgente/alta está diferida y debe moverse a fecha original
                    checkout_date = task.reservation.check_out_date if task.reservation else task.scheduled_date
                    is_deferred = task.scheduled_date > checkout_date
                    
                    if is_deferred and task.priority in ['urgent', 'high']:
                        logger.info(f"🚨 Tarea {task.priority.upper()} diferida detectada: {task.building_property.name}")
                        logger.info(f"   Original: {checkout_date} | Actual: {task.scheduled_date} (+{(task.scheduled_date - checkout_date).days} días)")
                        
                        # Intentar encontrar personal disponible en la fecha original
                        best_staff_original = find_best_cleaning_staff(
                            checkout_date,
                            task.building_property,
                            task.reservation,
                            task
                        )
                        
                        if best_staff_original:
                            # Mover tarea a fecha original
                            old_date = task.scheduled_date
                            task.scheduled_date = checkout_date
                            task.staff_member = best_staff_original
                            task.save()
                            stats['reassigned'] += 1
                            
                            staff_name = f"{best_staff_original.first_name} {best_staff_original.last_name}"
                            logger.info(f"✅ FECHA REASIGNADA: {task.building_property.name} | {old_date} → {checkout_date} | Personal: {staff_name}")
                        else:
                            # Si no hay personal disponible en fecha original, intentar preemption
                            preemptable_tasks = find_preemptable_tasks_for_date(
                                checkout_date, 
                                task.priority
                            )
                            
                            if preemptable_tasks:
                                target_task = preemptable_tasks[0]
                                logger.info(f"🔄 Intentando preemption para mover a fecha original...")
                                
                                if preempt_task_for_urgent(task, target_task):
                                    # Mover tarea a fecha original después de preemption exitosa
                                    old_date = task.scheduled_date
                                    task.scheduled_date = checkout_date
                                    task.save()
                                    stats['preemptions'] += 1
                                    
                                    logger.info(f"✅ FECHA REASIGNADA POR PREEMPTION: {task.building_property.name} | {old_date} → {checkout_date}")
                                else:
                                    logger.warning(f"❌ No se pudo mover {task.building_property.name} a fecha original")
                            else:
                                logger.warning(f"⚠️ No se puede mover {task.building_property.name} a fecha original - sin personal disponible")
                    else:
                        # Lógica original: buscar mejor asignación de personal sin cambiar fecha
                        best_staff = find_best_cleaning_staff(
                            task.scheduled_date,
                            task.building_property,
                            task.reservation,
                            task
                        )
                        
                        if best_staff and best_staff != task.staff_member:
                            old_staff_name = f"{task.staff_member.first_name} {task.staff_member.last_name}"
                            new_staff_name = f"{best_staff.first_name} {best_staff.last_name}"
                            
                            task.staff_member = best_staff
                            task.save()
                            stats['reassigned'] += 1
                            
                            logger.info(f"🔄 REASIGNACIÓN mejorada: {task.building_property.name} | {old_staff_name} → {new_staff_name}")
                        
            except Exception as e:
                logger.error(f"Error reorganizando tarea {task.id}: {e}")
        
        # PASO 3: Intentar reasignar tareas pendientes
        pending_tasks = all_cleaning_tasks.filter(staff_member__isnull=True).order_by('-priority', 'scheduled_date')
        
        for task in pending_tasks:
            try:
                best_staff = find_best_cleaning_staff(
                    task.scheduled_date,
                    task.building_property, 
                    task.reservation,
                    task
                )
                
                if best_staff:
                    task.staff_member = best_staff
                    task.status = 'assigned'
                    task.save()
                    stats['reassigned'] += 1
                    
                    staff_name = f"{best_staff.first_name} {best_staff.last_name}"
                    logger.info(f"✅ ASIGNACIÓN nueva: {task.building_property.name} → {staff_name}")
                    
            except Exception as e:
                logger.error(f"Error asignando tarea pendiente {task.id}: {e}")
        
        logger.info(f"🎯 REORGANIZACIÓN COMPLETA FINALIZADA:")
        logger.info(f"   • Tareas evaluadas: {stats['total_evaluated']}")
        logger.info(f"   • Prioridades actualizadas: {stats['priority_changed']}")
        logger.info(f"   • Preemptions ejecutadas: {stats['preemptions']}")
        logger.info(f"   • Reasignaciones: {stats['reassigned']}")
        
        return stats
        
    except Exception as e:
        logger.error(f"❌ Error en reorganización completa: {e}")
        return {'total_evaluated': 0, 'reassigned': 0, 'priority_changed': 0, 'preemptions': 0}


def format_date_es(date):
    day = date.day
    month = MONTHS_ES[date.month]
    week_day = DAYS_ES[date.weekday()]
    return f"{week_day} {day} de {month}"


def format_date_range_es(check_in_date, check_out_date):
    """
    Formatea un rango de fechas en español legible.
    Ejemplos:
    - "del 11 al 12 de octubre" (mismo mes)
    - "del 30 de octubre al 2 de noviembre" (diferentes meses, mismo año)
    - "del 30 de diciembre al 2 de enero de 2025" (diferentes años)
    """
    if not check_in_date or not check_out_date:
        return ""
        
    # Obtener día y mes de cada fecha
    check_in_day = check_in_date.day
    check_in_month = MONTHS_ES[check_in_date.month]
    check_in_year = check_in_date.year
    
    check_out_day = check_out_date.day
    check_out_month = MONTHS_ES[check_out_date.month]
    check_out_year = check_out_date.year
    
    # Caso 1: Mismo mes y año
    if check_in_date.month == check_out_date.month and check_in_year == check_out_year:
        return f"del {check_in_day} al {check_out_day} de {check_in_month}"
    
    # Caso 2: Diferente mes, mismo año
    elif check_in_year == check_out_year:
        return f"del {check_in_day} de {check_in_month} al {check_out_day} de {check_out_month}"
    
    # Caso 3: Diferente año
    else:
        return f"del {check_in_day} de {check_in_month} al {check_out_day} de {check_out_month} de {check_out_year}"


def calculate_upcoming_age(born):
    today = date.today()
    this_year_birthday = date(today.year, born.month, born.day)
    next_birthday = this_year_birthday if today <= this_year_birthday else date(
        today.year + 1, born.month, born.day)
    return next_birthday.year - born.year


def notify_new_reservation(reservation):
    client_name = f"{reservation.client.first_name} {reservation.client.last_name}" if reservation.client else "Cliente desconocido"
    temperature_pool_status = "Sí" if reservation.temperature_pool else "No"

    check_in_date = format_date_es(reservation.check_in_date)
    check_out_date = format_date_es(reservation.check_out_date)
    price_usd = f"{reservation.price_usd:.2f} dólares"
    price_sol = f"{reservation.price_sol:.2f} soles"
    advance_payment = f"{reservation.advance_payment:.2f} {reservation.advance_payment_currency.upper()}"

    # Determinar el origen de la reserva para personalizar el mensaje
    origin_emoji = ""
    origin_text = ""
    if reservation.origin == 'client':
        origin_emoji = "💻"
        origin_text = "WEB CLIENTE"
    elif reservation.origin == 'air':
        origin_emoji = "🏠"
        origin_text = "AIRBNB"
    elif reservation.origin == 'aus':
        origin_emoji = "📞"
        origin_text = "AUSTIN"
    elif reservation.origin == 'man':
        origin_emoji = "🔧"
        origin_text = "MANTENIMIENTO"

    message = (
        f"{origin_emoji} **{origin_text}** - Reserva en {reservation.property.name}\n"
        f"Cliente: {client_name}\n"
        f"Check-in : {check_in_date}\n"
        f"Check-out : {check_out_date}\n"
        f"Invitados : {reservation.guests}\n"
        f"Temperado : {temperature_pool_status}\n"
        f"Precio (USD) : {price_usd}\n"
        f"Precio (Soles) : {price_sol}\n"
        f"Adelanto : {advance_payment}\n"
        f"Teléfono : +{reservation.client.tel_number}")

    message_today = (f"******PARA HOYYYY******\n"
                     f"Cliente: {client_name}\n"
                     f"Check-in : {check_in_date}\n"
                     f"Check-out : {check_out_date}\n"
                     f"Invitados : {reservation.guests}\n"
                     f"Temperado : {temperature_pool_status}\n")

    full_image_url = None
    rental_receipt = RentalReceipt.objects.filter(
        reservation=reservation).first()
    if rental_receipt and rental_receipt.file and rental_receipt.file.name:
        image_url = f"{settings.MEDIA_URL}{rental_receipt.file.name}"
        full_image_url = f"http://api.casaaustin.pe{image_url}"

    logger.debug(
        f"Enviando mensaje de Telegram: {message} con imagen: {full_image_url}"
    )

    # Si es una reserva desde el panel del cliente, enviar solo al canal de clientes
    if reservation.origin == 'client':
        client_message = (f"******************************************\n"
                          f"💻 RESERVA DESDE PANEL WEB 💻\n"
                          f"Cliente: {client_name}\n"
                          f"Propiedad: {reservation.property.name}\n"
                          f"Check-in : {check_in_date}\n"
                          f"Check-out : {check_out_date}\n"
                          f"Invitados : {reservation.guests}\n"
                          f"Temperado : {temperature_pool_status}\n"
                          f"💰 Total: {price_sol} soles\n"
                          f"📱 Teléfono: +{reservation.client.tel_number}\n"
                          f"******************************************")
        send_telegram_message(client_message, settings.CLIENTS_CHAT_ID,
                              full_image_url)
    else:
        # Para todas las demás reservas (airbnb, austin, mantenimiento), enviar al canal principal
        send_telegram_message(message, settings.CHAT_ID, full_image_url)

    if reservation.check_in_date == datetime.today().date():
        logger.debug(
            "Reserva para el mismo día detectada, enviando al segundo canal.")
        send_telegram_message(message_today, settings.SECOND_CHAT_ID,
                              full_image_url)

    birthday = format_date_es(
        reservation.client.date
    ) if reservation.client and reservation.client.date else "No disponible"
    upcoming_age = calculate_upcoming_age(
        reservation.client.date
    ) if reservation.client and reservation.client.date else "No disponible"
    message_personal_channel = (
        f"******Reserva en {reservation.property.name}******\n"
        f"Cliente: {client_name}\n"
        f"Cumpleaños: {birthday} (Cumple {upcoming_age} años)\n"
        f"Check-in : {check_in_date}\n"
        f"Check-out : {check_out_date}\n"
        f"Invitados : {reservation.guests}\n"
        f"Temperado : {temperature_pool_status}\n"
        f"Teléfono : https://wa.me/{reservation.client.tel_number}")
    send_telegram_message(message_personal_channel, settings.PERSONAL_CHAT_ID,
                          full_image_url)


def notify_voucher_uploaded(reservation):
    """Notifica cuando un cliente sube su voucher de pago"""
    client_name = f"{reservation.client.first_name} {reservation.client.last_name}" if reservation.client else "Cliente desconocido"

    check_in_date = format_date_es(reservation.check_in_date)
    check_out_date = format_date_es(reservation.check_out_date)
    price_sol = f"{reservation.price_sol:.2f} soles"

    # Contar vouchers existentes para esta reserva
    vouchers_count = RentalReceipt.objects.filter(reservation=reservation).count()
    voucher_info = "PRIMER VOUCHER" if vouchers_count == 1 else f"VOUCHER #{vouchers_count}"
    if vouchers_count == 2:
        voucher_info = "SEGUNDO VOUCHER"

    voucher_message = (f"📄 **{voucher_info} RECIBIDO** 📄\n"
                       f"Cliente: {client_name}\n"
                       f"Propiedad: {reservation.property.name}\n"
                       f"Check-in: {check_in_date}\n"
                       f"Check-out: {check_out_date}\n"
                       f"💰 Total: {price_sol}\n"
                       f"📱 Teléfono: +{reservation.client.tel_number}\n"
                       f"⏰ Estado: Pendiente de validación\n"
                       f"🆔 Reserva ID: {reservation.id}")

    # Obtener la imagen del voucher de pago
    voucher_image_url = None
    rental_receipt = RentalReceipt.objects.filter(
        reservation=reservation).first()
    if rental_receipt and rental_receipt.file and rental_receipt.file.name:
        image_url = f"{settings.MEDIA_URL}{rental_receipt.file.name}"
        voucher_image_url = f"http://api.casaaustin.pe{image_url}"

    logger.debug(
        f"Enviando notificación de voucher subido para reserva: {reservation.id} con imagen: {voucher_image_url}"
    )
    send_telegram_message(voucher_message, settings.CLIENTS_CHAT_ID,
                          voucher_image_url)


def notify_payment_approved(reservation):
    """Notifica al cliente por WhatsApp cuando su pago es aprobado"""
    from ..clients.whatsapp_service import send_whatsapp_payment_approved

    if not reservation.client or not reservation.client.tel_number:
        logger.warning(
            f"No se puede enviar WhatsApp para reserva {reservation.id}: cliente o teléfono no disponible"
        )
        return

    try:
        # Preparar datos para el template - solo primer nombre y primer apellido
        first_name = reservation.client.first_name.split(
        )[0] if reservation.client.first_name else ""

        # Obtener solo el primer apellido si existe
        first_last_name = ""
        if reservation.client.last_name:
            first_last_name = reservation.client.last_name.split()[0]

        # Combinar primer nombre y primer apellido
        client_name = f"{first_name} {first_last_name}".strip()

        # Formatear información del pago - siempre usar advance_payment para aprobaciones manuales
        # El advance_payment representa lo que realmente pagó el cliente
        if reservation.advance_payment and reservation.advance_payment > 0:
            if reservation.advance_payment_currency == 'usd':
                payment_info = f"${reservation.advance_payment:.2f}"
            else:
                payment_info = f"S/{reservation.advance_payment:.2f}"
        else:
            payment_info = "S/0.00"
            logger.warning(
                f"Reserva sin advance_payment para reserva {reservation.id}")

        # Formatear fecha de check-in (formato dd/mm/yyyy)
        check_in_formatted = reservation.check_in_date.strftime("%d/%m/%Y")
        check_in_text = f"Para la reserva del {check_in_formatted}"

        logger.info(
            f"Enviando WhatsApp de pago aprobado a {reservation.client.tel_number} para reserva {reservation.id}"
        )
        logger.info(
            f"Datos: Nombre: {client_name}, Pago: {payment_info}, Check-in: {check_in_text}"
        )

        # Enviar WhatsApp
        success = send_whatsapp_payment_approved(
            phone_number=reservation.client.tel_number,
            client_name=client_name,
            payment_info=payment_info,
            check_in_date=check_in_text)

        if success:
            logger.info(
                f"WhatsApp de pago aprobado enviado exitosamente para reserva {reservation.id}"
            )
        else:
            logger.error(
                f"Error al enviar WhatsApp de pago aprobado para reserva {reservation.id}"
            )

    except Exception as e:
        logger.error(
            f"Error al procesar notificación de pago aprobado para reserva {reservation.id}: {str(e)}"
        )


def hash_data(data):
    if data:
        return hashlib.sha256(data.strip().lower().encode()).hexdigest()
    return None


@receiver(post_save, sender=Reservation)
def reservation_post_save_handler(sender, instance, created, **kwargs):
    """Maneja las notificaciones cuando se crea o actualiza una reserva"""
    if created:
        logger.info(f"🔥 SIGNAL EJECUTADO: Nueva reserva creada ID {instance.id} - Origen: {instance.origin} - Cliente: {instance.client}")
        notify_new_reservation(instance)
        
        # 📊 ACTIVITY FEED: Crear actividad para nueva reserva
        if instance.client and instance.origin in ['aus', 'client']:
            try:
                from apps.events.models import ActivityFeed, ActivityFeedConfig
                
                logger.info(f"🎯 Intentando crear actividad de feed para reserva {instance.id}")
                
                # ✅ VERIFICAR CONFIGURACIÓN: ¿Está habilitado este tipo de actividad?
                if ActivityFeedConfig.is_type_enabled(ActivityFeed.ActivityType.RESERVATION_MADE):
                    # Usar configuración por defecto para visibilidad e importancia
                    is_public = ActivityFeedConfig.should_be_public(ActivityFeed.ActivityType.RESERVATION_MADE)
                    importance = ActivityFeedConfig.get_default_importance(ActivityFeed.ActivityType.RESERVATION_MADE)
                    
                    dates_str = format_date_range_es(instance.check_in_date, instance.check_out_date)
                    
                    activity = ActivityFeed.create_activity(
                        activity_type=ActivityFeed.ActivityType.RESERVATION_MADE,
                        client=instance.client,
                        property_location=instance.property,
                        is_public=is_public,
                        importance_level=importance,
                        activity_data={
                            'property_name': instance.property.name,
                            'dates': dates_str,
                            'check_in': instance.check_in_date.isoformat(),
                            'check_out': instance.check_out_date.isoformat(),
                            'origin': instance.origin
                        }
                    )
                    logger.info(f"✅ Actividad de nueva reserva creada exitosamente: {activity.id}")
                else:
                    logger.info(f"⚠️ Actividades de tipo 'reservation_made' están deshabilitadas")
                    
            except Exception as e:
                logger.error(f"❌ Error creando actividad de nueva reserva para reserva {instance.id}: {str(e)}")
                import traceback
                logger.error(f"📊 Traceback completo: {traceback.format_exc()}")

        # NUEVO: Crear tarea de limpieza automáticamente si la nueva reserva ya está aprobada
        if instance.status == 'approved':
            logger.info(f"New reservation created with approved status {instance.id} - Creating automatic cleaning task")
            create_automatic_cleaning_task(instance)
            
            # REORGANIZACIÓN INTELIGENTE: Evaluar si afecta prioridades de tareas existentes
            trigger_smart_reorganization(instance)
            
            # 📊 ACTIVITY FEED: Crear actividad de "Reserva Confirmada" cuando se crea directamente con status approved (desde admin)
            if instance.client and instance.origin in ['aus', 'client']:
                try:
                    from apps.events.models import ActivityFeed, ActivityFeedConfig
                    
                    # ✅ VERIFICAR CONFIGURACIÓN: ¿Está habilitado este tipo de actividad?
                    if ActivityFeedConfig.is_type_enabled(ActivityFeed.ActivityType.RESERVATION_CONFIRMED):
                        # Usar configuración por defecto para visibilidad e importancia
                        is_public = ActivityFeedConfig.should_be_public(ActivityFeed.ActivityType.RESERVATION_CONFIRMED)
                        importance = ActivityFeedConfig.get_default_importance(ActivityFeed.ActivityType.RESERVATION_CONFIRMED)
                        
                        dates_str = format_date_range_es(instance.check_in_date, instance.check_out_date)
                        
                        ActivityFeed.create_activity(
                            activity_type=ActivityFeed.ActivityType.RESERVATION_CONFIRMED,
                            client=instance.client,
                            property_location=instance.property,
                            is_public=is_public,
                            importance_level=importance,
                            activity_data={
                                'property_name': instance.property.name,
                                'dates': dates_str,
                                'check_in': instance.check_in_date.isoformat(),
                                'check_out': instance.check_out_date.isoformat(),
                                'status_change': 'approved_from_admin'
                            }
                        )
                        logger.info(f"✅ Actividad de reserva confirmada creada para nueva reserva aprobada {instance.id}")
                except Exception as e:
                    logger.error(f"❌ Error creando actividad de confirmación para nueva reserva aprobada {instance.id}: {str(e)}")

        # Verificar si la nueva reserva tiene pago completo
        if instance.full_payment:
            logger.debug(
                f"Nueva reserva {instance.id} creada con pago completo - Enviando flujo ChatBot"
            )
            send_chatbot_flow_payment_complete(instance)
    else:
        # Verificar si cambió a estado pending (primer voucher) o under_review (segundo voucher)
        if instance.status in ['pending', 'under_review'] and instance.origin == 'client':
            logger.debug(
                f"Reserva {instance.id} cambió a estado {instance.status} - Voucher subido"
            )
            notify_voucher_uploaded(instance)

        # Verificar si cambió a estado approved (pago aprobado) y no se ha enviado la notificación
        elif instance.status == 'approved' and instance.origin == 'client' and not instance.payment_approved_notification_sent:
            logger.debug(
                f"Reserva {instance.id} cambió a estado approved - Pago aprobado"
            )
            notify_payment_approved(instance)
            # Marcar como enviado para evitar duplicados
            instance.payment_approved_notification_sent = True
            instance.save(update_fields=['payment_approved_notification_sent'])
            
            # 📊 ACTIVITY FEED: Crear actividad para reserva confirmada (pending → approved)
            if instance.client and instance.origin in ['aus', 'client']:
                try:
                    from apps.events.models import ActivityFeed, ActivityFeedConfig
                    
                    # ✅ VERIFICAR CONFIGURACIÓN: ¿Está habilitado este tipo de actividad?
                    if ActivityFeedConfig.is_type_enabled(ActivityFeed.ActivityType.RESERVATION_CONFIRMED):
                        # Usar configuración por defecto para visibilidad e importancia
                        is_public = ActivityFeedConfig.should_be_public(ActivityFeed.ActivityType.RESERVATION_CONFIRMED)
                        importance = ActivityFeedConfig.get_default_importance(ActivityFeed.ActivityType.RESERVATION_CONFIRMED)
                        
                        dates_str = format_date_range_es(instance.check_in_date, instance.check_out_date)
                        
                        ActivityFeed.create_activity(
                            activity_type=ActivityFeed.ActivityType.RESERVATION_CONFIRMED,  # ✅ Cambio a RESERVATION_CONFIRMED
                            client=instance.client,
                            property_location=instance.property,
                            is_public=is_public,
                            importance_level=importance,
                            activity_data={
                                'property_name': instance.property.name,
                                'dates': dates_str,
                                'check_in': instance.check_in_date.isoformat(),
                                'check_out': instance.check_out_date.isoformat(),
                                'status_change': 'approved'
                            }
                        )
                        logger.info(f"Actividad de reserva confirmada creada para reserva {instance.id}")  # ✅ Mensaje actualizado
                except Exception as e:
                    logger.error(f"Error creando actividad de reserva confirmada para reserva {instance.id}: {str(e)}")  # ✅ Mensaje actualizado

        # Verificar si cambió el campo full_payment a True (pago completado)
        if hasattr(instance, '_original_full_payment'):
            if not instance._original_full_payment and instance.full_payment:
                logger.debug(
                    f"Reserva {instance.id} marcada como pago completo - Enviando flujo ChatBot"
                )
                send_chatbot_flow_payment_complete(instance)

        # Verificar logros después de actualizar el estado de la reserva
        try:
            if instance.client:
                check_and_assign_achievements(instance.client.id)

                # También verificar logros del cliente que refirió si existe
                if instance.client.referred_by:
                    check_and_assign_achievements(
                        instance.client.referred_by.id)
        except Exception as e:
            logger.error(
                f"Error verificando logros después de actualizar reserva: {str(e)}"
            )

        # NUEVO: Crear tarea de limpieza automáticamente cuando se aprueba la reserva
        if instance.status == 'approved' and hasattr(instance, '_original_status') and instance._original_status != 'approved':
            logger.info(f"Reservation {instance.id} status changed to approved - Creating automatic cleaning task")
            create_automatic_cleaning_task(instance)
            
            # REORGANIZACIÓN INTELIGENTE: Evaluar si afecta prioridades de tareas existentes
            trigger_smart_reorganization(instance)
            
            # 📊 ACTIVITY FEED: Crear actividad para reserva aprobada (desde admin o otros orígenes)
            if instance.client and instance.origin in ['aus', 'client'] and not instance.payment_approved_notification_sent:
                try:
                    from apps.events.models import ActivityFeed, ActivityFeedConfig
                    
                    # ✅ VERIFICAR CONFIGURACIÓN: ¿Está habilitado este tipo de actividad?
                    if ActivityFeedConfig.is_type_enabled(ActivityFeed.ActivityType.PAYMENT_COMPLETED):
                        # Usar configuración por defecto para visibilidad e importancia
                        is_public = ActivityFeedConfig.should_be_public(ActivityFeed.ActivityType.PAYMENT_COMPLETED)
                        importance = ActivityFeedConfig.get_default_importance(ActivityFeed.ActivityType.PAYMENT_COMPLETED)
                        
                        dates_str = format_date_range_es(instance.check_in_date, instance.check_out_date)
                        
                        ActivityFeed.create_activity(
                            activity_type=ActivityFeed.ActivityType.PAYMENT_COMPLETED,
                            client=instance.client,
                            property_location=instance.property,
                            is_public=is_public,
                            importance_level=importance,
                            activity_data={
                                'property_name': instance.property.name,
                                'dates': dates_str,
                                'check_in': instance.check_in_date.isoformat(),
                                'check_out': instance.check_out_date.isoformat(),
                                'status_change': 'approved_by_admin'
                            }
                        )
                        logger.info(f"Actividad de reserva aprobada creada para reserva {instance.id}")
                except Exception as e:
                    logger.error(f"Error creando actividad de reserva aprobada para reserva {instance.id}: {str(e)}")
                
        # 📊 ACTIVITY FEED: Crear actividad para reserva cancelada
        if instance.status == 'cancelled' and hasattr(instance, '_original_status') and instance._original_status != 'cancelled':
            if instance.client and instance.origin in ['aus', 'client']:
                try:
                    from apps.events.models import ActivityFeed, ActivityFeedConfig
                    
                    # ✅ VERIFICAR CONFIGURACIÓN: ¿Está habilitado este tipo de actividad?
                    if ActivityFeedConfig.is_type_enabled(ActivityFeed.ActivityType.RESERVATION_MADE):
                        # Usar configuración por defecto para visibilidad e importancia
                        is_public = ActivityFeedConfig.should_be_public(ActivityFeed.ActivityType.RESERVATION_MADE)
                        importance = ActivityFeedConfig.get_default_importance(ActivityFeed.ActivityType.RESERVATION_MADE)
                        
                        dates_str = format_date_range_es(instance.check_in_date, instance.check_out_date)
                        
                        ActivityFeed.create_activity(
                            activity_type=ActivityFeed.ActivityType.RESERVATION_MADE,
                            client=instance.client,
                            property_location=instance.property,
                            is_public=is_public,
                            importance_level=importance,
                            activity_data={
                                'property_name': instance.property.name,
                                'dates': dates_str,
                                'check_in': instance.check_in_date.isoformat(),
                                'check_out': instance.check_out_date.isoformat(),
                                'status_change': 'cancelled'
                            }
                        )
                        logger.info(f"Actividad de cancelación de reserva creada para reserva {instance.id}")
                except Exception as e:
                    logger.error(f"Error creando actividad de cancelación para reserva {instance.id}: {str(e)}")

        # NUEVO: Actualizar tareas de limpieza si cambió la fecha de checkout
        if hasattr(instance, '_original_check_out_date'):
            original_checkout = instance._original_check_out_date
            current_checkout = instance.check_out_date
            
            if original_checkout != current_checkout:
                logger.info(f"Checkout date changed for reservation {instance.id}: {original_checkout} -> {current_checkout}")
                update_cleaning_tasks_for_checkout_change(instance, original_checkout, current_checkout)


def send_chatbot_flow_payment_complete(reservation):
    """Envía flujo de ChatBot Builder cuando el pago está completo"""
    if not reservation.client or not reservation.client.id_manychat:
        logger.warning(
            f"No se puede enviar flujo ChatBot para reserva {reservation.id}: cliente o id_manychat no disponible"
        )
        return

    # Configuración de la API ChatBot Builder
    api_token = "1680437.Pgur5IA4kUXccspOK389nZugThdLB9h"
    flow_id = "1727388146335"  # Flujo para pago completo
    api_base_url = "https://app.chatgptbuilder.io/api"

    # URL para enviar el flujo
    url = f"{api_base_url}/contacts/{reservation.client.id_manychat}/send/{flow_id}"

    # Encabezados
    headers = {"X-ACCESS-TOKEN": api_token, "Content-Type": "application/json"}

    try:
        response = requests.post(url, headers=headers)
        if response.status_code == 200:
            logger.info(
                f"✅ Flujo de pago completo enviado a usuario {reservation.client.id_manychat} para reserva {reservation.id}"
            )
        else:
            logger.error(
                f"❌ Error enviando flujo de pago completo a {reservation.client.id_manychat}. Código: {response.status_code}"
            )
            logger.error(f"Respuesta: {response.text}")
    except Exception as e:
        logger.error(
            f"⚠️ Error enviando flujo ChatBot para reserva {reservation.id}: {e}"
        )


def send_purchase_event_to_meta(
        phone,
        email,
        first_name,
        last_name,
        amount,
        currency="USD",
        ip=None,
        user_agent=None,
        fbc=None,
        fbp=None,
        fbclid=None,
        utm_source=None,
        utm_medium=None,
        utm_campaign=None,
        birthday=None  # <-- Se añade aquí
):
    user_data = {}

    # Identificadores hash
    if phone:
        user_data["ph"] = [hash_data(phone)]
    if email:
        user_data["em"] = [hash_data(email)]
    if first_name:
        user_data["fn"] = [hash_data(first_name)]
    if last_name:
        user_data["ln"] = [hash_data(last_name)]

    # ✅ Fecha de nacimiento
    if birthday:
        try:
            # Asegurar formato correcto MMDDYYYY

            bday = datetime.strptime(birthday, "%Y-%m-%d").strftime("%m%d%Y")
            logger.debug(f"Fecha de nacimiento sin hash: {bday}")
            user_data["db"] = [hash_data(bday)]
        except Exception as e:
            logger.warning(
                f"Error procesando fecha de nacimiento '{birthday}': {e}")

    # Datos del navegador
    if ip:
        user_data["client_ip_address"] = ip
    if user_agent:
        user_data["client_user_agent"] = user_agent

    # Meta click ID y cookies
    if fbc:
        user_data["fbc"] = fbc
    if fbp:
        user_data["fbp"] = fbp
    if fbclid:
        user_data[
            "click_id"] = fbclid  # Usualmente no obligatorio si ya tienes fbc/fbp

    # Armamos el payload
    payload = {
        "data": [{
            "event_name": "Purchase",
            "event_time": int(datetime.now().timestamp()),
            "action_source": "website",
            "user_data": user_data,
            "custom_data": {
                "value": float(amount),
                "currency": currency,
                "utm_source": utm_source,
                "utm_medium": utm_medium,
                "utm_campaign": utm_campaign,
            }
        }],
        "access_token":
        settings.META_PIXEL_TOKEN
    }

    # Logging completo para depuración
    logger.debug("Payload enviado a Meta:\n%s", json.dumps(payload, indent=2))

    # Enviar evento a Meta
    response = requests.post(
        "https://graph.facebook.com/v18.0/7378335482264695/events",
        json=payload,
        headers={"Content-Type": "application/json"})

    if response.status_code == 200:
        logger.debug(
            f"Evento de conversión enviado correctamente a Meta. Respuesta: {response.text}"
        )
    else:
        logger.warning(
            f"Error al enviar evento a Meta. Código: {response.status_code} Respuesta: {response.text}"
        )


# ============================================================================
# NUEVOS SIGNALS PARA ACTUALIZACIÓN AUTOMÁTICA DE TAREAS DE LIMPIEZA
# ============================================================================

@receiver(pre_save, sender=Reservation)
def reservation_pre_save_handler(sender, instance, **kwargs):
    """Guarda el estado original antes de modificar la reserva"""
    if instance.pk:  # Solo si la reserva ya existe
        try:
            # Obtener la reserva original desde la base de datos
            original = Reservation.objects.get(pk=instance.pk)
            # Guardar los valores originales en la instancia
            instance._original_check_out_date = original.check_out_date
            instance._original_status = original.status
        except Reservation.DoesNotExist:
            # Si no existe, es una nueva reserva
            instance._original_check_out_date = None
            instance._original_status = None
    else:
        # Nueva reserva
        instance._original_check_out_date = None
        instance._original_status = None


def update_cleaning_tasks_for_checkout_change(reservation, original_checkout, new_checkout):
    """Actualiza las tareas de limpieza cuando cambia la fecha de checkout"""
    if not WorkTask:  # Verificar si el modelo WorkTask está disponible
        logger.warning("WorkTask model not available, skipping task update")
        return
    
    try:
        # Buscar tareas de limpieza relacionadas con esta reserva
        cleaning_tasks = WorkTask.objects.filter(
            reservation=reservation,
            task_type='checkout_cleaning',
            scheduled_date=original_checkout,  # Tareas programadas para la fecha original
            status__in=['pending', 'assigned']  # Solo tareas que aún no han iniciado
        )
        
        updated_count = 0
        for task in cleaning_tasks:
            # Actualizar la fecha programada
            old_date = task.scheduled_date
            task.scheduled_date = new_checkout
            task.save()
            
            logger.info(
                f"✅ Updated cleaning task {task.id} for reservation {reservation.id}: "
                f"{old_date} -> {new_checkout}"
            )
            updated_count += 1
        
        if updated_count > 0:
            logger.info(f"Successfully updated {updated_count} cleaning tasks for reservation {reservation.id}")
        else:
            logger.info(f"No cleaning tasks found to update for reservation {reservation.id}")
            
    except Exception as e:
        logger.error(f"❌ Error updating cleaning tasks for reservation {reservation.id}: {str(e)}")


def create_automatic_cleaning_task(reservation):
    """Crear automáticamente tarea de limpieza cuando se aprueba una reserva"""
    if not WorkTask or not StaffMember:
        logger.warning("Staff models not available, skipping automatic task creation")
        return
    
    try:
        # Verificar que no exista ya una tarea de limpieza para esta reserva
        existing_task = WorkTask.objects.filter(
            reservation=reservation,
            task_type='checkout_cleaning',
            deleted=False
        ).first()
        
        if existing_task:
            logger.info(f"Cleaning task already exists for reservation {reservation.id}")
            return
        
        # PASO 1: Crear la tarea de limpieza SIN asignar primero
        cleaning_task = WorkTask.objects.create(
            staff_member=None,  # Sin asignar inicialmente
            building_property=reservation.property,
            reservation=reservation,
            task_type='checkout_cleaning',
            title=f"Limpieza checkout - {reservation.property.name}",
            description=f"Limpieza post-checkout para reserva #{reservation.id}\nCliente: {f'{reservation.client.first_name} {reservation.client.last_name}'.strip() if reservation.client else 'N/A'}",
            scheduled_date=reservation.check_out_date,
            estimated_duration=timezone.timedelta(hours=2),  # 2 horas por defecto
            priority='medium',  # Temporal - será actualizada
            status='pending',
            requires_photo_evidence=True
        )
        
        # PASO 2: Calcular y establecer la prioridad de la tarea
        try:
            priority_label, priority_score, gap_days = compute_task_priority(cleaning_task)
            cleaning_task.priority = priority_label
            cleaning_task.save()
            
            # Actualizar descripción con información de prioridad si es relevante
            if gap_days is not None and gap_days <= 1:
                if gap_days == 0:
                    cleaning_task.description += f"\n🚨 URGENTE: Check-in MISMO DÍA"
                else:
                    cleaning_task.description += f"\n🔥 ALTA PRIORIDAD: Check-in en {gap_days} día(s)"
                cleaning_task.save()
            
            logger.info(f"🎯 Tarea {cleaning_task.id} establecida con prioridad {priority_label}")
            
        except Exception as e:
            logger.error(f"Error calculando prioridad para tarea {cleaning_task.id}: {e}")
            # Mantener prioridad 'medium' por defecto
        
        # PASO 3: Buscar el mejor personal considerando la prioridad de la tarea
        assigned_staff = find_best_cleaning_staff(reservation.check_out_date, reservation.property, reservation, cleaning_task)
        
        # PASO 4: Asignar el personal a la tarea O INTENTAR PREEMPTION INMEDIATAMENTE
        if assigned_staff:
            cleaning_task.staff_member = assigned_staff
            cleaning_task.status = 'assigned'
            cleaning_task.save()
        else:
            logger.warning(f"No cleaning staff available for reservation {reservation.id} on {reservation.check_out_date}")
            logger.info(f"🔍 DEBUG: Tarea {cleaning_task.id} tiene prioridad '{cleaning_task.priority}' - Evaluando si aplicar preemption...")
            
            # 🧠 PREEMPTION INMEDIATA: Para tareas urgentes/altas, intentar reasignar personal ANTES de diferir
            if cleaning_task.priority in ['urgent', 'high']:
                logger.info(f"🧠 EVALUANDO reasignación inteligente para tarea {cleaning_task.priority}")
                
                # PASO 1: Buscar tareas preemptables inmediatamente
                preemptable_tasks = find_preemptable_tasks_for_date(
                    reservation.check_out_date, 
                    cleaning_task.priority
                )
                
                preemption_successful = False
                if preemptable_tasks:
                    # Seleccionar mejor candidato (menor prioridad primero)
                    priority_order = {'low': 1, 'medium': 2, 'high': 3, 'urgent': 4}
                    best_target = min(preemptable_tasks, key=lambda t: priority_order.get(t.priority, 4))
                    preemption_successful = preempt_task_for_urgent(cleaning_task, best_target)
                
                if preemption_successful:
                    logger.info(f"✅ Preemption exitosa: tarea {cleaning_task.priority} asignada mediante reasignación de personal")
                    # Personal ya asignado por preempt_task_for_urgent, no hacer nada más
                    return
                else:
                    logger.info(f"⚠️ Preemption falló: {len(preemptable_tasks)} candidatos evaluados, ninguno viable")
            
            # Si llegamos aquí, preemption falló o no aplicaba - continuar con flujo normal
            logger.info(f"🔄 Continuando con reorganización tradicional y diferimiento para tarea {cleaning_task.priority}")
            
            # PASO 2: Reorganización tradicional como fallback
            if cleaning_task.priority in ['urgent', 'high']:
                trigger_smart_reorganization(reservation)
                
                # Verificar si la reorganización liberó personal
                assigned_staff = find_best_cleaning_staff(reservation.check_out_date, reservation.property, reservation, cleaning_task)
                if assigned_staff:
                    cleaning_task.staff_member = assigned_staff
                    cleaning_task.status = 'assigned'
                    cleaning_task.save()
                    logger.info(f"✅ Personal reasignado después de reorganización: {assigned_staff.first_name} {assigned_staff.last_name}")
                    return
            
            # PASO 3: Diferir como último recurso
            deferred_task = defer_cleaning_task_automatically(cleaning_task, reservation)
            if not deferred_task:
                # Si no se pudo diferir, la tarea queda pendiente para revisión manual
                logger.warning(f"⚠️ No se pudo diferir tarea {cleaning_task.id} - Queda pendiente para revisión manual")
        
        if assigned_staff:
            logger.info(
                f"✅ Created and assigned cleaning task {cleaning_task.id} to {assigned_staff.first_name} {assigned_staff.last_name} "
                f"for reservation {reservation.id} on {reservation.check_out_date}"
            )
        else:
            logger.info(
                f"✅ Created unassigned cleaning task {cleaning_task.id} for reservation {reservation.id} "
                f"on {reservation.check_out_date} - requires manual assignment"
            )
            
    except Exception as e:
        logger.error(f"❌ Error creating automatic cleaning task for reservation {reservation.id}: {str(e)}")


def find_best_cleaning_staff(scheduled_date, property_obj, reservation, task=None):
    """Encuentra el mejor personal de limpieza disponible para una fecha y propiedad específica"""
    if not StaffMember:
        return None
    
    try:
        # Buscar personal de limpieza activo (incluyendo 'both' que pueden limpiar)
        cleaning_staff = StaffMember.objects.filter(
            staff_type__in=['cleaning', 'both'],  # Incluir personal que puede limpiar
            status='active',
            deleted=False
        )
        
        if not cleaning_staff.exists():
            logger.warning("No active cleaning staff found")
            return None
        
        # Filtrar personal disponible
        available_staff = []
        
        for staff in cleaning_staff:
            if is_staff_available(staff, scheduled_date, property_obj, reservation):
                workload = get_staff_workload(staff, scheduled_date)
                available_staff.append((staff, workload))
        
        if not available_staff:
            logger.warning(f"No available cleaning staff for {scheduled_date}")
            return None
        
        # Ordenar por menor carga de trabajo (menor número = mejor)
        available_staff.sort(key=lambda x: x[1])
        best_staff, current_workload = available_staff[0]
        
        # Logging simple sin puntos
        logger.info(f"👷 PERSONAL SELECCIONADO para {scheduled_date}:")
        logger.info(f"   ✅ {best_staff.first_name} {best_staff.last_name} (carga actual: {current_workload} tareas)")
        
        return best_staff
        
    except Exception as e:
        logger.error(f"Error finding best cleaning staff: {str(e)}")
        return None


def is_staff_available(staff, scheduled_date, property_obj, reservation):
    """
    Verificar si un miembro del staff está disponible para una tarea en una fecha específica.
    Sin sistema de puntos - solo verifica disponibilidad y límites.
    """
    try:
        # Verificar disponibilidad en fin de semana
        weekday = scheduled_date.weekday()  # 0=Monday, 6=Sunday
        if weekday >= 5 and not staff.can_work_weekends:  # Sábado o domingo
            logger.debug(f"{staff.first_name} {staff.last_name} no puede trabajar fines de semana")
            return False
        
        # Contar tareas ya asignadas para esa fecha
        tasks_on_date = WorkTask.objects.filter(
            staff_member=staff,
            scheduled_date=scheduled_date,
            status__in=['pending', 'assigned', 'in_progress'],
            deleted=False
        ).count()
        
        # Determinar límite máximo basado en número de huéspedes
        guests = reservation.guests if reservation else 1
        if guests <= 2:
            # Para reservas pequeñas (≤2 personas), verificar que TODAS las tareas ya asignadas también tengan ≤2 personas
            existing_tasks = WorkTask.objects.filter(
                staff_member=staff,
                scheduled_date=scheduled_date,
                status__in=['pending', 'assigned', 'in_progress'],
                deleted=False
            ).select_related('reservation')
            
            # Verificar que todas las tareas existentes también sean de ≤2 huéspedes
            can_take_multiple = True
            for existing_task in existing_tasks:
                if existing_task.reservation and existing_task.reservation.guests > 2:
                    can_take_multiple = False
                    logger.debug(f"Personal {staff.first_name} ya tiene tarea con {existing_task.reservation.guests} huéspedes (>2), no puede tomar más tareas")
                    break
            
            if can_take_multiple:
                # Todas las tareas son ≤2 personas, puede manejar hasta 2 propiedades
                max_properties_today = min(2, staff.max_properties_per_day)
                logger.debug(f"Personal {staff.first_name} puede tomar hasta {max_properties_today} propiedades (todas ≤2 huéspedes)")
            else:
                # Ya tiene una tarea de >2 personas, solo 1 propiedad total
                max_properties_today = 1
                logger.debug(f"Personal {staff.first_name} limitado a 1 propiedad por tarea con >2 huéspedes")
        else:
            # Para reservas grandes (>2 personas), solo 1 propiedad por día
            max_properties_today = 1
            logger.debug(f"Reserva de {guests} huéspedes: personal {staff.first_name} limitado a 1 propiedad")
        
        # Verificar límite máximo de propiedades por día
        if tasks_on_date >= max_properties_today:
            logger.debug(f"Personal {staff.first_name} ya tiene {tasks_on_date} tareas (máximo {max_properties_today})")
            return False
        
        return True
        
    except Exception as e:
        logger.error(f"Error verificando disponibilidad de personal {staff.id}: {str(e)}")
        return False


def get_staff_workload(staff, scheduled_date):
    """Obtener la carga de trabajo actual de un miembro del staff para una fecha"""
    return WorkTask.objects.filter(
        staff_member=staff,
        scheduled_date=scheduled_date,
        status__in=['pending', 'assigned', 'in_progress'],
        deleted=False
    ).count()


def defer_cleaning_task_automatically(original_task, reservation):
    """
    Diferir automáticamente una tarea de limpieza cuando no hay personal disponible.
    
    Pasos:
    1. Registrar gap de limpieza para la fecha original
    2. Buscar próximo día laborable con personal disponible  
    3. Crear nueva tarea diferida
    4. Eliminar tarea original (no asignada)
    5. Marcar gap como resuelto cuando se asigna
    """
    if not PropertyCleaningGap or not WorkTask:
        logger.warning("PropertyCleaningGap or WorkTask models not available")
        return None
    
    try:
        original_date = original_task.scheduled_date
        property_obj = original_task.building_property
        
        # PASO 1: Registrar gap de limpieza para la fecha original
        gap_reason = determine_gap_reason(original_date, property_obj, reservation)
        
        # Verificar si ya existe un gap para esta fecha/propiedad
        existing_gap = PropertyCleaningGap.objects.filter(
            building_property=property_obj,
            gap_date=original_date,
            resolved=False
        ).first()
        
        if not existing_gap:
            gap = PropertyCleaningGap.objects.create(
                building_property=property_obj,
                reservation=reservation,
                gap_date=original_date,
                reason=gap_reason,
                original_required_date=original_date,
                notes=f"Diferido automáticamente por {gap_reason}"
            )
            logger.info(f"🚫 Gap registrado: {property_obj.name} sin limpieza el {original_date} ({gap_reason})")
        else:
            gap = existing_gap
            logger.info(f"🔄 Gap ya existe para {property_obj.name} el {original_date}")
        
        # PASO 2: Buscar próximo día laborable con personal disponible
        max_days_to_search = 7  # Buscar hasta 1 semana adelante
        current_date = original_date + timezone.timedelta(days=1)
        
        for day_offset in range(1, max_days_to_search + 1):
            candidate_date = original_date + timezone.timedelta(days=day_offset)
            
            # Verificar si ya existe una tarea de limpieza para esta reserva en cualquier fecha
            existing_deferred_task = WorkTask.objects.filter(
                reservation=reservation,
                task_type='checkout_cleaning',
                deleted=False,
                scheduled_date__gt=original_date  # Solo tareas futuras diferidas
            ).first()
            
            if existing_deferred_task:
                logger.info(f"⚠️ Ya existe tarea diferida para reserva {reservation.id} en {existing_deferred_task.scheduled_date}")
                # Eliminar tarea original no asignada
                original_task.delete()
                return existing_deferred_task
            
            # Buscar personal disponible para la fecha candidata
            available_staff = find_best_cleaning_staff(candidate_date, property_obj, reservation, None)
            
            if available_staff:
                # PASO 3: Crear nueva tarea diferida
                deferred_task = WorkTask.objects.create(
                    staff_member=available_staff,
                    building_property=property_obj,
                    reservation=reservation,
                    task_type='checkout_cleaning',
                    title=f"Limpieza diferida - {property_obj.name}",
                    description=f"Limpieza post-checkout DIFERIDA desde {original_date}\n"
                              f"Reserva #{reservation.id}\n"
                              f"Cliente: {f'{reservation.client.first_name} {reservation.client.last_name}'.strip() if reservation.client else 'N/A'}\n"
                              f"🔄 DIFERIDO: Personal no disponible el {original_date}",
                    scheduled_date=candidate_date,
                    estimated_duration=timezone.timedelta(hours=2),
                    priority=original_task.priority,  # Mantener prioridad original
                    status='assigned',
                    requires_photo_evidence=True
                )
                
                # PASO 4: Eliminar tarea original (no asignada)
                original_task.delete()
                
                # PASO 5: Marcar gap como resuelto
                gap.mark_resolved(candidate_date)
                
                logger.info(
                    f"✅ DIFERIMIENTO EXITOSO: Tarea {deferred_task.id} creada para {property_obj.name}\n"
                    f"   📅 Original: {original_date} → Diferida: {candidate_date}\n" 
                    f"   👷 Asignada a: {available_staff.first_name} {available_staff.last_name}\n"
                    f"   🏠 Casa estuvo {day_offset} día(s) sin limpieza"
                )
                
                return deferred_task
        
        # PASO 6: Si no se pudo diferir en 7 días, mantener tarea original como pending
        logger.warning(
            f"❌ No se pudo diferir tarea para {property_obj.name} - Sin personal disponible en {max_days_to_search} días\n"
            f"   📅 Fecha original: {original_date}\n"
            f"   🔍 Búsqueda hasta: {original_date + timezone.timedelta(days=max_days_to_search)}"
        )
        
        # Agregar nota al gap indicando que no se pudo resolver automáticamente
        gap.notes += f"\n⚠️ No se pudo diferir automáticamente - Sin personal disponible por {max_days_to_search} días"
        gap.save()
        
        return None
        
    except Exception as e:
        logger.error(f"❌ Error diferiendo tarea automáticamente: {str(e)}")
        return None


def determine_gap_reason(scheduled_date, property_obj, reservation):
    """Determina la razón específica por la cual no hay personal disponible"""
    try:
        # Verificar si es fin de semana
        weekday = scheduled_date.weekday()
        if weekday >= 5:  # Sábado o domingo
            weekend_staff = StaffMember.objects.filter(
                staff_type='cleaning',
                status='active',
                deleted=False,
                can_work_weekends=True
            ).count()
            
            if weekend_staff == 0:
                return PropertyCleaningGap.GapReason.WEEKEND_UNAVAILABLE
        
        # Verificar si hay personal activo en general
        total_staff = StaffMember.objects.filter(
            staff_type='cleaning',
            status='active',
            deleted=False
        ).count()
        
        if total_staff == 0:
            return PropertyCleaningGap.GapReason.NO_STAFF_AVAILABLE
        
        # Verificar si todos están sobrecargados
        guests = reservation.guests if reservation else 1
        for staff in StaffMember.objects.filter(staff_type='cleaning', status='active', deleted=False):
            tasks_on_date = WorkTask.objects.filter(
                staff_member=staff,
                scheduled_date=scheduled_date,
                status__in=['pending', 'assigned', 'in_progress'],
                deleted=False
            ).count()
            
            max_properties = 2 if guests <= 2 else 1
            if tasks_on_date < max_properties:
                return PropertyCleaningGap.GapReason.CAPACITY_EXCEEDED
        
        # Por defecto, es sobrecarga general
        return PropertyCleaningGap.GapReason.STAFF_OVERLOAD
        
    except Exception as e:
        logger.error(f"Error determinando razón del gap: {e}")
        return PropertyCleaningGap.GapReason.STAFF_OVERLOAD


# ============================================================================
# SEÑALES PARA NOTIFICACIONES PUSH
# ============================================================================

@receiver(pre_save, sender=Reservation)
def track_reservation_push_changes(sender, instance, **kwargs):
    """
    Guarda el estado anterior de la reserva para detectar cambios
    y enviar notificaciones push apropiadas
    """
    if instance.pk:
        try:
            instance._old_reservation = Reservation.objects.get(pk=instance.pk)
        except Reservation.DoesNotExist:
            instance._old_reservation = None
    else:
        instance._old_reservation = None


@receiver(post_save, sender=Reservation)
def send_reservation_push_notifications(sender, instance, created, **kwargs):
    """
    Envía notificaciones push a CLIENTES y ADMINISTRADORES cuando se crea o modifica una reserva
    """
    # Verificar que la reserva tiene datos mínimos
    if not instance.property:
        logger.debug(f"Reserva {instance.id} sin propiedad - no se envía notificación push")
        return
    
    try:
        from apps.clients.expo_push_service import ExpoPushService, NotificationTypes
        
        # 1. RESERVA NUEVA CREADA
        if created:
            logger.info(f"📱 Nueva reserva {instance.id} creada - Enviando notificaciones push")
            
            # A) Notificar al CLIENTE
            if instance.client:
                notification = NotificationTypes.reservation_created(instance)
                result = ExpoPushService.send_to_client(
                    client=instance.client,
                    title=notification['title'],
                    body=notification['body'],
                    data=notification['data']
                )
                if result and result.get('success'):
                    logger.info(f"✅ Notificación enviada al cliente: {result.get('sent', 0)} dispositivo(s)")
                elif result:
                    logger.debug(f"Cliente sin tokens: {result.get('error', 'Sin tokens')}")
            
            # B) Notificar a ADMINISTRADORES
            client_name = f"{instance.client.first_name} {instance.client.last_name}" if instance.client else "Cliente no especificado"
            check_in = NotificationTypes._format_date(instance.check_in_date)
            check_out = NotificationTypes._format_date(instance.check_out_date)
            price = NotificationTypes._format_price(instance.price_usd)
            guests = instance.guests or 1
            
            result_admin = ExpoPushService.send_to_admins(
                title="Nueva Reserva Creada",
                body=f"{client_name} - {instance.property.name}\n{check_in} al {check_out} | {guests} huéspedes | {price} USD",
                data={
                    "type": "admin_reservation_created",
                    "reservation_id": str(instance.id),
                    "property_name": instance.property.name,
                    "client_name": client_name,
                    "check_in": str(instance.check_in_date),
                    "check_out": str(instance.check_out_date),
                    "guests": guests,
                    "price_usd": str(instance.price_usd),
                    "screen": "AdminReservationDetail"
                }
            )
            if result_admin and result_admin.get('success'):
                logger.info(f"✅ Notificación enviada a {result_admin.get('sent', 0)} administrador(es)")
            return
        
        # 2. RESERVA MODIFICADA - Detectar cambios importantes  
        old = getattr(instance, '_old_reservation', None)
        if not old:
            return
        
        client_name = f"{instance.client.first_name} {instance.client.last_name}" if instance.client else "Cliente"
        
        # 3. CAMBIO DE ESTADO (Pago aprobado, cancelado, etc.)
        if old.status != instance.status:
            logger.info(f"📱 Cambio de estado en reserva {instance.id}: {old.status} → {instance.status}")
            
            # A) Notificar al CLIENTE
            if instance.client:
                if instance.status in ['pago_confirmado', 'pagado', 'confirmed', 'approved']:
                    notification = NotificationTypes.payment_approved(instance)
                elif instance.status in ['cancelled', 'cancelado']:
                    reason = getattr(instance, 'cancellation_reason', None) or "Sin motivo"
                    notification = NotificationTypes.reservation_cancelled(instance, reason=reason)
                elif instance.status in ['pending', 'pendiente', 'under_review']:
                    notification = NotificationTypes.payment_pending(instance)
                else:
                    notification = None
                
                if notification:
                    result = ExpoPushService.send_to_client(
                        client=instance.client,
                        title=notification['title'],
                        body=notification['body'],
                        data=notification['data']
                    )
                    if result and result.get('success'):
                        logger.info(f"✅ Notificación enviada al cliente: {result.get('sent', 0)} dispositivo(s)")
            
            # B) Notificar a ADMINISTRADORES
            status_display = {
                'pago_confirmado': 'Pago Confirmado',
                'pagado': 'Pagado',
                'confirmed': 'Confirmada',
                'approved': 'Aprobada',
                'cancelled': 'Cancelada',
                'cancelado': 'Cancelada',
                'pending': 'Pendiente',
                'pendiente': 'Pendiente',
                'under_review': 'En Revisión'
            }.get(instance.status, instance.status.title())
            
            result_admin = ExpoPushService.send_to_admins(
                title=f"Cambio de Estado: {status_display}",
                body=f"{client_name} - {instance.property.name}\nNuevo estado: {status_display}",
                data={
                    "type": "admin_status_changed",
                    "reservation_id": str(instance.id),
                    "client_name": client_name,
                    "property_name": instance.property.name,
                    "old_status": old.status,
                    "new_status": instance.status,
                    "screen": "AdminReservationDetail"
                }
            )
            if result_admin and result_admin.get('success'):
                logger.info(f"✅ Notificación enviada a {result_admin.get('sent', 0)} admin(s)")
        
        # 4-6. DETECTAR TODOS LOS CAMBIOS Y CONSOLIDAR EN UNA NOTIFICACIÓN
        changes = []
        changes_data = {}
        
        # Detectar cambios de fechas
        dates_changed = old.check_in_date != instance.check_in_date or old.check_out_date != instance.check_out_date
        if dates_changed:
            check_in = NotificationTypes._format_date(instance.check_in_date)
            check_out = NotificationTypes._format_date(instance.check_out_date)
            changes.append(f"Fechas: {check_in} al {check_out}")
            changes_data.update({
                "dates_changed": True,
                "check_in": str(instance.check_in_date),
                "check_out": str(instance.check_out_date)
            })
        
        # Detectar cambios de precio
        price_changed = old.price_usd != instance.price_usd or old.price_sol != instance.price_sol
        if price_changed:
            price_usd = NotificationTypes._format_price(instance.price_usd)
            price_pen = NotificationTypes._format_price(instance.price_sol)
            changes.append(f"Precio: {price_usd} USD / S/{price_pen}")
            changes_data.update({
                "price_changed": True,
                "old_price_usd": str(old.price_usd),
                "new_price_usd": str(instance.price_usd),
                "old_price_pen": str(old.price_sol),
                "new_price_pen": str(instance.price_sol)
            })
        
        # Detectar cambios de huéspedes
        guests_changed = old.guests != instance.guests
        if guests_changed:
            old_guests = old.guests or 0
            new_guests = instance.guests or 0
            changes.append(f"Huéspedes: {new_guests} persona{'s' if new_guests != 1 else ''}")
            changes_data.update({
                "guests_changed": True,
                "old_guests": old_guests,
                "new_guests": new_guests
            })
        
        # Si hay cambios, enviar UNA sola notificación consolidada
        if changes:
            logger.info(f"📱 Cambios en reserva {instance.id}: {', '.join(changes)}")
            
            # Construir mensaje consolidado
            changes_text = "\n".join(changes)
            
            # Determinar tipo de notificación basado en cambios
            if len(changes) > 1:
                notification_type = "reservation_updated"
                title_client = "Reserva Actualizada"
                title_admin = "Reserva Modificada"
            elif dates_changed:
                notification_type = "reservation_dates_changed"
                title_client = "Fechas Actualizadas"
                title_admin = "Cambio de Fechas"
            elif price_changed:
                notification_type = "reservation_price_changed"
                title_client = "Precio Actualizado"
                title_admin = "Cambio de Precio"
            else:  # guests_changed
                notification_type = "reservation_guests_changed"
                title_client = "Huéspedes Actualizados"
                title_admin = "Cambio de Huéspedes"
            
            # A) Notificar al CLIENTE
            if instance.client:
                notification = NotificationTypes.custom(
                    title=title_client,
                    body=f"Tu reserva en {instance.property.name} ha sido actualizada:\n{changes_text}",
                    data={
                        "type": notification_type,
                        "notification_type": notification_type,
                        "reservation_id": str(instance.id),
                        "property_name": instance.property.name,
                        **changes_data,
                        "screen": "ReservationDetail"
                    }
                )
                result = ExpoPushService.send_to_client(
                    client=instance.client,
                    title=notification['title'],
                    body=notification['body'],
                    data=notification['data']
                )
                if result and result.get('success'):
                    logger.info(f"✅ Notificación consolidada enviada al cliente: {result.get('sent', 0)} dispositivo(s)")
            
            # B) Notificar a ADMINISTRADORES
            admin_type = f"admin_{notification_type}" if not notification_type.startswith("admin_") else notification_type
            result_admin = ExpoPushService.send_to_admins(
                title=title_admin,
                body=f"{client_name} - {instance.property.name}\n{changes_text}",
                data={
                    "type": admin_type,
                    "notification_type": admin_type,
                    "reservation_id": str(instance.id),
                    "client_name": client_name,
                    "property_name": instance.property.name,
                    **changes_data,
                    "screen": "AdminReservationDetail"
                }
            )
            if result_admin and result_admin.get('success'):
                logger.info(f"✅ Notificación consolidada enviada a {result_admin.get('sent', 0)} admin(s)")
    
    except ImportError:
        logger.warning("ExpoPushService no disponible - notificaciones push deshabilitadas")
    except Exception as e:
        logger.error(f"❌ Error enviando notificación push para reserva {instance.id}: {str(e)}", exc_info=True)

@receiver(pre_delete, sender=Reservation)
def reservation_pre_delete_handler(sender, instance, **kwargs):
    """
    Maneja notificaciones push cuando se elimina una reserva.
    Notifica tanto al cliente como a los administradores.
    """
    try:
        from apps.clients.expo_push_service import ExpoPushService, NotificationTypes
        
        if not instance or instance.deleted:
            return
        
        logger.info(f"🗑️ Eliminando reserva {instance.id} - Enviando notificaciones")
        
        # Información de la reserva
        client_name = f"{instance.client.first_name} {instance.client.last_name}" if instance.client else "Cliente desconocido"
        check_in = NotificationTypes._format_date(instance.check_in_date)
        check_out = NotificationTypes._format_date(instance.check_out_date)
        price = NotificationTypes._format_price(instance.price_usd)
        guests = instance.guests or 1
        
        # NOTIFICAR AL CLIENTE
        if instance.client:
            notification = NotificationTypes.custom(
                title="Reserva Cancelada",
                body=f"Tu reserva en {instance.property.name} ha sido cancelada.\nFechas: {check_in} al {check_out}\nSi tienes dudas, contáctanos.",
                data={
                    "type": "reservation_deleted",
                    "notification_type": "reservation_deleted",
                    "reservation_id": str(instance.id),
                    "property_name": instance.property.name,
                    "check_in": str(instance.check_in_date),
                    "check_out": str(instance.check_out_date),
                    "price_usd": str(instance.price_usd),
                    "guests": guests,
                    "screen": "Reservations"
                }
            )
            result = ExpoPushService.send_to_client(
                client=instance.client,
                title=notification['title'],
                body=notification['body'],
                data=notification['data']
            )
            if result and result.get('success'):
                logger.info(f"✅ Notificación de eliminación enviada al cliente: {result.get('sent', 0)} dispositivo(s)")
        
        # NOTIFICAR A ADMINISTRADORES
        result_admin = ExpoPushService.send_to_admins(
            title="Reserva Eliminada",
            body=f"{client_name} - {instance.property.name}\n{check_in} al {check_out} | {guests} huéspedes | {price} USD",
            data={
                "type": "admin_reservation_deleted",
                "notification_type": "admin_reservation_deleted",
                "reservation_id": str(instance.id),
                "property_name": instance.property.name,
                "client_name": client_name,
                "check_in": str(instance.check_in_date),
                "check_out": str(instance.check_out_date),
                "guests": guests,
                "price_usd": str(instance.price_usd),
                "screen": "AdminReservations"
            }
        )
        if result_admin and result_admin.get('success'):
            logger.info(f"✅ Notificación de eliminación enviada a {result_admin.get('sent', 0)} administrador(es)")
    
    except ImportError:
        logger.warning("ExpoPushService no disponible - notificaciones push de eliminación deshabilitadas")
    except Exception as e:
        logger.error(f"❌ Error enviando notificación de eliminación para reserva {instance.id}: {str(e)}", exc_info=True)
