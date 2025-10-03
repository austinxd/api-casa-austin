import pandas as pd
from django.core.management.base import BaseCommand
from datetime import datetime

from apps.clients.models import Clients
from apps.property.models import Property
from apps.reservation.models import Reservation


class Command(BaseCommand):
    help = 'Verifica duplicados entre el Excel y la base de datos'

    def add_arguments(self, parser):
        parser.add_argument(
            '--file',
            type=str,
            required=True,
            help='Ruta al archivo Excel con las reservas'
        )
        parser.add_argument(
            '--sheet',
            type=str,
            default=0,
            help='Nombre o índice de la hoja a importar (default: primera hoja)'
        )

    PROPERTY_MAPPING = {
        'casa austin 1': '573c665065a74e81883a2b910159731b',
        'casa austin 2': '9a04892a4ba54b1092b52a72f6d89d57',
        'casa austin 3': '0ff9b525ff7c4be3b8723937d958c1a6',
        'casa austin 4': 'd9d4e844c38f4adeaa5c5def19652ad0',
    }

    def handle(self, *args, **options):
        file_path = options['file']
        sheet = options['sheet']

        self.stdout.write(self.style.WARNING(f'\n{"="*80}'))
        self.stdout.write(self.style.WARNING('VERIFICACIÓN DE RESERVAS DUPLICADAS'))
        self.stdout.write(self.style.WARNING(f'{"="*80}\n'))

        try:
            df = pd.read_excel(file_path, sheet_name=sheet)
        except Exception as e:
            self.stdout.write(self.style.ERROR(f'Error al leer archivo: {str(e)}'))
            return

        self.stdout.write(f'Archivo: {file_path}')
        self.stdout.write(f'Total de filas en Excel: {len(df)}\n')

        duplicates = []
        no_duplicates = 0
        errors = 0

        for idx, row in df.iterrows():
            row_num = idx + 2
            
            casa = str(row.get('casa', '')).strip().lower()
            dni = str(row.get('DNI', '')).strip()
            check_in_str = row.get('check in')
            check_out_str = row.get('check out')

            if pd.isna(casa) or pd.isna(dni) or pd.isna(check_in_str) or pd.isna(check_out_str):
                errors += 1
                continue

            property_uuid = self.PROPERTY_MAPPING.get(casa)
            if not property_uuid:
                errors += 1
                continue

            try:
                property_obj = Property.objects.get(uuid=property_uuid, deleted=False)
            except Property.DoesNotExist:
                errors += 1
                continue

            dni = dni.strip()
            if dni.isdigit() and len(dni) < 8:
                dni = dni.zfill(8)

            try:
                client = Clients.objects.get(number_doc=dni, deleted=False)
            except Clients.DoesNotExist:
                errors += 1
                continue

            try:
                if isinstance(check_in_str, str):
                    check_in = datetime.strptime(check_in_str, '%Y-%m-%d').date()
                else:
                    check_in = check_in_str.date() if hasattr(check_in_str, 'date') else check_in_str

                if isinstance(check_out_str, str):
                    check_out = datetime.strptime(check_out_str, '%Y-%m-%d').date()
                else:
                    check_out = check_out_str.date() if hasattr(check_out_str, 'date') else check_out_str
            except:
                errors += 1
                continue

            existing = Reservation.objects.filter(
                client=client,
                property=property_obj,
                check_in_date=check_in,
                check_out_date=check_out,
                deleted=False
            ).first()

            if existing:
                duplicates.append({
                    'row': row_num,
                    'client': f"{client.first_name} {client.last_name}",
                    'property': property_obj.name,
                    'check_in': check_in,
                    'check_out': check_out,
                    'reservation_id': existing.uuid
                })
            else:
                no_duplicates += 1

        self.stdout.write(self.style.WARNING(f'\n{"="*80}'))
        self.stdout.write(self.style.WARNING('RESULTADOS'))
        self.stdout.write(self.style.WARNING(f'{"="*80}\n'))

        self.stdout.write(f'Total procesadas: {len(df)}')
        self.stdout.write(self.style.SUCCESS(f'✓ Sin duplicados: {no_duplicates}'))
        self.stdout.write(self.style.ERROR(f'✗ Duplicadas (ya en BD): {len(duplicates)}'))
        self.stdout.write(f'✗ Errores/No válidas: {errors}\n')

        if duplicates:
            self.stdout.write(self.style.ERROR(f'\n{"="*80}'))
            self.stdout.write(self.style.ERROR(f'RESERVAS DUPLICADAS ENCONTRADAS ({len(duplicates)})'))
            self.stdout.write(self.style.ERROR(f'{"="*80}\n'))

            by_property = {}
            for dup in duplicates:
                prop = dup['property']
                if prop not in by_property:
                    by_property[prop] = []
                by_property[prop].append(dup)

            for prop, dups in sorted(by_property.items()):
                self.stdout.write(self.style.ERROR(f'\n{prop}: {len(dups)} duplicadas'))
                for dup in dups[:10]:
                    self.stdout.write(
                        f"  Row {dup['row']}: {dup['client']} | "
                        f"{dup['check_in']} → {dup['check_out']} | "
                        f"ID: {dup['reservation_id']}"
                    )
                if len(dups) > 10:
                    self.stdout.write(f"  ... y {len(dups) - 10} más")

        self.stdout.write('')
