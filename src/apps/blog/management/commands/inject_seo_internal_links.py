"""Inserta enlaces internos contextuales en 3 blog posts clave para
transferir autoridad SEO hacia las landings comerciales.

Plan SEO §4.2, §4.3, §4.4. Mapeo:

    Blog post                                                  → Landing destino
    ---------------------------------------------------------------------------
    guia-para-organizar-una-boda-en-una-casa-de-playa          → /casa-playa-matrimonio-boda-lima
    como-planificar-una-fiesta-en-una-casa-con-piscina         → /casa-playa-cumpleanos-lima
    guia-de-etiqueta-para-usar-el-jacuzzi-en-hoteles-...       → /hotel-con-jacuzzi-lima

Cada blog post recibe:
- Un Hero CTA al inicio (antes del primer H2)
- Un CTA al final (antes de "</article>" o al final del content)

Idempotente: si ya existe el marker `data-seo-inject="..."`, no duplica.

Uso:
    # Previsualizar cambios sin guardar:
    python manage.py inject_seo_internal_links --dry-run

    # Aplicar:
    python manage.py inject_seo_internal_links --apply

    # Revertir (quita los bloques inyectados):
    python manage.py inject_seo_internal_links --revert
"""
import re
from django.core.management.base import BaseCommand, CommandError

from apps.blog.models import BlogPost

# Marker para identificar bloques inyectados por este comando.
MARKER_ID = 'casa-austin-seo-internal-link'

# Configuración por blog post. Slug → bloques HTML.
INJECTIONS = {
    'guia-para-organizar-una-boda-en-una-casa-de-playa': {
        'landing': '/casa-playa-matrimonio-boda-lima',
        'hero': (
            f'<div data-seo-inject="{MARKER_ID}" class="seo-hero-cta" '
            f'style="background:#fff9f3;border-left:4px solid #d4a574;'
            f'padding:16px 20px;margin:0 0 24px 0;border-radius:6px;">'
            f'<p style="margin:0 0 8px 0;font-weight:700;font-size:1.05rem;">'
            f'¿Buscas alquilar una casa de playa para tu matrimonio?</p>'
            f'<p style="margin:0 0 12px 0;color:#555;">Conoce nuestras casas '
            f'diseñadas para bodas en la playa cerca de Lima, con capacidad '
            f'para hasta 60 invitados, piscina y vista al mar.</p>'
            f'<a href="/casa-playa-matrimonio-boda-lima" '
            f'style="display:inline-block;background:#c9805b;color:#fff;'
            f'padding:10px 20px;border-radius:4px;text-decoration:none;'
            f'font-weight:600;">Ver casas para matrimonios →</a>'
            f'</div>'
        ),
        'footer': (
            f'<div data-seo-inject="{MARKER_ID}" class="seo-footer-cta" '
            f'style="text-align:center;margin:32px 0 16px 0;">'
            f'<a href="/casa-playa-matrimonio-boda-lima" '
            f'style="display:inline-block;background:#c9805b;color:#fff;'
            f'padding:12px 28px;border-radius:4px;text-decoration:none;'
            f'font-weight:600;font-size:1.05rem;">'
            f'Ver casas disponibles para tu boda en la playa →</a>'
            f'</div>'
        ),
    },
    'como-planificar-una-fiesta-en-una-casa-con-piscina': {
        'landing': '/casa-playa-cumpleanos-lima',
        'hero': (
            f'<div data-seo-inject="{MARKER_ID}" class="seo-hero-cta" '
            f'style="background:#fff9f3;border-left:4px solid #d4a574;'
            f'padding:16px 20px;margin:0 0 24px 0;border-radius:6px;">'
            f'<p style="margin:0 0 8px 0;font-weight:700;font-size:1.05rem;">'
            f'¿Buscas una casa con piscina para tu cumpleaños?</p>'
            f'<p style="margin:0 0 12px 0;color:#555;">Nuestras casas de '
            f'playa con piscina temperada son ideales para celebrar '
            f'cumpleaños en grupo cerca de Lima.</p>'
            f'<a href="/casa-playa-cumpleanos-lima" '
            f'style="display:inline-block;background:#c9805b;color:#fff;'
            f'padding:10px 20px;border-radius:4px;text-decoration:none;'
            f'font-weight:600;">Ver casas para cumpleaños →</a>'
            f'</div>'
        ),
        'footer': (
            f'<div data-seo-inject="{MARKER_ID}" class="seo-footer-cta" '
            f'style="text-align:center;margin:32px 0 16px 0;">'
            f'<a href="/casa-playa-cumpleanos-lima" '
            f'style="display:inline-block;background:#c9805b;color:#fff;'
            f'padding:12px 28px;border-radius:4px;text-decoration:none;'
            f'font-weight:600;font-size:1.05rem;">'
            f'Ver casas con piscina para fiestas de cumpleaños →</a>'
            f'</div>'
        ),
    },
    'guia-de-etiqueta-para-usar-el-jacuzzi-en-hoteles-compartidos-y-privados': {
        'landing': '/hotel-con-jacuzzi-lima',
        'hero': (
            f'<div data-seo-inject="{MARKER_ID}" class="seo-hero-cta" '
            f'style="background:#fff9f3;border-left:4px solid #d4a574;'
            f'padding:16px 20px;margin:0 0 24px 0;border-radius:6px;">'
            f'<p style="margin:0 0 8px 0;font-weight:700;font-size:1.05rem;">'
            f'¿Buscas alquilar una casa con jacuzzi privado?</p>'
            f'<p style="margin:0 0 12px 0;color:#555;">Disfruta de un jacuzzi '
            f'exclusivo en nuestras casas de playa cerca de Lima — sin '
            f'compartir, listo desde tu llegada.</p>'
            f'<a href="/hotel-con-jacuzzi-lima" '
            f'style="display:inline-block;background:#c9805b;color:#fff;'
            f'padding:10px 20px;border-radius:4px;text-decoration:none;'
            f'font-weight:600;">Ver casas con jacuzzi privado →</a>'
            f'</div>'
        ),
        'footer': (
            f'<div data-seo-inject="{MARKER_ID}" class="seo-footer-cta" '
            f'style="text-align:center;margin:32px 0 16px 0;">'
            f'<a href="/hotel-con-jacuzzi-lima" '
            f'style="display:inline-block;background:#c9805b;color:#fff;'
            f'padding:12px 28px;border-radius:4px;text-decoration:none;'
            f'font-weight:600;font-size:1.05rem;">'
            f'Ver opciones de casas con jacuzzi en Lima →</a>'
            f'</div>'
        ),
    },
}

# Patrón regex para detectar bloques previamente inyectados (idempotencia).
INJECTED_BLOCK_RE = re.compile(
    rf'<div\s+data-seo-inject="{MARKER_ID}"[^>]*>.*?</div>',
    re.DOTALL,
)


def _strip_existing_injections(html):
    """Elimina cualquier bloque inyectado previamente por este comando."""
    return INJECTED_BLOCK_RE.sub('', html)


def _insert_hero_block(html, hero_block):
    """Inserta el hero block antes del primer <h2>. Si no hay <h2>, lo pone
    al inicio del contenido."""
    m = re.search(r'<h2[^>]*>', html, re.IGNORECASE)
    if m:
        return html[:m.start()] + hero_block + html[m.start():]
    return hero_block + html


def _append_footer_block(html, footer_block):
    """Agrega el footer block al final del HTML del post."""
    return html + footer_block


class Command(BaseCommand):
    help = (
        'Inyecta enlaces internos SEO en blog posts clave (bodas, '
        'piscina/cumpleaños, jacuzzi). Idempotente.'
    )

    def add_arguments(self, parser):
        parser.add_argument(
            '--dry-run', action='store_true',
            help='Muestra qué cambiaría sin guardar nada.',
        )
        parser.add_argument(
            '--apply', action='store_true',
            help='Aplica los cambios a la BD.',
        )
        parser.add_argument(
            '--revert', action='store_true',
            help='Quita los bloques inyectados previamente.',
        )

    def handle(self, *args, **opts):
        if not (opts.get('dry_run') or opts.get('apply') or opts.get('revert')):
            raise CommandError(
                'Pasa una de: --dry-run, --apply, --revert',
            )
        revert = bool(opts.get('revert'))
        apply_ = bool(opts.get('apply'))

        for slug, cfg in INJECTIONS.items():
            try:
                post = BlogPost.objects.get(slug=slug, deleted=False)
            except BlogPost.DoesNotExist:
                self.stdout.write(self.style.WARNING(
                    f"⚠ Blog post no encontrado: {slug}"
                ))
                continue

            original_len = len(post.content or '')
            # Limpiar inyecciones previas SIEMPRE — así re-ejecutar el
            # comando con prompts distintos no acumula bloques.
            clean = _strip_existing_injections(post.content or '')

            if revert:
                new_content = clean
                action = 'REVERT'
            else:
                new_content = _insert_hero_block(clean, cfg['hero'])
                new_content = _append_footer_block(new_content, cfg['footer'])
                action = 'INJECT'

            delta = len(new_content) - original_len
            self.stdout.write(
                f"\n[{action}] {slug}"
                f"\n  → landing: {cfg['landing']}"
                f"\n  → bytes change: {delta:+d} (was {original_len}, now {len(new_content)})"
            )

            if apply_ or revert:
                post.content = new_content
                post.save(update_fields=['content', 'updated'])
                self.stdout.write(self.style.SUCCESS(
                    f"  ✓ guardado"
                ))
            else:
                self.stdout.write(self.style.WARNING(
                    "  (dry-run, no se guardó)"
                ))

        self.stdout.write("")
        if apply_:
            self.stdout.write(self.style.SUCCESS("Done. Cambios aplicados."))
        elif revert:
            self.stdout.write(self.style.SUCCESS("Done. Bloques inyectados removidos."))
        else:
            self.stdout.write(self.style.WARNING(
                "Done. Vuelve a correr con --apply para guardar."
            ))
