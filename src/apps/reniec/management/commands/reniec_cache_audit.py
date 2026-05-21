"""Auditoría del cache de Reniec.

Recorre todos los DNICache y cuenta cuántos tienen foto, firma, huellas.
Útil para detectar cuántos clientes quedaron sin imágenes (porque la
llamada original no pasó include_photo=True).

Uso:
    python manage.py reniec_cache_audit
    python manage.py reniec_cache_audit --by-source   # desglosa por fuente
    python manage.py reniec_cache_audit --sample 10   # imprime 10 ejemplos sin foto
"""
from django.core.management.base import BaseCommand
from django.db.models import Q

from apps.reniec.models import DNICache


class Command(BaseCommand):
    help = "Audita la cobertura de imágenes (foto/firma/huellas) en DNICache."

    def add_arguments(self, parser):
        parser.add_argument('--by-source', action='store_true', help='Desglose por campo `source`.')
        parser.add_argument('--sample', type=int, default=0, help='Imprime N DNIs sin foto.')

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

        if opts['sample']:
            self.stdout.write(f"\n=== Sample de {opts['sample']} DNIs sin foto ===\n")
            no_photo = DNICache.objects.filter(
                Q(foto__isnull=True) | Q(foto=''),
            ).order_by('-created')[:opts['sample']]
            for c in no_photo:
                self.stdout.write(
                    f"  DNI {c.dni} | {c.nombres or ''} {c.apellido_paterno or ''} | "
                    f"source={c.source or '-'} | created={c.created.strftime('%Y-%m-%d') if c.created else '-'}"
                )

        self.stdout.write("\n" + self.style.SUCCESS("Audit completo."))
