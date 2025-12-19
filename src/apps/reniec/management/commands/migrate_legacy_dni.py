"""
Comando para migrar datos de DNI desde la BD legacy (rutificador_bd.dni_info)
a la nueva tabla de cache Django (reniec_dni_cache).

Uso:
    python manage.py migrate_legacy_dni
    python manage.py migrate_legacy_dni --batch-size=500
    python manage.py migrate_legacy_dni --dry-run
"""

import MySQLdb
from django.core.management.base import BaseCommand
from django.conf import settings
from apps.reniec.models import DNICache


class Command(BaseCommand):
    help = 'Migra datos de DNI desde rutificador_bd.dni_info a reniec_dni_cache'

    def add_arguments(self, parser):
        parser.add_argument(
            '--batch-size',
            type=int,
            default=1000,
            help='Número de registros a procesar por lote (default: 1000)'
        )
        parser.add_argument(
            '--dry-run',
            action='store_true',
            help='Solo mostrar cuántos registros se migrarían sin hacer cambios'
        )

    def handle(self, *args, **options):
        batch_size = options['batch_size']
        dry_run = options['dry_run']

        # Configuración de la BD legacy
        legacy_db_config = {
            'host': getattr(settings, 'RENIEC_LEGACY_DB_HOST', 'localhost'),
            'user': getattr(settings, 'RENIEC_LEGACY_DB_USER', 'rutificador'),
            'passwd': getattr(settings, 'RENIEC_LEGACY_DB_PASSWORD', '!Rutificador123'),
            'db': getattr(settings, 'RENIEC_LEGACY_DB_NAME', 'rutificador_bd'),
            'charset': 'utf8mb4',
        }

        self.stdout.write(f"Conectando a BD legacy: {legacy_db_config['host']}/{legacy_db_config['db']}")

        try:
            conn = MySQLdb.connect(**legacy_db_config)
            cursor = conn.cursor(MySQLdb.cursors.DictCursor)
        except Exception as e:
            self.stderr.write(self.style.ERROR(f"Error conectando a BD legacy: {e}"))
            return

        # Contar registros
        cursor.execute("SELECT COUNT(*) as total FROM dni_info")
        total = cursor.fetchone()['total']
        self.stdout.write(f"Total registros en dni_info: {total}")

        # Contar ya migrados
        already_migrated = DNICache.objects.count()
        self.stdout.write(f"Registros ya en reniec_dni_cache: {already_migrated}")

        if dry_run:
            self.stdout.write(self.style.WARNING("--dry-run: No se realizarán cambios"))
            cursor.close()
            conn.close()
            return

        # Migrar en lotes
        offset = 0
        migrated = 0
        skipped = 0
        errors = 0

        while offset < total:
            cursor.execute(f"SELECT * FROM dni_info LIMIT {batch_size} OFFSET {offset}")
            rows = cursor.fetchall()

            if not rows:
                break

            for row in rows:
                dni = row.get('dni')
                if not dni:
                    errors += 1
                    continue

                # Verificar si ya existe
                if DNICache.objects.filter(dni=dni).exists():
                    skipped += 1
                    continue

                try:
                    # Funciones auxiliares
                    def parse_date(date_val):
                        if date_val and hasattr(date_val, 'strftime'):
                            return date_val
                        return None

                    def capitalize_name(name):
                        if not name:
                            return ''
                        return ' '.join(word.capitalize() for word in str(name).lower().split())

                    def get_int(val):
                        if val and str(val).isdigit():
                            return int(val)
                        return None

                    DNICache.objects.create(
                        dni=dni,
                        # Datos del documento
                        nu_dni=row.get('nuDni'),
                        nu_ficha=row.get('nuFicha'),
                        nu_imagen=row.get('nuImagen'),
                        digito_verificacion=row.get('digitoVerificacion'),
                        # Datos personales
                        nombres=capitalize_name(row.get('preNombres')),
                        apellido_paterno=capitalize_name(row.get('apePaterno')),
                        apellido_materno=capitalize_name(row.get('apeMaterno')),
                        apellido_casada=capitalize_name(row.get('apCasada')),
                        # Datos adicionales
                        fecha_nacimiento=parse_date(row.get('feNacimiento')),
                        estatura=get_int(row.get('estatura')),
                        sexo=(row.get('sexo') or '')[:1].upper(),
                        estado_civil=row.get('estadoCivil'),
                        grado_instruccion=row.get('gradoInstruccion'),
                        # Fechas del documento
                        fecha_emision=parse_date(row.get('feEmision')),
                        fecha_inscripcion=parse_date(row.get('feInscripcion')),
                        fecha_caducidad=parse_date(row.get('feCaducidad')),
                        # Padres
                        nom_padre=row.get('nomPadre'),
                        nom_madre=row.get('nomMadre'),
                        # Ubicación de nacimiento
                        pais=row.get('pais'),
                        departamento=row.get('departamento'),
                        provincia=row.get('provincia'),
                        distrito=row.get('distrito'),
                        # Dirección actual
                        pais_direccion=row.get('paisDireccion'),
                        departamento_direccion=row.get('depaDireccion'),
                        provincia_direccion=row.get('provDireccion'),
                        distrito_direccion=row.get('distDireccion'),
                        direccion=row.get('desDireccion'),
                        # Contacto
                        telefono=row.get('telefono'),
                        email=row.get('email'),
                        # Otros datos
                        dona_organos=row.get('donaOrganos'),
                        observacion=row.get('observacion'),
                        # Restricciones
                        fecha_restriccion=row.get('feRestriccion'),
                        de_restriccion=row.get('deRestriccion'),
                        # Datos electorales
                        gp_votacion=row.get('gpVotacion'),
                        multas_electorales=row.get('multasElectorales'),
                        multa_admin=row.get('multaAdmin'),
                        # Actualización
                        fecha_actualizacion=parse_date(row.get('feActualizacion')),
                        # Documentos sustento
                        doc_sustento=row.get('docSustento'),
                        nu_doc_sustento=row.get('nuDocSustento'),
                        nu_doc_declarante=row.get('nuDocDeclarante'),
                        vinculo_declarante=row.get('vinculoDeclarante'),
                        # Cancelación
                        cancelacion=row.get('cancelacion'),
                        # Fallecimiento
                        fecha_fallecimiento=parse_date(row.get('feFallecimiento')),
                        depa_fallecimiento=row.get('depaFallecimiento'),
                        prov_fallecimiento=row.get('provFallecimiento'),
                        dist_fallecimiento=row.get('distFallecimiento'),
                        # Ubigeo
                        codigo_postal=row.get('codigo_postal'),
                        ubigeo_reniec=row.get('ubigeo_reniec'),
                        ubigeo_inei=row.get('ubigeo_inei'),
                        ubigeo_sunat=row.get('ubigeo_sunat'),
                        # Imágenes
                        foto=row.get('imagen_foto'),
                        huella_izquierda=row.get('huella_izquierda'),
                        huella_derecha=row.get('huella_derecha'),
                        firma=row.get('firma'),
                        # Metadatos
                        raw_data=None,
                        source='legacy'
                    )
                    migrated += 1

                except Exception as e:
                    errors += 1
                    self.stderr.write(f"Error migrando DNI {dni}: {e}")

            offset += batch_size
            self.stdout.write(f"Progreso: {offset}/{total} ({migrated} migrados, {skipped} ya existían, {errors} errores)")

        cursor.close()
        conn.close()

        self.stdout.write(self.style.SUCCESS(f"""
Migración completada:
  - Total en legacy: {total}
  - Migrados: {migrated}
  - Ya existían: {skipped}
  - Errores: {errors}
  - Total en cache Django: {DNICache.objects.count()}
"""))
