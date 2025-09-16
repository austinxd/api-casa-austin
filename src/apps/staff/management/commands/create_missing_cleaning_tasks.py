from django.core.management.base import BaseCommand
from django.utils import timezone
from apps.reservation.models import Reservation
from apps.staff.models import WorkTask, PropertyCleaningGap
from apps.reservation.signals import create_automatic_cleaning_task, get_priority_from_property
import logging

logger = logging.getLogger(__name__)

def calculate_priority_for_reservation(reservation):
    """
    Calcula la prioridad de una reserva basada en la proximidad del próximo check-in.
    Retorna una tupla (priority_order, priority_label, gap_days) para ordenamiento.
    USA función centralizada para evitar duplicación de lógica.
    """
    try:
        # Usar la función centralizada para evitar duplicación
        priority_label, gap_days = get_priority_from_property(
            reservation.property.id,
            reservation.check_out_date
        )
        
        # Mapear a orden numérico para sorting: 1=urgente, 2=alta, 3=media, 4=baja
        priority_order_map = {
            'urgent': 1,
            'high': 2, 
            'medium': 3,
            'low': 4
        }
        priority_order = priority_order_map.get(priority_label, 4)
        
        return (priority_order, priority_label, gap_days)
            
    except Exception as e:
        logger.error(f"Error calculando prioridad para reserva {reservation.id}: {e}")
        return (4, 'low', None)  # Prioridad baja por defecto en caso de error

class Command(BaseCommand):
    help = 'Crear tareas de limpieza para reservas aprobadas existentes que no tienen tareas asignadas'

    def add_arguments(self, parser):
        parser.add_argument(
            '--dry-run',
            action='store_true',
            help='Solo mostrar qué se haría sin ejecutar los cambios'
        )
        parser.add_argument(
            '--start-date',
            type=str,
            help='Procesar solo reservas desde esta fecha (YYYY-MM-DD)'
        )

    def handle(self, *args, **options):
        dry_run = options['dry_run']
        start_date = options.get('start_date')
        
        # Filtros base - solo reservas desde hoy en adelante
        from datetime import date
        today = date.today()
        
        filters = {
            'status': 'approved',
            'check_out_date__gte': today,  # Solo reservas futuras o de hoy
            'deleted': False,  # Solo reservas NO eliminadas
        }
        
        # Si se especifica fecha de inicio, usarla en lugar de hoy
        if start_date:
            try:
                from datetime import datetime
                start_date_obj = datetime.strptime(start_date, '%Y-%m-%d').date()
                filters['check_out_date__gte'] = start_date_obj
                self.stdout.write(f'📅 Procesando reservas desde: {start_date}')
            except ValueError:
                self.stdout.write(
                    self.style.ERROR(f'Formato de fecha inválido: {start_date}. Usa YYYY-MM-DD')
                )
                return
        else:
            self.stdout.write(f'📅 Procesando reservas desde hoy: {today}')

        # Buscar reservas aprobadas sin tareas de limpieza
        approved_reservations = Reservation.objects.filter(**filters)
        
        reservations_to_process = []
        for reservation in approved_reservations:
            # Verificar si ya tiene tarea de limpieza
            existing_task = WorkTask.objects.filter(
                reservation=reservation,
                task_type='checkout_cleaning'
            ).first()
            
            if not existing_task:
                reservations_to_process.append(reservation)

        self.stdout.write(f'\n📊 RESUMEN:')
        self.stdout.write(f'   • Total reservas aprobadas encontradas: {approved_reservations.count()}')
        self.stdout.write(f'   • Reservas SIN tarea de limpieza: {len(reservations_to_process)}')
        
        # ============================================================================
        # 🚀 FASE 1: CREAR TAREAS DE LIMPIEZA FALTANTES (SI HAY)
        # ============================================================================
        
        # Inicializar variables de control
        created_count = 0
        deferred_count = 0
        error_count = 0
        gaps_created = 0
        reservations_with_priority = []  # Inicializar para evitar errores de scope
        
        if not reservations_to_process:
            self.stdout.write(
                self.style.SUCCESS('✅ Todas las reservas aprobadas ya tienen sus tareas de limpieza asignadas!')
            )
        else:
            # NUEVO: Ordenar reservas por prioridad antes de procesarlas
            self.stdout.write(f'\n🎯 CALCULANDO PRIORIDADES Y ORDENANDO...')
            
            # Calcular prioridad para cada reserva
            for reservation in reservations_to_process:
                priority_order, priority_label, gap_days = calculate_priority_for_reservation(reservation)
                reservations_with_priority.append((reservation, priority_order, priority_label, gap_days))
            
            # Ordenar por prioridad: primero urgente (1), luego alta (2), media (3), baja (4)
            # Dentro de cada grupo, ordenar por gap_days (menor número = mayor urgencia)
            reservations_with_priority.sort(key=lambda x: (x[1], x[3] if x[3] is not None else 999, x[0].check_out_date))
            
            # Actualizar la lista de reservas a procesar con el orden prioritario
            reservations_to_process = [item[0] for item in reservations_with_priority]
            
            self.stdout.write(f'\n📋 RESERVAS A PROCESAR (ORDENADAS POR PRIORIDAD):')
            for i, (reservation, priority_order, priority_label, gap_days) in enumerate(reservations_with_priority):
                client_name = f'{reservation.client.first_name} {reservation.client.last_name}'.strip() if reservation.client else 'N/A'
                
                # Emojis por prioridad
                priority_emoji = {
                    'urgent': '🚨',
                    'high': '🔥', 
                    'medium': '📅',
                    'low': '📋'
                }.get(priority_label, '📋')
                
                gap_info = f" (próximo check-in en {gap_days} día(s))" if gap_days is not None else " (sin próximo check-in)"
                
                self.stdout.write(
                    f'   {i+1:2d}. {priority_emoji} {priority_label.upper()} | ID: {reservation.id} | Cliente: {client_name} | '
                    f'Propiedad: {reservation.property.name} | Checkout: {reservation.check_out_date}{gap_info}'
                )

            # Solo procesar reservas si NO es dry-run
            if not dry_run:
                self.stdout.write(f'\n🚀 PROCESANDO {len(reservations_to_process)} reservas...')
                
                from apps.staff.models import PropertyCleaningGap
                initial_gaps = PropertyCleaningGap.objects.count()
                
                for reservation in reservations_to_process:
                    try:
                        create_automatic_cleaning_task(reservation)
                        created_count += 1
                        client_name = f'{reservation.client.first_name} {reservation.client.last_name}'.strip() if reservation.client else 'N/A'
                        
                        # Verificar si la tarea fue asignada o diferida
                        task = WorkTask.objects.filter(
                            reservation=reservation,
                            task_type='checkout_cleaning'
                        ).first()
                        
                        if task:
                            if task.scheduled_date == reservation.check_out_date:
                                # Tarea asignada para el día original
                                staff_name = task.staff_member.full_name if task.staff_member else 'Sin asignar'
                                self.stdout.write(
                                    f'   ✅ Tarea asignada: {reservation.id} ({client_name}) → {staff_name}'
                                )
                            else:
                                # Tarea diferida
                                deferred_count += 1
                                days_diff = (task.scheduled_date - reservation.check_out_date).days
                                staff_name = task.staff_member.full_name if task.staff_member else 'Sin asignar'
                                self.stdout.write(
                                    f'   🔄 Tarea DIFERIDA: {reservation.id} ({client_name}) → {staff_name} (+{days_diff} días)'
                                )
                        
                    except Exception as e:
                        error_count += 1
                        self.stdout.write(
                            self.style.ERROR(f'   ❌ Error procesando reserva {reservation.id}: {str(e)}')
                        )
                
                # Contar gaps creados en este proceso
                final_gaps = PropertyCleaningGap.objects.count()
                gaps_created = final_gaps - initial_gaps
            else:
                self.stdout.write(
                    self.style.WARNING('\n🔍 MODO DRY-RUN - Creación de tareas omitida.')
                )

        # ============================================================================
        # 🧠 FASE 2: REORGANIZACIÓN COMPLETA DE TODAS LAS TAREAS EXISTENTES
        # ============================================================================
        
        if dry_run:
            self.stdout.write(f'\n🧠 ANALIZANDO todas las tareas existentes (MODO DRY-RUN)...')
        else:
            self.stdout.write(f'\n🧠 INICIANDO reorganización completa de todas las tareas...')
        
        # Buscar TODAS las tareas de limpieza futuras (pendientes, asignadas)
        all_cleaning_tasks = WorkTask.objects.filter(
            task_type='checkout_cleaning',
            scheduled_date__gte=timezone.now().date(),  # Solo futuras
            status__in=['pending', 'assigned'],  # Solo no completadas
            deleted=False
        ).select_related('staff_member', 'building_property', 'reservation').order_by('scheduled_date', 'priority')
        
        reorganization_stats = {
            'total_evaluated': all_cleaning_tasks.count(),
            'reassigned': 0,
            'priority_changed': 0,
            'preemptions': 0,
            'deferred': 0,
            'errors': 0
        }
        
        self.stdout.write(f'   📊 Evaluando {reorganization_stats["total_evaluated"]} tareas existentes...')
        
        # Solo importar y ejecutar reorganización si NO es dry-run
        if not dry_run:
            # Importar funciones de reorganización
            from apps.reservation.signals import (
                reorganize_affected_tasks, 
                find_preemptable_tasks_for_date,
                preempt_task_for_urgent,
                find_best_cleaning_staff
            )
            
            # Evaluar cada tarea para posible reorganización
            for task in all_cleaning_tasks:
                try:
                    # Guardar estado original
                    original_staff = task.staff_member
                    original_priority = task.priority
                    
                    # PASO 1: Recalcular prioridad basada en context actual
                    if task.reservation:
                        
                        # Recalcular gap_days y prioridad usando lógica simplificada
                        today = timezone.now().date()
                        next_checkin_same_property = task.reservation.property.reservation_set.filter(
                            status='approved',
                            check_in_date__gt=task.reservation.check_out_date,
                            check_in_date__gte=today
                        ).order_by('check_in_date').first()
                        
                        if next_checkin_same_property:
                            gap_days = (next_checkin_same_property.check_in_date - task.reservation.check_out_date).days
                        else:
                            gap_days = None
                        
                        # Calcular nueva prioridad
                        if gap_days is not None:
                            if gap_days == 0:  # Check-in el mismo día
                                new_priority = 'urgent'
                                priority_label = 'URGENTE'
                            elif gap_days == 1:  # Check-in al día siguiente
                                new_priority = 'high'
                                priority_label = 'ALTA'
                            elif gap_days <= 3:  # Check-in en pocos días
                                new_priority = 'medium'
                                priority_label = 'MEDIA'
                            else:  # Check-in lejano
                                new_priority = 'low'
                                priority_label = 'BAJA'
                        else:
                            # Sin próximo check-in conocido
                            new_priority = 'medium'
                            priority_label = 'MEDIA'
                        
                        if new_priority != task.priority:
                            task.priority = new_priority
                            task.save()
                            reorganization_stats['priority_changed'] += 1
                            self.stdout.write(f'   🔄 Prioridad actualizada: Tarea {task.id} → {priority_label}')
                    
                    # PASO 2: Si es tarea urgente/alta sin asignar, intentar preemption
                    if task.priority in ['urgent', 'high'] and not task.staff_member:
                        preemptable_tasks = find_preemptable_tasks_for_date(
                            task.scheduled_date, 
                            task.priority
                        )
                        
                        if preemptable_tasks:
                            # Seleccionar mejor candidato
                            priority_order = {'low': 1, 'medium': 2, 'high': 3, 'urgent': 4}
                            best_target = min(preemptable_tasks, key=lambda t: priority_order.get(t.priority, 4))
                            
                            if preempt_task_for_urgent(task, best_target):
                                reorganization_stats['preemptions'] += 1
                                staff_name = task.staff_member.full_name if task.staff_member else 'N/A'
                                self.stdout.write(f'   ⚡ PREEMPTION: Tarea {task.id} robó personal → {staff_name}')
                                continue
                    
                    # PASO 3: Buscar mejor asignación si no está asignada o si hay mejor opción
                    if not task.staff_member or task.priority in ['urgent', 'high']:
                        better_staff = find_best_cleaning_staff(
                            task.scheduled_date, 
                            task.building_property, 
                            task.reservation, 
                            task
                        )
                        
                        if better_staff and better_staff != original_staff:
                            task.staff_member = better_staff
                            task.status = 'assigned'
                            task.save()
                            reorganization_stats['reassigned'] += 1
                            
                            if original_staff:
                                self.stdout.write(f'   ↔️  REASIGNACIÓN: Tarea {task.id} ({original_staff.full_name} → {better_staff.full_name})')
                            else:
                                self.stdout.write(f'   ✅ ASIGNACIÓN: Tarea {task.id} → {better_staff.full_name}')
                    
                except Exception as e:
                    reorganization_stats['errors'] += 1
                    self.stdout.write(self.style.ERROR(f'   ❌ Error reorganizando tarea {task.id}: {str(e)}'))
        else:
            # En modo dry-run, solo mostrar análisis sin cambios
            self.stdout.write(
                self.style.WARNING('   🔍 MODO DRY-RUN - Reorganización omitida (solo análisis realizado)')
            )
        
        # Mostrar estadísticas de reorganización
        self.stdout.write(f'\n🎯 REORGANIZACIÓN COMPLETADA:')
        self.stdout.write(f'   • Tareas evaluadas: {reorganization_stats["total_evaluated"]}')
        if reorganization_stats['priority_changed'] > 0:
            self.stdout.write(f'   • Prioridades actualizadas: {reorganization_stats["priority_changed"]}')
        if reorganization_stats['reassigned'] > 0:
            self.stdout.write(f'   • Tareas reasignadas: {reorganization_stats["reassigned"]}')
        if reorganization_stats['preemptions'] > 0:
            self.stdout.write(self.style.SUCCESS(f'   • Preemptions exitosas: {reorganization_stats["preemptions"]}'))
        if reorganization_stats['errors'] > 0:
            self.stdout.write(self.style.ERROR(f'   • Errores de reorganización: {reorganization_stats["errors"]}'))
        else:
            self.stdout.write(self.style.SUCCESS('   • Sin errores en reorganización ✅'))

        # ============================================================================
        # 📊 RESUMEN FINAL COMBINADO
        # ============================================================================
        self.stdout.write(f'\n🎯 RESULTADOS FINALES:')
        self.stdout.write(f'   • Tareas creadas exitosamente: {created_count}')
        self.stdout.write(f'   • Tareas asignadas el día original: {created_count - deferred_count}')
        if deferred_count > 0:
            self.stdout.write(
                self.style.WARNING(f'   • Tareas DIFERIDAS automáticamente: {deferred_count}')
            )
        if gaps_created > 0:
            self.stdout.write(
                self.style.WARNING(f'   • Gaps registrados (días sin limpieza): {gaps_created}')
            )
        if error_count > 0:
            self.stdout.write(
                self.style.ERROR(f'   • Errores encontrados: {error_count}')
            )
        else:
            self.stdout.write(
                self.style.SUCCESS('   • Sin errores ✅')
            )
            
        if created_count > 0:
            self.stdout.write(
                self.style.SUCCESS(f'\n🎉 ¡Proceso completado! Se crearon {created_count} tareas de limpieza.')
            )
            if deferred_count > 0:
                self.stdout.write(
                    self.style.WARNING(f'⚠️  {deferred_count} tareas fueron diferidas automáticamente por sobrecarga de personal.')
                )
            if gaps_created > 0:
                self.stdout.write(
                    self.style.WARNING(f'📊 Usa la API /api/v1/cleaning-gaps/ para consultar detalles de los gaps registrados.')
                )