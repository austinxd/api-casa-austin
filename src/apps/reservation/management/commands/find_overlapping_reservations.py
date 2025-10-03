from django.core.management.base import BaseCommand
from django.db.models import Q
from apps.reservation.models import Reservation
from apps.property.models import Property


class Command(BaseCommand):
    help = 'Encuentra reservas que se solapan en la misma propiedad'

    def add_arguments(self, parser):
        parser.add_argument(
            '--property',
            type=str,
            help='UUID de una propiedad específica para analizar (opcional)'
        )
        parser.add_argument(
            '--status',
            type=str,
            default='approved',
            help='Estado de reservas a analizar (default: approved, use "all" para todas)'
        )

    def handle(self, *args, **options):
        property_uuid = options.get('property')
        status_filter = options.get('status')

        self.stdout.write(self.style.WARNING(f'\n{"="*80}'))
        self.stdout.write(self.style.WARNING('ANÁLISIS DE RESERVAS SOLAPADAS'))
        self.stdout.write(self.style.WARNING(f'{"="*80}\n'))

        # Obtener propiedades a analizar
        if property_uuid:
            properties = Property.objects.filter(uuid=property_uuid, deleted=False)
        else:
            properties = Property.objects.filter(deleted=False)

        if not properties.exists():
            self.stdout.write(self.style.ERROR('No se encontraron propiedades'))
            return

        total_overlaps = 0
        overlap_details = []

        for property_obj in properties:
            # Obtener reservas de esta propiedad
            reservations = Reservation.objects.filter(
                property=property_obj,
                deleted=False
            ).exclude(status='cancelled')

            if status_filter != 'all':
                reservations = reservations.filter(status=status_filter)

            reservations = reservations.order_by('check_in_date')

            if reservations.count() < 2:
                continue

            # Comparar cada reserva con las demás
            reservations_list = list(reservations)
            property_overlaps = []

            for i, res_a in enumerate(reservations_list):
                for res_b in reservations_list[i+1:]:
                    # Verificar si se solapan
                    # Dos reservas se solapan si: check_in_A < check_out_B AND check_in_B < check_out_A
                    if res_a.check_in_date < res_b.check_out_date and res_b.check_in_date < res_a.check_out_date:
                        overlap_days = self.calculate_overlap_days(
                            res_a.check_in_date, res_a.check_out_date,
                            res_b.check_in_date, res_b.check_out_date
                        )
                        
                        property_overlaps.append({
                            'property': property_obj.name,
                            'res_a_id': str(res_a.uuid),
                            'res_a_client': f"{res_a.client.first_name} {res_a.client.last_name}" if res_a.client else "Sin cliente",
                            'res_a_dates': f"{res_a.check_in_date} → {res_a.check_out_date}",
                            'res_a_status': res_a.status,
                            'res_b_id': str(res_b.uuid),
                            'res_b_client': f"{res_b.client.first_name} {res_b.client.last_name}" if res_b.client else "Sin cliente",
                            'res_b_dates': f"{res_b.check_in_date} → {res_b.check_out_date}",
                            'res_b_status': res_b.status,
                            'overlap_days': overlap_days
                        })

            if property_overlaps:
                overlap_details.append({
                    'property': property_obj.name,
                    'overlaps': property_overlaps
                })
                total_overlaps += len(property_overlaps)

        # Mostrar resultados
        self.stdout.write(self.style.WARNING(f'\n{"="*80}'))
        self.stdout.write(self.style.WARNING('RESULTADOS'))
        self.stdout.write(self.style.WARNING(f'{"="*80}\n'))

        self.stdout.write(f'Propiedades analizadas: {properties.count()}')
        
        if total_overlaps > 0:
            self.stdout.write(self.style.ERROR(f'⚠️  INCONSISTENCIAS ENCONTRADAS: {total_overlaps} solapamientos\n'))

            for detail in overlap_details:
                self.stdout.write(self.style.ERROR(f'\n{"="*80}'))
                self.stdout.write(self.style.ERROR(f'{detail["property"]}: {len(detail["overlaps"])} conflictos'))
                self.stdout.write(self.style.ERROR(f'{"="*80}\n'))

                for overlap in detail['overlaps']:
                    self.stdout.write(self.style.ERROR(f'\n🔴 CONFLICTO ({overlap["overlap_days"]} días solapados):'))
                    self.stdout.write(f'   Reserva 1: {overlap["res_a_client"]}')
                    self.stdout.write(f'              {overlap["res_a_dates"]} ({overlap["res_a_status"]})')
                    self.stdout.write(f'              ID: {overlap["res_a_id"]}')
                    self.stdout.write(f'   Reserva 2: {overlap["res_b_client"]}')
                    self.stdout.write(f'              {overlap["res_b_dates"]} ({overlap["res_b_status"]})')
                    self.stdout.write(f'              ID: {overlap["res_b_id"]}')
        else:
            self.stdout.write(self.style.SUCCESS('✓ No se encontraron reservas solapadas\n'))
            self.stdout.write(self.style.SUCCESS('  Todas las reservas están correctamente distribuidas'))

        self.stdout.write('')

    def calculate_overlap_days(self, start_a, end_a, start_b, end_b):
        """Calcula cuántos días se solapan dos reservas"""
        overlap_start = max(start_a, start_b)
        overlap_end = min(end_a, end_b)
        overlap_days = (overlap_end - overlap_start).days
        return max(0, overlap_days)
