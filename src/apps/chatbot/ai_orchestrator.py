import json
import logging
import re
from datetime import date

from django.conf import settings
from django.utils import timezone

from .models import ChatSession, ChatMessage
from .tool_executor import ToolExecutor, TOOL_DEFINITIONS
from .channel_sender import get_sender
from .utils import calc_bed_capacity

logger = logging.getLogger(__name__)


TOOL_NAMES = (
    'notify_team', 'check_availability', 'check_calendar',
    'check_late_checkout', 'escalate_to_human', 'log_unanswered_question',
    'identify_client', 'schedule_visit', 'get_property_info',
    'check_reservations', 'get_pricing_table',
)

# Regex que captura tool calls en cualquier formato:
# tool_name(...), [tool_name(...)], *tool_name*, `tool_name`, - tool_name(...)
_TOOL_PATTERN = re.compile(
    r'[\[\(*`_\-•]*\s*('
    + '|'.join(TOOL_NAMES)
    + r')\s*[\]\)*`_]*'
    r'(?:\s*\(.*\))?'       # argumentos opcionales entre paréntesis
    r'[\]\)*`_]*',
    re.IGNORECASE,
)


def sanitize_response(text):
    """Limpia el texto de respuesta antes de enviar al cliente.
    Elimina llamadas a herramientas expuestas, errores internos y
    instrucciones IA que GPT haya incluido por error."""
    if not text:
        return text

    # Eliminar bloques completos [INSTRUCCIÓN ...] + todas sus líneas siguientes
    # hasta un doble salto de línea o fin de texto
    text = re.sub(
        r'\[INSTRUCCI[ÓO]N[^\]]*\].*?(?=\n\s*\n|\Z)',
        '',
        text,
        flags=re.IGNORECASE | re.DOTALL,
    )
    # Eliminar marcadores internos de herramientas
    text = re.sub(
        r'^---\s*SIN ALTERNATIVAS CERCANAS\s*---.*$',
        '',
        text,
        flags=re.MULTILINE,
    )
    # Eliminar líneas sueltas que son continuación de instrucciones IA
    # (por si GPT copió instrucciones sin el tag [INSTRUCCIÓN])
    text = re.sub(
        r'^(?:PROHIBIDO:|Tu respuesta DEBE|Solo agrega UNA|NOTA INTERNA:).*$',
        '',
        text,
        flags=re.MULTILINE | re.IGNORECASE,
    )

    lines = text.split('\n')
    cleaned = []

    for line in lines:
        stripped = line.strip()

        if not stripped:
            cleaned.append(line)
            continue

        # Eliminar líneas que son SOLO una llamada a herramienta
        # Captura: tool_name(...), [tool_name(...)], *tool_name*, `tool_name`
        cleaned_stripped = re.sub(r'[\[\]\(\)*`_\-•\s]', '', stripped)
        if cleaned_stripped and any(
            cleaned_stripped.startswith(t) or cleaned_stripped == t
            for t in TOOL_NAMES
        ):
            # Si la línea es básicamente solo el nombre de la herramienta + args
            if re.match(
                r'^[\[\(*`_\-•\s]*('
                + '|'.join(TOOL_NAMES)
                + r')[\s\]\)*`_]*(\(.*\))?\s*[\]\)*`_]*$',
                stripped,
                re.IGNORECASE,
            ):
                continue

        # Eliminar errores internos expuestos
        if stripped.startswith('Error al ejecutar') or stripped.startswith('Error:'):
            continue

        # Eliminar líneas con "⚠️ PRECIO BASE" (instrucción interna)
        if '⚠️ PRECIO BASE' in stripped:
            continue

        # Eliminar inline tool calls dentro de texto mixto
        # Ej: "el precio sería: *check_availability* ¿Te gustaría..."
        if any(t in stripped for t in TOOL_NAMES):
            line = _TOOL_PATTERN.sub('', line)
            # Limpiar puntuación huérfana (": ¿Te gustaría" → "¿Te gustaría")
            line = re.sub(r':\s*([¿¡])', r'\1', line)
            line = re.sub(r'\s{2,}', ' ', line)
            stripped = line.strip()
            if not stripped:
                continue

        cleaned.append(line)

    result = '\n'.join(cleaned).strip()

    # Limpiar dobles saltos de línea excesivos
    result = re.sub(r'\n{4,}', '\n\n\n', result)

    return result


class AIOrchestrator:
    """
    Orquestador de IA que gestiona las interacciones con OpenAI.
    - Construye mensajes con contexto
    - Ejecuta function calling
    - Maneja fallback de modelo
    - Guarda mensajes y métricas
    - Soporta WhatsApp, Instagram y Messenger
    """

    def __init__(self, config):
        self.config = config

    def process_message(self, session, inbound_message, send_wa=True):
        """Procesa un mensaje entrante y genera respuesta con IA.

        Args:
            session: ChatSession
            inbound_message: ChatMessage object o string con el contenido
            send_wa: Si True, envía respuesta por WhatsApp. False para modo test.

        Returns:
            str: Texto de la respuesta generada
        """
        try:
            response_text, tool_calls_data, model_used, tokens = self._call_ai(
                session, inbound_message, self.config.primary_model
            )
        except Exception as e:
            logger.error(f"Error con modelo primario: {e}")
            try:
                response_text, tool_calls_data, model_used, tokens = self._call_ai(
                    session, inbound_message, self.config.fallback_model
                )
            except Exception as e2:
                logger.error(f"Error con modelo fallback: {e2}")
                response_text = "¡Hola! 😊 En este momento no puedo procesar tu consulta. Nuestro equipo te atenderá en breve, o puedes contactarnos directamente: 📲 https://wa.me/51999902992"
                tool_calls_data = []
                model_used = 'error'
                tokens = 0

        # Guardia determinística: detectar intención de compra explícita en el mensaje
        # entrante y forzar notify_team(ready_to_book) si el modelo no lo hizo.
        self._force_ready_to_book_if_intent(session, inbound_message, tool_calls_data)

        # Sanitizar respuesta antes de enviar
        response_text = sanitize_response(response_text)

        # Guardia: eliminar precios fabricados si no se usó herramienta de precios
        response_text = self._guard_fabricated_prices(response_text, tool_calls_data)

        # Inyector: si el turno llamó check_availability pero la respuesta no incluye
        # la cotización formateada, inyectarla automáticamente.
        response_text = self._inject_missing_quote(response_text, tool_calls_data)

        # Enviar por el canal correspondiente
        wa_message_id = None
        if send_wa:
            sender = get_sender(session.channel)
            wa_message_id = sender.send_text_message(session.wa_id, response_text)

        # Detectar intención basada en herramientas usadas
        intent = self._detect_intent(tool_calls_data)

        # Quitar campos _prefixed antes de persistir (uso solo in-memory)
        tool_calls_for_db = [
            {k: v for k, v in tc.items() if not k.startswith('_')}
            for tc in tool_calls_data
        ]

        ChatMessage.objects.create(
            session=session,
            direction=ChatMessage.DirectionChoices.OUTBOUND_AI,
            message_type=ChatMessage.MessageTypeChoices.TEXT,
            content=response_text,
            wa_message_id=wa_message_id,
            ai_model=model_used,
            tokens_used=tokens,
            tool_calls=tool_calls_for_db,
            intent_detected=intent,
        )

        # Actualizar contadores
        session.total_messages += 1
        session.ai_messages += 1
        session.last_message_at = timezone.now()
        session.save(update_fields=[
            'total_messages', 'ai_messages', 'last_message_at'
        ])

        return response_text

    def _call_ai(self, session, inbound_message, model):
        """Realiza la llamada a OpenAI con function calling"""
        import openai

        client = openai.OpenAI(api_key=settings.OPENAI_API_KEY)

        messages = self._build_messages(session, inbound_message)

        response = client.chat.completions.create(
            model=model,
            messages=messages,
            tools=TOOL_DEFINITIONS,
            tool_choice="auto",
            temperature=self.config.temperature,
            max_tokens=self.config.max_tokens_per_response,
        )

        choice = response.choices[0]
        total_tokens = response.usage.total_tokens if response.usage else 0
        tool_calls_data = []

        # Si hay tool_calls, ejecutarlas y hacer segunda llamada
        if choice.message.tool_calls:
            messages.append(choice.message)

            executor = ToolExecutor(session)
            seen_calls = set()  # Dedup: evitar misma herramienta con mismos args

            for tool_call in choice.message.tool_calls:
                func_name = tool_call.function.name
                try:
                    arguments = json.loads(tool_call.function.arguments)
                except json.JSONDecodeError:
                    arguments = {}

                # Dedup: si ya ejecutamos esta misma herramienta con los mismos args, skip
                dedup_key = f"{func_name}:{json.dumps(arguments, sort_keys=True)}"
                if dedup_key in seen_calls:
                    logger.info(f"Herramienta duplicada, saltando: {func_name}({arguments})")
                    messages.append({
                        "role": "tool",
                        "tool_call_id": tool_call.id,
                        "content": "(Ya consultado arriba, ver resultado anterior)",
                    })
                    continue
                seen_calls.add(dedup_key)

                # Guardia: bloquear check_availability sin guests o con guests=1 sin confirmación
                if func_name == 'check_availability' and (
                    not arguments.get('guests') or arguments.get('guests') == 1
                ):
                    user_text = ' '.join(
                        m.get('content', '') for m in messages
                        if m.get('role') == 'user'
                    ).lower()
                    solo_indicators = [
                        r'\b1\s*persona', r'\buna\s*persona',
                        r'\bsol[oó]?\s*yo\b', r'\bsoy\s*sol[oa]\b',
                        r'\bvoy\s*sol[oa]\b', r'\biré?\s*sol[oa]\b',
                        r'\bsomos\s*1\b', r'\bsoy\s*1\b',
                    ]
                    if not any(re.search(p, user_text) for p in solo_indicators):
                        logger.warning(
                            f"Blocked check_availability(guests=1) — "
                            f"no explicit single-person intent"
                        )
                        messages.append({
                            "role": "tool",
                            "tool_call_id": tool_call.id,
                            "content": (
                                "⚠️ BLOQUEADO: No puedes cotizar para 1 persona. "
                                "El cliente NO confirmó que es solo 1 persona. "
                                "Pregúntale: '¿Cuántas personas serían para "
                                "darte el precio exacto?' ANTES de cotizar."
                            ),
                        })
                        tool_calls_data.append({
                            'name': func_name,
                            'arguments': arguments,
                            'result_preview': 'BLOCKED: guests=1 without confirmation',
                        })
                        continue

                logger.info(f"Ejecutando herramienta: {func_name}({arguments})")
                result = executor.execute(func_name, arguments)

                tool_calls_data.append({
                    'name': func_name,
                    'arguments': arguments,
                    'result_preview': str(result)[:200],
                    '_result_full': str(result),  # in-memory; no se persiste en BD
                })

                messages.append({
                    "role": "tool",
                    "tool_call_id": tool_call.id,
                    "content": str(result),
                })

            # Si se usó check_availability, recordar copiar cotización verbatim
            used_tools = [tc['name'] for tc in tool_calls_data]
            if 'check_availability' in used_tools or 'check_late_checkout' in used_tools:
                messages.append({
                    "role": "system",
                    "content": (
                        "RECORDATORIO CRÍTICO: La herramienta devolvió una cotización FORMATEADA con emojis, "
                        "asteriscos y saltos de línea. DEBES copiar y pegar ese texto EXACTAMENTE tal cual en tu "
                        "respuesta. NO resumas los precios en una oración. NO cambies el formato. "
                        "Después de la cotización, agrega solo una pregunta de cierre breve."
                    ),
                })

            # Segunda llamada con resultados de herramientas
            # Usar más tokens si hay cotización (la cotización formateada ocupa ~350 tokens)
            pricing_tools = {'check_availability', 'check_late_checkout', 'get_property_info'}
            has_pricing = bool(pricing_tools & set(used_tools))
            second_max_tokens = (
                max(self.config.max_tokens_per_response, 1200) if has_pricing
                else self.config.max_tokens_per_response
            )

            response2 = client.chat.completions.create(
                model=model,
                messages=messages,
                temperature=self.config.temperature,
                max_tokens=second_max_tokens,
            )

            response_text = response2.choices[0].message.content or ""
            total_tokens += response2.usage.total_tokens if response2.usage else 0
        else:
            response_text = choice.message.content or ""

            # Guardia: si el bot promete consultar/verificar/escalar pero no llamó herramientas,
            # forzar una segunda llamada para que ejecute la acción prometida
            check_patterns = [
                r'voy a (?:consultar|verificar|revisar|checar|buscar)',
                r'(?:déjame|dejame|permíteme|permiteme) (?:consultar|verificar|revisar|checar|buscar)',
                r'(?:por favor|espera|dame) un momento',
                r'voy a (?:cotizar|revisar la disponibilidad)',
            ]
            escalate_patterns = [
                r'voy a (?:escalar|contactar|avisar|coordinar|transferir|derivar)',
                r'(?:voy a|vamos a) (?:pedir|solicitar) que te (?:llamen|contacten)',
                r'(?:te|lo) (?:voy a|vamos a) (?:contactar|llamar)',
                r'en breve te (?:llamarán|contactarán|atenderán)',
                r'nuestro equipo te (?:contactará|llamará|atenderá)',
                r'lo escalo (?:de inmediato|al equipo|ahora)',
            ]
            promised_check = any(re.search(p, response_text, re.IGNORECASE) for p in check_patterns)
            promised_escalate = any(re.search(p, response_text, re.IGNORECASE) for p in escalate_patterns)

            if promised_check or promised_escalate:
                logger.warning(
                    f"Bot promised ({'escalate' if promised_escalate else 'check'}) "
                    f"but made no tool call: {response_text[:100]}"
                )
                messages.append(choice.message)
                if promised_escalate:
                    guard_msg = (
                        "⚠️ ERROR: Dijiste que ibas a escalar/contactar/avisar al equipo "
                        "pero NO llamaste ninguna herramienta. DEBES llamar "
                        "escalate_to_human() si el cliente necesita soporte humano, "
                        "o notify_team(reason='needs_human_assist', details='...') "
                        "o notify_team(reason='ready_to_book', details='...') si "
                        "está listo para reservar. NO respondas con texto — ejecuta "
                        "la acción que prometiste AHORA."
                    )
                else:
                    guard_msg = (
                        "⚠️ ERROR: Dijiste que ibas a consultar/verificar algo pero NO "
                        "llamaste ninguna herramienta. DEBES usar check_availability() "
                        "o la herramienta correspondiente AHORA. NO respondas con texto — "
                        "ejecuta la acción que prometiste."
                    )
                messages.append({
                    "role": "system",
                    "content": guard_msg,
                })
                retry = client.chat.completions.create(
                    model=model,
                    messages=messages,
                    tools=TOOL_DEFINITIONS,
                    tool_choice="auto",
                    temperature=self.config.temperature,
                    max_tokens=self.config.max_tokens_per_response,
                )
                retry_choice = retry.choices[0]
                total_tokens += retry.usage.total_tokens if retry.usage else 0

                if retry_choice.message.tool_calls:
                    # Ejecutar las herramientas del retry
                    messages.append(retry_choice.message)
                    executor = ToolExecutor(session)
                    for tool_call in retry_choice.message.tool_calls:
                        func_name = tool_call.function.name
                        try:
                            arguments = json.loads(tool_call.function.arguments)
                        except json.JSONDecodeError:
                            arguments = {}

                        # Aplicar misma guardia de guests
                        if func_name == 'check_availability' and (
                            not arguments.get('guests') or arguments.get('guests') == 1
                        ):
                            user_text = ' '.join(
                                m.get('content', '') for m in messages
                                if m.get('role') == 'user'
                            ).lower()
                            solo_indicators = [
                                r'\b1\s*persona', r'\buna\s*persona',
                                r'\bsol[oó]?\s*yo\b', r'\bsoy\s*sol[oa]\b',
                                r'\bvoy\s*sol[oa]\b', r'\biré?\s*sol[oa]\b',
                                r'\bsomos\s*1\b', r'\bsoy\s*1\b',
                            ]
                            if not any(re.search(p, user_text) for p in solo_indicators):
                                messages.append({
                                    "role": "tool",
                                    "tool_call_id": tool_call.id,
                                    "content": (
                                        "⚠️ BLOQUEADO: No puedes cotizar para 1 persona. "
                                        "Pregúntale cuántas personas serían."
                                    ),
                                })
                                tool_calls_data.append({
                                    'name': func_name, 'arguments': arguments,
                                    'result_preview': 'BLOCKED: guests missing/1',
                                })
                                continue

                        result = executor.execute(func_name, arguments)
                        tool_calls_data.append({
                            'name': func_name, 'arguments': arguments,
                            'result_preview': str(result)[:200],
                            '_result_full': str(result),
                        })
                        messages.append({
                            "role": "tool",
                            "tool_call_id": tool_call.id,
                            "content": str(result),
                        })

                    # Respuesta final con los resultados
                    used_tools = [tc['name'] for tc in tool_calls_data]
                    if 'check_availability' in used_tools or 'check_late_checkout' in used_tools:
                        messages.append({
                            "role": "system",
                            "content": (
                                "RECORDATORIO CRÍTICO: La herramienta devolvió una cotización FORMATEADA. "
                                "DEBES copiar y pegar ese texto EXACTAMENTE en tu respuesta."
                            ),
                        })

                    pricing_tools = {'check_availability', 'check_late_checkout', 'get_property_info'}
                    has_pricing = bool(pricing_tools & set(used_tools))
                    final_max = (
                        max(self.config.max_tokens_per_response, 1200) if has_pricing
                        else self.config.max_tokens_per_response
                    )
                    final_resp = client.chat.completions.create(
                        model=model,
                        messages=messages,
                        temperature=self.config.temperature,
                        max_tokens=final_max,
                    )
                    response_text = final_resp.choices[0].message.content or ""
                    total_tokens += final_resp.usage.total_tokens if final_resp.usage else 0
                else:
                    # Retry tampoco llamó herramientas, usar su texto
                    response_text = retry_choice.message.content or response_text

        return response_text, tool_calls_data, model, total_tokens

    def _build_messages(self, session, inbound_message):
        """Construye el array de mensajes para OpenAI.

        inbound_message puede ser un ChatMessage object o un string.
        """
        messages = [
            {"role": "system", "content": self._build_system_prompt(session)}
        ]

        # Determinar si es objeto ChatMessage o string
        is_obj = isinstance(inbound_message, ChatMessage)
        msg_content = inbound_message.content if is_obj else str(inbound_message)

        # Últimos 20 mensajes del historial
        recent_qs = ChatMessage.objects.filter(
            session=session, deleted=False
        )
        if is_obj:
            recent_qs = recent_qs.exclude(id=inbound_message.id)
        recent_messages = recent_qs.order_by('-created')[:20]

        # Revertir para orden cronológico
        for msg in reversed(list(recent_messages)):
            if msg.direction == ChatMessage.DirectionChoices.INBOUND:
                messages.append({"role": "user", "content": msg.content})
            elif msg.direction in [
                ChatMessage.DirectionChoices.OUTBOUND_AI,
                ChatMessage.DirectionChoices.OUTBOUND_HUMAN,
            ]:
                messages.append({"role": "assistant", "content": msg.content})

        # Mensaje actual
        messages.append({"role": "user", "content": msg_content})

        # Consolidar mensajes consecutivos del mismo usuario
        # (cuando el cliente envía ráfagas: "Hola" + "para el sábado" + "somos 10")
        consolidated = [messages[0]]  # system prompt
        for msg in messages[1:]:
            if (msg["role"] == "user"
                    and consolidated
                    and consolidated[-1]["role"] == "user"):
                consolidated[-1]["content"] += "\n" + msg["content"]
            else:
                consolidated.append(msg)

        return consolidated

    def _build_property_context(self):
        """Construye secciones dinámicas de propiedades desde la BD."""
        from apps.property.models import Property

        props = list(
            Property.objects.filter(deleted=False)
            .order_by('capacity_max')
            .values('name', 'capacity_max', 'dormitorios', 'banos',
                    'caracteristicas', 'detalle_dormitorios')
        )
        if not props:
            return {
                'INFO_CASAS': '(No hay propiedades registradas)',
                'CLASIFICACION_POR_TAMANO': '(No hay propiedades registradas)',
                'REGLA_CAPACIDADES': '(No hay propiedades registradas)',
            }

        # --- INFO_CASAS: specs de cada propiedad ---
        info_lines = []
        for p in props:
            name = p['name']
            cap = p['capacity_max'] or '?'
            dorms = p['dormitorios'] or '?'
            banos = p['banos'] or '?'
            chars = p.get('caracteristicas') or []
            chars_str = ''
            if isinstance(chars, list) and chars:
                chars_str = ' — ' + ', '.join(str(c) for c in chars[:6])
            line = f"- {name}: {dorms} hab/{banos} baños, ingreso hasta {cap} personas"
            # Solo resumen de camas (sin detalle por habitación — forzar get_property_info)
            detalle = p.get('detalle_dormitorios') or {}
            bed_cap, _ = calc_bed_capacity(detalle)
            if bed_cap:
                line += f", camas para {bed_cap} personas"
            if chars_str:
                line += chars_str
            info_lines.append(line)
        info_casas = '\n'.join(info_lines)

        # --- CLASIFICACION_POR_TAMANO: rangos automáticos ---
        sorted_props = sorted(props, key=lambda p: p['capacity_max'] or 0)
        ranges = []
        prev_max = 0
        for i, p in enumerate(sorted_props):
            cap = p['capacity_max'] or 0
            name = p['name']
            # Agrupar propiedades con misma capacidad
            same_cap = [x['name'] for x in sorted_props if x['capacity_max'] == cap]
            label = ' o '.join(same_cap)
            if i == 0:
                ranges.append(f"- 1-{cap} personas: PRIORIZAR {name} (la más ajustada y económica)")
            elif cap != prev_max:
                ranges.append(f"- {prev_max + 1}-{cap}: Recomendar {label}")
            prev_max = max(prev_max, cap)
        max_cap = sorted_props[-1]['capacity_max'] or 0
        biggest = sorted_props[-1]['name']
        ranges.append(f"- {max_cap}+: Recomendar {biggest} + otra casa combinada")
        clasificacion = '\n'.join(ranges)

        # --- REGLA_CAPACIDADES: resumen una línea ---
        caps = [f"{p['name']} = máx {p['capacity_max']}" for p in props if p['capacity_max']]
        regla = ', '.join(caps)

        return {
            'INFO_CASAS': info_casas,
            'CLASIFICACION_POR_TAMANO': clasificacion,
            'REGLA_CAPACIDADES': regla,
        }

    def _build_system_prompt(self, session):
        """Construye el system prompt dinámico con contexto de ventas"""
        base_prompt = self.config.system_prompt

        # Inyectar datos de propiedades desde la BD
        property_ctx = self._build_property_context()
        for key, value in property_ctx.items():
            base_prompt = base_prompt.replace('{' + key + '}', value)

        context_parts = [base_prompt]

        # Fecha actual con calendario de próximos 14 días
        from datetime import timedelta
        days_es = {
            0: 'lunes', 1: 'martes', 2: 'miércoles',
            3: 'jueves', 4: 'viernes', 5: 'sábado', 6: 'domingo',
        }
        today = date.today()
        day_name = days_es[today.weekday()]
        calendar_lines = []
        for i in range(14):
            d = today + timedelta(days=i)
            label = ""
            if i == 0:
                label = " (HOY)"
            elif i == 1:
                label = " (MAÑANA)"
            elif d.weekday() in (4, 5, 6) and i <= 7:
                label = " (ESTE FIN DE SEMANA)" if d.weekday() == 5 else ""
            calendar_lines.append(
                f"  {days_es[d.weekday()]} {d.strftime('%d/%m/%Y')} = {d.strftime('%Y-%m-%d')}{label}"
            )
        context_parts.append(
            f"\nHoy es {day_name} {today.strftime('%d/%m/%Y')}."
            f"\nCalendario próximos días (usa estas fechas EXACTAS):\n"
            + '\n'.join(calendar_lines)
            + "\n\n⚠️ RECORDATORIO: Cuando el cliente dice 'el 21 de marzo', check_in = 2026-03-21 (ESE MISMO DÍA, no el siguiente). NUNCA sumes 1 día a la fecha que dijo el cliente."
        )

        # Feriados próximos (Semana Santa, Fiestas Patrias, etc.)
        upcoming_holidays = self._get_upcoming_holidays(today)
        if upcoming_holidays:
            holiday_lines = []
            for h_date, h_name in upcoming_holidays:
                holiday_lines.append(
                    f"  {h_name}: {days_es[h_date.weekday()]} "
                    f"{h_date.strftime('%d/%m/%Y')} = {h_date.strftime('%Y-%m-%d')}"
                )
            context_parts.append(
                "\nFeriados y fechas especiales próximos:\n"
                + '\n'.join(holiday_lines)
            )

        # Disambiguation de meses
        context_parts.append(
            "\n⚠️ MESES: Si el cliente dice un mes diferente al actual "
            "(ej: 'agosto', 'julio', 'diciembre'), usa ESE mes exacto. "
            "NO lo confundas con el mes actual. Fechas de cualquier mes "
            "futuro son válidas."
        )

        # Disambiguation de fechas consecutivas
        context_parts.append(
            "\n⚠️ FECHAS CONSECUTIVAS: Si el cliente dice 'el 30 y 31', "
            "'15, 16 y 17', o similar, interpretar como rango de estadía: "
            "check_in = primer día, check_out = último día + 1. "
            "Ejemplo: '30 y 31 de marzo' → check_in=2026-03-30, check_out=2026-04-01 (2 noches). "
            "'15, 16 y 17 de abril' → check_in=2026-04-15, check_out=2026-04-18 (3 noches). "
            "NO interpretar como fechas sueltas separadas."
        )

        # Día sin mes — debe preguntar antes de ejecutar tools
        context_parts.append(
            "\n⚠️ DÍA SIN MES: Si el cliente da un día de la semana o un número sin mes "
            "(ej: 'sábado 16', 'el 5', 'el 20', 'este fin de semana'), "
            "PREGUNTA EXPLÍCITAMENTE el mes ANTES de ejecutar check_calendar o "
            "check_availability. NO asumas el mes actual ni el siguiente. "
            "Ejemplo: cliente dice 'sábado 16 a domingo 17' → responde "
            "'¿De qué mes serían esas fechas? Así te confirmo disponibilidad.'"
        )

        # Reglas de interpretación de mensajes ambiguos
        context_parts.append(
            "\n⚠️ NÚMEROS SUELTOS EN MENSAJES:"
            "\nSi el cliente envía una fecha junto con un número suelto (ej: 'fecha 13 de junio 10', "
            "'para el 5 de abril 8', '20 de mayo, 15'), ese número suelto SIEMPRE es la cantidad "
            "de PERSONAS, NO parte de la fecha. Pregunta para confirmar: '¿Son 10 personas?'"
            "\nSi el cliente da personas y un mes sin fecha exacta (ej: 'para 15 personas para abril', "
            "'somos 8 en mayo'), PREGUNTA la fecha exacta. NUNCA respondas sin cotizar — "
            "pide el día específico y luego usa check_availability()."
        )

        # Formato según canal
        if session.channel == 'instagram':
            context_parts.append(
                "\n⚠️ FORMATO INSTAGRAM: Estás en Instagram Direct. "
                "NO uses asteriscos (*bold*) — no funcionan en IG. "
                "Usa MAYÚSCULAS para énfasis en vez de asteriscos."
            )

        # Información del cliente vinculado
        if session.client:
            client = session.client
            referral = client.referral_code or 'No tiene'
            client_info = (
                f"\n\nCliente identificado: {client.first_name} {client.last_name or ''}"
                f"\n- Documento: {client.number_doc}"
                f"\n- Teléfono: {client.tel_number}"
                f"\n- Código de referido (clave WiFi): {referral}"
                f"\n- ID: {client.id}"
            )
            if hasattr(client, 'points_balance') and client.points_balance:
                points = float(client.points_balance)
                if points > 0:
                    client_info += f"\n- Puntos: {points:.0f} (menciónale que tiene puntos acumulados)"
            context_parts.append(client_info)

            # Reserva activa futura del cliente
            active_res = self._get_active_reservation(client, today)
            if active_res:
                res_info = (
                    f"\n\n🏠 RESERVA ACTIVA del cliente:"
                    f"\n- Propiedad: {active_res.property.name}"
                    f"\n- Check-in: {active_res.check_in_date.strftime('%d/%m/%Y')}"
                    f"\n- Check-out: {active_res.check_out_date.strftime('%d/%m/%Y')}"
                    f"\n- Huéspedes: {active_res.guests}"
                    f"\n- Estado: {active_res.status}"
                    f"\n- Pago completo: {'Sí' if active_res.full_payment else 'No'}"
                )
                if active_res.property.guest_instructions:
                    res_info += f"\n- Instrucciones de la casa:\n{active_res.property.guest_instructions}"
                if active_res.property.hora_ingreso:
                    res_info += f"\n- Hora de ingreso: {active_res.property.hora_ingreso.strftime('%H:%M')}"
                if active_res.property.hora_salida:
                    res_info += f"\n- Hora de salida: {active_res.property.hora_salida.strftime('%H:%M')}"
                if active_res.property.location:
                    res_info += f"\n- Ubicación: {active_res.property.location}"
                context_parts.append(res_info)
        else:
            context_parts.append(
                "\n\nCliente NO identificado aún. No necesitas identificarlo para cotizar. "
                "Solo pide DNI si el cliente quiere consultar reservas o puntos."
            )

        # Tipo de cambio actual
        from apps.property.pricing_models import ExchangeRate
        exchange_rate = ExchangeRate.get_current_rate()

        # Instrucciones técnicas (SIEMPRE presentes)
        context_parts.append(
            "\n\nREGLAS TÉCNICAS (obligatorias):"
            "\n- Responde SIEMPRE en español."
            "\n- NUNCA inventes precios ni disponibilidad. SIEMPRE usa las herramientas."
            "\n- Pregunta de disponibilidad sin personas → check_calendar. Con personas → check_availability."
            "\n- Cuando check_availability/check_late_checkout devuelvan cotización formateada, COPIA Y PEGA EXACTO carácter por carácter. PROHIBIDO resumir en prosa o cambiar formato."
            "\n- ⚠️ REGLA CRÍTICA DE FECHAS: Cada vez que el cliente mencione fechas (nuevas O las mismas de antes), "
            "DEBES llamar check_availability o check_calendar DE NUEVO. NUNCA reutilices resultados anteriores "
            "de la conversación. La disponibilidad cambia en tiempo real. PROHIBIDO decir 'según lo que consulté antes' "
            "o usar precios/disponibilidad de mensajes anteriores. SIEMPRE consulta fresco."
            "\n- Si el cliente cambia personas o fechas, llama check_availability de nuevo."
            "\n- PROHIBIDO mezclar resultados: si consultaste fecha A y luego fecha B, la respuesta de B debe "
            "ser SOLO con datos de la consulta B. Nunca combines datos de consultas diferentes."
            "\n- Para reservar: https://casaaustin.pe | Soporte: 📲 https://wa.me/51999902992 | 📞 +51 935 900 900"
            f"\n\n💱 TIPO DE CAMBIO: 1 USD = S/{exchange_rate} SOL"
            "\n- Si el cliente pregunta cuánto es en soles, multiplica el precio en USD por el tipo de cambio."
            "\n- Si el cliente pregunta cuánto es en dólares desde soles, divide entre el tipo de cambio."
            "\n- SIEMPRE muestra ambas monedas cuando hagas conversiones. Ejemplo: '$100 equivale a S/380 al tipo de cambio actual.'"
        )

        # === Reglas ANTI-ALUCINACIÓN (políticas no documentadas) ===
        context_parts.append(
            "\n\n🚫 POLÍTICAS QUE NO PUEDES INVENTAR:"
            "\nNunca afirmes reglas, políticas o beneficios que no vengan explícitamente de "
            "una herramienta o del contexto del sistema. En particular:"
            "\n- DESCUENTOS: NO inventes porcentajes de descuento (15%, 20%, etc.) ni "
            "promociones automáticas. Solo menciona descuentos validados por "
            "validate_discount_code() o promos ya comunicadas en el historial."
            "\n- REGLAS DE PRECIO: NUNCA afirmes 'el precio es el mismo para X personas' "
            "o 'las tarifas no cambian si son menos de X'. SIEMPRE re-ejecuta "
            "check_availability cuando cambie el número de personas. Los precios varían "
            "con los guests."
            "\n- POLÍTICAS DE CASA no listadas abajo (fumadores, menores de edad, "
            "horarios especiales) — si no está en el contexto del sistema, di: "
            "'Déjame confirmar esa política con el equipo' y escala con notify_team."
            "\n- INVITADOS ADICIONALES / VISITAS DE DÍA: usa los datos del tool "
            "check_availability (ya incluye la advertencia estándar). No inventes tarifas."
        )

        # === Políticas CONOCIDAS (sí puedes responder) ===
        context_parts.append(
            "\n\n📋 POLÍTICAS OFICIALES (puedes responder con seguridad):"

            "\n\n🎉 EVENTOS, MÚSICA, ORQUESTAS Y BULLA:"
            "\n- Casa Austin 1: NO se permite fiestas, bulla, orquestas ni música alta "
            "en absoluto. Es una casa familiar/tranquila. Si el cliente menciona "
            "fiesta/evento/orquesta/DJ para Casa Austin 1, SIEMPRE recomiéndale Casa "
            "Austin 2, 3 o 4."
            "\n- Casas Austin 2, 3 y 4: tienen ventanas y mamparas insuladas (acústicas). "
            "La reunión con música y bulla es TOLERABLE dentro de la casa SIEMPRE que "
            "las ventanas y mamparas estén cerradas. En el área de piscina (exterior) "
            "el volumen debe ser CONTROLADO. Se permite orquesta, DJ o cantante "
            "cumpliendo esto."
            "\n- Regla rápida para el cliente: 'Si buscas celebrar con música, te "
            "recomiendo Casa Austin 2, 3 o 4, que tienen ventanas insuladas. Puedes "
            "tener bulla adentro con ventanas cerradas; en la zona de piscina el "
            "volumen debe ser moderado. Casa Austin 1 no permite fiestas ni música alta.'"

            "\n\n🕐 FULL DAY / INGRESO ANTICIPADO:"
            "\n- El alquiler estándar es por NOCHE con check-in a las 3:00 PM."
            "\n- Ingresar antes (p.ej. full day temprano) SOLO es posible si la noche "
            "anterior NO fue alquilada. Depende exclusivamente de la disponibilidad "
            "de la noche anterior."
            "\n- Cuando pregunten por full day: explica esta regla y si puedes, usa "
            "check_calendar para verificar si la noche anterior está libre y poder "
            "confirmarlo. Ejemplo: 'El full day depende de si la noche anterior "
            "(fecha X) no está alquilada. Déjame verificar… sí/no está disponible.'"
            "\n- NO hay tarifa aparte de full day: es el mismo precio de la noche "
            "anterior, si está libre."

            "\n\n🐕 MASCOTAS:"
            "\n- Sí se permiten mascotas en todas las casas."
            "\n- REGLA CLAVE: cada mascota cuenta como UNA PERSONA en la reserva "
            "(afecta cotización). Ejemplo: 10 personas + 2 perros = cotizar con "
            "guests=12 en check_availability."
            "\n- Cuando el cliente mencione mascotas, SIEMPRE pregunta la cantidad "
            "y súmala al número de personas antes de cotizar."
            "\n- Responde al cliente: 'Sí, aceptamos mascotas 🐕. Solo ten en cuenta "
            "que cada mascota cuenta como una persona adicional en la reserva. "
            "¿Cuántas mascotas llevarías?'"

            "\n\n🍽️ SERVICIO DE ALIMENTOS / CHEF:"
            "\n- NO ofrecemos servicio de alimentos, chef, desayuno, almuerzo ni cena."
            "\n- Las casas tienen cocina equipada para que los huéspedes preparen "
            "sus propios alimentos."
            "\n- Si el cliente pregunta, responde: 'No ofrecemos servicio de "
            "alimentos ni chef. Las casas tienen cocina completa equipada para que "
            "puedas preparar tus propias comidas. Si necesitas, puedes contratar "
            "un proveedor externo por tu cuenta.'"
        )

        # === BLOQUE VENTA 1: CIERRE PERSUASIVO POST-COTIZACIÓN ===
        # Analisis de 179 conversaciones: 56% quedan frías después de cotizar.
        # Problema: la cotización termina en "¿Te animas?" — demasiado pasivo.
        context_parts.append(
            "\n\n🎯 CIERRE PERSUASIVO DESPUÉS DE COTIZAR:"
            "\nCuando uses check_availability y muestres la cotización, NUNCA cierres con "
            "un '¿Te animas a reservar? 😊' solitario. Es pasivo y los clientes se enfrían. "
            "DESPUÉS del bloque formateado de precios, agrega UN cierre persuasivo con los "
            "siguientes ingredientes (mezcla variada, no uses siempre los mismos):"

            "\n\n1️⃣ GANCHO SEGÚN CONTEXTO DEL CLIENTE:"
            "\n   Si en el historial mencionó...  usa el gancho correspondiente:"
            "\n   - 'cumpleaños/celebración/reunión' → 'Ideal para tu celebración 🎉'"
            "\n   - 'familia/descansar/escapada' → 'Perfecto para desconectarse sin las prisas '"
            "   'de Lima 🌊'"
            "\n   - 'amigos/grupo/compañeros' → 'El espacio ideal para juntar al grupo 🏖️'"
            "\n   - 'niños/hijos/familia' → 'Piscina segura y áreas amplias — los niños no '"
            "   'quieren volverse 👧'"
            "\n   - 'aniversario/pareja/romántico' → 'Un escenario privilegiado para tu '"
            "   'ocasión especial 💕'"

            "\n\n2️⃣ CTA ACCIÓN CON BAJA FRICCIÓN (reemplaza ¿te animas?):"
            "\n   En vez de preguntar pasivo, OFRECE una acción concreta:"
            "\n   - '¿Te paso el link para asegurar la fecha hoy con el 50%? Te toma 2 minutos.'"
            "\n   - '¿Quieres que te envíe el link de pago y separamos esa fecha ahora?'"
            "\n   - '¿Prefieres reservar directo en web o que mi equipo te guíe paso a paso?'"
            "\n   - Si hay varias casas en la cotización: '¿Cuál casa te convence más — "
            "{CA2 o CA3}? Te paso el link con esa seleccionada.'"

            "\n\n⚠️ NO calcules ni menciones 'precio por persona' / 'precio dividido' — "
            "mantén el precio tal cual lo entregó la cotización formateada."
            "\n⚠️ NO satures — 2-3 líneas máximo después de la cotización."
            "\n⚠️ NO inventes datos (no digas 'ya hay N reservas para esa fecha' si no es "
            "verdad). SÍ puedes mencionar: 'los fines de semana se llenan primero' o "
            "'es una de nuestras fechas más pedidas' si son fines de semana o feriados."
        )

        # === BLOQUE VENTA 2: RECOTIZACIÓN = BUYING SIGNAL FUERTE ===
        # Analisis: 33% de clientes recotizan (cambian fechas/personas/casas).
        # Es señal fuerte de compra que el bot hoy ignora.
        recent_quotes = ChatMessage.objects.filter(
            session=session,
            deleted=False,
            direction=ChatMessage.DirectionChoices.OUTBOUND_AI,
            intent_detected='availability_check',
        ).count()
        if recent_quotes >= 2:
            context_parts.append(
                "\n\n🔥 BUYING SIGNAL DETECTADO — CLIENTE EVALUANDO OPCIONES:"
                f"\nEste cliente YA pidió {recent_quotes} cotizaciones en esta conversación "
                "(cambió fechas, personas o casas). ESTO ES SEÑAL FUERTE DE COMPRA. "
                "No lo trates como lead frío ni lo dejes evaluando solo. Haz lo siguiente:"
                "\n- Reconoce su evaluación sin juzgarlo: 'Veo que estás comparando "
                "opciones — buena decisión, es importante elegir bien 👍'"
                "\n- Pregunta su CRITERIO decisor: '¿Qué es lo que más te importa para "
                "tu grupo: el precio, el espacio, o la ubicación?' — así afinas la "
                "recomendación."
                "\n- Si muestra dudas entre casas, PROPÓN una: 'Para lo que me cuentas, "
                "te recomiendo [Casa X] porque [razón concreta basada en su contexto]'."
                "\n- Ofrece PONER EN CONTACTO con humano (baja fricción de decisión):"
                "\n  'Si quieres, mi equipo te puede llamar en 2 minutos para resolver "
                "todas tus dudas de una vez. ¿Te sirve?' → "
                "usa notify_team(reason='needs_human_assist', details='cliente evaluando "
                "varias opciones, pedir llamada')."
                "\n- Pregunta el bloqueo directo: '¿Hay algo específico que te frena "
                "para cerrar hoy? Te ayudo a resolverlo.'"
            )

        # === BLOQUE VENTA 3: RESCATE ANTE OBJECIÓN DE TIEMPO ===
        # Analisis: solo 2% objetan explícitamente con "lo voy a pensar", pero el
        # patrón es claro y el bot responde pasivo "perfecto, aquí estoy".
        context_parts.append(
            "\n\n💬 RESCATE ANTE 'LO VOY A PENSAR' / 'LUEGO TE AVISO':"
            "\nCuando el cliente diga cualquier variante de:"
            "\n- 'lo voy a pensar', 'déjame pensarlo'"
            "\n- 'luego te aviso', 'después te confirmo', 'ahora le confirmo'"
            "\n- 'estamos analizando', 'estamos viendo'"
            "\n- 'lo consulto con [pareja/familia/grupo]'"
            "\n- 'voy a verlo', 'te aviso mañana'"
            "\n\n⛔ NO respondas 'Perfecto, aquí estoy cuando decidas'. Eso es dejar "
            "ir al cliente. Intenta UNA vez más con valor agregado:"
            "\n\n'Claro, tómate el tiempo que necesites. Mientras decides, ¿te sirve si:'"
            "\n- 'Te paso fotos específicas de [la casa que cotizamos]'"
            "\n- 'Mi equipo te llama para resolver todas las dudas en 2 minutos (tú eliges "
            "la hora)'"
            "\n- 'Te guardo la fecha tentativa por 24h mientras decides (si la casa sigue "
            "libre, la aseguro sin pago aún)'"
            "\n\nY si el cliente AÚN rechaza la ayuda, CAPTURA info de seguimiento:"
            "\n'Perfecto. ¿Cuándo te acomoda que te escriba de vuelta para saber tu "
            "decisión: mañana en la mañana, o el [día]?'"
            "\n\n⚠️ NUNCA fuerces. Si el cliente responde 'no gracias', respeta y cierra "
            "amigablemente: '¡Todo bien! Cualquier cosa me escribes 🏖️'."
        )

        # === Detección de reinicio de conversación post-cotización ===
        if session.quoted_at:
            context_parts.append(
                "\n\n🔁 CONVERSACIÓN EXISTENTE CON COTIZACIÓN PREVIA:"
                "\nEste cliente YA recibió una cotización antes. Si el mensaje actual parece "
                "un saludo genérico o reinicio ('Hola', 'Me interesa conocer más…', "
                "'Quiero más información'), NO reinicies el funnel desde cero. En su lugar:"
                "\n- Retoma el contexto: '¡Hola de nuevo! Retomando tu consulta anterior, "
                "¿seguimos con la reserva o prefieres revisar otras fechas?'"
                "\n- Si ya hubo intención de compra o link enviado, pregunta directamente: "
                "'¿Necesitas ayuda para completar el pago o tienes alguna duda?'"
                "\n- NO pidas fechas ni personas otra vez si ya están en el historial; úsalas."
            )

        # === INSTRUCCIONES DINÁMICAS según estado de la conversación ===
        context_parts.append(self._build_sales_context(session, today))

        return '\n'.join(context_parts)

    def _get_active_reservation(self, client, today):
        """Busca la reserva activa más próxima del cliente (en curso o futura)"""
        from apps.reservation.models import Reservation

        return Reservation.objects.filter(
            client=client,
            check_out_date__gte=today,
            status='approved',
            deleted=False,
        ).order_by('check_in_date').first()

    def _build_in_stay_context(self, res):
        """Contexto para huésped EN CURSO (check_in <= hoy <= check_out)"""
        return (
            "\n\nETAPA: SOPORTE DURANTE ESTADÍA 🏠"
            f"\n- El cliente está AHORA MISMO alojado en {res.property.name}."
            "\n- Modo: SOPORTE (no vender). Ayúdale con lo que necesite de la casa."
            "\n- Si tiene un PROBLEMA (algo roto, falta algo, emergencia), usa notify_team(reason='needs_human_assist', details='[describe el problema]') para alertar al equipo."
            "\n- Comparte las instrucciones de la casa si pregunta (WiFi, dirección, estacionamiento, etc.)."
            "\n- Si pregunta por disponibilidad para OTRAS fechas, atiende con check_availability normalmente (modo venta para nueva reserva)."
            "\n- Tono: servicial, cálido. 'Estamos para ti durante toda tu estadía.'"
        )

    def _build_pre_checkin_context(self, res, days_until):
        """Contexto PRE CHECK-IN (≤7 días para check_in)"""
        return (
            "\n\nETAPA: PRE CHECK-IN 📋"
            f"\n- El cliente tiene reserva en {res.property.name} en {days_until} día{'s' if days_until != 1 else ''}."
            "\n- Modo: PREPARACIÓN. Comparte proactivamente:"
            "\n  • Dirección e instrucciones de llegada"
            "\n  • Hora de check-in y check-out"
            "\n  • Qué traer / qué NO traer"
            "\n  • Info de WiFi, estacionamiento, etc."
            + (
                "\n- ⚠️ PAGO PENDIENTE: El cliente NO ha completado el pago al 100%. "
                "Recuérdale amablemente: 'Para activar la llave digital necesitas completar el pago. "
                "¿Necesitas ayuda con eso?'"
                if not res.full_payment else ""
            )
            + "\n- Si pregunta por OTRAS fechas, atiende con check_availability normalmente."
            "\n- Tono: entusiasta. '¡Ya falta poco para tu escapada! 🏖️'"
        )

    def _build_pending_payment_context(self, res):
        """Contexto PAGO PENDIENTE (>7 días, sin pago 100%)"""
        return (
            "\n\nETAPA: RECORDATORIO DE PAGO 💳"
            f"\n- El cliente tiene reserva en {res.property.name} pero NO ha completado el pago."
            "\n- Recuérdale amablemente el saldo pendiente."
            "\n- Menciona: 'La llave digital se activa al completar el pago al 100%.'"
            "\n- Opciones de pago: tarjeta o transferencia en casaaustin.pe"
            "\n- Si pregunta por OTRAS fechas, atiende con check_availability normalmente."
            "\n- Tono: amigable pero claro sobre la importancia de completar el pago."
        )

    def _build_sales_context(self, session, today):
        """Genera instrucciones de venta dinámicas según el estado de la conversación"""
        from datetime import timedelta

        parts = []

        # === DETECTAR RESERVA ACTIVA (post-venta) ===
        if session.client:
            active_res = self._get_active_reservation(session.client, today)
            if active_res:
                days_until = (active_res.check_in_date - today).days

                if days_until <= 0:
                    # EN CURSO: check_in ya pasó o es hoy, check_out >= hoy
                    parts.append(self._build_in_stay_context(active_res))
                    return ''.join(parts)
                elif days_until <= 7:
                    # PRE CHECK-IN: ≤7 días
                    parts.append(self._build_pre_checkin_context(active_res, days_until))
                    return ''.join(parts)
                elif not active_res.full_payment:
                    # PAGO PENDIENTE: >7 días, sin pago 100%
                    parts.append(self._build_pending_payment_context(active_res))
                    return ''.join(parts)
                # CONFIRMADA LEJANA: >7 días, pagada → flujo normal de ventas

        # Detectar etapa del embudo
        has_quote = session.quoted_at is not None
        msg_count = session.total_messages
        is_new = msg_count <= 2

        if is_new:
            # Primer contacto — modo bienvenida
            parts.append(
                "\n\nETAPA: PRIMER CONTACTO"
                "\n- Dale la bienvenida cálida y pregunta por sus fechas."
                "\n- Si el cliente ya mencionó fechas, usa check_calendar para mostrar disponibilidad inmediata."
                "\n- Si dio fechas + personas, usa check_availability directo para cotizar."
            )
        elif not has_quote:
            # Verificar si ya hubo intentos de check_availability (fechas dadas pero sin disponibilidad)
            had_availability_check = ChatMessage.objects.filter(
                session=session,
                deleted=False,
                intent_detected='availability_check',
            ).exists()

            if had_availability_check:
                # Cliente YA dio fechas pero no había disponibilidad
                parts.append(
                    "\n\nETAPA: SIN COTIZACIÓN — FECHAS YA PROPORCIONADAS (sin disponibilidad previa)"
                    "\n- El cliente YA dio fechas y personas antes, pero no había disponibilidad."
                    "\n- NO le pidas fechas ni personas de nuevo."
                    "\n- Si el cliente dice 'ya te dije' o similar, RECONÓCELO y usa los datos del historial."
                    "\n- Si el cliente da nuevas fechas → LLAMA check_availability directo (si falta checkout, asume 1 noche)."
                    "\n- Si el cliente da nuevas fechas + personas → LLAMA check_availability INMEDIATO. NO preguntes más."
                    "\n- ⚠️ NUNCA respondas sobre disponibilidad sin llamar la herramienta. Aunque recuerdes "
                    "resultados anteriores, DEBES volver a consultar porque la disponibilidad cambia en tiempo real."
                    "\n- Ofrece alternativas proactivamente: otros fines de semana, fechas entre semana, otro mes."
                    "\n- Si no avanza: 'Entiendo que esas fechas estaban ocupadas. ¿Puedo buscar para otras fechas?'"
                )
            else:
                # Conversación activa sin cotización y sin intentos previos
                parts.append(
                    "\n\nETAPA: SIN COTIZACIÓN AÚN"
                    "\n- Prioridad #1: Conseguir fechas y COTIZAR."
                    "\n- Si el cliente da fechas sin personas → check_calendar (disponibilidad) → pregunta personas → check_availability (precios)."
                    "\n- Si el cliente da fechas + personas → check_availability directo."
                    "\n- Si el cliente ya dio fecha y personas en mensajes anteriores → USA check_availability AHORA. No preguntes más."
                    "\n- Si solo tienes check-in sin check-out, asume 1 noche y cotiza."
                    "\n- NUNCA respondas '¿quieres reservar?' o '¿te ayudo a elegir?' sin haber mostrado PRECIOS primero."
                    "\n- Si ya llevas varios mensajes sin fechas, pregunta directamente:"
                    '\n  "¿Ya tienes fechas en mente? Te cotizo al instante 🏖️"'
                )
        else:
            # Ya tiene cotización — modo cierre
            parts.append(
                "\n\nETAPA: POST-COTIZACIÓN (ya recibió precios)"
                "\n- Prioridad #1: Guiar al cliente a reservar en casaaustin.pe"
                "\n- Recuérdale: 'Solo necesitas el 50% de adelanto para separar tu fecha'"
                "\n- Si tiene dudas, resuélvelas rápido y vuelve al cierre."
                "\n- Si dice que quiere reservar, usa notify_team(ready_to_book) Y guíalo a casaaustin.pe"
                "\n- ⚠️ Si el cliente pregunta por NUEVAS FECHAS o DIFERENTES fechas (incluyendo 'hoy', 'mañana', "
                "otra fecha distinta a la cotizada), DEBES llamar check_availability o check_calendar DE NUEVO. "
                "NUNCA asumas disponibilidad ni reutilices la cotización anterior. La disponibilidad cambia en tiempo real."
            )

        # Detectar urgencia por fechas cercanas (si hay contexto de fechas)
        # Revisamos últimas herramientas ejecutadas para extraer fechas cotizadas
        last_check = ChatMessage.objects.filter(
            session=session,
            deleted=False,
            direction=ChatMessage.DirectionChoices.OUTBOUND_AI,
            intent_detected='availability_check',
        ).order_by('-created').first()

        if last_check and last_check.tool_calls:
            for tc in last_check.tool_calls:
                if tc.get('name') == 'check_availability':
                    args = tc.get('arguments', {})
                    check_in_str = args.get('check_in', '')
                    try:
                        from datetime import datetime as dt
                        check_in_date = dt.strptime(check_in_str, '%Y-%m-%d').date()
                        days_until = (check_in_date - today).days
                        if 0 < days_until <= 3:
                            parts.append(
                                "\n\n⚡ URGENCIA ALTA: El check-in es en menos de 3 días."
                                "\n- Transmite urgencia genuina: 'Tu fecha es muy pronto, "
                                "te recomiendo reservar hoy para asegurar disponibilidad'"
                                "\n- Menciona que alguien más podría reservar antes."
                            )
                        elif 0 < days_until <= 7:
                            parts.append(
                                "\n\n⏰ URGENCIA MEDIA: El check-in es esta semana/próxima semana."
                                "\n- Menciona que fines de semana se llenan rápido."
                                "\n- Sugiere reservar pronto para no perder la fecha."
                            )
                    except (ValueError, TypeError):
                        pass
                    break  # Solo necesitamos la última cotización

        # Señal de fin de semana actual
        days_to_saturday = (5 - today.weekday()) % 7
        if days_to_saturday <= 2:
            parts.append(
                "\n\n📅 CONTEXTO: Este fin de semana está muy cerca."
                "\n- Si el cliente pregunta por 'este finde/sábado/fin de semana', "
                "transmite que la disponibilidad es limitada."
            )

        # Si la conversación lleva muchos mensajes sin cierre
        if has_quote and msg_count >= 8:
            parts.append(
                "\n\n🎯 CONVERSACIÓN LARGA: Ya llevas varios mensajes."
                "\n- Sé más directo con el cierre."
                "\n- Pregunta: '¿Te gustaría que el equipo te ayude a completar la reserva?'"
                "\n- Si no avanza, ofrece resolver su última duda y cierra."
            )

        return ''.join(parts)

    @staticmethod
    def _get_min_price_usd():
        """Obtiene la menor tarifa base en USD de PropertyPricing."""
        from apps.property.pricing_models import PropertyPricing
        try:
            from django.db.models import Min
            result = PropertyPricing.objects.aggregate(
                min_price=Min('weekday_low_season_usd')
            )
            price = result.get('min_price')
            if price and price > 0:
                return int(price)
        except Exception:
            pass
        return 65  # fallback

    @staticmethod
    def _extract_user_text(inbound_message):
        if isinstance(inbound_message, ChatMessage):
            return (inbound_message.content or '').strip()
        return str(inbound_message or '').strip()

    # Patrones de intención de compra explícita. Si el cliente escribe una de
    # estas frases, forzamos notify_team(ready_to_book) aunque el modelo no lo
    # haya hecho. Visto en producción: David Tafur ("aceptan tarjeta"),
    # Ignacio Vidal ("Quiero pagar") — 0 notificaciones automáticas en 21 conv.
    READY_TO_BOOK_PATTERNS = [
        r'\bquiero\s+(?:pagar|reservar|confirmar|separar)\b',
        r'\bdeseo\s+(?:pagar|reservar|confirmar|alquilar)\b',
        r'\bme\s+anim[oa]\b',
        r'\baceptan?\s+tarjeta\b',
        r'\bc[oó]mo\s+(?:pago|reservo|hago\s+el\s+pago|hago\s+la\s+reserva)\b',
        r'\benv[ií]a(?:me)?\s+(?:el\s+)?(?:link|enlace)',
        r'\b(?:dame|p[aá]same|manda(?:me)?)\s+(?:el\s+)?(?:link|enlace)\b',
        r'\blist[oa]\s+(?:para\s+)?(?:pagar|reservar)\b',
        r'\bvamos\s+a\s+reservar\b',
        r'\bya\s+voy\s+a\s+(?:pagar|reservar)\b',
        r'\bnecesito\s+ayuda\s+(?:con|para)\s+(?:el\s+)?pago\b',
    ]

    def _force_ready_to_book_if_intent(self, session, inbound_message, tool_calls_data):
        """Si el mensaje entrante contiene intención de compra explícita y el
        modelo NO llamó notify_team(ready_to_book) ni escalate_to_human,
        disparamos notify_team directamente para alertar al equipo."""
        user_text = self._extract_user_text(inbound_message).lower()
        if not user_text:
            return

        if not any(re.search(p, user_text) for p in self.READY_TO_BOOK_PATTERNS):
            return

        # ¿El modelo ya alertó?
        already_alerted = False
        for tc in tool_calls_data or []:
            name = tc.get('name')
            args = tc.get('arguments') or {}
            if name == 'escalate_to_human':
                already_alerted = True
                break
            if name == 'notify_team' and args.get('reason') in (
                'ready_to_book', 'needs_human_assist'
            ):
                already_alerted = True
                break
        if already_alerted:
            return

        logger.warning(
            f"ready_to_book intent detected in inbound but model did not notify_team. "
            f"Forcing notify_team for session {session.id}. Text: {user_text[:100]}"
        )
        try:
            executor = ToolExecutor(session)
            result = executor.execute('notify_team', {
                'reason': 'ready_to_book',
                'details': f"Intención de compra detectada automáticamente: \"{user_text[:200]}\"",
            })
            tool_calls_data.append({
                'name': 'notify_team',
                'arguments': {'reason': 'ready_to_book', 'auto_triggered': True},
                'result_preview': str(result)[:200],
            })
        except Exception as e:
            logger.error(f"Error forcing notify_team: {e}", exc_info=True)

    @staticmethod
    def _inject_missing_quote(text, tool_calls_data):
        """Si el turno ejecutó check_availability y la respuesta del modelo no
        contiene el bloque formateado de cotización, lo inyecta directamente
        desde el result_preview.

        Visto en producción: Rosamia — el bot llamó check_availability y
        respondió solo "¿Te animas a reservar? 😊" sin pegar la cotización.
        """
        if not text:
            text = ''

        # Marcadores del bloque de cotización (ver _check_availability en tool_executor)
        has_price_block = (
            ('PRECIO PARA' in text and 'PERSONA' in text)
            or 'Late checkout disponible' in text
        )
        if has_price_block:
            return text

        # Buscar el último result completo de check_availability / check_late_checkout
        quote_text = None
        for tc in reversed(tool_calls_data or []):
            name = tc.get('name')
            if name not in ('check_availability', 'check_late_checkout'):
                continue
            full = tc.get('_result_full') or ''
            if not full or 'BLOCKED' in full:
                continue
            # Solo inyectamos si el result parece realmente una cotización formateada
            if 'PRECIO PARA' in full or 'Late checkout disponible' in full:
                quote_text = full.strip()
                break

        if not quote_text:
            return text

        logger.warning(
            "Model did not echo quote after check_availability — "
            "injecting formatted quote automatically"
        )

        # Si el texto del modelo es muy corto (tipo "¿Te animas?"), lo usamos
        # como pregunta de cierre después de la cotización. Si es largo,
        # anteponemos la cotización y mantenemos el texto.
        stripped = text.strip()
        if len(stripped) < 80:
            closer = stripped or "¿Te animas a reservar? 😊"
            return f"{quote_text}\n\n{closer}"
        return f"{quote_text}\n\n{stripped}"

    @staticmethod
    def _extract_numbers_from_tool_outputs(tool_calls_data):
        """Extrae todos los números monetarios de los outputs de tools ejecutadas
        en el turno actual. Se usa para whitelistar precios legítimos y evitar
        falsos positivos del guard (p.ej. sumas de cotización + late checkout)."""
        whitelist = set()
        num_re = re.compile(r'\d[\d,]*(?:\.\d+)?')
        for tc in tool_calls_data or []:
            full = tc.get('_result_full') or tc.get('result_preview') or ''
            for match in num_re.finditer(full):
                raw = match.group(0)
                # Normalizar (quitar comas, dejar punto decimal)
                try:
                    val = float(raw.replace(',', ''))
                except ValueError:
                    continue
                if val >= 10:  # ignora dígitos pequeños (1, 2, 3 personas, etc.)
                    whitelist.add(round(val, 2))
                    # También sin decimales para que $370.00 matchee $370
                    whitelist.add(round(val))
        return whitelist

    @staticmethod
    def _price_in_whitelist(price_str, whitelist):
        """Devuelve True si el precio string está en la whitelist (con tolerancia
        a decimales y sumas aproximadas)."""
        raw = re.sub(r'[^\d.,]', '', price_str).replace(',', '')
        try:
            val = float(raw)
        except ValueError:
            return False
        if round(val, 2) in whitelist or round(val) in whitelist:
            return True
        # Tolerancia: sumas de 2 elementos de la whitelist (ej. noche + late checkout)
        vals = list(whitelist)
        for i, a in enumerate(vals):
            for b in vals[i:]:
                if abs((a + b) - val) < 1.0:
                    return True
        return False

    @staticmethod
    def _guard_fabricated_prices(text, tool_calls_data):
        """Elimina precios fabricados cuando no se usó herramienta de precios.

        El modelo a veces inventa precios sin llamar check_availability.
        Esta guardia elimina esos precios para evitar desinformación.

        Excepción: si se usó una herramienta de precios en este turno, los
        números que correspondan a outputs reales (o sumas razonables de ellos)
        son válidos y NO se tachan. Esto evita el falso positivo donde el bot
        suma cotización + late checkout (aritmética legítima).
        """
        import random

        pricing_tools = {'check_availability', 'check_late_checkout', 'get_pricing_table'}
        used_pricing = any(tc.get('name') in pricing_tools for tc in tool_calls_data or [])

        # Detectar montos en $ o S/ (con o sin comas/puntos de miles, mínimo 2 dígitos)
        price_re = re.compile(r'(?:\$|S/\.?)\s*\d[\d,]*\d(?:\.\d+)?')
        if not price_re.search(text):
            return text

        # Si se usó herramienta de precios, whitelistar los números del output y
        # solo tachar precios que NO estén en esa lista (ni sumas razonables).
        if used_pricing:
            whitelist = AIOrchestrator._extract_numbers_from_tool_outputs(tool_calls_data)
            if whitelist:
                bad_prices = [
                    m.group(0) for m in price_re.finditer(text)
                    if not AIOrchestrator._price_in_whitelist(m.group(0), whitelist)
                ]
                if not bad_prices:
                    # Todos los precios son legítimos → no tocar el texto
                    return text
                logger.warning(
                    f"Partial price guard: found {len(bad_prices)} prices "
                    f"outside tool-output whitelist: {bad_prices[:3]}"
                )
                # Tachar solo líneas con precios no whitelistados
                lines = text.split('\n')
                cleaned_lines = []
                for line in lines:
                    bad_in_line = any(
                        not AIOrchestrator._price_in_whitelist(m.group(0), whitelist)
                        for m in price_re.finditer(line)
                    )
                    has_price = bool(price_re.search(line))
                    if has_price and bad_in_line:
                        continue  # Drop la línea
                    cleaned_lines.append(line)
                text = '\n'.join(cleaned_lines).strip()
                text = re.sub(r'\n{3,}', '\n\n', text)
                return text or ""
            # Si se usó tool pero no extrajimos nada, ser conservador y no tachar
            return text

        logger.warning("Fabricated prices detected — stripping (no pricing tool used)")

        min_price = AIOrchestrator._get_min_price_usd()

        # Eliminar líneas que contienen precios fabricados
        lines = text.split('\n')
        cleaned = [line for line in lines if not price_re.search(line)]
        text = '\n'.join(cleaned).strip()
        text = re.sub(r'\n{3,}', '\n\n', text)

        # Variaciones de fallback cuando casi todo el mensaje eran precios
        fallback_variations = [
            (
                f"Nuestros precios arrancan desde ${min_price}/noche para 2 personas "
                f"(toda la casa) y varían según la fecha, temporada y cantidad de personas 😊 "
                f"¿Para qué fechas y cuántas personas necesitas? Te doy el precio exacto al instante 🏖️"
            ),
            (
                f"Las tarifas van desde ${min_price} por noche para 2 personas y dependen "
                f"de la fecha y el tamaño del grupo. Para darte el precio exacto, "
                f"¿me confirmas tus fechas y cuántas personas serían? 😊"
            ),
            (
                f"¡Con gusto te cotizo! Los precios parten desde ${min_price}/noche "
                f"y cambian según fecha, temporada y número de personas. "
                f"¿Qué fechas tienes en mente y cuántos serían? 🏖️"
            ),
        ]

        if len(text.strip()) < 30:
            return random.choice(fallback_variations)

        # Si el mensaje no pide fechas, agregar redirect con variación
        if not any(w in text.lower() for w in ['fecha', 'cuándo', 'cuando', 'cuántas', 'cuantas']):
            redirect_variations = [
                (
                    f"\n\nLos precios van desde ${min_price}/noche y varían según fecha, "
                    f"temporada y personas. ¿Me confirmas tus fechas y cuántas "
                    f"personas serían? 😊"
                ),
                (
                    f"\n\nPara darte el precio exacto necesito tus fechas y número de personas. "
                    f"Las tarifas arrancan desde ${min_price}/noche 🏖️"
                ),
                (
                    f"\n\nNuestras tarifas parten desde ${min_price}/noche. "
                    f"¿Qué fechas y cuántas personas serían para cotizarte? 😊"
                ),
            ]
            text += random.choice(redirect_variations)

        return text

    def _detect_intent(self, tool_calls_data):
        """Detecta la intención principal basada en las herramientas usadas"""
        if not tool_calls_data:
            return ''

        tool_names = [tc['name'] for tc in tool_calls_data]

        # notify_team captura el intent real decidido por GPT
        for tc in tool_calls_data:
            if tc['name'] == 'notify_team':
                return tc.get('arguments', {}).get('reason', 'notify')

        if 'escalate_to_human' in tool_names:
            return 'escalation'
        if 'check_availability' in tool_names:
            return 'availability_check'
        if 'check_calendar' in tool_names:
            return 'calendar_check'
        if 'schedule_visit' in tool_names:
            return 'visit_scheduled'

        return ''

    @staticmethod
    def _get_upcoming_holidays(today):
        """Calcula feriados peruanos próximos incluyendo Semana Santa."""
        from datetime import timedelta as td

        def _easter(year):
            """Algoritmo de Computus para calcular Domingo de Pascua."""
            a = year % 19
            b = year // 100
            c = year % 100
            d = b // 4
            e = b % 4
            f = (b + 8) // 25
            g = (b - f + 1) // 3
            h = (19 * a + b - d - g + 15) % 30
            i = c // 4
            k = c % 4
            el = (32 + 2 * e + 2 * i - h - k) % 7
            m = (a + 11 * h + 22 * el) // 451
            month = (h + el - 7 * m + 114) // 31
            day = ((h + el - 7 * m + 114) % 31) + 1
            return date(year, month, day)

        holidays = []
        for year in (today.year, today.year + 1):
            easter = _easter(year)
            holidays.extend([
                (easter - td(days=3), "Jueves Santo"),
                (easter - td(days=2), "Viernes Santo"),
                (date(year, 5, 1), "Día del Trabajo"),
                (date(year, 6, 29), "San Pedro y San Pablo"),
                (date(year, 7, 28), "Fiestas Patrias"),
                (date(year, 7, 29), "Fiestas Patrias"),
                (date(year, 8, 30), "Santa Rosa de Lima"),
                (date(year, 10, 8), "Combate de Angamos"),
                (date(year, 12, 25), "Navidad"),
                (date(year, 12, 31), "Año Nuevo (mín 3 noches)"),
            ])

        return sorted(
            (d, name) for d, name in holidays if 0 < (d - today).days <= 90
        )
