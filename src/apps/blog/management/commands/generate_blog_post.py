"""
Management command para generar blog posts con IA.

Uso:
    python manage.py generate_blog_post                          # auto (SC + fallback)
    python manage.py generate_blog_post --dry-run                # preview sin crear nada
    python manage.py generate_blog_post --topic-type property    # forzar tipo
    python manage.py generate_blog_post --keyword "casa playa"   # forzar keyword
    python manage.py generate_blog_post --no-search-console      # solo templates

Cron recomendado (L/Mi/Vi a las 8am):
    0 8 * * 1,3,5 cd /path/to/src && python manage.py generate_blog_post
"""
import json

from django.core.management.base import BaseCommand


class Command(BaseCommand):
    help = 'Genera un blog post con IA (Claude) como borrador'

    def add_arguments(self, parser):
        parser.add_argument(
            '--dry-run',
            action='store_true',
            help='Muestra el plan sin crear nada',
        )
        parser.add_argument(
            '--topic-type',
            type=str,
            default=None,
            choices=[
                'property', 'lima_travel', 'beaches', 'seasonal',
                'tips', 'events', 'gastronomy', 'family',
            ],
            help='Forzar un tipo de tema específico',
        )
        parser.add_argument(
            '--keyword',
            type=str,
            default=None,
            help='Forzar una keyword específica',
        )
        parser.add_argument(
            '--no-search-console',
            action='store_true',
            help='No usar datos de Search Console (solo templates)',
        )

    def handle(self, *args, **options):
        dry_run = options['dry_run']
        topic_type = options['topic_type']
        keyword = options['keyword']
        use_sc = not options['no_search_console']

        if dry_run:
            self.stdout.write("Modo DRY RUN — no se creará nada\n")

        try:
            from apps.blog.content_generator import BlogContentGenerator

            generator = BlogContentGenerator()
            result = generator.generate(
                dry_run=dry_run,
                force_topic_type=topic_type,
                force_keyword=keyword,
                use_search_console=use_sc,
            )

            if dry_run:
                self.stdout.write(self.style.WARNING("=== DRY RUN ===\n"))
                self.stdout.write(json.dumps(result, indent=2, ensure_ascii=False))
                self.stdout.write("\n")
            else:
                self.stdout.write(self.style.SUCCESS(
                    f"\nBlog post generado exitosamente:\n"
                    f"  - Título: {result['title']}\n"
                    f"  - Slug: {result['slug']}\n"
                    f"  - Tipo: {result['topic_type']}\n"
                    f"  - Keyword: {result.get('keyword', 'N/A')}\n"
                    f"  - Imagen: {'Sí' if result.get('has_image') else 'No'}\n"
                    f"  - Estado: BORRADOR (revisar en admin antes de publicar)\n"
                    f"  - ID: {result['post_id']}"
                ))

        except ValueError as e:
            self.stdout.write(self.style.WARNING(f"Configuración faltante: {e}"))

        except Exception as e:
            self.stdout.write(self.style.ERROR(f"Error generando blog post: {e}"))
            raise
