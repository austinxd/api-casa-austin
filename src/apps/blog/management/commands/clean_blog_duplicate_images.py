"""Limpia las imágenes duplicadas en el content de blog posts.

Posts migrados desde WordPress tienen la imagen de portada también
embebida dentro del content HTML (a menudo envuelta en <a>...<img></a>
para hacerla clickeable). El frontend además renderiza
`featured_image_url` como <img> separado encima del content. Resultado:
la misma imagen se ve dos veces.

Este comando busca dentro del content TODAS las <img>, las compara
contra featured_image, y elimina las que coincidan (junto con el
wrapper <a>/<figure>/<p>-solo-con-imagen si lo tienen).

Idempotente: re-correrlo no hace nada si la imagen ya fue removida.

Uso:
    python manage.py clean_blog_duplicate_images --dry-run
    python manage.py clean_blog_duplicate_images --apply
    python manage.py clean_blog_duplicate_images --slug <slug> --apply
"""
import os
import re
from urllib.parse import urlparse

from django.core.management.base import BaseCommand, CommandError

from apps.blog.models import BlogPost


# Regex para extraer src del <img>
SRC_RE = re.compile(r'\bsrc=["\']([^"\']+)["\']', re.IGNORECASE)


def _filename(url_or_path):
    if not url_or_path:
        return ''
    try:
        parsed = urlparse(url_or_path)
        path = parsed.path or url_or_path
    except Exception:
        path = url_or_path
    return os.path.basename(path)


def _normalize(name):
    """Quita el sufijo de resolución WordPress y la extensión."""
    if not name:
        return ''
    base, _ext = os.path.splitext(name)
    base = re.sub(r'-\d{2,4}x\d{2,4}$', '', base)
    return base.lower()


def _is_duplicate(img_src, featured_url):
    if not img_src or not featured_url:
        return False
    a = _normalize(_filename(img_src))
    b = _normalize(_filename(featured_url))
    if not a or not b:
        return False
    return a == b or a in b or b in a


def _featured_url_from_post(post):
    """Reconstruye la URL del featured_image como la ve el frontend."""
    try:
        if post.featured_image and post.featured_image.name:
            return post.featured_image.name
    except Exception:
        pass
    # Fallback: buscar la URL desde otros campos comunes.
    return ''


def _remove_duplicate_image(content, featured_url):
    """Encuentra la primera <img> cuyo src coincide con featured_url y
    elimina la unidad visual completa: el <a>...<img>...</a> wrapper si
    existe; si no, el <figure>; si no, el <p> que solo contenga la
    imagen; si no, solo el <img>.

    Devuelve (new_content, removed_block) donde removed_block es el
    HTML eliminado (para logging) o None si no encontró nada.
    """
    # Iterar sobre todas las <img> hasta encontrar la que matchea
    for img_match in re.finditer(r'<img\b[^>]*>', content, re.IGNORECASE):
        img_tag = img_match.group(0)
        src_match = SRC_RE.search(img_tag)
        img_src = src_match.group(1) if src_match else ''
        if not _is_duplicate(img_src, featured_url):
            continue

        # Encontramos la <img> duplicada. Ver si está envuelta en <a>.
        img_start, img_end = img_match.span()

        # ¿Hay un <a> que abre justo antes (con poco contenido entre el
        # <a> y el <img>)?
        a_open = None
        a_close_end = None
        # Buscar el <a ...> más cercano antes de img_start, en el mismo párrafo
        # (sin <p> o <div> intermedios).
        search_window = content[max(0, img_start - 300):img_start]
        # Última ocurrencia de <a ...> en el search_window
        for m in re.finditer(r'<a\b[^>]*>', search_window, re.IGNORECASE):
            a_open = m  # quedamos con el último

        if a_open:
            a_open_start_in_window = a_open.start()
            a_open_abs_start = max(0, img_start - 300) + a_open_start_in_window
            # Buscar el </a> correspondiente DESPUÉS del <img>
            close_search = content[img_end:img_end + 500]
            close_match = re.search(r'</a>', close_search, re.IGNORECASE)
            if close_match:
                a_close_end = img_end + close_match.end()
                # Verificar que entre el <a> y el <img> no hay texto
                # significativo (solo whitespace) — para no comernos
                # links que tienen texto + imagen.
                between = content[a_open.end() + (img_start - 300 if img_start - 300 > 0 else 0):img_start]
                # Si entre el <a> y el <img> hay solo whitespace y/o
                # tags vacíos, consideramos que el <a> envuelve la img.
                if re.match(r'^\s*$', re.sub(r'<[^>]+>', '', between)):
                    block_start = a_open_abs_start
                    block_end = a_close_end
                else:
                    block_start, block_end = img_start, img_end
            else:
                block_start, block_end = img_start, img_end
        else:
            block_start, block_end = img_start, img_end

        # Expandir hacia atrás: ¿hay un <figure> o <p> abriendo justo
        # antes que solo contenga este bloque?
        for tag in ('figure', 'p'):
            tag_open_re = re.compile(rf'<{tag}\b[^>]*>\s*$', re.IGNORECASE)
            preceding = content[:block_start]
            m_open = None
            for m in tag_open_re.finditer(preceding):
                m_open = m
            if m_open:
                # Buscar el </tag> después del block_end
                following = content[block_end:block_end + 200]
                m_close = re.match(rf'\s*</{tag}>', following, re.IGNORECASE)
                if m_close:
                    block_start = m_open.start()
                    block_end = block_end + m_close.end()
                    break  # no anidamos más

        removed = content[block_start:block_end]
        new_content = content[:block_start] + content[block_end:]
        # Limpiar saltos de línea/whitespace huérfanos
        new_content = re.sub(r'\n\s*\n\s*\n+', '\n\n', new_content)
        return new_content, removed

    return content, None


class Command(BaseCommand):
    help = (
        "Elimina imágenes duplicadas en el content de blog posts cuando "
        "coinciden con featured_image."
    )

    def add_arguments(self, parser):
        parser.add_argument('--dry-run', action='store_true')
        parser.add_argument('--apply', action='store_true')
        parser.add_argument('--slug', help='Solo procesar este slug.')

    def handle(self, *args, **opts):
        if not (opts.get('dry_run') or opts.get('apply')):
            raise CommandError('Pasa --dry-run o --apply.')

        apply_ = bool(opts.get('apply'))
        qs = BlogPost.objects.filter(deleted=False)
        if opts.get('slug'):
            qs = qs.filter(slug=opts['slug'])

        total = qs.count()
        modified = 0
        no_change = 0

        for post in qs:
            content = post.content or ''
            featured = _featured_url_from_post(post)
            if not content.strip() or not featured:
                no_change += 1
                continue

            new_content, removed = _remove_duplicate_image(content, featured)
            if not removed:
                no_change += 1
                continue

            delta = len(new_content) - len(content)
            self.stdout.write(
                f"\n[CLEAN] {post.slug}"
                f"\n  → featured: {_filename(featured)}"
                f"\n  → removed ({len(removed)} bytes): {removed[:160]}..."
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
        self.stdout.write(f"Total posts revisados: {total}")
        self.stdout.write(f"Posts modificados:     {modified}")
        self.stdout.write(f"Sin cambio:            {no_change}")
        if not apply_:
            self.stdout.write(self.style.WARNING(
                "\n(dry-run) Re-ejecuta con --apply para guardar."
            ))
