"""
Management command para generar blog posts con IA.

Uso:
    python manage.py generate_blog_post                          # genera siempre
    python manage.py generate_blog_post --dry-run                # preview sin crear nada
    python manage.py generate_blog_post --topic-type property    # forzar tipo
    python manage.py generate_blog_post --keyword "casa playa"   # forzar keyword
    python manage.py generate_blog_post --no-search-console      # solo templates
    python manage.py generate_blog_post --auto                   # decide aleatoriamente (para cron diario)

Cron recomendado (diario, el --auto decide si genera o no):
    0 8 * * * cd /path/to/src && python manage.py generate_blog_post --auto
"""
import json
import random
from datetime import timedelta

from django.core.management.base import BaseCommand
from django.utils import timezone


class Command(BaseCommand):
    help = 'Genera un blog post con IA como borrador'

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
        parser.add_argument(
            '--auto',
            action='store_true',
            help='Modo automático: decide aleatoriamente si genera (3-4 posts/semana, sin patrón fijo)',
        )

    def _should_generate(self):
        """
        Decide si generar hoy basándose en:
        - Probabilidad ~50% (3-4 de 7 días)
        - Mínimo 24h desde el último post generado
        - Máximo 3 días sin generar (fuerza generación)
        - No generar domingos (baja actividad)
        """
        from apps.blog.models import BlogTopicPlan

        now = timezone.now()

        # No generar domingos
        if now.weekday() == 6:
            self.stdout.write("Domingo — descansando.")
            return False

        # Ver cuándo fue el último post generado
        last = BlogTopicPlan.objects.order_by('-generated_at').first()
        if last:
            hours_since_last = (now - last.generated_at).total_seconds() / 3600

            # Mínimo 24h entre posts
            if hours_since_last < 24:
                self.stdout.write(f"Último post hace {hours_since_last:.0f}h — muy pronto, saltando.")
                return False

            # Si pasaron más de 3 días, forzar generación
            if hours_since_last > 72:
                self.stdout.write(f"Último post hace {hours_since_last:.0f}h — forzando generación.")
                return True

        # Probabilidad base ~50% (ajustada para ~3.5 posts/semana sin domingos)
        roll = random.random()
        if roll < 0.55:
            self.stdout.write(f"Hoy sí toca generar (roll={roll:.2f})")
            return True
        else:
            self.stdout.write(f"Hoy no toca (roll={roll:.2f}) — saltando.")
            return False

    def handle(self, *args, **options):
        dry_run = options['dry_run']
        topic_type = options['topic_type']
        keyword = options['keyword']
        use_sc = not options['no_search_console']
        auto = options['auto']

        # Modo auto: decidir si generar
        if auto and not self._should_generate():
            return

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
