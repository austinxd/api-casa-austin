
from django.core.management.base import BaseCommand
from apps.clients.models import SearchTracking
from apps.clients.views import SearchTrackingExportView
import logging

logger = logging.getLogger(__name__)

class Command(BaseCommand):
    help = 'Sincronizar datos de SearchTracking con Google Sheets'

    def add_arguments(self, parser):
        parser.add_argument(
            '--days',
            type=int,
            default=7,
            help='Número de días hacia atrás para sincronizar (default: 7)'
        )
        parser.add_argument(
            '--all',
            action='store_true',
            help='Sincronizar todos los registros'
        )

    def handle(self, *args, **options):
        try:
            export_view = SearchTrackingExportView()
            
            # Preparar queryset
            queryset = SearchTracking.objects.filter(deleted=False)
            
            if not options['all']:
                from datetime import datetime, timedelta
                days_back = options['days']
                since_date = datetime.now() - timedelta(days=days_back)
                queryset = queryset.filter(search_timestamp__gte=since_date)
            
            # Preparar datos como en la vista
            export_data = []
            for tracking in queryset.select_related('client', 'property').order_by('-search_timestamp'):
                data = {
                    'id': tracking.id,
                    'search_timestamp': tracking.search_timestamp.isoformat() if tracking.search_timestamp else None,
                    'check_in_date': tracking.check_in_date.isoformat() if tracking.check_in_date else None,
                    'check_out_date': tracking.check_out_date.isoformat() if tracking.check_out_date else None,
                    'guests': tracking.guests,
                    'client_info': {
                        'id': tracking.client.id if tracking.client else None,
                        'first_name': tracking.client.first_name if tracking.client else None,
                        'last_name': tracking.client.last_name if tracking.client else None,
                        'email': tracking.client.email if tracking.client else None,
                        'tel_number': tracking.client.tel_number if tracking.client else None,
                    } if tracking.client else None,
                    'property_info': {
                        'id': tracking.property.id if tracking.property else None,
                        'name': tracking.property.name if tracking.property else None,
                    } if tracking.property else None,
                    'technical_data': {
                        'ip_address': tracking.ip_address,
                        'session_key': tracking.session_key,
                        'user_agent': tracking.user_agent,
                        'referrer': tracking.referrer,
                    },
                    'created': tracking.created.isoformat() if hasattr(tracking, 'created') and tracking.created else None,
                }
                export_data.append(data)
            
            # Enviar a Google Sheets
            result = export_view.send_to_google_sheets(export_data)
            
            if result['success']:
                self.stdout.write(
                    self.style.SUCCESS(
                        f'✅ Sincronización exitosa: {result.get("successful_sends", 0)} registros enviados'
                    )
                )
                if result.get('failed_sends', 0) > 0:
                    self.stdout.write(
                        self.style.WARNING(
                            f'⚠️ {result["failed_sends"]} registros fallaron'
                        )
                    )
            else:
                self.stdout.write(
                    self.style.ERROR(f'❌ Error en sincronización: {result.get("message", "Error desconocido")}')
                )
                
        except Exception as e:
            self.stdout.write(
                self.style.ERROR(f'❌ Error ejecutando comando: {str(e)}')
            )
