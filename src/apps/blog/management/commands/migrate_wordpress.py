"""
Management command para migrar posts de WordPress a Django.

Uso:
    python manage.py migrate_wordpress
    python manage.py migrate_wordpress --dry-run   # solo muestra lo que haría
"""
import os
import re
import requests
from io import BytesIO
from urllib.parse import urlparse

from django.core.files.base import ContentFile
from django.core.management.base import BaseCommand
from django.utils.dateparse import parse_datetime
from django.utils.text import slugify

from apps.blog.models import BlogCategory, BlogPost


WP_BASE = "https://casaaustin.pe/blog"
WP_API = f"{WP_BASE}/wp-json/wp/v2"


class Command(BaseCommand):
    help = "Migra posts y categorías desde WordPress REST API al modelo Blog de Django"

    def add_arguments(self, parser):
        parser.add_argument(
            '--dry-run',
            action='store_true',
            help='Solo muestra lo que haría sin crear nada',
        )

    def handle(self, *args, **options):
        dry_run = options['dry_run']

        self.stdout.write(self.style.MIGRATE_HEADING("=== Migracion WordPress → Django Blog ==="))
        if dry_run:
            self.stdout.write(self.style.WARNING("MODO DRY-RUN: no se creara nada"))

        # 1. Migrar categorías
        categories_map = self._migrate_categories(dry_run)

        # 2. Migrar posts
        self._migrate_posts(categories_map, dry_run)

        self.stdout.write(self.style.SUCCESS("\nMigracion completada."))

    # ------------------------------------------------------------------
    # Categorías
    # ------------------------------------------------------------------

    def _migrate_categories(self, dry_run):
        """Obtiene categorías de WP y las crea en Django. Retorna map {wp_id: BlogCategory}."""
        self.stdout.write("\n--- Categorias ---")
        url = f"{WP_API}/categories?per_page=100"
        data = self._wp_get(url)

        categories_map = {}
        for idx, cat in enumerate(data):
            wp_id = cat['id']
            name = cat['name']
            slug = cat['slug']
            description = cat.get('description', '')

            self.stdout.write(f"  Categoria: {name} (slug={slug})")

            if not dry_run:
                obj, created = BlogCategory.objects.get_or_create(
                    slug=slug,
                    defaults={
                        'name': name,
                        'description': description,
                        'order': idx,
                    }
                )
                categories_map[wp_id] = obj
                status = "CREADA" if created else "YA EXISTIA"
                self.stdout.write(f"    -> {status}")
            else:
                categories_map[wp_id] = None

        self.stdout.write(f"  Total categorias: {len(data)}")
        return categories_map

    # ------------------------------------------------------------------
    # Posts
    # ------------------------------------------------------------------

    def _migrate_posts(self, categories_map, dry_run):
        """Obtiene posts paginados de WP y los crea en Django."""
        self.stdout.write("\n--- Posts ---")

        page = 1
        total_created = 0
        total_skipped = 0

        while True:
            url = f"{WP_API}/posts?per_page=100&page={page}&_embed"
            try:
                data = self._wp_get(url)
            except Exception:
                break

            if not data:
                break

            for post in data:
                slug = post['slug']
                title = post['title']['rendered']
                content_html = post['content']['rendered']
                excerpt = post['excerpt']['rendered']
                date_str = post.get('date_gmt') or post.get('date')
                published_date = parse_datetime(date_str) if date_str else None

                # Strip HTML tags from excerpt
                excerpt_clean = re.sub(r'<[^>]+>', '', excerpt).strip()

                # Category
                wp_cat_ids = post.get('categories', [])
                category = None
                for cid in wp_cat_ids:
                    if cid in categories_map:
                        category = categories_map[cid]
                        break

                self.stdout.write(f"  Post: {title[:60]}... (slug={slug})")

                if dry_run:
                    total_created += 1
                    continue

                # Skip if already exists
                if BlogPost.objects.filter(slug=slug).exists():
                    self.stdout.write(f"    -> YA EXISTE, omitido")
                    total_skipped += 1
                    continue

                # Rewrite internal image URLs in content
                content_html = self._rewrite_image_urls(content_html)

                blog_post = BlogPost(
                    title=title,
                    slug=slug,
                    content=content_html,
                    excerpt=excerpt_clean[:500],
                    meta_description=excerpt_clean[:160],
                    category=category,
                    author="Casa Austin",
                    status='published',
                    published_date=published_date,
                )
                # Save first without image to get PK
                blog_post.save()

                # Download featured image
                featured_url = self._get_featured_image_url(post)
                if featured_url:
                    self._download_and_set_image(blog_post, featured_url)

                total_created += 1
                self.stdout.write(f"    -> CREADO")

            page += 1

        self.stdout.write(f"\n  Posts creados: {total_created}")
        self.stdout.write(f"  Posts omitidos (ya existian): {total_skipped}")

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    def _wp_get(self, url):
        """GET request a la API de WordPress."""
        resp = requests.get(url, timeout=30)
        if resp.status_code == 400:
            # WP retorna 400 cuando la pagina no existe
            return []
        resp.raise_for_status()
        return resp.json()

    def _get_featured_image_url(self, post):
        """Extrae la URL de la imagen destacada del post embebido."""
        try:
            embedded = post.get('_embedded', {})
            media = embedded.get('wp:featuredmedia', [])
            if media and len(media) > 0:
                return media[0].get('source_url')
        except (KeyError, IndexError, TypeError):
            pass
        return None

    def _download_and_set_image(self, blog_post, image_url):
        """Descarga una imagen y la asigna como featured_image."""
        try:
            resp = requests.get(image_url, timeout=30)
            resp.raise_for_status()

            # Extraer nombre del archivo
            parsed = urlparse(image_url)
            filename = os.path.basename(parsed.path) or 'featured.jpg'

            blog_post.featured_image.save(
                filename,
                ContentFile(resp.content),
                save=True
            )
            self.stdout.write(f"    -> Imagen descargada: {filename}")
        except Exception as e:
            self.stdout.write(self.style.WARNING(f"    -> Error descargando imagen: {e}"))

    def _rewrite_image_urls(self, html_content):
        """Reescribe URLs de imágenes de WordPress al dominio de la API."""
        # Reemplazar rutas de wp-content/uploads a la nueva ubicación
        # Las imágenes inline del content se dejan como están (siguen apuntando a WP)
        # Solo se reescriben las rutas relativas
        html_content = html_content.replace(
            '/blog/wp-content/uploads/',
            'https://casaaustin.pe/blog/wp-content/uploads/'
        )
        return html_content
