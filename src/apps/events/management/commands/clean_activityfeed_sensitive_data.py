from django.core.management.base import BaseCommand
from django.db import connection, transaction
from django.utils import timezone
from apps.events.models import ActivityFeed
import json
import logging

logger = logging.getLogger(__name__)


class Command(BaseCommand):
    help = 'Elimina datos sensibles (price_sol, reservation_id) del activity_data histórico en ActivityFeed'

    def add_arguments(self, parser):
        parser.add_argument(
            '--dry-run',
            action='store_true',
            help='Solo muestra qué registros serían afectados sin modificarlos',
        )
        parser.add_argument(
            '--backup-file',
            type=str,
            default=f'activityfeed_backup_{timezone.now().strftime("%Y%m%d_%H%M%S")}.json',
            help='Archivo donde respaldar los datos antes de modificarlos',
        )

    def handle(self, *args, **options):
        dry_run = options['dry_run']
        backup_file = options['backup_file']
        
        self.stdout.write('🔍 Analizando ActivityFeed para datos sensibles...')
        
        # Contar registros que contienen datos sensibles
        affected_count = self._count_affected_records()
        
        if affected_count == 0:
            self.stdout.write(
                self.style.SUCCESS('✅ No se encontraron registros con datos sensibles. ¡Todo limpio!')
            )
            return
        
        self.stdout.write(f'📊 Encontrados {affected_count} registros con datos sensibles')
        
        if dry_run:
            self.stdout.write(
                self.style.WARNING(f'🔄 DRY RUN: Se limpiarían {affected_count} registros')
            )
            self._show_sample_records()
            return
        
        # Crear respaldo antes de modificar
        self.stdout.write(f'💾 Creando respaldo en {backup_file}...')
        backup_count = self._create_backup(backup_file)
        self.stdout.write(f'✅ Respaldados {backup_count} registros')
        
        # Ejecutar limpieza
        self.stdout.write('🧹 Limpiando datos sensibles...')
        cleaned_count = self._clean_sensitive_data()
        
        # Verificar resultados
        remaining_count = self._count_affected_records()
        
        if remaining_count == 0:
            self.stdout.write(
                self.style.SUCCESS(f'✅ Limpieza completada. {cleaned_count} registros procesados')
            )
        else:
            self.stdout.write(
                self.style.ERROR(f'⚠️ Advertencia: {remaining_count} registros aún contienen datos sensibles')
            )

    def _count_affected_records(self):
        """Cuenta registros que contienen price_sol o reservation_id en activity_data"""
        with connection.cursor() as cursor:
            if connection.vendor == 'postgresql':
                cursor.execute("""
                    SELECT COUNT(*) FROM events_activityfeed 
                    WHERE activity_data ?| array['price_sol','reservation_id']
                """)
            else:
                # MySQL/SQLite fallback
                cursor.execute("""
                    SELECT COUNT(*) FROM events_activityfeed 
                    WHERE activity_data LIKE '%"price_sol"%' 
                       OR activity_data LIKE '%"reservation_id"%'
                """)
            return cursor.fetchone()[0]

    def _show_sample_records(self):
        """Muestra algunos registros de ejemplo que serían afectados"""
        activities = ActivityFeed.objects.filter(
            activity_data__has_any_keys=['price_sol', 'reservation_id']
        )[:3]
        
        self.stdout.write('\n📋 Ejemplos de registros que serían limpiados:')
        for activity in activities:
            self.stdout.write(f'  ID: {activity.id} - Tipo: {activity.activity_type}')
            if 'price_sol' in activity.activity_data:
                self.stdout.write(f'    ❌ price_sol: {activity.activity_data["price_sol"]}')
            if 'reservation_id' in activity.activity_data:
                self.stdout.write(f'    ❌ reservation_id: {activity.activity_data["reservation_id"]}')

    def _create_backup(self, backup_file):
        """Crea respaldo de registros que serán modificados"""
        activities = ActivityFeed.objects.filter(
            activity_data__has_any_keys=['price_sol', 'reservation_id']
        ).values('id', 'activity_type', 'created', 'activity_data')
        
        backup_data = []
        for activity in activities:
            backup_data.append({
                'id': str(activity['id']),  # Convertir UUID a string
                'activity_type': activity['activity_type'],
                'created': activity['created'].isoformat(),
                'activity_data': activity['activity_data']
            })
        
        with open(backup_file, 'w', encoding='utf-8') as f:
            json.dump(backup_data, f, indent=2, ensure_ascii=False)
        
        return len(backup_data)

    def _clean_sensitive_data(self):
        """Elimina campos sensibles usando SQL optimizado por motor de BD"""
        with connection.cursor() as cursor:
            if connection.vendor == 'postgresql':
                # PostgreSQL: usar operador jsonb -
                cursor.execute("""
                    UPDATE events_activityfeed 
                    SET activity_data = activity_data - 'price_sol' - 'reservation_id'
                    WHERE activity_data ?| array['price_sol','reservation_id']
                """)
            elif connection.vendor == 'mysql':
                # MySQL: usar JSON_REMOVE
                cursor.execute("""
                    UPDATE events_activityfeed 
                    SET activity_data = JSON_REMOVE(activity_data, '$.price_sol', '$.reservation_id')
                    WHERE JSON_CONTAINS_PATH(activity_data, 'one', '$.price_sol', '$.reservation_id')
                """)
            else:
                # SQLite: fallback usando ORM por lotes
                return self._clean_with_orm()
            
            return cursor.rowcount

    def _clean_with_orm(self):
        """Fallback: limpieza usando ORM para SQLite"""
        activities = ActivityFeed.objects.filter(
            activity_data__has_any_keys=['price_sol', 'reservation_id']
        )
        
        count = 0
        for activity in activities:
            # Copiar activity_data y eliminar campos sensibles
            cleaned_data = activity.activity_data.copy()
            cleaned_data.pop('price_sol', None)
            cleaned_data.pop('reservation_id', None)
            
            # Actualizar solo si cambió algo
            if cleaned_data != activity.activity_data:
                activity.activity_data = cleaned_data
                activity.save(update_fields=['activity_data'])
                count += 1
        
        return count