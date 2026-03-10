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
    'check_reservations',
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

    # Eliminar bloques completos [INSTRUCCIÓN ...] incluyendo multi-línea
    text = re.sub(
        r'\[INSTRUCCI[ÓO]N[^\]]*\]',
        '',
        text,
        flags=re.IGNORECASE | re.DOTALL,
    )
    # Eliminar líneas sueltas que son continuación de instrucciones IA
    # (empiezan con PROHIBIDO:, Tu respuesta DEBE, Solo agrega, NOTA INTERNA:)
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

        # Sanitizar respuesta antes de enviar
        response_text = sanitize_response(response_text)

        # Enviar por el canal correspondiente
        wa_message_id = None
        if send_wa:
            sender = get_sender(session.channel)
            wa_message_id = sender.send_text_message(session.wa_id, response_text)

        # Detectar intención basada en herramientas usadas
        intent = self._detect_intent(tool_calls_data)

        ChatMessage.objects.create(
            session=session,
            direction=ChatMessage.DirectionChoices.OUTBOUND_AI,
            message_type=ChatMessage.MessageTypeChoices.TEXT,
            content=response_text,
            wa_message_id=wa_message_id,
            ai_model=model_used,
            tokens_used=tokens,
            tool_calls=tool_calls_data,
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

                logger.info(f"Ejecutando herramienta: {func_name}({arguments})")
                result = executor.execute(func_name, arguments)

                tool_calls_data.append({
                    'name': func_name,
                    'arguments': arguments,
                    'result_preview': str(result)[:200],
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
            response2 = client.chat.completions.create(
                model=model,
                messages=messages,
                temperature=self.config.temperature,
                max_tokens=self.config.max_tokens_per_response,
            )

            response_text = response2.choices[0].message.content or ""
            total_tokens += response2.usage.total_tokens if response2.usage else 0
        else:
            response_text = choice.message.content or ""

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

        return messages

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
            # Capacidad de camas
            detalle = p.get('detalle_dormitorios') or {}
            bed_cap, bed_summary = calc_bed_capacity(detalle)
            if bed_cap:
                line += f", camas para {bed_cap} personas ({bed_summary})"
            if chars_str:
                line += chars_str
            # Distribución por habitación
            if isinstance(detalle, dict) and detalle:
                rooms_desc = []
                for room in detalle.values():
                    if not isinstance(room, dict):
                        continue
                    nombre = room.get('nombre', '')
                    camas = room.get('camas', {})
                    camas_parts = []
                    for tipo, cant in camas.items():
                        if cant and cant > 0:
                            camas_parts.append(f"{cant} {tipo}")
                    if camas_parts:
                        rooms_desc.append(f"{nombre}: {', '.join(camas_parts)}")
                if rooms_desc:
                    line += '\n  Habitaciones: ' + ' | '.join(rooms_desc)
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
