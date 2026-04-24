"""
Analiza mensajes inbound del chatbot y los clasifica en categorías de
preguntas frecuentes. Mantiene un watermark (checkpoint) para procesar solo
los mensajes nuevos desde la última corrida, evitando reanálisis.

Flujo por mensaje:
1. Prompt con categorías fijas + frases descriptivas existentes en esa
   categoría (cacheado por OpenAI después del 1er hit).
2. Modelo (gpt-4.1-nano) devuelve JSON: {category, match_id|null, new_label|null}.
3. Si match_id → suma +1 al count del FrequentQuestion existente.
4. Si new_label → crea un FrequentQuestion nuevo con count=1.

Uso: python manage.py analyze_frequent_questions
Cron recomendado: diario 2am Lima.
"""
import json
import logging
from datetime import timedelta

from django.core.management.base import BaseCommand
from django.utils import timezone

from apps.chatbot.models import (
    ChatMessage, ChatbotConfiguration,
    FrequentQuestion, FrequentQuestionCheckpoint,
)

logger = logging.getLogger(__name__)


# Categorías predefinidas — legibles para el modelo.
CATEGORIES = {
    'how_to_book': '¿Cómo reservar? (proceso, pago, adelanto)',
    'pricing_general': 'Precios generales (desde cuánto, promedios, comparativas)',
    'availability': 'Disponibilidad de fechas específicas',
    'location': 'Ubicación (dirección, cómo llegar, distancia)',
    'photos': 'Fotos, videos o tour virtual de las casas',
    'capacity': 'Capacidad (cuántas personas, dormitorios, camas)',
    'amenities': 'Comodidades (piscina, jacuzzi, parrilla, WiFi, sonido, etc)',
    'parties_music': 'Fiestas, música, orquestas, volumen, bulla',
    'pets': 'Mascotas (aceptan, cargos, tipos)',
    'food_service': 'Servicio de alimentos, chef, catering',
    'check_in_out': 'Horarios de ingreso/salida, late checkout, early check-in',
    'full_day': 'Alquiler full day (uso diurno sin pernoctar)',
    'payment_methods': 'Métodos de pago (tarjeta, transferencia, Yape, Plin)',
    'discounts': 'Descuentos, promociones, códigos',
    'cancellation': 'Cancelaciones, reembolsos, cambios de fecha',
    'group_events': 'Eventos corporativos, bodas, grupos grandes',
    'security_policies': 'Seguridad, reglas, políticas de convivencia',
    'during_stay_support': 'Soporte durante estadía (problemas, dudas en casa)',
    'other': 'Tema no contemplado arriba — requiere revisión',
}

CATEGORY_LABELS = {
    'how_to_book': '¿Cómo reservo?',
    'pricing_general': '¿Desde qué precios?',
    'availability': '¿Hay disponibilidad?',
    'location': '¿Dónde queda?',
    'photos': 'Fotos / Ver la casa',
    'capacity': '¿Cuántas personas entran?',
    'amenities': 'Comodidades / Servicios',
    'parties_music': 'Fiestas, música y ruido',
    'pets': 'Mascotas',
    'food_service': 'Servicio de alimentos',
    'check_in_out': 'Horarios check-in / check-out',
    'full_day': 'Full day (solo de día)',
    'payment_methods': 'Métodos de pago',
    'discounts': 'Descuentos y promociones',
    'cancellation': 'Cancelaciones y reembolsos',
    'group_events': 'Eventos y grupos grandes',
    'security_policies': 'Seguridad y reglas',
    'during_stay_support': 'Soporte durante estadía',
    'other': 'Otros',
}


CLASSIFIER_SYSTEM_PROMPT = """Eres un clasificador de mensajes de clientes de Casa Austin (alquiler de casas de playa en Perú).

Tu tarea: clasificar UN mensaje del cliente y decidir si encaja con una pregunta frecuente ya existente o si introduce un tema nuevo.

CATEGORÍAS DISPONIBLES:
""" + "\n".join(f"- {k}: {v}" for k, v in CATEGORIES.items()) + """

REGLAS:
1. Elige la categoría que MEJOR encaja con la intención del mensaje.
2. Si el mensaje NO es una pregunta o consulta (solo saludo, confirmación, emoji, etc.), devuelve category="other" con new_label=null y match_id=null.
3. Si el mensaje encaja claramente con una pregunta frecuente existente de la misma categoría, devuelve match_id=<id de la existente> y new_label=null.
4. Si es un tema nuevo, devuelve match_id=null y new_label con una frase descriptiva clara que empiece con "Los usuarios preguntaron..." o "Los clientes quieren saber..." o similar. La frase debe ser agnóstica al usuario individual y capturar el tema para uso en reportes.

EJEMPLOS DE new_label:
- "Los usuarios preguntaron por mesas de billar"
- "Los clientes quieren saber si tienen estacionamiento 24 horas"
- "Preguntan si aceptan grupos grandes para eventos corporativos"
- "Consultan por el horario de ingreso anticipado"

FORMATO DE SALIDA (JSON estricto, SIN texto adicional):
{"category": "<key_de_la_lista>", "match_id": <int o null>, "new_label": "<frase o null>"}
"""


class Command(BaseCommand):
    help = 'Clasifica mensajes inbound en preguntas frecuentes (incremental)'

    def add_arguments(self, parser):
        parser.add_argument('--dry-run', action='store_true')
        parser.add_argument(
            '--limit', type=int, default=500,
            help='Máximo de mensajes a procesar por corrida (default 500)',
        )
        parser.add_argument(
            '--since-hours', type=int, default=None,
            help='Ignora el checkpoint y procesa los últimos N horas',
        )
        parser.add_argument(
            '--reset-checkpoint', action='store_true',
            help='Borra el checkpoint antes de empezar (fuerza reanálisis completo)',
        )

    def handle(self, *args, **options):
        dry_run = options['dry_run']
        limit = options['limit']
        since_hours = options['since_hours']

        config = ChatbotConfiguration.get_config()
        if not config.is_active:
            self.stdout.write('Chatbot inactivo, saltando análisis.')
            return

        import openai
        from django.conf import settings
        client = openai.OpenAI(api_key=settings.OPENAI_API_KEY)

        # Checkpoint
        if options['reset_checkpoint']:
            FrequentQuestionCheckpoint.objects.all().delete()
            self.stdout.write('Checkpoint reseteado.')
        checkpoint = FrequentQuestionCheckpoint.get_singleton()

        # Ventana de análisis
        if since_hours is not None:
            since = timezone.now() - timedelta(hours=since_hours)
        elif checkpoint.last_analyzed_message_created:
            since = checkpoint.last_analyzed_message_created
        else:
            since = timezone.now() - timedelta(days=30)

        qs = ChatMessage.objects.filter(
            deleted=False,
            direction=ChatMessage.DirectionChoices.INBOUND,
            message_type=ChatMessage.MessageTypeChoices.TEXT,
            created__gt=since,
        ).order_by('created')[:limit]

        total = qs.count()
        self.stdout.write(
            f'Analizando mensajes desde {since.isoformat()} '
            f'(máx {limit}): {total} mensajes nuevos.'
        )

        if total == 0:
            self.stdout.write('Nada nuevo que analizar.')
            return

        processed = 0
        classified = 0
        errors = 0
        last_ts = None

        # Modelo: el más barato de OpenAI
        classifier_model = 'gpt-4.1-nano'

        for msg in qs:
            content = (msg.content or '').strip()
            if not content or len(content) < 3:
                processed += 1
                last_ts = msg.created
                continue
            # Filtrar mensajes claramente no-preguntas
            if len(content) <= 5 and not content.endswith('?'):
                processed += 1
                last_ts = msg.created
                continue

            # Construir prompt user con frases existentes en cada categoría
            # (limitadas a top 8 por categoría para controlar tokens)
            existing_block = self._build_existing_block()

            user_prompt = (
                f"MENSAJE DEL CLIENTE:\n{content[:500]}\n\n"
                f"PREGUNTAS FRECUENTES EXISTENTES (para posible match):\n"
                f"{existing_block}\n\n"
                f"Clasifica el mensaje y responde SOLO con el JSON."
            )

            if dry_run:
                self.stdout.write(f'[DRY] {content[:80]}')
                processed += 1
                last_ts = msg.created
                continue

            try:
                resp = client.chat.completions.create(
                    model=classifier_model,
                    messages=[
                        {"role": "system", "content": CLASSIFIER_SYSTEM_PROMPT},
                        {"role": "user", "content": user_prompt},
                    ],
                    temperature=0,
                    max_tokens=150,
                    response_format={"type": "json_object"},
                )
                raw = resp.choices[0].message.content or ""
                data = json.loads(raw)
            except Exception as e:
                logger.error(f"Error clasificando msg {msg.id}: {e}")
                errors += 1
                processed += 1
                last_ts = msg.created
                continue

            category = data.get('category') or 'other'
            if category not in CATEGORIES:
                category = 'other'
            match_id = data.get('match_id')
            new_label = (data.get('new_label') or '').strip()

            self._apply_classification(
                msg, category, match_id, new_label,
            )
            classified += 1
            processed += 1
            last_ts = msg.created

            if processed % 50 == 0:
                self.stdout.write(f'  progreso: {processed}/{total}')

        # Actualizar checkpoint
        if last_ts and not dry_run:
            checkpoint.last_analyzed_message_created = last_ts
            checkpoint.total_messages_analyzed = (
                checkpoint.total_messages_analyzed + processed
            )
            checkpoint.save()

        self.stdout.write(self.style.SUCCESS(
            f'✓ Procesados: {processed} | Clasificados: {classified} | '
            f'Errores: {errors}'
        ))

    def _build_existing_block(self):
        """Construye un bloque con frases existentes por categoría.
        Limita a las 8 más frecuentes por categoría para controlar tokens."""
        lines = []
        for cat_key in CATEGORIES.keys():
            if cat_key == 'other':
                continue
            top = FrequentQuestion.objects.filter(
                category=cat_key
            ).order_by('-count')[:8]
            items = list(top)
            if not items:
                lines.append(f"\n[{cat_key}]: (sin preguntas previas)")
                continue
            lines.append(f"\n[{cat_key}]:")
            for fq in items:
                lines.append(f"  id={fq.id.hex[:8]} (×{fq.count}): {fq.label}")
        return '\n'.join(lines) if lines else '(sin preguntas previas)'

    def _apply_classification(self, msg, category, match_id, new_label):
        """Aplica la clasificación: match existente o crea nueva.
        `match_id` viene como string hex corto (primeros 8 chars del UUID)."""
        now = timezone.now()

        if match_id:
            # Buscar por prefijo del UUID (los primeros 8 chars)
            prefix = str(match_id).replace('-', '').lower()[:8]
            if prefix:
                fq = FrequentQuestion.objects.filter(
                    category=category,
                ).extra(
                    where=["REPLACE(CAST(id AS CHAR), '-', '') LIKE %s"],
                    params=[f"{prefix}%"],
                ).first()
                if fq:
                    fq.count += 1
                    fq.last_seen_at = now
                    samples = list(fq.sample_messages or [])
                    if len(samples) < 5:
                        samples.append({
                            'content': (msg.content or '')[:300],
                            'session_id': str(msg.session_id),
                            'created': msg.created.isoformat(),
                        })
                        fq.sample_messages = samples
                    fq.save(update_fields=[
                        'count', 'last_seen_at', 'sample_messages', 'updated',
                    ])
                    return

        # No hubo match — crear nueva si hay label o es descartable
        if not new_label:
            return  # mensaje no aportó — no crear fila

        FrequentQuestion.objects.create(
            category=category,
            category_label=CATEGORY_LABELS.get(category, category),
            label=new_label,
            count=1,
            last_seen_at=now,
            sample_messages=[{
                'content': (msg.content or '')[:300],
                'session_id': str(msg.session_id),
                'created': msg.created.isoformat(),
            }],
        )
