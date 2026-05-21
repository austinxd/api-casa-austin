"""Refresca todos los DNICache que quedaron con source='lazy_pending'.

Cuando descubrimos un familiar nuevo a través del árbol genealógico de
otro DNI, _ensure_dni_cache() crea un registro placeholder con
source='lazy_pending' y dispara un lookup en background. Si el thread
no completó (ej. proceso terminó antes), el cache queda vacío sin foto.

Este comando recorre TODOS los registros lazy_pending y los re-consulta
a Leder con include_photo=True para enriquecerlos.

Costo: 1 crédito Leder por DNI a refrescar.

Uso:
    python manage.py reniec_refresh_lazy_pending
    python manage.py reniec_refresh_lazy_pending --dry-run
    python manage.py reniec_refresh_lazy_pending --limit 10
"""
import time

from django.core.management.base import BaseCommand

from apps.reniec.models import DNICache
from apps.reniec.service import ReniecService


class Command(BaseCommand):
    help = "Re-consulta a Leder todos los DNICache con source='lazy_pending' para completarlos con foto/firma/etc."

    def add_arguments(self, parser):
        parser.add_argument('--dry-run', action='store_true', help='Solo muestra qué se refrescaría, sin llamar Leder.')
        parser.add_argument('--limit', type=int, default=0, help='Limitar a los primeros N (0 = todos).')
        parser.add_argument('--delay', type=float, default=0.5, help='Pausa entre lookups (default 0.5s para no martillar Leder).')

    def handle(self, *args, **opts):
        # Detectar lazy_pending: source explícito o sin nombres cargados
        qs = DNICache.objects.filter(source='lazy_pending').order_by('created')
        total = qs.count()

        # Fallback: también detectar los que no tienen source='lazy_pending' pero
        # claramente están vacíos (sin nombres y sin foto). Esos pueden ser pre-bug.
        empty_qs = DNICache.objects.filter(nombres__in=['', None], foto__in=['', None]).exclude(source='lazy_pending')
        empty_count = empty_qs.count()

        self.stdout.write(f"Encontrados:")
        self.stdout.write(f"  - source='lazy_pending':       {total}")
        self.stdout.write(f"  - sin nombres+sin foto (otros): {empty_count}")
        all_qs = list(qs) + list(empty_qs)
        if opts['limit']:
            all_qs = all_qs[:opts['limit']]
        self.stdout.write(f"  Total a refrescar: {len(all_qs)}")
        self.stdout.write('')

        if opts['dry_run']:
            for c in all_qs[:20]:
                self.stdout.write(f"  - {c.dni} (source={c.source}, nombres={c.nombres[:30] if c.nombres else ''})")
            if len(all_qs) > 20:
                self.stdout.write(f"  ... y {len(all_qs) - 20} más")
            self.stdout.write(self.style.WARNING("--dry-run: no se llamó Leder."))
            return

        ok, fail = 0, 0
        delay = opts['delay']
        for i, cache in enumerate(all_qs, 1):
            dni = cache.dni
            try:
                success, _ = ReniecService.lookup(
                    dni=dni,
                    source_app='backfill_lazy_pending',
                    include_photo=True,
                    include_full_data=True,
                )
                if success:
                    ok += 1
                    self.stdout.write(f"  [{i}/{len(all_qs)}] ✓ {dni}")
                else:
                    fail += 1
                    self.stdout.write(self.style.WARNING(f"  [{i}/{len(all_qs)}] ✗ {dni} (Leder no devolvió data)"))
            except Exception as e:
                fail += 1
                self.stdout.write(self.style.ERROR(f"  [{i}/{len(all_qs)}] ✗ {dni}: {e}"))
            if delay > 0:
                time.sleep(delay)

        self.stdout.write('')
        self.stdout.write(self.style.SUCCESS(f"Completado: ✓ {ok} refrescados, ✗ {fail} fallaron."))
