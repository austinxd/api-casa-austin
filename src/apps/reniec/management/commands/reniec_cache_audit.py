"""Auditoría del cache de Reniec.

Recorre todos los DNICache y cuenta cuántos tienen foto, firma, huellas.
Útil para detectar cuántos clientes quedaron sin imágenes (porque la
llamada original no pasó include_photo=True).

Uso:
    python manage.py reniec_cache_audit
    python manage.py reniec_cache_audit --by-source     # desglosa por fuente
    python manage.py reniec_cache_audit --by-date       # cobertura últimos 7/30 días vs total
    python manage.py reniec_cache_audit --sample 10     # imprime 10 ejemplos sin foto
    python manage.py reniec_cache_audit --sample-recent 10  # 10 más recientes sin foto
"""
from datetime import timedelta

from django.core.management.base import BaseCommand
from django.db.models import Q, Count
from django.utils import timezone

from apps.reniec.models import DNICache


class Command(BaseCommand):
    help = "Audita la cobertura de imágenes (foto/firma/huellas) en DNICache."

    def add_arguments(self, parser):
        parser.add_argument('--by-source', action='store_true', help='Desglose por campo `source`.')
        parser.add_argument('--by-date', action='store_true', help='Cobertura últimos 7d, 30d, 90d vs total.')
        parser.add_argument('--sample', type=int, default=0, help='Imprime N DNIs sin foto (más antiguos).')
        parser.add_argument('--sample-recent', type=int, default=0, help='Imprime N DNIs sin foto MÁS RECIENTES.')

    def handle(self, *args, **opts):
        total = DNICache.objects.count()
        if total == 0:
            self.stdout.write(self.style.WARNING("DNICache está vacío."))
            return

        # Conteos
        with_foto = DNICache.objects.exclude(Q(foto__isnull=True) | Q(foto='')).count()
        with_firma = DNICache.objects.exclude(Q(firma__isnull=True) | Q(firma='')).count()
        with_hi = DNICache.objects.exclude(Q(huella_izquierda__isnull=True) | Q(huella_izquierda='')).count()
        with_hd = DNICache.objects.exclude(Q(huella_derecha__isnull=True) | Q(huella_derecha='')).count()

        def pct(n):
            return f"{(n / total * 100):.1f}%"

        self.stdout.write(f"\n=== DNICache audit ({total:,} registros totales) ===\n")
        self.stdout.write(f"  Con foto:             {with_foto:>6,} ({pct(with_foto)})")
        self.stdout.write(f"  Con firma:            {with_firma:>6,} ({pct(with_firma)})")
        self.stdout.write(f"  Con huella izquierda: {with_hi:>6,} ({pct(with_hi)})")
        self.stdout.write(f"  Con huella derecha:   {with_hd:>6,} ({pct(with_hd)})")
        self.stdout.write(f"  Sin foto:             {total - with_foto:>6,} ({pct(total - with_foto)})")
        self.stdout.write(f"  Sin ninguna imagen:   {DNICache.objects.filter(Q(foto__isnull=True) | Q(foto='')).filter(Q(firma__isnull=True) | Q(firma='')).count():>6,}")

        if opts['by_source']:
            self.stdout.write(f"\n=== Por fuente (source) ===\n")
            from django.db.models import Count
            by_src = DNICache.objects.values('source').annotate(
                total=Count('id'),
                con_foto=Count('id', filter=~Q(foto__isnull=True) & ~Q(foto='')),
            ).order_by('-total')
            for row in by_src:
                src = row['source'] or '(none)'
                t = row['total']
                cf = row['con_foto']
                self.stdout.write(f"  {src:>20}  {t:>6,} total  →  {cf:>6,} con foto ({(cf/t*100 if t else 0):.0f}%)")

        if opts['by_date']:
            self.stdout.write(f"\n=== Cobertura por cohorte temporal ===\n")
            now = timezone.now()
            for label, days in [("Últimos 7 días", 7), ("Últimos 30 días", 30), ("Últimos 90 días", 90), ("Más antiguos (>90d)", None)]:
                if days is None:
                    cutoff = now - timedelta(days=90)
                    qs = DNICache.objects.filter(created__lt=cutoff)
                else:
                    cutoff = now - timedelta(days=days)
                    qs = DNICache.objects.filter(created__gte=cutoff)
                t = qs.count()
                cf = qs.exclude(Q(foto__isnull=True) | Q(foto='')).count()
                cfp = (cf / t * 100) if t else 0
                self.stdout.write(f"  {label:>22}  {t:>6,} reg.  →  {cf:>6,} con foto ({cfp:.1f}%)")

        if opts['by_source']:
            self.stdout.write(f"\n=== Por fuente (source) ===\n")
            by_src = DNICache.objects.values('source').annotate(
                total=Count('id'),
                con_foto=Count('id', filter=~Q(foto__isnull=True) & ~Q(foto='')),
            ).order_by('-total')
            for row in by_src:
                src = row['source'] or '(none)'
                t = row['total']
                cf = row['con_foto']
                self.stdout.write(f"  {src:>20}  {t:>6,} total  →  {cf:>6,} con foto ({(cf/t*100 if t else 0):.0f}%)")

        if opts['sample']:
            self.stdout.write(f"\n=== Sample de {opts['sample']} DNIs sin foto (MÁS ANTIGUOS) ===\n")
            no_photo = DNICache.objects.filter(
                Q(foto__isnull=True) | Q(foto=''),
            ).order_by('created')[:opts['sample']]
            for c in no_photo:
                self.stdout.write(
                    f"  DNI {c.dni} | {(c.nombres or '')[:20]:20} | "
                    f"source={c.source or '-':>15} | created={c.created.strftime('%Y-%m-%d') if c.created else '-'}"
                )

        if opts['sample_recent']:
            self.stdout.write(f"\n=== Sample de {opts['sample_recent']} DNIs sin foto (MÁS RECIENTES) ===\n")
            no_photo = DNICache.objects.filter(
                Q(foto__isnull=True) | Q(foto=''),
            ).order_by('-created')[:opts['sample_recent']]
            for c in no_photo:
                self.stdout.write(
                    f"  DNI {c.dni} | {(c.nombres or '')[:20]:20} | "
                    f"source={c.source or '-':>15} | created={c.created.strftime('%Y-%m-%d %H:%M') if c.created else '-'}"
                )

        self.stdout.write("\n" + self.style.SUCCESS("Audit completo."))
