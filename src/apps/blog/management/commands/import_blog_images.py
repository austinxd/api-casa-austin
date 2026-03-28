"""
Importa imágenes de WordPress desde el disco local del servidor.

Busca la featured image de cada post en el HTML del content,
la copia desde /srv/casaaustin/wordpress/wp-content/uploads/ al media de Django,
y reescribe las URLs internas del content para apuntar a /media/.

Uso:
    python manage.py import_blog_images
    python manage.py import_blog_images --wp-root /srv/casaaustin/wordpress
    python manage.py import_blog_images --dry-run
"""
import os
import re
import glob

from django.conf import settings
from django.core.files.base import ContentFile
from django.core.management.base import BaseCommand

from apps.blog.models import BlogPost


DEFAULT_WP_ROOT = "/srv/casaaustin/wordpress"


class Command(BaseCommand):
    help = "Importa imagenes de WordPress desde disco local y actualiza URLs en content"

    def add_arguments(self, parser):
        parser.add_argument(
            '--wp-root',
            default=DEFAULT_WP_ROOT,
            help=f'Ruta raiz de WordPress (default: {DEFAULT_WP_ROOT})',
        )
        parser.add_argument(
            '--dry-run',
            action='store_true',
            help='Solo muestra lo que haria sin modificar nada',
        )

    def handle(self, *args, **options):
        wp_root = options['wp_root']
        dry_run = options['dry_run']
        uploads_dir = os.path.join(wp_root, "wp-content", "uploads")

        if not os.path.isdir(uploads_dir):
            self.stderr.write(self.style.ERROR(
                f"No se encontro el directorio de uploads: {uploads_dir}"
            ))
            return

        self.stdout.write(self.style.MIGRATE_HEADING("=== Importar imagenes de blog desde WordPress ==="))
        if dry_run:
            self.stdout.write(self.style.WARNING("MODO DRY-RUN"))

        posts = BlogPost.objects.filter(deleted=False, status='published')
        self.stdout.write(f"Posts a procesar: {posts.count()}")

        img_imported = 0
        content_updated = 0

        for post in posts:
            self.stdout.write(f"\n  [{post.slug}]")

            # 1. Featured image: buscar la primera imagen grande en el content
            if not post.featured_image:
                image_path = self._find_featured_image(post.content, uploads_dir)
                if image_path:
                    self.stdout.write(f"    Featured image: {os.path.basename(image_path)}")
                    if not dry_run:
                        self._set_featured_image(post, image_path)
                        img_imported += 1
                else:
                    self.stdout.write(f"    Sin imagen encontrada en disco")

            # 2. Reescribir URLs de wp-content/uploads en el content
            new_content, count = self._rewrite_content_images(
                post.content, uploads_dir, post, dry_run
            )
            if count > 0:
                self.stdout.write(f"    URLs reescritas en content: {count}")
                if not dry_run:
                    post.content = new_content
                    post.save(update_fields=['content'])
                    content_updated += 1

        self.stdout.write(self.style.SUCCESS(
            f"\nResultado: {img_imported} featured images importadas, "
            f"{content_updated} posts con content actualizado"
        ))

    def _find_featured_image(self, html_content, uploads_dir):
        """Busca la primera imagen referenciada en el HTML que exista en disco."""
        # Buscar todas las URLs de imágenes de wp-content/uploads
        patterns = [
            r'src=["\'](?:https?://casaaustin\.pe)?/blog/wp-content/uploads/([^"\']+)["\']',
            r'src=["\'](?:https?://casaaustin\.pe)?/wp-content/uploads/([^"\']+)["\']',
        ]
        for pattern in patterns:
            matches = re.findall(pattern, html_content)
            for rel_path in matches:
                # Preferir la imagen sin sufijos de tamaño (-300x200, etc)
                clean_path = re.sub(r'-\d+x\d+(?=\.\w+$)', '', rel_path)
                full_path = os.path.join(uploads_dir, clean_path)
                if os.path.isfile(full_path):
                    return full_path
                # Si no existe la limpia, intentar con la original
                full_path = os.path.join(uploads_dir, rel_path)
                if os.path.isfile(full_path):
                    return full_path
        return None

    def _set_featured_image(self, post, image_path):
        """Lee un archivo del disco y lo asigna como featured_image del post."""
        try:
            filename = os.path.basename(image_path)
            with open(image_path, 'rb') as f:
                post.featured_image.save(
                    filename,
                    ContentFile(f.read()),
                    save=True
                )
        except Exception as e:
            self.stderr.write(self.style.WARNING(f"    Error importando imagen: {e}"))

    def _rewrite_content_images(self, html_content, uploads_dir, post, dry_run):
        """
        Copia imágenes inline del content a media de Django y reescribe las URLs.
        Retorna (nuevo_html, cantidad_reemplazos).
        """
        count = 0
        media_base = f"blog_content/{post.id}"
        media_dir = os.path.join(settings.MEDIA_ROOT, media_base)

        def replace_match(match):
            nonlocal count
            prefix = match.group(1)  # src=" o src='
            rel_path = match.group(2)
            suffix = match.group(3)  # " o '

            source_path = os.path.join(uploads_dir, rel_path)
            if not os.path.isfile(source_path):
                return match.group(0)  # No existe, dejar como está

            filename = os.path.basename(rel_path)
            new_url = f"/media/{media_base}/{filename}"

            if not dry_run:
                os.makedirs(media_dir, exist_ok=True)
                dest_path = os.path.join(media_dir, filename)
                if not os.path.isfile(dest_path):
                    import shutil
                    shutil.copy2(source_path, dest_path)

            count += 1
            return f"{prefix}{new_url}{suffix}"

        # Reescribir URLs absolutas y relativas de wp-content/uploads
        pattern = r'(src=["\'])(?:https?://casaaustin\.pe)?/(?:blog/)?wp-content/uploads/([^"\']+)(["\'])'
        new_html = re.sub(pattern, replace_match, html_content)

        return new_html, count
