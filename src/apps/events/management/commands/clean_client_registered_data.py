from django.core.management.base import BaseCommand
from apps.events.models import ActivityFeed
import logging

logger = logging.getLogger(__name__)


class Command(BaseCommand):
    help = 'Limpia información sensible de actividades CLIENT_REGISTERED existentes'

    def add_arguments(self, parser):
        parser.add_argument(
            '--dry-run',
            action='store_true',
            help='Solo muestra qué se limpiaría sin hacer cambios',
        )

    def handle(self, *args, **options):
        dry_run = options['dry_run']
        
        # Buscar todas las actividades CLIENT_REGISTERED
        client_activities = ActivityFeed.objects.filter(
            activity_type=ActivityFeed.ActivityType.CLIENT_REGISTERED
        )
        
        self.stdout.write(f'Encontradas {client_activities.count()} actividades CLIENT_REGISTERED')
        
        count_cleaned = 0
        count_already_clean = 0
        
        # Campos sensibles que deben ser eliminados
        sensitive_fields = [
            'email', 'phone', 'tel_number', 'client_id', 'client_name',
            'document_number', 'document_type', 'password_set', 'created_at'
        ]
        
        for activity in client_activities:
            # Verificar si contiene datos sensibles
            has_sensitive_data = any(field in activity.activity_data for field in sensitive_fields)
            
            if has_sensitive_data:
                if not dry_run:
                    # Crear nuevo activity_data solo con campos seguros
                    clean_data = {}
                    
                    # Mantener solo campos seguros necesarios
                    safe_fields = ['referral_info', 'referred_by_info', 'registration_method']
                    for field in safe_fields:
                        if field in activity.activity_data:
                            clean_data[field] = activity.activity_data[field]
                    
                    # Asegurar que registration_method existe
                    if 'registration_method' not in clean_data:
                        clean_data['registration_method'] = 'web_form'
                    
                    # Actualizar la actividad
                    activity.activity_data = clean_data
                    activity.save(update_fields=['activity_data'])
                    
                    self.stdout.write(f'✅ Limpiada actividad {activity.id}')
                else:
                    self.stdout.write(f'🔍 [DRY RUN] Se limpiaría actividad {activity.id}')
                    self.stdout.write(f'    Datos sensibles encontrados: {[f for f in sensitive_fields if f in activity.activity_data]}')
                
                count_cleaned += 1
            else:
                count_already_clean += 1
        
        if dry_run:
            self.stdout.write(
                self.style.WARNING(f'DRY RUN: Se limpiarían {count_cleaned} actividades')
            )
            self.stdout.write(f'{count_already_clean} actividades ya están limpias')
        else:
            self.stdout.write(
                self.style.SUCCESS(f'✅ Se limpiaron {count_cleaned} actividades CLIENT_REGISTERED')
            )
            self.stdout.write(f'{count_already_clean} actividades ya estaban limpias')