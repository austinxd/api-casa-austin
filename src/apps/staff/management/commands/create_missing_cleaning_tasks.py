from django.core.management.base import BaseCommand
from django.utils import timezone
from apps.reservation.models import Reservation
from apps.staff.models import WorkTask
from apps.reservation.signals import create_automatic_cleaning_task
import logging

logger = logging.getLogger(__name__)

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
        
        if not reservations_to_process:
            self.stdout.write(
                self.style.SUCCESS('✅ Todas las reservas aprobadas ya tienen sus tareas de limpieza asignadas!')
            )
            return

        self.stdout.write(f'\n📋 RESERVAS A PROCESAR:')
        for reservation in reservations_to_process:
            client_name = f'{reservation.client.first_name} {reservation.client.last_name}'.strip() if reservation.client else 'N/A'
            self.stdout.write(
                f'   • ID: {reservation.id} | Cliente: {client_name} | '
                f'Propiedad: {reservation.property.name} | Checkout: {reservation.check_out_date}'
            )

        if dry_run:
            self.stdout.write(
                self.style.WARNING('\n🔍 MODO DRY-RUN - No se realizaron cambios. Usa --dry-run=false para ejecutar.')
            )
            return

        # Procesar reservas
        created_count = 0
        error_count = 0
        
        self.stdout.write(f'\n🚀 PROCESANDO {len(reservations_to_process)} reservas...')
        
        for reservation in reservations_to_process:
            try:
                create_automatic_cleaning_task(reservation)
                created_count += 1
                client_name = f'{reservation.client.first_name} {reservation.client.last_name}'.strip() if reservation.client else 'N/A'
                self.stdout.write(
                    f'   ✅ Tarea creada para reserva {reservation.id} ({client_name})'
                )
            except Exception as e:
                error_count += 1
                self.stdout.write(
                    self.style.ERROR(f'   ❌ Error procesando reserva {reservation.id}: {str(e)}')
                )

        # Resumen final
        self.stdout.write(f'\n🎯 RESULTADOS FINALES:')
        self.stdout.write(f'   • Tareas creadas exitosamente: {created_count}')
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