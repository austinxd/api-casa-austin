import pandas as pd
from django.core.management.base import BaseCommand
from django.db import transaction
from datetime import datetime
from decimal import Decimal
import sys

from apps.clients.models import Clients
from apps.property.models import Property
from apps.reservation.models import Reservation


class Command(BaseCommand):
    help = 'Importa reservas históricas desde un archivo Excel'

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
        parser.add_argument(
            '--commit',
            action='store_true',
            help='Confirmar e insertar las reservas en la base de datos (sin este flag solo muestra preview)'
        )
        parser.add_argument(
            '--limit',
            type=int,
            default=None,
            help='Limitar el número de filas a procesar (útil para pruebas)'
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
        commit = options['commit']
        limit = options['limit']

        self.stdout.write(self.style.WARNING(f'\n{"="*80}'))
        self.stdout.write(self.style.WARNING('IMPORTACIÓN DE RESERVAS HISTÓRICAS'))
        self.stdout.write(self.style.WARNING(f'{"="*80}\n'))

        self.stdout.write(f'Archivo: {file_path}')
        self.stdout.write(f'Hoja: {sheet}')
        self.stdout.write(f'Modo: {"INSERCIÓN REAL" if commit else "PREVIEW (solo lectura)"}')
        if limit:
            self.stdout.write(f'Límite: {limit} filas\n')

        try:
            df = pd.read_excel(file_path, sheet_name=sheet)
            
            if limit:
                df = df.head(limit)

            self.stdout.write(self.style.SUCCESS(f'\n✓ Archivo cargado: {len(df)} filas encontradas\n'))

            results = self.process_dataframe(df)

            self.show_summary(results)

            if commit:
                self.insert_reservations(results)
            else:
                self.stdout.write(self.style.WARNING('\n⚠ MODO PREVIEW: No se insertaron registros'))
                self.stdout.write(self.style.WARNING('   Usa --commit para confirmar la inserción\n'))

        except FileNotFoundError:
            self.stdout.write(self.style.ERROR(f'\n✗ Error: Archivo no encontrado: {file_path}\n'))
            sys.exit(1)
        except Exception as e:
            self.stdout.write(self.style.ERROR(f'\n✗ Error: {str(e)}\n'))
            import traceback
            traceback.print_exc()
            sys.exit(1)

    def process_dataframe(self, df):
        results = {
            'valid': [],
            'errors': [],
            'stats': {
                'total': len(df),
                'valid': 0,
                'client_not_found': 0,
                'property_not_found': 0,
                'invalid_dates': 0,
                'missing_data': 0,
                'duplicates': 0,
                'other_errors': 0
            }
        }

        for idx, row in df.iterrows():
            try:
                result = self.validate_row(row, idx)
                
                if result['valid']:
                    results['valid'].append(result)
                    results['stats']['valid'] += 1
                else:
                    results['errors'].append(result)
                    error_type = result.get('error_type', 'other_errors')
                    results['stats'][error_type] += 1

            except Exception as e:
                results['errors'].append({
                    'row': idx + 2,
                    'error': f'Error inesperado: {str(e)}',
                    'error_type': 'other_errors'
                })
                results['stats']['other_errors'] += 1

        return results

    def validate_row(self, row, idx):
        row_num = idx + 2

        propiedad = str(row.get('PROPIEDAD', '')).strip().lower()
        nombre = str(row.get('NOMBRE', '')).strip()
        dni = str(row.get('DNI', '')).strip()
        telefono = str(row.get('TELEFONO', '')).strip()
        
        if pd.isna(propiedad) or not propiedad:
            return {
                'valid': False,
                'row': row_num,
                'error': 'Propiedad vacía',
                'error_type': 'missing_data',
                'data': row.to_dict()
            }

        property_uuid = self.PROPERTY_MAPPING.get(propiedad)
        if not property_uuid:
            return {
                'valid': False,
                'row': row_num,
                'error': f'Propiedad desconocida: "{propiedad}"',
                'error_type': 'property_not_found',
                'data': row.to_dict()
            }

        try:
            property_obj = Property.objects.get(id=property_uuid, deleted=False)
        except Property.DoesNotExist:
            return {
                'valid': False,
                'row': row_num,
                'error': f'Propiedad no existe en BD: {property_uuid}',
                'error_type': 'property_not_found',
                'data': row.to_dict()
            }

        if pd.isna(dni) or not dni:
            return {
                'valid': False,
                'row': row_num,
                'error': 'DNI vacío',
                'error_type': 'missing_data',
                'data': row.to_dict()
            }

        dni = dni.strip()
        if dni.isdigit() and len(dni) < 8:
            dni = dni.zfill(8)

        try:
            client = Clients.objects.get(number_doc=dni, deleted=False)
        except Clients.DoesNotExist:
            return {
                'valid': False,
                'row': row_num,
                'error': f'Cliente no encontrado con DNI: {dni}',
                'error_type': 'client_not_found',
                'data': row.to_dict()
            }
        except Clients.MultipleObjectsReturned:
            return {
                'valid': False,
                'row': row_num,
                'error': f'Múltiples clientes con DNI: {dni}',
                'error_type': 'client_not_found',
                'data': row.to_dict()
            }

        try:
            check_in = pd.to_datetime(row['CHECK-IN']).date()
            check_out = pd.to_datetime(row['CHECK-OUT']).date()
        except Exception as e:
            return {
                'valid': False,
                'row': row_num,
                'error': f'Fechas inválidas: {str(e)}',
                'error_type': 'invalid_dates',
                'data': row.to_dict()
            }

        if check_in >= check_out:
            return {
                'valid': False,
                'row': row_num,
                'error': f'Check-out debe ser después de check-in',
                'error_type': 'invalid_dates',
                'data': row.to_dict()
            }

        existing = Reservation.objects.filter(
            client=client,
            property=property_obj,
            check_in_date=check_in,
            check_out_date=check_out,
            deleted=False
        ).exists()

        if existing:
            return {
                'valid': False,
                'row': row_num,
                'error': f'Reserva duplicada (ya existe en BD)',
                'error_type': 'duplicates',
                'data': row.to_dict()
            }

        precio_sol = row.get('PRECIO S/', 0)
        precio_usd = row.get('PRECIO $', 0)
        num_pax = row.get('N° Pax', 1)
        adelanto_pct = row.get('ADELANTO %', 0)

        try:
            if not pd.isna(precio_sol):
                precio_sol_str = str(precio_sol).replace('S/.', '').replace('S/', '').replace(',', '').strip()
                precio_sol = float(precio_sol_str) if precio_sol_str else 0.0
            else:
                precio_sol = 0.0
                
            if not pd.isna(precio_usd):
                precio_usd_str = str(precio_usd).replace('$', '').replace(',', '').strip()
                precio_usd = float(precio_usd_str) if precio_usd_str else 0.0
            else:
                precio_usd = 0.0
                
            num_pax = int(num_pax) if not pd.isna(num_pax) else 1
            
            if not pd.isna(adelanto_pct):
                adelanto_pct_str = str(adelanto_pct).replace('%', '').strip()
                adelanto_pct = float(adelanto_pct_str) if adelanto_pct_str else 0.0
            else:
                adelanto_pct = 0.0
        except Exception as e:
            return {
                'valid': False,
                'row': row_num,
                'error': f'Error en datos numéricos: {str(e)}',
                'error_type': 'other_errors',
                'data': row.to_dict()
            }

        return {
            'valid': True,
            'row': row_num,
            'client': client,
            'property': property_obj,
            'check_in': check_in,
            'check_out': check_out,
            'price_sol': Decimal(str(precio_sol)),
            'price_usd': Decimal(str(precio_usd)),
            'num_pax': num_pax,
            'adelanto_pct': adelanto_pct,
            'data': row.to_dict()
        }

    def show_summary(self, results):
        stats = results['stats']
        
        self.stdout.write(self.style.WARNING(f'\n{"="*80}'))
        self.stdout.write(self.style.WARNING('RESUMEN DE VALIDACIÓN'))
        self.stdout.write(self.style.WARNING(f'{"="*80}\n'))

        self.stdout.write(f'Total de filas procesadas: {stats["total"]}')
        self.stdout.write(self.style.SUCCESS(f'✓ Válidas: {stats["valid"]}'))
        self.stdout.write(self.style.ERROR(f'✗ Con errores: {stats["total"] - stats["valid"]}\n'))

        if stats['total'] - stats['valid'] > 0:
            self.stdout.write(self.style.ERROR('Detalle de errores:'))
            self.stdout.write(f'  • Cliente no encontrado: {stats["client_not_found"]}')
            self.stdout.write(f'  • Propiedad no encontrada: {stats["property_not_found"]}')
            self.stdout.write(f'  • Fechas inválidas: {stats["invalid_dates"]}')
            self.stdout.write(f'  • Datos faltantes: {stats["missing_data"]}')
            self.stdout.write(f'  • Duplicados: {stats["duplicates"]}')
            self.stdout.write(f'  • Otros errores: {stats["other_errors"]}\n')

        if results['valid']:
            self.stdout.write(self.style.SUCCESS(f'\n{"="*80}'))
            self.stdout.write(self.style.SUCCESS('RESERVAS VÁLIDAS PARA IMPORTAR'))
            self.stdout.write(self.style.SUCCESS(f'{"="*80}\n'))

            by_property = {}
            for item in results['valid']:
                prop_name = item['property'].name
                if prop_name not in by_property:
                    by_property[prop_name] = []
                by_property[prop_name].append(item)

            for prop_name, items in by_property.items():
                self.stdout.write(self.style.SUCCESS(f'\n{prop_name}: {len(items)} reservas'))
                for item in items[:5]:
                    client_name = f"{item['client'].first_name} {item['client'].last_name}"
                    self.stdout.write(
                        f"  Row {item['row']}: {client_name} | "
                        f"{item['check_in']} → {item['check_out']} | "
                        f"S/. {item['price_sol']} / $ {item['price_usd']}"
                    )
                if len(items) > 5:
                    self.stdout.write(f"  ... y {len(items) - 5} más")

        if results['errors']:
            self.stdout.write(self.style.ERROR(f'\n{"="*80}'))
            self.stdout.write(self.style.ERROR('ERRORES ENCONTRADOS (primeros 10)'))
            self.stdout.write(self.style.ERROR(f'{"="*80}\n'))

            for error in results['errors'][:10]:
                self.stdout.write(self.style.ERROR(f"Row {error['row']}: {error['error']}"))
            
            if len(results['errors']) > 10:
                self.stdout.write(self.style.ERROR(f"\n... y {len(results['errors']) - 10} errores más\n"))

    def insert_reservations(self, results):
        if not results['valid']:
            self.stdout.write(self.style.WARNING('\n⚠ No hay reservas válidas para insertar\n'))
            return

        self.stdout.write(self.style.WARNING(f'\n{"="*80}'))
        self.stdout.write(self.style.WARNING('INSERTANDO RESERVAS EN LA BASE DE DATOS'))
        self.stdout.write(self.style.WARNING(f'{"="*80}\n'))

        inserted = 0
        errors = 0

        with transaction.atomic():
            for item in results['valid']:
                try:
                    reservation = Reservation.objects.create(
                        client=item['client'],
                        property=item['property'],
                        check_in_date=item['check_in'],
                        check_out_date=item['check_out'],
                        price_sol=item['price_sol'],
                        price_usd=item['price_usd'],
                        guests=item['num_pax'],
                        status='approved',
                        origin='aus',
                        late_checkout=False,
                        deleted=False
                    )
                    inserted += 1
                    
                    if inserted % 10 == 0:
                        self.stdout.write(f'  Insertadas: {inserted}/{len(results["valid"])}...')

                except Exception as e:
                    errors += 1
                    self.stdout.write(self.style.ERROR(
                        f'  ✗ Error insertando Row {item["row"]}: {str(e)}'
                    ))

        self.stdout.write(self.style.SUCCESS(f'\n✓ Inserción completada:'))
        self.stdout.write(self.style.SUCCESS(f'  • Reservas insertadas: {inserted}'))
        if errors > 0:
            self.stdout.write(self.style.ERROR(f'  • Errores: {errors}'))
        self.stdout.write('')
