"""
Corrige enlaces internos rotos en el content de los posts del blog.

Problemas detectados:
1. casaaustin.pe/blogcasas-... → falta / entre blog y la ruta
2. casaaustin.pe/blog/casas-en-alquiler/... → el /blog/ sobra para rutas del SPA
3. casaaustin.pe/blog/listings/... → rutas internas de WP que no existen
4. casaaustin.pe/blog/action/... → rutas internas de WP que no existen
5. casaaustin.pe/blog/slug-de-post → enlaces entre posts, deben quedarse como /blog/slug

Uso:
    python manage.py fix_blog_links
    python manage.py fix_blog_links --dry-run
"""
import re

from django.core.management.base import BaseCommand

from apps.blog.models import BlogPost


# Rutas del SPA que NO son posts de blog
SPA_ROUTES = [
    'casas-en-alquiler',
    'casas-alquiler-punta-hermosa',
    'casas-alquiler-los-pulpos',
    'casas-alquiler-cieneguilla',
    'casas-de-playa',
    'departamentos-airbnb',
    'disponibilidad',
    'despedida-soltera-casa-playa-lima',
    'despedida-soltero-casa-playa-lima',
    'casa-playa-cumpleanos-lima',
    'casa-playa-pet-friendly-lima',
    'casa-playa-matrimonio-boda-lima',
    'casa-playa-ano-nuevo-lima',
    'casa-playa-piscina-temperada-lima',
    'casa-playa-grupo-grande-lima',
    'hotel-con-jacuzzi-lima',
    'airbnb-punta-hermosa-casas-playa',
    'alternativa-booking-casa-playa-lima',
    'alquiler-mansiones-para-eventos-peru',
]

# Rutas de WP que no tienen equivalente en el SPA - eliminar enlace
WP_ONLY_ROUTES = [
    'listings/',
    'action/',
    'alquileres-de-temporada/',
]


class Command(BaseCommand):
    help = "Corrige enlaces internos rotos en posts del blog"

    def add_arguments(self, parser):
        parser.add_argument(
            '--dry-run',
            action='store_true',
            help='Solo muestra lo que haria',
        )

    def handle(self, *args, **options):
        dry_run = options['dry_run']

        self.stdout.write(self.style.MIGRATE_HEADING("=== Fix blog links ==="))
        if dry_run:
            self.stdout.write(self.style.WARNING("MODO DRY-RUN"))

        # Get all blog post slugs for reference
        blog_slugs = set(
            BlogPost.objects.filter(deleted=False).values_list('slug', flat=True)
        )

        posts = BlogPost.objects.filter(deleted=False)
        total_fixed = 0
        posts_updated = 0

        for post in posts:
            content = post.content
            original = content
            fixes = 0

            # --- FIX 1: casaaustin.pe/blogXXX (missing slash) ---
            # e.g. /blogcasas-alquiler-punta-hermosa → /casas-alquiler-punta-hermosa
            def fix_blog_concat(match):
                nonlocal fixes
                prefix = match.group(1)  # href="
                path = match.group(2)    # casas-alquiler-punta-hermosa or casas-en-alquiler/...
                suffix = match.group(3)  # "

                fixes += 1
                return f'{prefix}https://casaaustin.pe/{path}{suffix}'

            content = re.sub(
                r'(href=["\'])https://casaaustin\.pe/blog(?!/)([^"\']+)(["\'])',
                fix_blog_concat,
                content
            )

            # --- FIX 2: /blog/casas-en-alquiler/... → /casas-en-alquiler/... ---
            # SPA routes that were prefixed with /blog/
            def fix_blog_spa_route(match):
                nonlocal fixes
                prefix = match.group(1)
                path = match.group(2)  # casas-en-alquiler/casa-austin-1 etc
                suffix = match.group(3)

                fixes += 1
                return f'{prefix}https://casaaustin.pe/{path}{suffix}'

            spa_pattern = '|'.join(re.escape(r) for r in SPA_ROUTES)
            content = re.sub(
                rf'(href=["\'])https://casaaustin\.pe/blog/({spa_pattern}[^"\']*?)(["\'])',
                fix_blog_spa_route,
                content
            )

            # --- FIX 3: /blog/listings/... and /blog/action/... → remove or redirect ---
            for wp_route in WP_ONLY_ROUTES:
                pattern = rf'(href=["\'])https://casaaustin\.pe/blog/{re.escape(wp_route)}[^"\']*(["\'])'
                content = re.sub(
                    pattern,
                    r'\1https://casaaustin.pe/casas-en-alquiler\2',
                    content
                )
                # Count replacements
                if content != original:
                    fixes += 1

            # --- FIX 4: /blog/slug-de-otro-post → verify it's a real blog post ---
            # These are correct links between blog posts, leave them as /blog/slug
            # But fix any remaining /blog/alquileres-de-temporada/... type links
            content = re.sub(
                r'(href=["\'])https://casaaustin\.pe/blog/alquileres-de-temporada/([^"\']+)(["\'])',
                lambda m: f'{m.group(1)}https://casaaustin.pe/blog/{m.group(2)}{m.group(3)}'
                if m.group(2).rstrip('/') in blog_slugs
                else f'{m.group(1)}https://casaaustin.pe/casas-en-alquiler{m.group(3)}',
                content
            )

            if content != original:
                posts_updated += 1
                total_fixed += fixes
                self.stdout.write(f"  [{post.slug[:50]}] {fixes} enlaces corregidos")
                if not dry_run:
                    post.content = content
                    post.save(update_fields=['content'])

        self.stdout.write(self.style.SUCCESS(
            f"\nResultado: {total_fixed} enlaces corregidos en {posts_updated} posts"
        ))
