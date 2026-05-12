"""Reporte de UnresolvedQuestion para evaluar cobertura de G_FAQ (R2).

Lista las top N preguntas sin responder de los últimos D días, agrupadas por
keyword/tema, marcando cuáles YA cubre G_FAQ actual y cuáles siguen
requiriendo respuesta humana o un nuevo guard.

Uso:
    python manage.py chatbot_unresolved_report
    python manage.py chatbot_unresolved_report --days 30 --top 30
    python manage.py chatbot_unresolved_report --status pending --days 7
"""
import re
from collections import Counter, defaultdict
from datetime import timedelta

from django.core.management.base import BaseCommand
from django.utils import timezone

from apps.chatbot.models import UnresolvedQuestion
from apps.chatbot.guards import FAQ_TOPICS


# Keywords amplias para agrupar visualmente (no son los regex de los guards,
# solo para ordenar el reporte por tema y dar señal al equipo).
GROUP_KEYWORDS = {
    'pet_friendly':    ['mascota', 'perro', 'gato', 'pet friendly', 'perrit'],
    'check_in_out':    ['check in', 'check-in', 'check out', 'check-out',
                        'hora de ingreso', 'hora de salida', 'a que hora'],
    'location':        ['donde queda', 'ubicacion', 'ubicación', 'direccion',
                        'dirección', 'maps', 'cómo llego', 'como llego',
                        'pulpos'],
    'pool_jacuzzi':    ['piscina', 'jacuzzi', 'jacussi', 'temperad',
                        'agua caliente'],
    'party_music':     ['fiesta', 'dj', 'orquesta', 'cantante', 'recepción',
                        'recepcion', 'música', 'musica', 'bulla'],
    'extra_services':  ['decoración', 'decoracion', 'catering', 'cocinero',
                        'mesero', 'mozo', 'desayuno', 'globos'],
    'parking':         ['cochera', 'estacionamiento', 'parking',
                        'camionetas', 'autos'],
    'grill':           ['parrilla', 'bbq', 'carbón', 'leña'],
    'wifi':            ['wifi', 'wi-fi', 'internet', 'señal'],
    'photos_videos':   ['video', 'foto', 'ver la casa'],
    'children':        ['niño', 'niña', 'menores', 'bebe', 'bebé'],
    'visitors':        ['visita', 'visitante', 'invitado'],
    # Temas NO cubiertos por G_FAQ — útil para detectar nuevos guards.
    'pricing':         ['precio', 'costo', 'cuánto', 'cuanto', 'tarifa'],
    'capacity':        ['capacidad', 'cuántas personas', 'cuantas personas'],
    'payment':         ['pago', 'voucher', 'depósito', 'deposito', 'transferencia',
                        'tarjeta', 'yape', 'plin'],
    'cancellation':    ['cancelar', 'reembolso', 'devolución', 'devolucion'],
    'discount':        ['descuento', 'promoción', 'promocion', 'código',
                        'codigo'],
    'security_deposit': ['garantía', 'garantia', 'depósito de garantía'],
}

COVERED_BY_FAQ = {t['topic'] for t in FAQ_TOPICS}


def classify(text):
    """Devuelve la lista de grupos detectados en el texto (lower)."""
    if not text:
        return ['_empty']
    low = text.lower()
    hits = []
    for group, kws in GROUP_KEYWORDS.items():
        if any(kw in low for kw in kws):
            hits.append(group)
    return hits or ['_other']


class Command(BaseCommand):
    help = "Reporte de preguntas sin resolver del chatbot."

    def add_arguments(self, parser):
        parser.add_argument(
            '--days', type=int, default=30,
            help='Ventana hacia atrás en días (default 30).',
        )
        parser.add_argument(
            '--top', type=int, default=20,
            help='Top N preguntas a listar (default 20).',
        )
        parser.add_argument(
            '--status', default='all',
            choices=['all', 'pending', 'resolved', 'ignored'],
            help='Filtrar por estado (default all).',
        )

    def handle(self, *args, **opts):
        days = opts['days']
        top = opts['top']
        status = opts['status']

        since = timezone.now() - timedelta(days=days)
        qs = UnresolvedQuestion.objects.filter(
            deleted=False, created__gte=since,
        )
        if status != 'all':
            qs = qs.filter(status=status)

        total = qs.count()
        self.stdout.write(self.style.SUCCESS(
            f"\n=== UnresolvedQuestion · últimos {days} días · "
            f"status={status} · total={total} ==="
        ))
        if total == 0:
            self.stdout.write("Sin preguntas en la ventana.")
            return

        # Conteo por grupo
        by_group = Counter()
        examples = defaultdict(list)
        for uq in qs.order_by('-created'):
            groups = classify(uq.question)
            for g in groups:
                by_group[g] += 1
                if len(examples[g]) < 3:
                    examples[g].append(uq.question[:120].replace('\n', ' '))

        self.stdout.write(self.style.SUCCESS(
            f"\n--- Conteo por tema ({len(by_group)} grupos) ---"
        ))
        rows = sorted(by_group.items(), key=lambda x: (-x[1], x[0]))
        for group, count in rows:
            mark = '✓ FAQ' if group in COVERED_BY_FAQ else '· NEW '
            self.stdout.write(f"  [{mark}] {group:20s} {count:>4} preguntas")

        self.stdout.write(self.style.SUCCESS(
            f"\n--- Top {top} preguntas más recientes (sin agrupar) ---"
        ))
        for i, uq in enumerate(qs.order_by('-created')[:top], 1):
            cat = uq.category or '-'
            stat = uq.status
            preview = uq.question[:140].replace('\n', ' ')
            groups = ','.join(classify(uq.question))
            self.stdout.write(
                f" {i:2}. [{stat:>10}|{cat:>10}|{groups:>20}] {preview}"
            )

        self.stdout.write(self.style.SUCCESS(
            f"\n--- Ejemplos por grupo (NEW = no cubierto por G_FAQ) ---"
        ))
        for group, count in rows:
            if group in COVERED_BY_FAQ or group in ('_empty', '_other'):
                continue
            self.stdout.write(f"\n  [NEW · {group}] {count} preguntas:")
            for ex in examples[group]:
                self.stdout.write(f"    - {ex}")

        self.stdout.write(self.style.SUCCESS(
            f"\n--- Cobertura de G_FAQ ---"
        ))
        covered = sum(
            count for g, count in by_group.items()
            if g in COVERED_BY_FAQ
        )
        new = sum(
            count for g, count in by_group.items()
            if g not in COVERED_BY_FAQ and g not in ('_empty',)
        )
        other = by_group.get('_other', 0)
        empty = by_group.get('_empty', 0)
        self.stdout.write(
            f"  Cubiertas por G_FAQ: {covered} ({covered/total:.0%})"
        )
        self.stdout.write(
            f"  Temas nuevos:        {new} ({new/total:.0%})"
        )
        self.stdout.write(
            f"  Sin clasificar:      {other} ({other/total:.0%})"
        )
        if empty:
            self.stdout.write(f"  Vacías:              {empty}")
