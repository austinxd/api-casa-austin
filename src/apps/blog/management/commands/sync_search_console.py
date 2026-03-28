"""
Management command para sincronizar datos de Google Search Console.

Uso:
    python manage.py sync_search_console              # últimos 28 días
    python manage.py sync_search_console --days 90    # últimos 90 días

Se recomienda ejecutar 1x/día via cron:
    0 6 * * * cd /path/to/src && python manage.py sync_search_console
"""
from django.core.management.base import BaseCommand


class Command(BaseCommand):
    help = 'Sincroniza datos de Google Search Console a la base de datos local'

    def add_arguments(self, parser):
        parser.add_argument(
            '--days',
            type=int,
            default=28,
            help='Número de días a consultar (default: 28)',
        )

    def handle(self, *args, **options):
        days = options['days']

        self.stdout.write(f"Sincronizando Search Console (últimos {days} días)...")

        try:
            from apps.blog.search_console import SearchConsoleClient

            client = SearchConsoleClient()
            result = client.sync_to_database(days=days)

            self.stdout.write(self.style.SUCCESS(
                f"Sincronización completada:\n"
                f"  - Rango: {result['date_range']}\n"
                f"  - Total filas: {result['total_rows']}\n"
                f"  - Nuevos: {result['created']}\n"
                f"  - Actualizados: {result['updated']}"
            ))

        except ValueError as e:
            self.stdout.write(self.style.WARNING(f"Configuración faltante: {e}"))
            self.stdout.write(
                "Configura GOOGLE_SEARCH_CONSOLE_KEY_FILE y "
                "GOOGLE_SEARCH_CONSOLE_SITE_URL en tu .env"
            )

        except Exception as e:
            self.stdout.write(self.style.ERROR(f"Error: {e}"))
            raise
