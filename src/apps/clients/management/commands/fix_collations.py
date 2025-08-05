
from django.core.management.base import BaseCommand
from django.db import connection


class Command(BaseCommand):
    help = 'Convierte todas las tablas a utf8mb4_unicode_ci collation'

    def handle(self, *args, **options):
        with connection.cursor() as cursor:
            # Obtener el nombre de la base de datos
            cursor.execute("SELECT DATABASE()")
            db_name = cursor.fetchone()[0]
            
            # Cambiar collation de la base de datos
            cursor.execute(f"ALTER DATABASE {db_name} COLLATE utf8mb4_unicode_ci")
            self.stdout.write(
                self.style.SUCCESS(f'✅ Base de datos {db_name} actualizada')
            )
            
            # Obtener todas las tablas
            cursor.execute("SHOW TABLES")
            tables = [row[0] for row in cursor.fetchall()]
            
            # Convertir cada tabla
            for table in tables:
                try:
                    cursor.execute(
                        f"ALTER TABLE {table} CONVERT TO CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci"
                    )
                    self.stdout.write(
                        self.style.SUCCESS(f'✅ Tabla {table} convertida')
                    )
                except Exception as e:
                    self.stdout.write(
                        self.style.ERROR(f'❌ Error en tabla {table}: {str(e)}')
                    )
            
            self.stdout.write(
                self.style.SUCCESS('\n🎯 Proceso completado')
            )
