from django.core.management.base import BaseCommand
from django.utils import timezone
from apps.clients.models import SearchTracking
from apps.clients.views import SearchTrackingExportView
import logging

logger = logging.getLogger('apps')

class Command(BaseCommand):
    help = 'Sincronizar datos de SearchTracking con Google Sheets'

    def add_arguments(self, parser):
        parser.add_argument(
            '--days',
            type=int,
            default=30,
            help='Número de días hacia atrás para sincronizar (default: 30)'
        )
        parser.add_argument(
            '--all',
            action='store_true',
            help='Sincronizar todos los registros (ignorar --days)'
        )

    def handle(self, *args, **options):
        try:
            self.stdout.write('🔄 Iniciando sincronización con Google Sheets...')

            # Obtener registros de SearchTracking
            queryset = SearchTracking.objects.filter(deleted=False)

            if not options['all']:
                from datetime import timedelta
                days_ago = timezone.now() - timedelta(days=options['days'])
                queryset = queryset.filter(search_timestamp__gte=days_ago)

            queryset = queryset.select_related('client', 'property').order_by('-search_timestamp')

            self.stdout.write(f'📊 Encontrados {queryset.count()} registros para sincronizar')

            if not queryset.exists():
                self.stdout.write(self.style.WARNING('⚠️ No hay registros para sincronizar'))
                return

            # Usar la misma lógica de exportación que SearchTrackingExportView
            export_view = SearchTrackingExportView()

            # Preparar datos
            export_data = []
            for tracking in queryset:
                data = {
                    'id': str(tracking.id),
                    'search_timestamp': tracking.search_timestamp.isoformat() if tracking.search_timestamp else None,
                    'check_in_date': tracking.check_in_date.strftime('%Y-%m-%d') if tracking.check_in_date else None,
                    'check_out_date': tracking.check_out_date.strftime('%Y-%m-%d') if tracking.check_out_date else None,
                    'guests': tracking.guests,
                    'client_info': {
                        'id': str(tracking.client.id) if tracking.client else 'ANONIMO',
                        'first_name': tracking.client.first_name if tracking.client else 'Usuario',
                        'last_name': tracking.client.last_name if tracking.client else 'Anónimo',
                        'email': tracking.client.email if tracking.client else 'anonimo@casaaustin.pe',
                        'tel_number': tracking.client.tel_number if tracking.client else 'Sin teléfono',
                    } if tracking.client else {
                        'id': 'ANONIMO',
                        'first_name': 'Usuario',
                        'last_name': 'Anónimo',
                        'email': 'anonimo@casaaustin.pe',
                        'tel_number': 'Sin teléfono',
                    },
                    'property_info': {
                        'id': str(tracking.property.id) if tracking.property else 'SIN_PROPIEDAD',
                        'name': tracking.property.name if tracking.property else 'Búsqueda general',
                    } if tracking.property else {
                        'id': 'SIN_PROPIEDAD',
                        'name': 'Búsqueda general',
                    },
                    'technical_data': {
                        'ip_address': str(tracking.ip_address) if tracking.ip_address else None,
                        'session_key': str(tracking.session_key) if tracking.session_key else None,
                        'user_agent': str(tracking.user_agent) if tracking.user_agent else None,
                        'referrer': str(tracking.referrer) if tracking.referrer else None,
                    },
                'created': tracking.created.strftime('%Y-%m-%d') if hasattr(tracking, 'created') and tracking.created else None,
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
                            f'⚠️ {result.get("failed_sends", 0)} registros fallaron'
                        )
                    )
            else:
                self.stdout.write(
                    self.style.ERROR(
                        f'❌ Error en sincronización: {result.get("message", "Error desconocido")}'
                    )
                )

        except Exception as e:
            logger.error(f"Error en comando sync_google_sheets: {str(e)}")
            self.stdout.write(
                self.style.ERROR(f'❌ Error ejecutando comando: {str(e)}')
            )