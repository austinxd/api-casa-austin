
from django.core.management.base import BaseCommand
from django.db import connection


class Command(BaseCommand):
    help = 'Convierte todas las tablas a utf8mb4_unicode_ci collation'

    def handle(self, *args, **options):
        with connection.cursor() as cursor:
            # Obtener el nombre de la base de datos
            cursor.execute("SELECT DATABASE()")
            db_name = cursor.fetchone()[0]
            
            # Deshabilitar verificaciones de foreign keys
            cursor.execute("SET FOREIGN_KEY_CHECKS = 0")
            self.stdout.write(
                self.style.WARNING('⚠️ Foreign key checks deshabilitadas temporalmente')
            )
            
            # Cambiar collation de la base de datos
            cursor.execute(f"ALTER DATABASE {db_name} COLLATE utf8mb4_unicode_ci")
            self.stdout.write(
                self.style.SUCCESS(f'✅ Base de datos {db_name} actualizada')
            )
            
            # Obtener todas las tablas
            cursor.execute("SHOW TABLES")
            tables = [row[0] for row in cursor.fetchall()]
            
            # Convertir cada tabla
            success_count = 0
            error_count = 0
            
            for table in tables:
                try:
                    cursor.execute(
                        f"ALTER TABLE {table} CONVERT TO CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci"
                    )
                    self.stdout.write(
                        self.style.SUCCESS(f'✅ Tabla {table} convertida')
                    )
                    success_count += 1
                except Exception as e:
                    self.stdout.write(
                        self.style.ERROR(f'❌ Error en tabla {table}: {str(e)}')
                    )
                    error_count += 1
            
            # Rehabilitar verificaciones de foreign keys
            cursor.execute("SET FOREIGN_KEY_CHECKS = 1")
            self.stdout.write(
                self.style.SUCCESS('✅ Foreign key checks rehabilitadas')
            )
            
            # Resumen final
            self.stdout.write(
                self.style.SUCCESS(f'\n🎯 Proceso completado:')
            )
            self.stdout.write(
                self.style.SUCCESS(f'   📊 Tablas convertidas exitosamente: {success_count}')
            )
            if error_count > 0:
                self.stdout.write(
                    self.style.WARNING(f'   ⚠️ Tablas con errores: {error_count}')
                )
            else:
                self.stdout.write(
                    self.style.SUCCESS(f'   🎉 Todas las tablas convertidas sin errores!')
                )
