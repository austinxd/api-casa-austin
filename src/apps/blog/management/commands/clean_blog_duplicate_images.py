"""Limpia las imágenes duplicadas al inicio del content de blog posts.

Posts migrados desde WordPress vienen con la imagen de portada embebida
al INICIO del content HTML. El frontend (blog-detail.tsx) además
renderiza `featured_image_url` como <img> por separado encima del
content. Resultado: la misma imagen se ve dos veces.

Este comando recorre todos los blog posts y elimina el primer <img>
del content si:
  (a) Es el primer elemento visible (puede venir envuelto en <p>, <figure>
      o varios <div>).
  (b) Su src coincide con featured_image (mismo filename o url).

Es seguro re-correrlo: si la imagen ya fue removida, no hace nada.

Uso:
    python manage.py clean_blog_duplicate_images --dry-run
    python manage.py clean_blog_duplicate_images --apply
"""
import os
import re
from urllib.parse import urlparse

from django.core.management.base import BaseCommand, CommandError

from apps.blog.models import BlogPost


# Regex: captura la primera imagen del content, posiblemente envuelta
# en <figure>, <p>, <div> (a veces de WordPress). Solo si está cerca
# del inicio del HTML.
LEADING_IMG_RE = re.compile(
    r'^\s*'
    r'(?P<wrapper_open>(?:<(?:figure|p|div)[^>]*>\s*)*)'
    r'(?P<img><img\b[^>]*>)'
    r'(?:\s*<figcaption[^>]*>.*?</figcaption>)?'
    r'(?P<wrapper_close>(?:\s*</(?:figure|p|div)>)*)'
    r'(?P<after>\s*)',
    re.IGNORECASE | re.DOTALL,
)

# Regex para extraer el src del img.
SRC_RE = re.compile(r'\bsrc=["\']([^"\']+)["\']', re.IGNORECASE)


def _filename(url_or_path):
    """Devuelve solo el filename (sin path/dominio/query) para comparación."""
    if not url_or_path:
        return ''
    try:
        # Limpiar query string
        parsed = urlparse(url_or_path)
        path = parsed.path or url_or_path
    except Exception:
        path = url_or_path
    return os.path.basename(path)


def _normalize(name):
    """Quita el sufijo de tamaño de WordPress ('-1024x768') y la
    extensión para comparar nombres en distintas resoluciones."""
    if not name:
        return ''
    base, _ext = os.path.splitext(name)
    base = re.sub(r'-\d{2,4}x\d{2,4}$', '', base)
    return base.lower()


def _is_duplicate_of_featured(img_src, featured_url):
    """Heurística: comparar nombres normalizados ignorando rutas y sufijos
    de WordPress de resoluciones."""
    if not img_src or not featured_url:
        return False
    a = _normalize(_filename(img_src))
    b = _normalize(_filename(featured_url))
    if not a or not b:
        return False
    # Match exacto o uno contiene al otro (WordPress a veces guarda
    # `casa-austin-2.jpg` y `casa-austin-2-1024x768.jpg`).
    return a == b or a in b or b in a


class Command(BaseCommand):
    help = (
        "Elimina la primera imagen duplicada del content de cada blog "
        "post si coincide con featured_image."
    )

    def add_arguments(self, parser):
        parser.add_argument(
            '--dry-run', action='store_true',
            help='Muestra qué cambiaría sin guardar.',
        )
        parser.add_argument(
            '--apply', action='store_true',
            help='Aplica los cambios.',
        )
        parser.add_argument(
            '--slug',
            help='Solo procesar este slug (debug).',
        )
        parser.add_argument(
            '--force', action='store_true',
            help='Quita la primera <img> del content aunque NO coincida '
                 'con featured_image. Usar con cuidado.',
        )

    def handle(self, *args, **opts):
        if not (opts.get('dry_run') or opts.get('apply')):
            raise CommandError('Pasa --dry-run o --apply.')

        apply_ = bool(opts.get('apply'))
        force = bool(opts.get('force'))

        qs = BlogPost.objects.filter(deleted=False)
        if opts.get('slug'):
            qs = qs.filter(slug=opts['slug'])

        total = qs.count()
        modified = 0
        skipped_no_match = 0
        skipped_no_img = 0
        skipped_no_featured = 0

        for post in qs:
            content = post.content or ''
            featured = ''
            try:
                if post.featured_image and post.featured_image.name:
                    featured = post.featured_image.name
            except Exception:
                featured = ''

            if not content.strip():
                continue

            m = LEADING_IMG_RE.match(content)
            if not m:
                skipped_no_img += 1
                continue

            img_tag = m.group('img')
            src_m = SRC_RE.search(img_tag)
            img_src = src_m.group(1) if src_m else ''

            should_remove = False
            reason = ''
            if force:
                should_remove = True
                reason = 'forced'
            elif featured and _is_duplicate_of_featured(img_src, featured):
                should_remove = True
                reason = (
                    f'match featured (img="{_filename(img_src)}" '
                    f'vs featured="{_filename(featured)}")'
                )
            else:
                if not featured:
                    skipped_no_featured += 1
                else:
                    skipped_no_match += 1

            if not should_remove:
                continue

            new_content = LEADING_IMG_RE.sub('', content, count=1)
            # Eliminar saltos de línea extras al inicio
            new_content = new_content.lstrip()

            delta = len(new_content) - len(content)
            self.stdout.write(
                f"\n[CLEAN] {post.slug}"
                f"\n  → img: {img_src}"
                f"\n  → featured: {featured}"
                f"\n  → reason: {reason}"
                f"\n  → bytes change: {delta:+d}"
            )

            if apply_:
                post.content = new_content
                post.save(update_fields=['content', 'updated'])
                self.stdout.write(self.style.SUCCESS("  ✓ guardado"))
            else:
                self.stdout.write(self.style.WARNING("  (dry-run, no se guardó)"))
            modified += 1

        self.stdout.write("\n" + "=" * 60)
        self.stdout.write(f"Total posts revisados:    {total}")
        self.stdout.write(f"Posts modificados:        {modified}")
        self.stdout.write(f"Skipped (sin img inicio): {skipped_no_img}")
        self.stdout.write(f"Skipped (sin featured):   {skipped_no_featured}")
        self.stdout.write(f"Skipped (no match):       {skipped_no_match}")
        if not apply_:
            self.stdout.write(self.style.WARNING(
                "\n(dry-run) Vuelve a correr con --apply para guardar."
            ))
