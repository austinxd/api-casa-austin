"""
Corrige URLs de imagenes rotas en posts del blog y re-importa featured images faltantes.

Problema: la migracion original genero URLs duplicadas como:
    https://casaaustin.pehttps://casaaustin.pe/blog/wp-content/uploads/...

Este comando:
1. Arregla todas las URLs rotas en el content HTML
2. Copia imagenes inline de wp-content/uploads al media de Django
3. Asigna featured_image a posts que no la tienen

Uso:
    python manage.py fix_blog_images
    python manage.py fix_blog_images --wp-root /srv/casaaustin/wordpress
    python manage.py fix_blog_images --dry-run
"""
import os
import re
import shutil

from django.conf import settings
from django.core.files.base import ContentFile
from django.core.management.base import BaseCommand

from apps.blog.models import BlogPost


DEFAULT_WP_ROOT = "/srv/casaaustin/wordpress"


class Command(BaseCommand):
    help = "Corrige URLs rotas de imagenes y re-importa featured images faltantes"

    def add_arguments(self, parser):
        parser.add_argument(
            '--wp-root',
            default=DEFAULT_WP_ROOT,
            help=f'Ruta raiz de WordPress (default: {DEFAULT_WP_ROOT})',
        )
        parser.add_argument(
            '--dry-run',
            action='store_true',
            help='Solo muestra lo que haria',
        )

    def handle(self, *args, **options):
        wp_root = options['wp_root']
        dry_run = options['dry_run']
        uploads_dir = os.path.join(wp_root, "wp-content", "uploads")

        self.stdout.write(self.style.MIGRATE_HEADING("=== Fix blog images ==="))
        if dry_run:
            self.stdout.write(self.style.WARNING("MODO DRY-RUN"))

        posts = BlogPost.objects.filter(deleted=False)
        self.stdout.write(f"Posts a procesar: {posts.count()}")

        urls_fixed = 0
        images_imported = 0
        featured_set = 0

        for post in posts:
            self.stdout.write(f"\n  [{post.slug[:50]}]")

            # --- PASO 1: Fix broken URLs in content ---
            content = post.content
            original_content = content

            # Fix doubled domain: https://casaaustin.pehttps://casaaustin.pe/blog/wp-content/...
            content = re.sub(
                r'https://casaaustin\.pe(?:https://casaaustin\.pe)+',
                'https://casaaustin.pe',
                content
            )

            # Now normalize all wp-content/uploads references to a consistent form
            # Convert absolute WP URLs to relative paths for processing
            # Pattern: any variation of casaaustin.pe/blog/wp-content/uploads/PATH
            #       or casaaustin.pe/wp-content/uploads/PATH

            media_base = f"blog_content/{post.id}"
            media_dir = os.path.join(settings.MEDIA_ROOT, media_base)

            def replace_wp_image(match):
                nonlocal urls_fixed, images_imported
                prefix = match.group(1)   # src="
                rel_path = match.group(2)  # 2024/04/filename.jpg
                suffix = match.group(3)   # "

                # Try to find the file on disk
                source_path = os.path.join(uploads_dir, rel_path)
                filename = os.path.basename(rel_path)
                new_url = f"/media/{media_base}/{filename}"

                if os.path.isfile(source_path):
                    if not dry_run:
                        os.makedirs(media_dir, exist_ok=True)
                        dest_path = os.path.join(media_dir, filename)
                        if not os.path.isfile(dest_path):
                            shutil.copy2(source_path, dest_path)
                            images_imported += 1
                    urls_fixed += 1
                    return f"{prefix}{new_url}{suffix}"
                else:
                    # File not on disk - at least fix the broken URL
                    # Point to the WP uploads URL that might still work
                    urls_fixed += 1
                    return f"{prefix}https://casaaustin.pe/blog/wp-content/uploads/{rel_path}{suffix}"

            # Match all wp-content/uploads references (broken or not)
            content = re.sub(
                r'((?:src|href)=["\'])(?:https?://casaaustin\.pe)?(?:/blog)?/wp-content/uploads/([^"\']+)(["\'])',
                replace_wp_image,
                content
            )

            if content != original_content:
                self.stdout.write(f"    Content actualizado")
                if not dry_run:
                    post.content = content
                    post.save(update_fields=['content'])

            # --- PASO 2: Set featured_image if missing ---
            if not post.featured_image:
                image_path = self._find_best_image(content, uploads_dir, media_dir, media_base)
                if image_path:
                    self.stdout.write(f"    Featured image: {os.path.basename(image_path)}")
                    if not dry_run:
                        try:
                            filename = os.path.basename(image_path)
                            with open(image_path, 'rb') as f:
                                post.featured_image.save(
                                    filename,
                                    ContentFile(f.read()),
                                    save=True
                                )
                            featured_set += 1
                        except Exception as e:
                            self.stderr.write(f"    Error: {e}")
                else:
                    self.stdout.write(f"    Sin imagen para featured")

        self.stdout.write(self.style.SUCCESS(
            f"\nResultado: {urls_fixed} URLs corregidas, "
            f"{images_imported} imagenes copiadas a media, "
            f"{featured_set} featured images asignadas"
        ))

    def _find_best_image(self, html_content, uploads_dir, media_dir, media_base):
        """Busca la mejor imagen para usar como featured, desde disco local o media."""
        # First check media dir (images already copied)
        if os.path.isdir(media_dir):
            for f in sorted(os.listdir(media_dir)):
                if f.lower().endswith(('.jpg', '.jpeg', '.png', '.webp')):
                    return os.path.join(media_dir, f)

        # Then check wp-content/uploads references in content
        patterns = [
            r'wp-content/uploads/([^"\'<>\s]+\.(?:jpg|jpeg|png|webp))',
        ]
        for pattern in patterns:
            matches = re.findall(pattern, html_content, re.IGNORECASE)
            for rel_path in matches:
                # Try without size suffix first
                clean_path = re.sub(r'-\d+x\d+(?=\.\w+$)', '', rel_path)
                full_path = os.path.join(uploads_dir, clean_path)
                if os.path.isfile(full_path):
                    return full_path
                full_path = os.path.join(uploads_dir, rel_path)
                if os.path.isfile(full_path):
                    return full_path

        return None
