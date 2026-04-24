"""
Analiza CONVERSACIONES COMPLETAS del chatbot para extraer preguntas
frecuentes. Para cada conversación madura (sin actividad reciente), pasa
el transcript completo al modelo y le pide identificar las preguntas
genuinas que hizo el cliente, con categoría y frase descriptiva.

Ventajas vs analizar mensaje por mensaje:
- El modelo ve el contexto completo (respuestas del cliente tipo "20 personas"
  no se confunden con preguntas).
- Múltiples formas de preguntar lo mismo dentro de la misma conversación
  se consolidan automáticamente en una sola pregunta.
- No requiere filtros determinísticos (cliente VS bot, ruido, saludos).

Flujo:
1. Selecciona sesiones con:
   - last_message_at antes de (now - MIN_INACTIVITY_HOURS), o status=closed.
   - No analizadas previamente (conversation_context['fq_analyzed_at'] vacío).
   - Con al menos N mensajes (total_messages >= 2).
2. Por cada sesión:
   - Arma transcript (user + assistant, últimos 40 msgs).
   - Llama al modelo (gpt-4.1-nano) con prompt que pide JSON con lista
     de preguntas [{category, match_id|null, new_label|null}, ...].
   - Aplica cada pregunta: match vs existentes o crea nueva en
     FrequentQuestion.
   - Marca la sesión: conversation_context['fq_analyzed_at'] = now.
3. Actualiza checkpoint.

Uso: python manage.py analyze_frequent_questions
Cron recomendado: diario 2am Lima.
"""
import json
import logging
from datetime import timedelta

from django.core.management.base import BaseCommand
from django.utils import timezone

from apps.chatbot.models import (
    ChatSession, ChatMessage, ChatbotConfiguration,
    FrequentQuestion, FrequentQuestionCheckpoint,
)

logger = logging.getLogger(__name__)


MIN_INACTIVITY_HOURS = 48   # antigüedad mínima del último mensaje
MIN_TOTAL_MESSAGES = 2      # evita sesiones con solo 1 mensaje de bienvenida
MAX_TRANSCRIPT_MESSAGES = 40  # trunca transcripts muy largos
MAX_MESSAGE_CHARS = 400       # trunca mensajes individuales


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


CLASSIFIER_SYSTEM_PROMPT = """Eres un analizador de conversaciones del chatbot de Casa Austin (alquiler de casas de playa en Perú).

Tu tarea: leer una conversación WhatsApp entre un cliente y Valeria (asesora) e identificar SOLO las preguntas o consultas genuinas que hizo el cliente.

IGNORA solo lo siguiente:
- Saludos aislados sin contenido ("Hola" solo, "Buenas tardes" solo)
- Confirmaciones o respuestas a Valeria ("sí", "ok", "listo", "gracias", "claro")
- Datos que el cliente da como respuesta a preguntas del bot ("20 personas", "el 25 de abril", "casa 3")
- Mensajes muy cortos sin contexto claro (emojis solos, "?")

EXTRAE (enfoque AGRESIVO — capturamos intención del cliente, no solo preguntas):
1. Preguntas explícitas: "¿Aceptan mascotas?", "¿Cuál es el precio?"
2. Consultas implícitas: "Quisiera información sobre la piscina", "Necesito saber el horario"
3. EXPRESIONES DE INTENCIÓN (importantes — se consideran consulta):
   - "Quisiera reservar" / "Quiero reservar una casa" → tema: cómo reservar
   - "Me interesa conocer más sobre las casas" → tema: información general
   - "Quiero información" / "Información por favor" → tema: información general
   - "Necesito ayuda con casaaustin.pe" → tema: ayuda con sitio/reserva
   - "Estoy interesada en alquilar" → tema: alquiler general
   - "Busco una casa para..." → tema: búsqueda con contexto
   Estas cuentan como "consulta" porque revelan duda del cliente.
4. Dudas sobre políticas, servicios o proceso.

La regla práctica: ¿el cliente está BUSCANDO una respuesta/información?
Si sí → captúralo. Si solo está confirmando o respondiendo al bot → ignóralo.

CATEGORÍAS DISPONIBLES:
""" + "\n".join(f"- {k}: {v}" for k, v in CATEGORIES.items()) + """

⚠️ GUÍA PARA CASOS AMBIGUOS DE CATEGORIZACIÓN:
- Pregunta por PRECIO + FECHA específica → usa `availability` (pide cotización).
  Ej: "¿precio para el 25 de abril?" → availability.
- Pregunta por PRECIO sin fecha o genérica → usa `pricing_general`.
  Ej: "¿desde qué precios?", "¿cuánto cuesta la casa?" → pricing_general.
- Pregunta por CAPACIDAD → siempre `capacity`, NO `availability`.
  Ej: "¿cuántas personas entran?", "¿para cuántos es la casa?" → capacity.
- Pregunta por CÓMO RESERVAR, voucher, adelanto, web → `how_to_book`.
- Pregunta por MÉTODOS de pago (tarjeta, Yape, etc) → `payment_methods`.
  Pero "¿ya procesaron mi pago?" → `during_stay_support` o `how_to_book`.
- Pregunta por MAPA, dirección, cómo llegar → `location`.
- Pregunta por FOTOS, video, ver la casa → `photos`.
- Pregunta por MASCOTAS → siempre `pets`.
- Pregunta por FIESTAS/MÚSICA/ORQUESTA/BULLA → siempre `parties_music`.
- Pregunta por EVENTOS corporativos, bodas, grupos >30 → `group_events`.
- Pregunta por FULL DAY/INGRESO ANTICIPADO → `full_day` o `check_in_out`.
  "¿Puedo entrar antes?" → check_in_out. "¿Solo de día?" → full_day.

⚠️ REGLA DE CONSOLIDACIÓN INTERNA (IMPORTANTE):
Dentro de UNA MISMA CONVERSACIÓN, el cliente a menudo reformula la misma
pregunta. Tú DEBES consolidarlas como UNA SOLA entrada en tu output.
Ejemplos de lo que es la MISMA pregunta:
- "cuánto cuesta" = "precio" = "desde qué monto" = "qué tarifas" → 1 entrada
- "¿hay disponibilidad?" = "¿está libre?" = "¿tienen fechas?" → 1 entrada
- "¿cuántas personas caben?" = "¿capacidad de la casa?" = "¿para cuántos es?" → 1 entrada
NUNCA devuelvas 2 entradas que signifiquen lo mismo aunque el cliente las
haya formulado con palabras distintas.

⚠️ MATCH CONTRA EXISTENTES (AGRESIVO):
Te daré una lista de preguntas frecuentes YA registradas (por categoría).
Para cada pregunta que identifiques, SIEMPRE revisa primero si es
"esencialmente la misma" que alguna de la lista. El criterio es SEMÁNTICO,
no literal. Casos que DEBEN hacer match:
- Tu pregunta: "cliente quiere saber cuándo hay fechas libres"
  Existente: "Los usuarios preguntan si hay disponibilidad"
  → MATCH (ambos sobre disponibilidad)
- Tu pregunta: "preguntaron el precio de las casas"
  Existente: "Los clientes piden el precio general"
  → MATCH (ambos precio general)
- Tu pregunta: "cuántas personas entran"
  Existente: "Los usuarios preguntan la capacidad"
  → MATCH (ambos capacidad)

Solo genera new_label si REALMENTE no hay nada parecido. Prefiere match
con algo existente 80% del tiempo cuando hay lista no vacía.

FORMATO DE SALIDA (JSON estricto, sin texto adicional):
{
  "questions": [
    {"category": "<key>", "match_id": "<id_hex8>"|null, "new_label": "<frase>"|null},
    ...
  ]
}

new_label debe empezar con "Los usuarios preguntaron...", "Los clientes
quieren saber si...", "Consultan por...", etc. Debe ser genérico (no
mencionar datos del cliente específico).

Si la conversación NO contiene ninguna pregunta genuina del cliente,
devuelve {"questions": []}.
"""


class Command(BaseCommand):
    help = 'Analiza conversaciones maduras y extrae preguntas frecuentes'

    def add_arguments(self, parser):
        parser.add_argument('--dry-run', action='store_true')
        parser.add_argument(
            '--limit', type=int, default=100,
            help='Máx sesiones a analizar por corrida (default 100)',
        )
        parser.add_argument(
            '--min-inactivity-hours', type=int, default=MIN_INACTIVITY_HOURS,
            help=f'Antigüedad mínima del último msg (default {MIN_INACTIVITY_HOURS}h)',
        )
        parser.add_argument(
            '--force-session',
            help='Analiza una sesión específica por UUID (ignora filtros)',
        )
        parser.add_argument(
            '--reset-all', action='store_true',
            help='Borra todos los FrequentQuestion y marcas de sesión analizada',
        )

    def handle(self, *args, **options):
        dry_run = options['dry_run']
        limit = options['limit']
        min_hours = options['min_inactivity_hours']
        force_session = options.get('force_session')

        config = ChatbotConfiguration.get_config()
        if not config.is_active:
            self.stdout.write('Chatbot inactivo, saltando análisis.')
            return

        if options['reset_all']:
            if not dry_run:
                FrequentQuestion.objects.all().delete()
                for s in ChatSession.objects.exclude(conversation_context={}):
                    ctx = s.conversation_context or {}
                    if 'fq_analyzed_at' in ctx:
                        ctx.pop('fq_analyzed_at', None)
                        s.conversation_context = ctx
                        s.save(update_fields=['conversation_context'])
                self.stdout.write('Reset completo.')
            else:
                self.stdout.write('[DRY] --reset-all descartaría FQs y marcas')
            return

        import openai
        from django.conf import settings
        client = openai.OpenAI(api_key=settings.OPENAI_API_KEY)

        # Query de sesiones candidatas
        if force_session:
            sessions = ChatSession.objects.filter(pk=force_session)
        else:
            cutoff = timezone.now() - timedelta(hours=min_hours)
            sessions = ChatSession.objects.filter(
                deleted=False,
                total_messages__gte=MIN_TOTAL_MESSAGES,
                last_message_at__lt=cutoff,
            ).exclude(
                conversation_context__fq_analyzed_at__isnull=False,
            ).order_by('last_message_at')[:limit]

        total = sessions.count()
        self.stdout.write(
            f'Sesiones candidatas (inactivas >{min_hours}h, no analizadas): {total}'
        )

        if total == 0:
            return

        processed = 0
        extracted_questions = 0
        errors = 0
        # Modelo específico para este command — mini es mucho mejor que nano
        # para clasificación con matching semántico. Corre 1 vez al día con
        # volumen bajo, costo sigue siendo ~$0.12/día (~$3.60/mes).
        classifier_model = 'gpt-4.1-mini'

        for session in sessions:
            transcript = self._build_transcript(session)
            if not transcript:
                self._mark_analyzed(session, skipped=True)
                processed += 1
                continue

            if dry_run:
                self.stdout.write(
                    f'\n[DRY] Sesión {str(session.id)[:8]} '
                    f'({session.wa_profile_name or session.wa_id}) — '
                    f'{session.total_messages} msgs'
                )
                self.stdout.write(f'  transcript preview: {transcript[:200]!r}')
                processed += 1
                continue

            try:
                existing_block = self._build_existing_block()
                user_prompt = (
                    f"TRANSCRIPT DE LA CONVERSACIÓN:\n{transcript}\n\n"
                    f"PREGUNTAS FRECUENTES EXISTENTES (para posible match):\n"
                    f"{existing_block}\n\n"
                    f"Identifica las preguntas del cliente y responde SOLO con el JSON."
                )
                resp = client.chat.completions.create(
                    model=classifier_model,
                    messages=[
                        {"role": "system", "content": CLASSIFIER_SYSTEM_PROMPT},
                        {"role": "user", "content": user_prompt},
                    ],
                    temperature=0,
                    max_tokens=600,
                    response_format={"type": "json_object"},
                )
                raw = resp.choices[0].message.content or '{}'
                data = json.loads(raw)
            except Exception as e:
                logger.error(f'Error analizando sesión {session.id}: {e}')
                errors += 1
                processed += 1
                continue

            questions = data.get('questions') or []
            for q in questions:
                if not isinstance(q, dict):
                    continue
                category = q.get('category') or 'other'
                if category not in CATEGORIES:
                    category = 'other'
                match_id = q.get('match_id')
                new_label = (q.get('new_label') or '').strip()
                self._apply_question(session, category, match_id, new_label)
                extracted_questions += 1

            self._mark_analyzed(session, skipped=False)
            processed += 1

            if processed % 10 == 0:
                self.stdout.write(
                    f'  progreso: {processed}/{total} — preguntas extraídas: {extracted_questions}'
                )

        # Actualizar checkpoint (solo informativo)
        if not dry_run:
            checkpoint = FrequentQuestionCheckpoint.get_singleton()
            checkpoint.total_messages_analyzed = (
                checkpoint.total_messages_analyzed + processed
            )
            checkpoint.save()

        self.stdout.write(self.style.SUCCESS(
            f'✓ Sesiones procesadas: {processed} | '
            f'Preguntas extraídas: {extracted_questions} | '
            f'Errores: {errors}'
        ))

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    def _build_transcript(self, session):
        """Arma un transcript legible de la sesión en orden cronológico."""
        msgs = ChatMessage.objects.filter(
            session=session, deleted=False,
        ).exclude(
            direction=ChatMessage.DirectionChoices.SYSTEM,
        ).order_by('created')[:MAX_TRANSCRIPT_MESSAGES]
        lines = []
        for m in msgs:
            role = {
                'inbound': 'Cliente',
                'outbound_ai': 'Valeria',
                'outbound_human': 'Admin',
            }.get(m.direction, 'Sistema')
            content = (m.content or '').strip()
            if not content:
                continue
            content = content[:MAX_MESSAGE_CHARS]
            lines.append(f'[{role}]: {content}')
        return '\n'.join(lines)

    def _build_existing_block(self):
        """Bloque con top 6 preguntas por categoría para match."""
        lines = []
        for cat_key in CATEGORIES.keys():
            if cat_key == 'other':
                continue
            top = FrequentQuestion.objects.filter(
                category=cat_key
            ).order_by('-count')[:6]
            items = list(top)
            if not items:
                continue
            lines.append(f'\n[{cat_key}]:')
            for fq in items:
                lines.append(
                    f'  id={fq.id.hex[:8]} (×{fq.count}): {fq.label}'
                )
        return '\n'.join(lines) if lines else '(sin preguntas previas)'

    def _apply_question(self, session, category, match_id, new_label):
        """Incrementa contador de pregunta existente o crea una nueva."""
        now = timezone.now()

        if match_id:
            prefix = str(match_id).replace('-', '').lower()[:8]
            if prefix:
                fq = FrequentQuestion.objects.filter(
                    category=category,
                ).extra(
                    where=["REPLACE(CAST(id AS CHAR), '-', '') LIKE %s"],
                    params=[f'{prefix}%'],
                ).first()
                if fq:
                    fq.count += 1
                    fq.last_seen_at = now
                    samples = list(fq.sample_messages or [])
                    if len(samples) < 5:
                        samples.append({
                            'session_id': str(session.id),
                            'wa_id': session.wa_id,
                            'created': now.isoformat(),
                        })
                        fq.sample_messages = samples
                    fq.save(update_fields=[
                        'count', 'last_seen_at', 'sample_messages', 'updated',
                    ])
                    return

        if not new_label:
            return

        FrequentQuestion.objects.create(
            category=category,
            category_label=CATEGORY_LABELS.get(category, category),
            label=new_label,
            count=1,
            last_seen_at=now,
            sample_messages=[{
                'session_id': str(session.id),
                'wa_id': session.wa_id,
                'created': now.isoformat(),
            }],
        )

    def _mark_analyzed(self, session, skipped=False):
        ctx = session.conversation_context or {}
        ctx['fq_analyzed_at'] = timezone.now().isoformat()
        if skipped:
            ctx['fq_skipped'] = True
        session.conversation_context = ctx
        session.save(update_fields=['conversation_context'])
