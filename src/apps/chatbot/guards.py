"""
Guards determinísticos para Austin Assistant.

Cada guard se ejecuta ANTES de llamar a OpenAI. Si matchea, devuelve un dict
con la respuesta canned y metadata para trazabilidad. Si no matchea, retorna
None y el flujo continúa al modelo.

Convenciones:
- intent_label = "guard:<nombre>"
- tool_call_meta se persiste en ChatMessage.tool_calls como evidencia
- Si guard responde, ChatMessage.tokens_used = 0
- Si hay duda, preferir NO interceptar (return None)
"""

import re

from .models import ChatMessage


# ============================================================================
# G1 — Aclaración USD/SOL
# ============================================================================

# Patrones de detección. Cualquier match dispara el guard.
# Importante: requerir contexto suficiente para no falsos positivos.
CURRENCY_CLARIFICATION_PATTERNS = [
    # Dos montos juntos (formato cotización: "$340-S/1224", "$340 · S/1224", etc.)
    r'\$\s*\d+(?:[.,]\d+)?\s*[\-\–\—.,·•/y\s]+\s*S/\.?\s*\d+',
    r'S/\.?\s*\d+(?:[.,]\d+)?\s*[\-\–\—.,·•/y\s]+\s*\$\s*\d+',
    # Pregunta directa sobre el formato dual
    r'\bqu[eé]\s+significa\s+(?:eso|el|los|esos)?\s*[\$\d]',
    r'\bpor\s+qu[eé]\s+(?:hay\s+)?(?:dos|2)\s+(?:precios|montos|valores|cifras)',
    r'\bcu[aá]l\s+es\s+(?:el\s+)?precio\s+(?:real|verdadero|final|exacto)',
    r'\bson\s+(?:los\s+)?(?:dos|2)\s+(?:montos|precios|valores)',
    # Conversión / equivalencia explícita
    r'\bson\s+d[oó]lares?\b',
    r'\bes\s+en\s+d[oó]lares?\b',
    r'\bd[oó]lares?\s+o\s+soles?\b',
    r'\bd[oó]lares?\s+y\s+(?:en\s+)?soles?\b',
    r'\bc[oó]mo\s+es\s+(?:eso\s+de\s+)?(?:los\s+)?d[oó]lares?\b',
    r'\b(?:o\s+sea\s+)?\d+\s*d[oó]lares?\s+y\s+(?:en\s+)?soles?\b',
    r'\b(?:en\s+)?soles?\s+cu[aá]nto\s+(?:es|ser[íi]a|sale|son)\b',
    r'\bcu[aá]nto\s+(?:es|son|ser[íi]a)\s+(?:eso\s+)?en\s+soles?\b',
    r'\bse\s+paga\s+en\s+soles?\??',
    r'\bel\s+precio\s+(?:es|est[aá])\s+en\s+(?:d[oó]lares?|soles?)',
    r'\bno\s+entiendo\s+(?:el|los)\s+precios?\b',
    r'\btipo\s+de\s+cambio\b',
    # Mensaje muy corto tipo "55 soles?" o "son dólares?"
    r'^\s*\d+\s*soles?\s*\??\s*$',
    r'\bcu[aá]nto\s+(?:son|es)\s+\$?\s*\d+\s+en\s+soles?\b',
]

CURRENCY_CLARIFICATION_RE = re.compile(
    '|'.join(CURRENCY_CLARIFICATION_PATTERNS),
    re.IGNORECASE,
)

# Regex para extraer "$NNN ... S/NNN" de la cotización guardada.
# Acepta separadores: espacios, ·, •, -, –, —, /, "y", ".", ",".
_QUOTE_PRICE_RE = re.compile(
    r'\$\s*(\d+(?:[.,]\d{1,2})?)\s*[\-\–\—·•/y\s.,]+\s*S/\.?\s*(\d+(?:[.,]\d{1,2})?)',
)

_PROPERTY_NAME_RE = re.compile(r'Casa\s+Austin\s+\d', re.IGNORECASE)


def _get_last_quote(session):
    """Recupera la última cotización (property, usd, sol) del historial.

    Busca en los últimos 10 mensajes outbound_ai con tool_calls. Si encuentra
    un check_availability o check_late_checkout, parsea el monto del
    result_preview o del content del mensaje.

    Returns:
        dict {property, usd, sol} | None
    """
    recent = ChatMessage.objects.filter(
        session=session,
        deleted=False,
        direction=ChatMessage.DirectionChoices.OUTBOUND_AI,
    ).exclude(tool_calls=[]).order_by('-created')[:10]

    for msg in recent:
        for tc in (msg.tool_calls or []):
            if tc.get('name') not in ('check_availability', 'check_late_checkout'):
                continue
            args = tc.get('arguments') or {}
            blob = (tc.get('result_preview') or '') + '\n' + (msg.content or '')
            m = _QUOTE_PRICE_RE.search(blob)
            if not m:
                continue
            usd, sol = m.group(1), m.group(2)
            prop = args.get('property_name') or _infer_property_from_text(blob)
            return {'property': prop, 'usd': usd, 'sol': sol}
    return None


def _infer_property_from_text(text):
    m = _PROPERTY_NAME_RE.search(text or '')
    return m.group(0) if m else 'la casa cotizada'


def try_currency_clarification(session, last_user_text):
    """Detecta preguntas de moneda/equivalencia y responde sin llamar al modelo.

    Args:
        session: ChatSession
        last_user_text: contenido del último mensaje del cliente (lower-case ok)

    Returns:
        dict {response, intent, tool_call_meta} si intercepta, None si no.
    """
    if not last_user_text:
        return None

    if not CURRENCY_CLARIFICATION_RE.search(last_user_text):
        return None

    quote = _get_last_quote(session)

    if quote:
        response = (
            "El primer monto está en dólares y el segundo es su equivalente en "
            "soles según el tipo de cambio vigente 😊\n\n"
            f"En tu cotización, {quote['property']} sale ${quote['usd']} · S/{quote['sol']}.\n\n"
            "Puedes pagar en soles desde la web."
        )
    else:
        response = (
            "El primer monto se muestra en dólares y el segundo en soles según el "
            "tipo de cambio vigente 😊\n\n"
            "Puedes pagar en soles desde la web."
        )

    return {
        'response': response,
        'intent': 'guard:currency_clarification',
        'tool_call_meta': {
            'name': 'guard',
            'guard': 'currency_clarification',
            'has_quote': quote is not None,
        },
    }


# ============================================================================
# G3 — "Qué casas tienen" (lista de propiedades)
# ============================================================================

# Triggers para preguntas genéricas sobre el catálogo de propiedades.
# IMPORTANTE: solo se aplica si NO hay datos específicos (fechas/personas)
# en el mismo mensaje, para no atropellar consultas reales de disponibilidad.
PROPERTY_LIST_PATTERNS = [
    r'\bqu[eé]\s+(?:tipo|tipos|clase)\s+(?:de\s+)?(?:casas?|propiedades)',
    r'\bqu[eé]\s+(?:casas?|propiedades)\s+(?:tienen|hay|ofrecen|manejan|alquilan)',
    r'\bcu[aá]les?\s+son\s+(?:las\s+)?(?:casas?|propiedades)',
    r'\bcu[aá]ntas?\s+(?:casas?|propiedades)\s+(?:tienen|hay)',
    r'\blista\s+de\s+(?:casas?|propiedades)',
    r'\b(?:casas?|propiedades)\s+disponibles?\s*\??\s*$',
    r'\b(?:m[eé]\s+)?(?:cu[eé]ntame|dime|inf[oó]rmame)\s+(?:de|sobre|acerca\s+de)\s+(?:las\s+)?(?:casas?|propiedades)',
    r'\bqu[eé]\s+ofrecen\s*\??',
    r'\bopciones?\s+de\s+(?:casas?|alojamiento|propiedades)',
]

PROPERTY_LIST_RE = re.compile(
    '|'.join(PROPERTY_LIST_PATTERNS),
    re.IGNORECASE,
)

# Si el mensaje incluye fecha o personas, NO disparamos: cae al flujo normal
# (el cliente quiere disponibilidad/cotización, no lista genérica).
SPECIFIC_DATA_PATTERNS = [
    # Personas
    r'\b\d+\s*(?:personas?|pax|amigos?|adultos?|gente|hu[eé]spedes?)\b',
    r'\bpara\s+\d+\b',
    r'\bsomos\s+\d+\b',
    # Fechas con mes
    r'\b(?:enero|febrero|marzo|abril|mayo|junio|julio|agosto|'
    r'septiembre|setiembre|octubre|noviembre|diciembre)\b',
    # Fechas tipo 25/03 o 25-03
    r'\b\d{1,2}\s*[/\-]\s*\d{1,2}\b',
    # "este finde" / "este fin de semana"
    r'\b(?:este|pr[oó]ximo)\s+(?:s[aá]bado|domingo|finde|fin\s+de\s+semana|viernes)\b',
    # "el sábado", "el 15"
    r'\bel\s+(?:s[aá]bado|domingo|viernes|\d{1,2})\b',
    # "feriado"
    r'\bferiado\b',
]

SPECIFIC_DATA_RE = re.compile(
    '|'.join(SPECIFIC_DATA_PATTERNS),
    re.IGNORECASE,
)


def _format_property_list():
    """Lee Property activas y arma el texto de respuesta canned.

    Aclara que las casas son independientes y que cada reserva es por casa
    completa (no se comparten espacios con otros huéspedes).

    Si la BD no responde por alguna razón, cae a una plantilla fija segura
    con las 4 casas conocidas (texto solicitado por el equipo).
    """
    fallback = (
        "Tenemos 4 casas privadas e independientes en Playa Los Pulpos.\n"
        "Cada reserva es por casa completa: no compartes piscina, jacuzzi "
        "ni espacios con otros huéspedes.\n\n"
        "Casa Austin 1: más íntima, ideal para familias o grupos pequeños.\n"
        "Casa Austin 2: amplia, cómoda para grupos medianos/grandes.\n"
        "Casa Austin 3: la más grande, ideal para eventos o grupos amplios.\n"
        "Casa Austin 4: similar a Casa Austin 2, perfecta para grupos.\n\n"
        "Todas tienen piscina, jacuzzi y ambientes privados.\n\n"
        "¿Para cuántas personas y qué fecha buscas?"
    )

    # Descripciones por player_id para casos conocidos. NO incluyen capacidad
    # explícita — el copy aprobado prefiere descripción cualitativa.
    KNOWN_DESCRIPTIONS = {
        'ca1': 'más íntima, ideal para familias o grupos pequeños.',
        'ca2': 'amplia, cómoda para grupos medianos/grandes.',
        'ca3': 'la más grande, ideal para eventos o grupos amplios.',
        'ca4': 'similar a Casa Austin 2, perfecta para grupos.',
    }

    try:
        from apps.property.models import Property
        props = list(
            Property.objects.filter(deleted=False)
            .order_by('player_id', 'name')
        )
    except Exception:
        return fallback

    if not props:
        return fallback

    lines = [
        f"Tenemos {len(props)} casas privadas e independientes en Playa Los Pulpos.",
        "Cada reserva es por casa completa: no compartes piscina, jacuzzi "
        "ni espacios con otros huéspedes.",
        "",
    ]
    for p in props:
        pid = (p.player_id or '').lower()
        desc = KNOWN_DESCRIPTIONS.get(pid)
        if not desc:
            cap = p.capacity_max or ''
            desc = f"hasta {cap} personas." if cap else "consulta capacidad."
        lines.append(f"{p.name}: {desc}")

    lines.append("")
    lines.append("Todas tienen piscina, jacuzzi y ambientes privados.")
    lines.append("")
    lines.append("¿Para cuántas personas y qué fecha buscas?")
    return "\n".join(lines)


def try_property_list(session, last_user_text):
    """Detecta preguntas genéricas tipo "qué casas tienen" y responde con
    la lista canned. NO dispara si el mensaje ya contiene fecha o personas.

    Returns:
        dict | None
    """
    if not last_user_text:
        return None

    if not PROPERTY_LIST_RE.search(last_user_text):
        return None

    # Salida segura: si hay datos específicos, dejar pasar al modelo
    # para que cotice/verifique disponibilidad en lugar de listar.
    if SPECIFIC_DATA_RE.search(last_user_text):
        return None

    response = _format_property_list()

    return {
        'response': response,
        'intent': 'guard:property_list',
        'tool_call_meta': {
            'name': 'guard',
            'guard': 'property_list',
        },
    }


# ============================================================================
# G4 — Identificador (DNI/nombre) tras reclamo de reserva
# ============================================================================
# Cuando el bot pidió 'nombre o documento' en su respuesta anterior (escenario
# de claim sin reserva encontrada) y el cliente responde con un DNI o nombre,
# este guard cierra el loop determinísticamente:
#   1. identify_client(document_number=...)
#   2. check_reservations()
#   3. notify_team con reason específica + contexto rico
#   4. Respuesta canned según escenario (approved/pending/not_found/name_only).

import logging

logger = logging.getLogger(__name__)

# Frase canónica de _check_reservations cuando se pide identificador.
_ASK_IDENTIFIER_MARKERS = (
    'con qué nombre o documento',
    'nombre o documento hiciste',
    'documento hiciste la reserva',
)

# Prefijos comunes de introducción del nombre que descartamos para extraer
# solo el nombre real (e.g. 'soy Augusto Martinez' → 'Augusto Martinez').
_NAME_INTRO_PREFIX_RE = re.compile(
    r'^(?:soy|mi\s+nombre\s+es|me\s+llamo|es|son)\s+',
    re.IGNORECASE,
)

# Palabras filler que NO son identificadores aunque cumplan otros patrones.
_FILLER_WORDS = {
    'si', 'sí', 'ok', 'no', 'gracias', 'dale', 'claro', 'listo',
    'ya', 'hola', 'buenas', 'bueno',
}

# DNI/CE peruano: 7-12 dígitos.
_DOC_NUM_RE = re.compile(r'\b(\d{7,12})\b')
# Nombre: 1-4 palabras alfabéticas (3+ chars la primera, 2+ las siguientes).
_NAME_RE = re.compile(
    r'^([A-Za-zÁÉÍÓÚÑáéíóúñ]{3,}(?:\s+[A-Za-zÁÉÍÓÚÑáéíóúñ]{2,}){0,3})$',
)

_BOOKING_URL_RE = re.compile(
    r'https://casaaustin\.pe/(?:reservar|disponibilidad)\?[^\s\n]+'
)


def _extract_identifier(user_text):
    """Devuelve {'type': 'document'|'name', 'value': str} o None."""
    if not user_text:
        return None
    text = user_text.strip()

    # Documento: cualquier secuencia de 7-12 dígitos
    m = _DOC_NUM_RE.search(text)
    if m:
        return {'type': 'document', 'value': m.group(1)}

    # Filler
    lower = text.lower().strip().rstrip('.!?')
    if lower in _FILLER_WORDS:
        return None

    # Strip prefijos del tipo 'soy', 'me llamo'
    name_text = _NAME_INTRO_PREFIX_RE.sub('', text).strip().rstrip('.!?')
    m = _NAME_RE.match(name_text)
    if m:
        return {'type': 'name', 'value': m.group(1).strip()}

    return None


def _last_ai_asked_for_identifier(session):
    """¿La última respuesta del bot pidió DNI/nombre para verificar reserva?"""
    last_ai = ChatMessage.objects.filter(
        session=session,
        deleted=False,
        direction=ChatMessage.DirectionChoices.OUTBOUND_AI,
    ).order_by('-created').first()
    if not last_ai:
        return False
    content = (last_ai.content or '').lower()
    return any(marker in content for marker in _ASK_IDENTIFIER_MARKERS)


def _find_last_booking_url(session):
    """Devuelve el último link parametrizado enviado en mensajes outbound."""
    recent = ChatMessage.objects.filter(
        session=session,
        deleted=False,
        direction=ChatMessage.DirectionChoices.OUTBOUND_AI,
    ).order_by('-created')[:15]
    for msg in recent:
        m = _BOOKING_URL_RE.search(msg.content or '')
        if m:
            return m.group(0)
    return None


def try_post_claim_identifier(session, last_user_text):
    """G4 — Cliente entregó DNI/nombre tras el prompt 'nombre o documento'.

    Activación:
    - Última respuesta del bot pidió 'con qué nombre o documento' (canonical).
    - Mensaje actual contiene un DNI (7-12 dígitos) O un nombre 1-4 palabras.

    Procesamiento determinístico:
    - DNI → identify_client → check_reservations → respuesta por escenario.
    - Nombre → respuesta soft + notify al equipo.
    Siempre dispara notify_team(reason='reservation_claimed_with_id_*') con
    contexto rico (identifier, wa_id, name, link, cotización).
    """
    if not last_user_text:
        return None

    if not _last_ai_asked_for_identifier(session):
        return None

    ident = _extract_identifier(last_user_text)
    if not ident:
        return None

    from .tool_executor import ToolExecutor
    from .reservation_lookup import client_phone_matches_wa_id
    executor = ToolExecutor(session)

    scenario = 'unknown'
    mismatch_detected = False
    mismatch_candidate = None

    if ident['type'] == 'document':
        # === Cross-check de seguridad (R3.1) ===
        # Antes de vincular session.client por DNI, verificar que el
        # teléfono registrado del Client coincida con el wa_id actual.
        # Si NO coincide → bloquear lookup, notificar al equipo y responder
        # genérico. Esto evita filtración de datos por DNI ajeno.
        from apps.clients.models import Clients
        try:
            mismatch_candidate = Clients.objects.filter(
                number_doc=ident['value'], deleted=False,
            ).first()
        except Exception as e:
            logger.error(f"G4 mismatch lookup failed: {e}", exc_info=True)
            mismatch_candidate = None

        if mismatch_candidate and not client_phone_matches_wa_id(
            mismatch_candidate, session.wa_id
        ):
            mismatch_detected = True
            scenario = 'mismatch'
        else:
            # No mismatch → proceder normal
            try:
                executor.execute('identify_client', {
                    'document_number': ident['value'],
                })
                session.refresh_from_db()
            except Exception as e:
                logger.error(f"G4 identify_client failed: {e}", exc_info=True)

            if session.client:
                try:
                    check_text = executor.execute('check_reservations', {})
                except Exception as e:
                    logger.error(
                        f"G4 check_reservations failed: {e}", exc_info=True,
                    )
                    check_text = ''
                # Parser de SCENARIO: nuevo formato (R3.1) + retro-compat con
                # texto previo ('CONFIRMADA', "estado 'pending'").
                sm = re.search(r'SCENARIO:\s*(\w+)', check_text)
                sc_label = sm.group(1) if sm else None
                if sc_label in ('approved_full', 'approved_with_advance'):
                    scenario = 'approved'
                elif sc_label in (
                    'pending_or_review', 'incomplete_no_voucher',
                    'incomplete_with_voucher',
                ):
                    scenario = 'pending_or_review'
                elif sc_label == 'cancelled':
                    scenario = 'cancelled'
                elif sc_label == 'rejected':
                    scenario = 'rejected'
                elif sc_label in ('not_found', 'no_reservations'):
                    scenario = 'no_reservations'
                else:
                    # Retro-compat
                    if 'CONFIRMADA' in check_text:
                        scenario = 'approved'
                    elif ("estado 'pending'" in check_text
                          or "estado 'under_review'" in check_text):
                        scenario = 'pending_or_review'
                    else:
                        scenario = 'no_reservations'
            else:
                scenario = 'document_not_found'
    else:  # name
        scenario = 'name_only'

    # Greeting name (primer nombre del cliente si lo identificamos, si no el
    # nombre dado por el cliente o el de WhatsApp).
    if session.client:
        greeting = session.client.first_name
    elif ident['type'] == 'name':
        greeting = ident['value'].split()[0]
    else:
        greeting = session.wa_profile_name or 'amigo'

    if scenario == 'mismatch':
        # Bloquear toda info de reserva — respuesta genérica.
        response = (
            "Gracias 😊 Aún no encuentro una reserva activa vinculada a "
            "este WhatsApp. Ya avisé al equipo para que lo revisen "
            "manualmente."
        )
        notify_reason = 'reservation_lookup_mismatch'
    elif scenario == 'approved':
        response = (
            "Perfecto 😊 Tu reserva ya figura confirmada. Te enviaremos/"
            "recordaremos los detalles de ingreso antes de tu llegada."
        )
        notify_reason = 'reservation_claimed_with_id_approved'
    elif scenario == 'pending_or_review':
        response = (
            "Perfecto 😊 Ya veo tu reserva registrada. El equipo validará "
            "el pago/voucher y te confirmará por este medio."
        )
        notify_reason = 'reservation_claimed_with_id_pending'
    elif scenario == 'cancelled':
        response = (
            "Veo que esa reserva está cancelada. Si quieres armar una "
            "nueva, te ayudo a cotizar 😊"
        )
        notify_reason = None  # no notify por cancelled (cliente informado)
    elif scenario == 'rejected':
        response = (
            "Gracias 😊 Ya avisé al equipo para que pueda revisar tu caso."
        )
        notify_reason = 'reservation_claimed_rejected'
    elif scenario == 'no_reservations':
        response = (
            f"Gracias {greeting} 😊 Aún no encuentro una reserva registrada "
            f"con ese documento. Ya avisé al equipo para que lo revise "
            f"manualmente."
        )
        notify_reason = 'reservation_claimed_with_id_not_found'
    elif scenario == 'document_not_found':
        response = (
            "Gracias 😊 Aún no encuentro una reserva registrada con ese "
            "documento. Ya avisé al equipo para que lo revise manualmente."
        )
        notify_reason = 'reservation_claimed_with_id_not_found'
    else:  # name_only
        response = (
            f"Gracias {greeting} 😊 Ya envié tus datos al equipo para que "
            f"puedan revisar la reserva.\n\n"
            f"Si subiste voucher o hiciste el pago, ellos lo validarán y "
            f"te confirmarán por este medio."
        )
        notify_reason = 'reservation_claimed_with_name'

    # Detalles ricos para notify_team
    details = [
        f"Identificador recibido post-claim: '{ident['value']}' ({ident['type']})",
        f"WhatsApp ID: {session.wa_id}",
        f"Nombre WhatsApp: {session.wa_profile_name or 'N/A'}",
        f"Escenario: {scenario}",
    ]
    if mismatch_detected and mismatch_candidate:
        # Mismatch — incluir contexto del Client encontrado (para que el
        # equipo investigue), pero NUNCA mostramos esto al cliente final.
        details.append(
            f"⚠️ MISMATCH: DNI '{ident['value']}' corresponde a "
            f"{mismatch_candidate.first_name} "
            f"{mismatch_candidate.last_name or ''}"
        )
        details.append(
            f"Teléfono registrado del Client: "
            f"{mismatch_candidate.tel_number or 'N/A'}"
        )
        details.append(
            f"NO se reveló info de reserva al cliente."
        )
    elif session.client:
        c = session.client
        details.append(
            f"Cliente vinculado: {c.first_name} {c.last_name or ''} "
            f"(DNI: {c.number_doc or 'N/A'})"
        )

    last_url = _find_last_booking_url(session)
    if last_url:
        details.append(f"Último link enviado: {last_url}")

    last_quote = _get_last_quote(session)
    if last_quote:
        details.append(
            f"Última cotización: ${last_quote.get('usd')} USD / "
            f"S/{last_quote.get('sol')}"
        )

    if notify_reason:
        try:
            executor.execute('notify_team', {
                'reason': notify_reason,
                'details': '\n'.join(details),
            })
        except Exception as e:
            logger.error(f"G4 notify_team failed: {e}", exc_info=True)

    logger.info(
        f"Guard G4 post_claim_identifier: scenario={scenario}, "
        f"id_type={ident['type']}, session={session.id}"
    )

    return {
        'response': response,
        'intent': 'guard:post_claim_identifier',
        'tool_call_meta': {
            'name': 'guard',
            'guard': 'post_claim_identifier',
            'scenario': scenario,
            'identifier_type': ident['type'],
            'notify_reason': notify_reason,
        },
    }


# ============================================================================
# G_REQUOTE — Repetir/resumir cotización anterior sin recotizar
# ============================================================================
# Si existe una cotización previa en la sesión y el cliente pregunta el
# precio sin dar nueva fecha o nuevo número de personas, re-emitimos la
# cotización guardada en formato compacto. 0 tokens. Sub-tipos:
#   A) IS_TOTAL  → "Sí 😊 es el precio total por toda la estadía..."
#   B) PER_PERSON → cálculo per-cápita desde la cotización
#   C) GENERIC    → re-render compacto con prefijo "Te resumo la cotización..."

IS_TOTAL_PATTERNS = [
    r'\b(?:eso|ese\s+precio|el\s+precio)\s+es\s+(?:el\s+)?total\??',
    r'\bes\s+(?:eso\s+|ese\s+)?(?:el\s+)?total\??',
    r'\bes\s+por\s+(?:toda\s+)?la\s+estad[ií]a\??',
    r'\btotal\s+por\s+(?:toda\s+)?la\s+estad[ií]a\??',
    r'^\s*es\s+total\??\s*$',
    r'^\s*total\??\s*$',
]
IS_TOTAL_RE = re.compile('|'.join(IS_TOTAL_PATTERNS), re.IGNORECASE)

PER_PERSON_PATTERNS = [
    r'\bpor\s+persona\b',
    r'\bcu[aá]nto\s+(?:sale|me\s+sale|toca|me\s+toca|paga)\s+(?:a\s+)?cada\s+(?:uno|persona)\b',
    r'\bpor\s+cada\s+(?:uno|persona|hu[eé]sped)\b',
    r'\bper\s*c[aá]pita\b',
]
PER_PERSON_RE = re.compile('|'.join(PER_PERSON_PATTERNS), re.IGNORECASE)

REQUOTE_GENERIC_PATTERNS = [
    r'\bcu[aá]nto\s+(?:cuesta|sale|ser[íi]a|me\s+sale|me\s+saldr[íi]a|pago|me\s+cobr[aá]n|est[aá])\b',
    r'\bcu[aá]l\s+(?:es|ser[íi]a)\s+(?:el\s+)?(?:precio|costo|total)\b',
    r'\bdame\s+(?:el\s+)?(?:precio|costo|total)\b',
    r'^\s*(?:el\s+)?precio\s*\??\s*$',
    r'^\s*(?:el\s+)?costo\s*\??\s*$',
    r'\ben\s+dinero\b',
    r'\bcu[aá]nto\s+(?:ser[íi]a|sale|cuesta)\s+(?:el\s+)?total\b',
    r'\bcu[aá]nto\s+(?:ser[íi]a|sale|cuesta)\s+por\s+(?:la\s+)?casa\b',
    r'\bcu[aá]nto\s+pago\b',
    r'\bme\s+(?:das|pas[aá]s|dec[ií]s)\s+(?:el\s+)?precio\b',
]
REQUOTE_GENERIC_RE = re.compile('|'.join(REQUOTE_GENERIC_PATTERNS), re.IGNORECASE)

# Parser de cotización emitida por _format_pricing_result.
# Casa N: $X ó S/Y  (también acepta 'Casa Austin N' por compatibilidad).
_REQUOTE_HOUSE_RE = re.compile(
    r'^(Casa\s+(?:Austin\s+)?\d+):\s*\$(\d+)\s+ó\s+S/(\d+)',
    re.MULTILINE,
)
_REQUOTE_HEADER_RE = re.compile(r'📅\s+(.+?)\s+·\s+(\d+)\s+persona')
_REQUOTE_URL_LABEL_RE = re.compile(
    r'🔗\s+(Ver opciones y reservar|Reserva directa):'
)
_REQUOTE_URL_RE = re.compile(
    r'https://casaaustin\.pe/(reservar|disponibilidad)\?([^\s\n]+)'
)
_REQUOTE_DISCOUNT_RE = re.compile(r'🎁[^\n]+')


def _get_full_last_quote(session):
    """Recupera la última cotización COMPLETA del historial (vs `_get_last_quote`
    que solo trae precios de una casa).

    Busca en los últimos 10 mensajes outbound_ai con tool_calls que incluyan
    check_availability, parsea el content y devuelve estructura rica.

    Returns:
        dict | None con keys: check_in, check_out, guests, date_display,
        houses[{name, usd, sol}], booking_url, url_label, discount_line,
        msg_age_seconds.
    """
    from django.utils import timezone as _tz

    recent = ChatMessage.objects.filter(
        session=session,
        deleted=False,
        direction=ChatMessage.DirectionChoices.OUTBOUND_AI,
    ).exclude(tool_calls=[]).order_by('-created')[:10]

    for msg in recent:
        has_avail = any(
            (tc.get('name') == 'check_availability')
            for tc in (msg.tool_calls or [])
        )
        if not has_avail:
            continue

        content = msg.content or ''

        url_m = _REQUOTE_URL_RE.search(content)
        if not url_m:
            continue
        url_full = url_m.group(0)
        url_type = url_m.group(1)
        params_str = url_m.group(2)
        params = {}
        for pair in params_str.split('&'):
            if '=' in pair:
                k, v = pair.split('=', 1)
                params[k] = v

        check_in = params.get('checkIn')
        check_out = params.get('checkOut')
        try:
            guests = int(params.get('guests', 0)) or None
        except ValueError:
            guests = None

        label_m = _REQUOTE_URL_LABEL_RE.search(content)
        url_label = label_m.group(1) if label_m else (
            'Ver opciones y reservar' if url_type == 'disponibilidad'
            else 'Reserva directa'
        )

        header_m = _REQUOTE_HEADER_RE.search(content)
        date_display = (
            header_m.group(1).strip() if header_m
            else (f"{check_in} → {check_out}" if check_in and check_out else '')
        )
        if not guests and header_m:
            try:
                guests = int(header_m.group(2))
            except ValueError:
                guests = None

        houses = []
        for cm in _REQUOTE_HOUSE_RE.finditer(content):
            houses.append({
                'name': cm.group(1).strip(),
                'usd': int(cm.group(2)),
                'sol': int(cm.group(3)),
            })

        if not houses:
            continue

        disc_m = _REQUOTE_DISCOUNT_RE.search(content)
        discount_line = disc_m.group(0).strip() if disc_m else None

        msg_age = (_tz.now() - msg.created).total_seconds()

        return {
            'check_in': check_in,
            'check_out': check_out,
            'guests': guests or 1,
            'date_display': date_display,
            'houses': houses,
            'booking_url': url_full,
            'url_label': url_label,
            'discount_line': discount_line,
            'msg_age_seconds': msg_age,
        }
    return None


def _short_name(name):
    """'Casa Austin 1' → 'Casa 1'."""
    m = re.match(r'^\s*Casa\s+Austin\s+(\d+)\s*$', name or '', re.IGNORECASE)
    if m:
        return f"Casa {m.group(1)}"
    return name or ''


_REQUOTE_IS_TOTAL_RESPONSE = (
    "Sí 😊 es el precio total por toda la estadía para la casa completa."
)


def _render_requote(quote):
    """C: re-emite la cotización compacta con prefijo conversacional."""
    guests = quote['guests']
    lines = [
        "Claro 😊 Te resumo la cotización anterior:",
        "",
        f"📅 {quote['date_display']} · {guests} persona{'s' if guests != 1 else ''}",
        "Precio total por toda la estadía:",
        "",
    ]
    for h in quote['houses']:
        lines.append(f"{_short_name(h['name'])}: ${h['usd']} ó S/{h['sol']}")
    lines.append("")
    lines.append(f"🔗 {quote['url_label']}:")
    lines.append(quote['booking_url'])
    lines.append("")
    lines.append("¿Quieres que te ayude a separarla con el 50%?")
    return "\n".join(lines)


def _render_per_person(quote):
    """B: per-cápita = sol_total / guests (entero)."""
    guests = max(int(quote['guests'] or 1), 1)
    if len(quote['houses']) == 1:
        h = quote['houses'][0]
        per = round(h['sol'] / guests)
        return (
            f"Para {guests} persona{'s' if guests != 1 else ''}, "
            f"{_short_name(h['name'])} saldría aprox S/{per} por persona 😊"
        )
    lines = [
        f"Para {guests} persona{'s' if guests != 1 else ''}, "
        f"queda aproximadamente:",
        "",
    ]
    for h in quote['houses']:
        per = round(h['sol'] / guests)
        lines.append(f"{_short_name(h['name'])}: S/{per} por persona")
    return "\n".join(lines)


def try_requote(session, last_user_text):
    """G_REQUOTE — Si hay cotización previa Y el cliente pregunta el precio
    SIN dar nueva fecha/personas, responder determinísticamente.

    Sub-tipos:
      - is_total   → confirmación corta.
      - per_person → cálculo per-cápita.
      - generic    → re-render compacto.
    """
    if not last_user_text:
        return None
    text = last_user_text

    # Gating: nueva fecha/personas → NO interceptar (pasa al modelo)
    if SPECIFIC_DATA_RE.search(text):
        return None

    is_total = bool(IS_TOTAL_RE.search(text))
    is_per_person = bool(PER_PERSON_RE.search(text))
    is_generic = bool(REQUOTE_GENERIC_RE.search(text))

    if not (is_total or is_per_person or is_generic):
        return None

    quote = _get_full_last_quote(session)
    if not quote:
        return None

    # Heurística de freshness: si la cotización tiene >30min y NO es solo
    # confirmar "es total?", dejar pasar al modelo (precios/disponibilidad
    # pueden haber cambiado).
    if quote['msg_age_seconds'] > 30 * 60 and not is_total:
        return None

    # Sub-tipo prioridad: is_total > per_person > generic
    if is_total:
        response = _REQUOTE_IS_TOTAL_RESPONSE
        subtype = 'is_total'
    elif is_per_person:
        response = _render_per_person(quote)
        subtype = 'per_person'
    else:
        response = _render_requote(quote)
        subtype = 'generic'

    logger.info(
        f"Guard G_REQUOTE: subtype={subtype}, "
        f"casas={len(quote['houses'])}, age={int(quote['msg_age_seconds'])}s, "
        f"session={session.id}"
    )

    return {
        'response': response,
        'intent': f'guard:requote:{subtype}',
        'tool_call_meta': {
            'name': 'guard',
            'guard': 'requote',
            'subtype': subtype,
            'houses_count': len(quote['houses']),
            'msg_age_seconds': int(quote['msg_age_seconds']),
        },
    }


# ============================================================================
# G_FAQ — Preguntas frecuentes (mascotas, check-in/out, ubicación, etc.)
# ============================================================================
# Cubre 12 temas comunes con respuestas deterministas (0 tokens). Conservador:
# si el mensaje contiene fecha/personas, dejar pasar al modelo para que
# combine FAQ + cotización en un turno.

# Maps URL canónico para Playa Los Pulpos. Usar fallback hasta que el
# equipo provea el link oficial de Google Maps.
_MAPS_URL = 'https://maps.app.goo.gl/Y8nDjWPB7QmKjxR99'

FAQ_TOPICS = [
    {
        'topic': 'pet_friendly',
        'patterns': [
            r'\bacepta(?:n|s)?\s+mascotas?\b',
            r'\b(?:puedo|podemos|podr[ií]a(?:n|mos)?)\s+llevar\s+'
            r'(?:a\s+)?(?:mi|el|la|los|las|un|una|nuestro|nuestra)?\s*'
            r'(?:perro|perra|perrito|perrita|gato|gata|mascota)',
            r'\bpet[\s\-]?friendly\b',
            r'\bllevar\s+(?:a\s+)?(?:mi\s+)?mascota',
            r'\bvan\s+(?:a\s+)?ir\s+(?:con\s+)?(?:mi\s+|nuestra\s+)?mascota',
            r'\bperrit[oa]s?\b',
            r'\bmis\s+mascotas?\b',
        ],
        'response': (
            "Sí 😊 Somos pet-friendly. Puedes llevar mascotas, solo "
            "ten en cuenta que cada mascota cuenta como persona "
            "adicional para la cotización.\n\n¿Cuántas mascotas llevarías?"
        ),
    },
    {
        'topic': 'check_in_out',
        'patterns': [
            r'\bhora\s+(?:de|del)\s+(?:ingreso|entrada|llegada|check[\s\-]?in)\b',
            r'\bhora\s+(?:de|del)\s+(?:salida|check[\s\-]?out)\b',
            r'\bcheck[\s\-]?in\b',
            r'\bcheck[\s\-]?out\b',
            r'\ba\s+qu[eé]\s+hora\s+(?:entramos|entran|llegamos|llegan|salimos|salen|nos\s+vamos)\b',
            r'\bdesde\s+qu[eé]\s+hora\s+(?:podemos\s+|se\s+puede\s+)?entrar\b',
            r'\bhasta\s+qu[eé]\s+hora\s+(?:podemos\s+|se\s+puede\s+)?(?:quedarnos|estar|salir)\b',
        ],
        'response': (
            "El check-in es desde las 3:00 p. m. y el check-out es "
            "hasta las 11:00 a. m. 😊\n\nSi necesitas late check-out, "
            "se puede revisar según disponibilidad."
        ),
    },
    {
        'topic': 'location',
        'patterns': [
            r'\bd[oó]nde\s+(?:queda|est[aá]n?|ubica|se\s+encuentra)',
            r'\bubicaci[oó]n\b',
            r'\bc[oó]mo\s+(?:llego|llegamos|llegar|se\s+llega)\b',
            r'\bdirecci[oó]n\b',
            r'\bgoogle\s+maps?\b',
            r'\bmaps?\b',
            r'\bqueda\s+(?:lejos|cerca)\b',
            r'\bplaya\s+los\s+pulpos?\b',
        ],
        'response': (
            "Estamos en Playa Los Pulpos, al sur de Lima, aproximadamente "
            f"a 25 minutos del Jockey Plaza 😊\n\nAquí puedes ver la "
            f"ubicación:\n{_MAPS_URL}\n\n¿Para qué fecha te gustaría cotizar?"
        ),
    },
    {
        'topic': 'pool_jacuzzi',
        'patterns': [
            r'\btiene[ns]?\s+piscina\b',
            r'\bhay\s+piscina\b',
            r'\bpiscina\s+temperada?\b',
            r'\bjacu[zss]+i\b',
            r'\b(?:se\s+puede\s+)?tempera(?:r|do|da)\s+(?:el\s+|la\s+)?'
            r'(?:jacu[zss]+i|piscina|agua)\b',
            r'\bagua\s+(?:caliente|tibia|temperada)\b',
            r'\bcalentar\s+(?:el\s+|la\s+)?(?:jacu[zss]+i|piscina|agua)\b',
        ],
        'response': (
            "Sí 😊 Todas las casas tienen piscina y jacuzzi.\n\n"
            "El servicio de jacuzzi temperado cuesta S/100 por noche."
        ),
    },
    {
        'topic': 'party_music',
        'patterns': [
            r'\b(?:se\s+puede|permiten|aceptan?)\s+(?:hacer\s+)?fiesta',
            r'\bfiestas?\??\s*$',
            r'\bm[uú]sica\s+(?:alta|fuerte|hasta|en\s+vivo)\b',
            r'\bdj\b',
            r'\borquesta\b',
            r'\bcantante\b',
            r'\brecepci[oó]n\b',
            r'\bcumplea[ñn]os\s+con\s+(?:m[uú]sica|fiesta)\b',
            r'\bbulla\b',
            r'\bcelebraci[oó]n\s+(?:con|y)\s+m[uú]sica\b',
        ],
        'response': (
            "Sí se pueden hacer celebraciones, pero depende de la casa 😊\n\n"
            "Casa Austin 1 es más tranquila y no permite fiestas ni "
            "música alta.\n"
            "Para celebraciones con música, recomendamos Casa Austin 2, 3 "
            "o 4, que tienen ventanas termoacústicas. La música debe "
            "manejarse con responsabilidad, especialmente en exteriores.\n\n"
            "¿Cuántas personas serían y para qué fecha?"
        ),
    },
    {
        'topic': 'extra_services',
        'patterns': [
            r'\bincluye?\s+decoraci[oó]n\b',
            r'\bdecoraci[oó]n\b',
            r'\bdecoran\b',
            r'\bservicios\s+adicionales\b',
            r'\bofrecen\s+catering\b',
            r'\bcatering\b',
            r'\b(?:hay|incluye[ns]?)\s+(?:comida|desayuno|almuerzo|cena)\b',
            r'\bcocinero\b',
            r'\bmeseros?\b',
            r'\bmozos?\b',
            r'\bglobos\b',
        ],
        'response': (
            "La reserva incluye la casa completa y sus ambientes "
            "privados 😊\n\nLa decoración, catering, comida, mozos u "
            "otros servicios adicionales no están incluidos por defecto. "
            "Si necesitas algo especial para un evento, puedo avisar al "
            "equipo para que te orienten según lo que buscas."
        ),
    },
    {
        'topic': 'parking',
        'patterns': [
            r'\bcochera\b',
            r'\bestacionamiento\b',
            r'\bparking\b',
            r'\bcu[aá]nt[oa]s\s+(?:carros|autos|veh[ií]culos|camionetas)\b',
            r'\bcamionetas?\b',
            r'\bdejar\s+(?:los\s+|nuestros\s+|mis\s+)?autos?\b',
            r'\bparquear\b',
        ],
        'response': (
            "Todas las casas tienen estacionamiento gratuito en la "
            "propiedad o zona de parqueo cercana 😊\n\nLa capacidad "
            "exacta puede variar según la casa y el tamaño de los "
            "vehículos. Si me dices qué casa estás viendo y cuántos "
            "autos llevarían, te ayudo a revisarlo."
        ),
    },
    {
        'topic': 'grill',
        'patterns': [
            r'\bparrilla\b',
            r'\bbbq\b',
            r'\bcarb[oó]n\b',
            r'\ble[ñn]a\b',
            r'\basad(?:o|ito)\b',
        ],
        'response': (
            "Sí 😊 Las casas cuentan con zona para parrilla. El carbón, "
            "leña o insumos normalmente los lleva el huésped."
        ),
    },
    {
        'topic': 'wifi',
        'patterns': [
            r'\bwi[\s\-]?fi\b',
            r'\binternet\b',
            r'\bse[ñn]al\b',
            r'\bteletrabajo\b',
        ],
        'response': (
            "Sí 😊 Las casas cuentan con WiFi. La velocidad puede variar "
            "por zona y demanda, pero es suficiente para uso normal "
            "durante la estadía."
        ),
    },
    {
        'topic': 'photos_videos',
        'patterns': [
            r'\bvideos?\b',
            r'\bfotos?\b',
            r'\b[aá]reas?\s+de\s+la\s+casa\b',
            r'\bver\s+la\s+casa\b',
            r'\bver\s+(?:las\s+)?casas?\b',
            r'\bquiero\s+ver\b',
            r'\bme\s+(?:muestras|envías|mandas)\s+fotos\b',
        ],
        'response_dynamic': 'photos_videos',
    },
    {
        'topic': 'children',
        'patterns': [
            r'\bni[ñn]os?\s+(?:pagan|cuentan|cuesta)\b',
            r'\bni[ñn]o\s+cuenta\b',
            r'\bcuentan\s+los\s+ni[ñn]os\b',
            r'\bmenores?\s+de\s+edad\b',
            r'\bbeb[eé]s?\b',
        ],
        'response': (
            "Los niños pequeños no se cuentan igual que un adulto para "
            "algunas consultas, pero para cotizar bien necesito saber "
            "cuántos adultos y cuántos niños irían 😊"
        ),
    },
    {
        'topic': 'visitors',
        'patterns': [
            r'\bpueden?\s+entrar\s+(?:visitas|amigos|gente)\b',
            r'\bvisitantes?\b',
            r'\binvitados?\s+de\s+d[ií]a\b',
            r'\bpersonas\s+adicionales\b',
            r'\bentran\s+y\s+salen\b',
        ],
        'response': (
            "Sí, pueden ir visitantes, pero cualquier visitante de día "
            "o de noche cuenta como persona adicional para la "
            "reserva 😊\n\nPor eso es importante cotizar con el número "
            "total de personas que ingresarán."
        ),
    },
]

# Compilar regex una sola vez al cargar el módulo.
for _topic in FAQ_TOPICS:
    _topic['_re'] = re.compile('|'.join(_topic['patterns']), re.IGNORECASE)


# Patrón para detectar 'Casa N', 'Casa Austin N', 'casa 3' en el mensaje.
_CASA_REF_RE = re.compile(
    r'\bcasa(?:\s+austin)?\s+(\d)\b',
    re.IGNORECASE,
)


def _render_photos_videos(text=None):
    """Construye respuesta dinámica para FAQ 'photos_videos'.

    - Si el mensaje menciona una casa específica (Casa 1/2/3/4 o Casa
      Austin N), responde solo con esa casa.
    - Si no, lista las 4 casas.

    Usa Property.slug si existe; cae a hardcoded si la query falla.
    """
    target_num = None
    if text:
        m = _CASA_REF_RE.search(text)
        if m:
            target_num = m.group(1)

    fallback_lines = [
        ('Casa 1', 'casa-austin-1'),
        ('Casa 2', 'casa-austin-2'),
        ('Casa 3', 'casa-austin-3'),
        ('Casa 4', 'casa-austin-4'),
    ]

    # Resolver lista (name, slug) desde la BD o fallback.
    pairs = []
    try:
        from apps.property.models import Property
        props = list(
            Property.objects.filter(deleted=False)
            .exclude(slug__isnull=True).exclude(slug='')
            .order_by('player_id', 'name')
        )
        for p in props:
            short = re.sub(
                r'^\s*Casa\s+Austin\s+(\d+)\s*$', r'Casa \1',
                p.name, flags=re.IGNORECASE,
            )
            pairs.append((short, p.slug, p.name))
    except Exception:
        pairs = [(n, s, f'Casa Austin {s[-1]}') for n, s in fallback_lines]
    if not pairs:
        pairs = [(n, s, f'Casa Austin {s[-1]}') for n, s in fallback_lines]

    # Single-casa: filtrar por número
    if target_num:
        match = None
        for short, slug, full in pairs:
            if short.endswith(target_num) or slug.endswith(target_num):
                match = (short, slug, full)
                break
        if match:
            short, slug, full = match
            return (
                f"Claro 😊 Puedes ver fotos y detalles de {full} aquí:\n"
                f"https://casaaustin.pe/casas-en-alquiler/{slug}\n\n"
                "Si necesitas un video específico, puedo avisar al equipo "
                "para que te ayuden."
            )
        # Si pidió Casa N pero no existe N, caer al listado completo.

    # Listado completo
    lines = ["Claro 😊 Puedes ver fotos y detalles de cada casa aquí:", ""]
    for short, slug, _full in pairs:
        lines.append(f"{short}: https://casaaustin.pe/casas-en-alquiler/{slug}")
    lines.append("")
    lines.append(
        "Si ya tienes una casa en mente, dime cuál y te paso el link directo."
    )
    return "\n".join(lines)


# Topics que tratan números legítimos (autos, parrillas, fotos de N casas)
# y NO deben gatearse por SPECIFIC_DATA cuando solo contiene "para N".
_FAQ_NUMBERS_OK_TOPICS = {'parking', 'grill', 'photos_videos'}


def try_faq(session, last_user_text):
    """G_FAQ — Detecta una FAQ entre los 12 topics y responde determinístico.

    Conservador:
    - Si el mensaje contiene SPECIFIC_DATA (fecha/personas explícitas),
      deja pasar al modelo (para que combine FAQ + cotización en un turno).
    - Excepción: topics donde un número es legítimo (parking/grill/photos)
      no se gatean por "para N" si no hay marcador claro de personas/fechas.
    - Si varios topics matchean, gana el primero por POSICIÓN en el texto.
    """
    if not last_user_text:
        return None
    text = last_user_text

    # Buscar el topic con match de menor posición (el primero mencionado).
    # También recolectamos TODOS los matches para detectar combos comunes.
    best_topic = None
    best_pos = None
    matched_topics = set()
    for topic in FAQ_TOPICS:
        m = topic['_re'].search(text)
        if not m:
            continue
        matched_topics.add(topic['topic'])
        if best_pos is None or m.start() < best_pos:
            best_pos = m.start()
            best_topic = topic
    if not best_topic:
        return None

    # Combo WiFi + Parrilla — devolver respuesta combinada en lugar del
    # primero por posición (caso visto en producción: "tienen wifi y parrilla?").
    if 'wifi' in matched_topics and 'grill' in matched_topics:
        # Mismo gating de SPECIFIC_DATA que abajo (parrilla/wifi son simples,
        # no llevan números — chequeo normal SPECIFIC_DATA).
        if SPECIFIC_DATA_RE.search(text):
            return None
        response = (
            "Sí 😊 Las casas cuentan con WiFi y zona para parrilla.\n\n"
            "El carbón, leña o insumos normalmente los lleva el huésped."
        )
        logger.info(
            f"Guard G_FAQ activado: topic=wifi+grill_combo, session={session.id}"
        )
        return {
            'response': response,
            'intent': 'guard:faq:wifi_grill_combo',
            'tool_call_meta': {
                'name': 'guard',
                'guard': 'faq',
                'topic': 'wifi_grill_combo',
            },
        }

    # Gating SPECIFIC_DATA — con excepción para topics con números legítimos.
    if best_topic['topic'] not in _FAQ_NUMBERS_OK_TOPICS:
        if SPECIFIC_DATA_RE.search(text):
            return None
    else:
        # Para parking/grill/photos: gatear solo si hay señal clara de
        # personas/fecha (no solo "para N"). Patrones explícitos:
        STRONG_DATE_PEOPLE_RE = re.compile(
            r'\b\d+\s*(?:personas?|pax|amigos?|adultos?|gente|hu[eé]spedes?)\b'
            r'|\bsomos\s+\d+\b'
            r'|\b(?:enero|febrero|marzo|abril|mayo|junio|julio|agosto|'
            r'septiembre|setiembre|octubre|noviembre|diciembre)\b'
            r'|\b\d{1,2}\s*[/\-]\s*\d{1,2}\b'
            r'|\bel\s+(?:s[aá]bado|domingo|viernes|\d{1,2})\b'
            r'|\bferiado\b',
            re.IGNORECASE,
        )
        if STRONG_DATE_PEOPLE_RE.search(text):
            return None

    topic_name = best_topic['topic']
    if best_topic.get('response_dynamic') == 'photos_videos':
        response = _render_photos_videos(text=text)
    else:
        response = best_topic['response']
    logger.info(
        f"Guard G_FAQ activado: topic={topic_name}, session={session.id}"
    )
    return {
        'response': response,
        'intent': f'guard:faq:{topic_name}',
        'tool_call_meta': {
            'name': 'guard',
            'guard': 'faq',
            'topic': topic_name,
        },
    }


# ============================================================================
# G_MAGIC_LINK — Generar magic link al confirmar reserva (R4)
# ============================================================================
# Si el cliente está vinculado (session.client existe) Y el mensaje es una
# afirmación corta post-cotización Y el feature flag MAGIC_LINK_ENABLED=True,
# generamos un magic link y respondemos con copy específico. En caso
# contrario, dejamos pasar al modelo (que enviará el link normal R1.0).

_AFFIRMATIVE_SHORT_PATTERNS = [
    r'^\s*s[ií]\s*[.!?]?\s*$',
    r'^\s*ok(?:ay|ey)?\s*[.!?]?\s*$',  # ok, okay, okey
    r'^\s*dale\s*[.!?]?\s*$',
    r'^\s*claro\s*[.!?]?\s*$',
    r'^\s*listo\s*[.!?]?\s*$',
    r'^\s*por\s*fa(?:vor)?\s*$',
    r'^\s*porfa\s*$',
    r'^\s*va(?:le|mos)?\s*[.!?]?\s*$',
    r'^\s*perfecto\s*[.!?]?\s*$',
    # Variantes cortas comunes de "sí" + cortesía/abreviación
    # NOTA: omitimos 'gracias' y 'amigo' aquí porque 'si gracias' o 'si amigo'
    # suele ser cortesía indeterminada, no decisión de reservar.
    r'^\s*s[ií]\s+(?:porfa|por\s*fa(?:vor)?|xfv|x?\s*fa(?:vor)?|pls|please|claro)\s*[.!?]?\s*$',
    # Interés explícito
    r'^\s*me\s+(?:gusta|interesa|anim[ao])\b',
    r'^\s*me\s+gustar[ií]a\b',
    # Otras formas afirmativas breves
    r'^\s*ya\s+pues\s*[.!?]?\s*$',
    r'^\s*genial\s*[.!?]?\s*$',
    r'^\s*excelente\s*[.!?]?\s*$',
    r'^\s*adelante\s*[.!?]?\s*$',
    r'^\s*obvio\s*[.!?]?\s*$',
    r'^\s*por\s+supuesto\s*[.!?]?\s*$',
    r'^\s*claro\s+que\s+s[ií]\s*[.!?]?\s*$',
    # NUEVO: "Ya + adjetivo" — "ya genial", "ya está", "ya perfecto"
    r'^\s*ya\s+(?:genial|perfecto|listo|claro|ok(?:ay|ey)?|est[aá])\s*[.!?]?\s*$',
    r'^\s*que\s+(?:genial|bueno|bien|chévere)\s*[.!?]?\s*$',
]

_AFFIRMATIVE_INTENT_PATTERNS = [
    r'\bquiero\s+(?:reservar|separar|continuar|el\s+link|ese\s+link)',
    r'\bp[aá]same\s+(?:el\s+)?(?:link|enlace)\b',
    # Verbos comunes para pedir el link: dame, déjame, envíame, mándame, manda
    r'\b(?:dame|d[eé]jame|env[ií]ame|m[aá]nda(?:me)?)\s+(?:el\s+)?(?:link|enlace)\b',
    # Usar s[ií] para captar 'si' sin tilde + más palabras
    r'\bs[ií][,\s]+(?:quiero|me\s+animo|por\s+favor|porfa|por\s+fa|xfv|claro)\b',
    r'\bme\s+anim[oa]\b',
    r'\b(?:lo\s+)?(?:voy\s+a|quiero|deseo)\s+(?:reservar|separar)\b',
]

_AFFIRMATIVE_RE = re.compile(
    '|'.join(_AFFIRMATIVE_SHORT_PATTERNS + _AFFIRMATIVE_INTENT_PATTERNS),
    re.IGNORECASE,
)

# Detección de "Casa N" / "Casa Austin N" (estricto: contiene la palabra "casa")
_CASA_REF_RE = re.compile(r'\bcasa\s+(?:austin\s+)?([1-4])\b', re.IGNORECASE)
# Detección laxa (solo cuando ya preguntamos cuál casa): "la 3", "3" solo
_CASA_REF_LAX_RE = re.compile(
    r'\bla\s+([1-4])\b|^\s*([1-4])\s*[.!?]?\s*$',
    re.IGNORECASE,
)


def _resolve_property_by_num(num):
    """Lookup Property por slug 'casa-austin-N'."""
    if not num:
        return None
    from apps.property.models import Property
    return Property.objects.filter(
        slug=f'casa-austin-{num}', deleted=False,
    ).first()


def try_continue_link_with_magic(session, last_user_text):
    """G_MAGIC_LINK — Dos fases para entregar magic link al cliente vinculado:

    Fase 1 (ask_house):
      - Cotización multi-casa + afirmación ("sí") → bot pregunta qué casa.
      - Setea conversation_context['magic_awaiting_house'] = check_in date.

    Fase 2 (send_link):
      - Cotización single-casa + afirmación → link directo con esa casa.
      - O bien: estamos awaiting_house Y el cliente envía "Casa N" / "la 3" /
        "3" → genera magic link con la casa elegida.
      - O bien: afirmación + casa explícita en un solo mensaje ("sí, casa 4")
        → salta la pregunta y genera link directo.

    Si falla cualquier check → return None (fallback a R1.0 normal).
    """
    from django.conf import settings

    if not getattr(settings, 'MAGIC_LINK_ENABLED', False):
        return None
    if not last_user_text:
        return None
    if not session or not session.client_id:
        return None

    quote = _get_full_last_quote(session)
    if not quote:
        return None

    # Parsear fechas y guests desde la cotización
    from datetime import datetime as _dt
    try:
        check_in = _dt.strptime(quote['check_in'], '%Y-%m-%d').date()
        check_out = _dt.strptime(quote['check_out'], '%Y-%m-%d').date()
        guests = int(quote['guests'])
    except (KeyError, TypeError, ValueError) as e:
        logger.warning(f"G_MAGIC_LINK: failed parsing quote: {e}")
        return None

    # Estado: ¿el bot está esperando que el cliente elija casa?
    ctx = session.conversation_context or {}
    awaiting = ctx.get('magic_awaiting_house')
    # Stale state: si la cotización actual difiere de la que motivó la
    # pregunta, descartamos el awaiting (el cliente recotizó).
    if awaiting and awaiting != quote['check_in']:
        ctx.pop('magic_awaiting_house', None)
        session.conversation_context = ctx
        session.save(update_fields=['conversation_context'])
        awaiting = None

    # Detectar afirmación + casa (estricto)
    is_affirmative = bool(_AFFIRMATIVE_RE.search(last_user_text))
    casa_match = _CASA_REF_RE.search(last_user_text)
    casa_num = int(casa_match.group(1)) if casa_match else None
    # Si NO hay "casa N" estricto pero estamos awaiting, aceptar laxos
    if not casa_num and awaiting:
        lax = _CASA_REF_LAX_RE.search(last_user_text.strip())
        if lax:
            casa_num = int(lax.group(1) or lax.group(2))

    # Si no hay ninguna señal procesable → fallback
    if not is_affirmative and not casa_num:
        return None

    # === Resolver property ===
    prop = None

    # (a) Cliente envió "Casa N" → validar que esa casa está en la cotización
    if casa_num:
        casa_in_quote = any(
            re.search(rf'\b{casa_num}\b', h.get('name', ''))
            for h in quote.get('houses', [])
        )
        if casa_in_quote:
            prop = _resolve_property_by_num(casa_num)

    # (b) Cotización single-casa: extraer property del booking_url o del nombre
    if not prop and len(quote.get('houses', [])) == 1:
        if 'property=' in (quote.get('booking_url') or ''):
            m = re.search(r'property=([^&]+)', quote['booking_url'])
            if m:
                from apps.property.models import Property
                prop = Property.objects.filter(
                    slug=m.group(1), deleted=False,
                ).first()
        if not prop:
            name = quote['houses'][0].get('name', '')
            num_match = re.search(r'(\d)', name)
            if num_match:
                prop = _resolve_property_by_num(num_match.group(1))

    # (c) Multi-casa + afirmación sin selección → preguntar qué casa
    houses_count = len(quote.get('houses', []))
    if not prop and is_affirmative and houses_count > 1:
        # Setear estado: estamos esperando la selección
        ctx['magic_awaiting_house'] = quote['check_in']
        session.conversation_context = ctx
        session.save(update_fields=['conversation_context'])

        house_names = [h.get('name', '') for h in quote['houses']]
        if len(house_names) > 1:
            names_str = ', '.join(house_names[:-1]) + ' o ' + house_names[-1]
        else:
            names_str = house_names[0]

        response = (
            f"¡Genial! 😊 ¿Qué casa quieres separar: {names_str}?"
        )
        logger.info(
            f"Guard G_MAGIC_LINK (ask_house): houses={houses_count} "
            f"session={session.id}"
        )
        return {
            'response': response,
            'intent': 'guard:magic_link:ask_house',
            'tool_call_meta': {
                'name': 'guard',
                'guard': 'magic_link',
                'phase': 'ask_house',
                'houses_count': houses_count,
            },
        }

    # (d) Sin property resolvable y no aplicó la pregunta → fallback
    if not prop:
        return None

    # === Generar (o reusar) magic link con prop resuelto ===
    from apps.clients.magic_link_service import find_or_create_magic_link

    try:
        magic, raw_token, was_reused = find_or_create_magic_link(
            client=session.client,
            chat_session=session,
            wa_id=session.wa_id,
            check_in=check_in,
            check_out=check_out,
            guests=guests,
            property=prop,
        )
    except ValueError as e:
        logger.warning(f"G_MAGIC_LINK rate limit / validation: {e}")
        return None
    except Exception as e:
        logger.error(f"G_MAGIC_LINK generation error: {e}", exc_info=True)
        return None

    # Reuso: si solo tenemos hash en BD, intentar recuperar el raw de context
    if was_reused and not raw_token:
        cached = (session.conversation_context or {}).get('active_magic_link') or {}
        if cached.get('magic_link_id') == str(magic.id):
            raw_token = cached.get('token')
        if not raw_token:
            logger.info(
                "G_MAGIC_LINK reuse hit pero raw no está cacheado — fallback"
            )
            return None

    # Cachear raw + metadata, limpiar awaiting (idempotente)
    ctx = session.conversation_context or {}
    ctx['active_magic_link'] = {
        'magic_link_id': str(magic.id),
        'token': raw_token,
        'expires_at': magic.expires_at.isoformat(),
        'property_slug': prop.slug if prop else None,
        'check_in': check_in.isoformat(),
        'check_out': check_out.isoformat(),
        'guests': guests,
    }
    ctx.pop('magic_awaiting_house', None)
    session.conversation_context = ctx
    session.save(update_fields=['conversation_context'])

    magic_url = f"https://casaaustin.pe/r/{raw_token}"
    name = session.client.first_name or 'amigo'
    casa_label = prop.name if prop else 'la casa'

    response = (
        f"Perfecto {name} 😊 Como ya tenemos tus datos registrados, "
        f"te dejo un link directo para continuar tu reserva en {casa_label}:\n\n"
        f"{magic_url}\n\n"
        f"Ahí confirmas los datos, revisas el monto y separas con el 50%."
    )

    logger.info(
        f"Guard G_MAGIC_LINK (send_link): client={session.client_id} "
        f"magic_link_id={magic.id} reused={was_reused} "
        f"prop={prop.slug if prop else None} session={session.id}"
    )

    return {
        'response': response,
        'intent': 'guard:magic_link',
        'tool_call_meta': {
            'name': 'guard',
            'guard': 'magic_link',
            'phase': 'send_link',
            'magic_link_id': str(magic.id),
            'was_reused': was_reused,
            'property_slug': prop.slug if prop else None,
        },
    }


# ============================================================================
# G_EXPRESS — Reserva Express simplificado (sin DNI por chat)
# ============================================================================
# El DNI y datos personales se llenan en el formulario web. El bot solo
# entrega el magic link con fechas/casa precargadas. La casa es OPCIONAL.
#
# Estados (conversation_context):
#   express_phase = 'awaiting_house' (única fase intermedia)
#   express_draft = {check_in, check_out, guests, property_slug?,
#                    houses_in_quote?, booking_url, source}
#   express_house_turns = int (timeout para destrabar)
#
# Activación inicial (sin estado previo):
#   - EXPRESS_RESERVATION_ENABLED=True
#   - session.client_id is None (cliente nuevo)
#   - mensaje matchea _AFFIRMATIVE_RE o _CASA_REF_RE
#   - hay cotización previa parseable

_DNI_DIGITS_RE = re.compile(r'\b(\d{8})\b')

_NO_DNI_INDICATORS_PATTERNS = [
    r'\bpasaporte\b',
    r'\bcarnet\s+de\s+extranjer[ií]a\b',
    r'\bcarnet\s+extranjer[ií]a\b',
    r'\bextranjer[oa]\b',
    r'\bno\s+tengo\s+dni\b',
    r'\bsin\s+dni\b',
    r'\bdocumento\s+extranjero\b',
]
_NO_DNI_INDICATORS_RE = re.compile(
    '|'.join(_NO_DNI_INDICATORS_PATTERNS), re.IGNORECASE,
)

_DECLINE_DNI_PATTERNS = [
    r'\bno\s+(?:quiero|deseo)\s+(?:dar|enviar|compartir)\b',
    r'\bdespu[eé]s\b',
    r'\bm[aá]s\s+tarde\b',
    r'\b(?:no\s+)?(?:lo\s+)?tengo\s+a\s+(?:la\s+)?mano\b',
    r'\bno\s+ahora\b',
]
_DECLINE_DNI_RE = re.compile(
    '|'.join(_DECLINE_DNI_PATTERNS), re.IGNORECASE,
)

_CONFIRM_NAME_PATTERNS = [
    r'^\s*s[ií]\s*[.!?]?\s*$',
    r'^\s*correcto\s*[.!?]?\s*$',
    r'^\s*ok(?:ay)?\s*[.!?]?\s*$',
    r'^\s*est[aá]\s+bien\s*[.!?]?\s*$',
    r'^\s*confirmado\s*[.!?]?\s*$',
    r'^\s*dale\s*[.!?]?\s*$',
    r'^\s*exacto\s*[.!?]?\s*$',
    r'\bes\s+correcto\b',
    r'\bs[ií]\s+est[aá]\s+bien\b',
    r'\bs[ií],?\s+(?:soy|correcto|exacto)\b',
]
_CONFIRM_NAME_RE = re.compile(
    '|'.join(_CONFIRM_NAME_PATTERNS), re.IGNORECASE,
)

_DENY_NAME_PATTERNS = [
    r'^\s*no\s*[.!?]?\s*$',
    r'\bno\s+soy\s+yo\b',
    r'\best[aá]\s+mal\b',
    r'\bincorrecto\b',
    r'\bhay\s+(?:un\s+)?error\b',
    r'\bno\s+es\s+correcto\b',
    r'\bese\s+no\s+soy\b',
]
_DENY_NAME_RE = re.compile(
    '|'.join(_DENY_NAME_PATTERNS), re.IGNORECASE,
)

# "Sin preferencia de casa" — el cliente no tiene preferencia o quiere
# elegir en la web. Generamos el link multi-casa y que decida ahí.
_NO_HOUSE_PREF_PATTERNS = [
    r'^\s*no\s*[.!?]?\s*$',
    r'\bcualquier[a]?\b',
    r'\bninguna\s+(?:en\s+)?especial\b',
    r'\bno\s+(?:tengo|s[eé])\b',
    r'\bda(?:me)?\s+igual\b',
    r'\bme\s+da\s+igual\b',
    r'\bsin\s+preferencia\b',
    r'\bno\s+importa\b',
    r'\bcualquiera\s+(?:est[aá]\s+bien|me\s+vale|me\s+sirve)\b',
    r'\ben\s+la\s+web\s+(?:elijo|veo|decido)\b',
    r'\b(?:el|ese|este|tu)\s+link\b',  # "dame el link", "el link"
    r'\benv[ií]a(?:me)?\s+el\s+link\b',
    r'\bgen[eé]ra(?:me)?\s+el\s+link\b',
    r'\bm[aá]nda(?:me)?\s+el\s+link\b',
]
_NO_HOUSE_PREF_RE = re.compile(
    '|'.join(_NO_HOUSE_PREF_PATTERNS), re.IGNORECASE,
)

# "Saltar DNI" — cliente prefiere no dar DNI por chat
_SKIP_DNI_PATTERNS = [
    r'\bno\s+(?:tengo|me\s+(?:s[eé]|acuerdo))\s+(?:el\s+)?dni\b',
    r'\bsin\s+dni\b',
    r'\b(?:lo\s+)?completo\s+(?:después|despu[eé]s|en\s+la\s+web|all[aá])\b',
    r'\b(?:lo\s+)?pongo\s+(?:después|despu[eé]s|en\s+la\s+web|all[aá])\b',
    r'\b(?:salt[aá](?:rme|telo)?|skip)\b',
    r'\bdame\s+el\s+link\s+(?:nom[aá]s|sin\s+dni|igual)\b',
    r'\b(?:no\s+quiero|prefiero\s+no)\s+(?:dar|enviar|compartir)\s+(?:el\s+)?dni\b',
    r'\bdespu[eé]s\s+(?:lo\s+)?(?:pongo|coloco|env[ií]o)\b',
    # NUEVO: caso wa=51938... ("Lo haré por la web gracias")
    r'\b(?:lo\s+)?(?:har[eé]|hago|har[aá]|haz)\s+(?:en\s+la\s+web|por\s+(?:la\s+)?web|all[aá])\b',
    r'\b(?:reservo|reservar[eé]|registro|registrar[eé])\s+(?:en\s+la\s+web|por\s+(?:la\s+)?web|directamente)\b',
    r'\b(?:ya\s+)?lo\s+veo\s+(?:en\s+la\s+web|all[aá])\b',
]
_SKIP_DNI_RE = re.compile(
    '|'.join(_SKIP_DNI_PATTERNS), re.IGNORECASE,
)


def _express_manual_required_response(session, intro=None):
    """Construye la respuesta + tool_call_meta para derivar a WhatsApp humano."""
    from django.conf import settings
    support_wa = getattr(
        settings, 'RESERVATION_SUPPORT_WHATSAPP', '51999902992',
    )
    intro = intro or (
        "Por ahora, el registro automático solo está disponible con DNI peruano."
    )
    response = (
        f"{intro}\n\n"
        "Si tienes pasaporte o carnet de extranjería, escríbenos por "
        f"WhatsApp para ayudarte a crear tu cuenta y continuar con tu "
        f"reserva:\n\nhttps://wa.me/{support_wa}"
    )
    # Marcar manual_required en el contexto para que el modelo no
    # re-active el flujo en el siguiente turno.
    ctx = session.conversation_context or {}
    ctx['express_phase'] = 'manual_required'
    ctx['express_manual_required'] = True
    session.conversation_context = ctx
    session.save(update_fields=['conversation_context'])
    return {
        'response': response,
        'intent': 'guard:express:manual_required',
        'tool_call_meta': {
            'name': 'guard',
            'guard': 'express',
            'phase': 'manual_required',
        },
    }


def _clear_express_state(session):
    """Limpia el flujo express del conversation_context."""
    ctx = session.conversation_context or {}
    for k in (
        'express_phase', 'express_draft', 'express_dni',
        'express_full_name', 'express_attempt_count',
        'express_manual_required', 'express_house_turns',
        'express_invalid_dni_count',
    ):
        ctx.pop(k, None)
    session.conversation_context = ctx
    session.save(update_fields=['conversation_context'])


def _emit_express_link(session, ctx, dni=None, full_name=None, prop=None):
    """Genera (o reúsa) un magic link express con lo que tengamos.

    Args:
        session: ChatSession.
        ctx: conversation_context actual (mutable).
        dni: opcional. Si está, debe haber sido validado vs RENIEC.
        full_name: opcional. Solo si dni también.
        prop: Property opcional. Si None, el frontend pide casa.

    Returns:
        Dict de respuesta del guard (response + intent) o None si falló.
    """
    from datetime import datetime as _dt

    draft = ctx.get('express_draft') or {}
    try:
        check_in = _dt.strptime(draft['check_in'], '%Y-%m-%d').date()
        check_out = _dt.strptime(draft['check_out'], '%Y-%m-%d').date()
        guests = int(draft['guests'])
    except Exception as e:
        logger.error(f"G_EXPRESS draft parse error: {e}", exc_info=True)
        _clear_express_state(session)
        return None

    from apps.clients.magic_link_service import create_express_magic_link
    try:
        magic, raw_token, was_reused = create_express_magic_link(
            chat_session=session,
            wa_id=session.wa_id,
            document_number=dni,
            validated_full_name=full_name,
            check_in=check_in,
            check_out=check_out,
            guests=guests,
            property=prop,
        )
    except ValueError as e:
        logger.warning(f"G_EXPRESS magic link blocked: {e} session={session.id}")
        _clear_express_state(session)
        return None
    except Exception as e:
        logger.error(f"G_EXPRESS magic link error: {e}", exc_info=True)
        _clear_express_state(session)
        return None

    # Reuso sin raw cacheado → abortar (raro)
    if was_reused and not raw_token:
        cached = ctx.get('active_magic_link') or {}
        if cached.get('magic_link_id') == str(magic.id):
            raw_token = cached.get('token')
        if not raw_token:
            logger.info("G_EXPRESS reuse sin raw cacheado — abortar magic")
            _clear_express_state(session)
            return None

    # Persistir + limpiar state express
    ctx = session.conversation_context or {}
    ctx['active_magic_link'] = {
        'magic_link_id': str(magic.id),
        'token': raw_token,
        'expires_at': magic.expires_at.isoformat(),
        'property_slug': prop.slug if prop else None,
        'check_in': check_in.isoformat(),
        'check_out': check_out.isoformat(),
        'guests': guests,
        'link_type': 'guest_express',
        'has_dni': bool(dni),
    }
    for k in (
        'express_phase', 'express_draft', 'express_dni',
        'express_full_name', 'express_attempt_count',
        'express_manual_required', 'express_house_turns',
        'express_invalid_dni_count',
    ):
        ctx.pop(k, None)
    session.conversation_context = ctx
    session.save(update_fields=['conversation_context'])

    # Construir respuesta dependiendo de qué datos tengamos.
    # NOTA: incluimos siempre "👆 Haz click aquí" + recordatorio de
    # urgencia (link válido 1h) para mejorar la tasa de consumo.
    url = f"https://casaaustin.pe/r/{raw_token}"
    if dni and full_name and prop:
        first_name = full_name.split()[0] if full_name else ''
        msg = (
            f"¡Listo {first_name}! 😊 Toca aquí para terminar tu reserva:\n\n"
            f"👉 {url}\n\n"
            f"✅ Ya dejé precargados:\n"
            f"   • {prop.name}\n"
            f"   • Tu DNI y nombre\n"
            f"   • Las fechas y cantidad de personas\n\n"
            f"Solo confirma y separas con el 50% para asegurar la fecha."
        )
    elif dni and full_name and not prop:
        first_name = full_name.split()[0] if full_name else ''
        msg = (
            f"¡Listo {first_name}! 😊 Toca aquí para terminar tu reserva:\n\n"
            f"👉 {url}\n\n"
            f"✅ Ya dejé tu DNI y nombre precargados. Solo eliges la "
            f"casa en la web y separas con el 50%."
        )
    elif prop and not dni:
        msg = (
            f"¡Listo! 😊 Toca aquí para terminar tu reserva en {prop.name}:\n\n"
            f"👉 {url}\n\n"
            f"Completas tus datos y separas con el 50% para asegurar la fecha."
        )
    else:
        # Anónimo total — solo fechas/personas precargadas
        msg = (
            f"¡Listo! 😊 Toca aquí para terminar tu reserva:\n\n"
            f"👉 {url}\n\n"
            f"Elige tu casa favorita, completas tus datos y separas con el 50%."
        )

    logger.info(
        f"G_EXPRESS (link_sent): session={session.id} "
        f"magic_link_id={magic.id} reused={was_reused} "
        f"prop={prop.slug if prop else 'none'} has_dni={bool(dni)}"
    )

    return {
        'response': msg,
        'intent': 'guard:express:link_sent',
        'tool_call_meta': {
            'name': 'guard', 'guard': 'express',
            'phase': 'link_sent',
            'magic_link_id': str(magic.id),
            'was_reused': was_reused,
            'property_slug': prop.slug if prop else None,
            'has_dni': bool(dni),
        },
    }


def _resolve_express_property(session, quote, last_user_text):
    """Resuelve la Property para Reserva Express buscando en este orden:

    1) URL del quote tiene `property=slug` → single-casa.
    2) Quote single-casa (1 house) → resolver por número del nombre.
    3) Mensaje actual del cliente menciona "Casa N" y esa casa está en el quote.
    4) Historial reciente (últimos 8 mensajes inbound) menciona "Casa N" y
       esa casa está en el quote.

    Returns:
        Property | None
    """
    from apps.property.models import Property

    if not quote:
        return None

    houses = quote.get('houses', []) or []

    # (1) URL trae property=
    if 'property=' in (quote.get('booking_url') or ''):
        m = re.search(r'property=([^&]+)', quote['booking_url'])
        if m:
            p = Property.objects.filter(slug=m.group(1), deleted=False).first()
            if p:
                return p

    # (2) Quote single-casa → resolver por número del nombre
    if len(houses) == 1:
        name = houses[0].get('name', '') or ''
        num_m = re.search(r'(\d)', name)
        if num_m:
            p = _resolve_property_by_num(num_m.group(1))
            if p:
                return p

    # Helper: ¿esa casa N está en el quote actual?
    def _casa_in_quote(num):
        return any(re.search(rf'\b{num}\b', h.get('name', '') or '') for h in houses)

    # (3) Mensaje actual menciona "Casa N"
    if last_user_text:
        m = _CASA_REF_RE.search(last_user_text)
        if m:
            num = int(m.group(1))
            if _casa_in_quote(num):
                return _resolve_property_by_num(num)
        # Forma laxa: "la 3", "3" — solo aplica si quote es multi-casa
        if len(houses) > 1:
            lax = _CASA_REF_LAX_RE.search(last_user_text.strip())
            if lax:
                num = int(lax.group(1) or lax.group(2))
                if _casa_in_quote(num):
                    return _resolve_property_by_num(num)

    # (4) Historial inbound reciente
    inbound = ChatMessage.objects.filter(
        session=session, deleted=False,
        direction=ChatMessage.DirectionChoices.INBOUND,
    ).order_by('-created')[:8]
    for msg in inbound:
        text = (msg.content or '')
        m = _CASA_REF_RE.search(text)
        if m:
            num = int(m.group(1))
            if _casa_in_quote(num):
                return _resolve_property_by_num(num)

    return None


def _build_full_name_from_reniec(data):
    """Concatena preNombres + apePaterno + apeMaterno → string limpio.

    ReniecService.lookup() retorna el dict envuelto en {'data': {...}}, así
    que primero desempaquetamos si vemos esa estructura.
    """
    if isinstance(data, dict) and isinstance(data.get('data'), dict):
        data = data['data']
    nombres = (data.get('preNombres') or '').strip()
    ap_p = (data.get('apePaterno') or '').strip()
    ap_m = (data.get('apeMaterno') or '').strip()
    parts = [p for p in (nombres, ap_p, ap_m) if p]
    return ' '.join(parts) if parts else ''


def try_express_dni_flow(session, last_user_text):
    """G_EXPRESS — flujo de Reserva Express simplificado (sin DNI por chat).

    El cliente recibe un magic link al confirmar que quiere reservar.
    El DNI y datos personales se completan en el formulario web.

    Máquina de estados:
        Entry → (si multi-casa) awaiting_house → link_sent
              ↘ (si single-casa o casa identificable) link_sent directo

    Si el feature flag está OFF, NO entra (return None) y todo cae a R1.0.
    """
    from django.conf import settings

    if not getattr(settings, 'EXPRESS_RESERVATION_ENABLED', False):
        return None
    if not last_user_text:
        return None
    if not session:
        return None

    ctx = session.conversation_context or {}
    phase = ctx.get('express_phase')

    # === Stale state cleanup: si recotizó otras fechas, limpiar ===
    if phase:
        quote = _get_full_last_quote(session)
        draft_check_in = (ctx.get('express_draft') or {}).get('check_in')
        if quote and draft_check_in and quote['check_in'] != draft_check_in:
            logger.info(
                f"G_EXPRESS stale state: cotización cambió, reset. "
                f"session={session.id}"
            )
            _clear_express_state(session)
            return None  # cae al modelo / otros guards

    # === Entry inicial: sin estado, sin session.client, hay cotización ===
    if not phase:
        if session.client_id:
            return None  # cliente existente → R4.1 (G_MAGIC_LINK) maneja
        quote = _get_full_last_quote(session)
        if not quote:
            return None

        # Solo activamos si el cliente:
        #   (a) afirmó querer reservar ("sí", "dale", "me interesa", etc.) o
        #   (b) mencionó "Casa N" específica (intención de elegir).
        has_affirmative = bool(_AFFIRMATIVE_RE.search(last_user_text))
        has_casa_ref = bool(_CASA_REF_RE.search(last_user_text))
        if not (has_affirmative or has_casa_ref):
            return None

        # Resolver property (URL del quote, single-casa, "Casa N" en historial)
        prop = _resolve_express_property(session, quote, last_user_text)
        houses_count = len(quote.get('houses', []) or [])

        # CASO 1: tenemos property identificada → link DIRECTO ✅
        if prop:
            # Setear draft mínimo y emitir
            ctx['express_draft'] = {
                'check_in': quote['check_in'],
                'check_out': quote['check_out'],
                'guests': quote['guests'],
                'booking_url': quote.get('booking_url'),
                'property_slug': prop.slug,
                'source': 'chatbot',
            }
            session.conversation_context = ctx
            session.save(update_fields=['conversation_context'])
            logger.info(
                f"G_EXPRESS direct link (single-casa o casa identificada) "
                f"session={session.id} prop={prop.slug}"
            )
            return _emit_express_link(session, ctx, dni=None, full_name=None, prop=prop)

        # CASO 2: multi-casa sin elección → pregunta SUAVE
        if houses_count > 1:
            ctx['express_phase'] = 'awaiting_house'
            ctx['express_draft'] = {
                'check_in': quote['check_in'],
                'check_out': quote['check_out'],
                'guests': quote['guests'],
                'houses_in_quote': [h.get('name', '') for h in quote.get('houses', [])],
                'booking_url': quote.get('booking_url'),
                'source': 'chatbot',
            }
            ctx['express_house_turns'] = 0
            session.conversation_context = ctx
            session.save(update_fields=['conversation_context'])
            house_names = [h.get('name', '') for h in quote['houses']]
            names_str = (
                ', '.join(house_names[:-1]) + ' o ' + house_names[-1]
                if len(house_names) > 1 else (house_names[0] if house_names else '')
            )
            logger.info(
                f"G_EXPRESS phase=awaiting_house session={session.id} "
                f"houses={houses_count}"
            )
            return {
                'response': (
                    f"¡Genial! 😊 ¿Tienes alguna casa preferida "
                    f"({names_str}) o te envío el link y eliges en la web?"
                ),
                'intent': 'guard:express:ask_house',
                'tool_call_meta': {
                    'name': 'guard', 'guard': 'express',
                    'phase': 'awaiting_house',
                    'houses_count': houses_count,
                },
            }

        # CASO 3: sin houses → no debería pasar pero por seguridad
        return None

    # === Phase: awaiting_house ===
    if phase == 'awaiting_house':
        text_lower = last_user_text.lower().strip()

        # 1) Cliente dijo "no/cualquiera/dame el link" → link sin casa
        if _NO_HOUSE_PREF_RE.search(last_user_text):
            logger.info(
                f"G_EXPRESS awaiting_house → link sin casa (sin preferencia) "
                f"session={session.id}"
            )
            return _emit_express_link(session, ctx, dni=None, full_name=None, prop=None)

        # 2) ¿Es pregunta? → dejar pasar al LLM/G_FAQ, mantener state
        is_question = bool(
            '?' in last_user_text or '¿' in last_user_text
            or re.search(
                r'\b(qu[eé]|cu[aá]l|cu[aá]ntas?|c[oó]mo|d[oó]nde|tiene|tienen|hay|'
                r'diferencia|incluye|cabe|capacidad|fotos?|videos?|im[aá]genes?|'
                r'piscina|jacuzzi|parrilla|cochera|wifi|mascot|ni[ñn]os?|'
                r'precio|cuesta|cu[aá]nto|costo|tama[ñn]o|metros?)\b',
                text_lower,
            )
        )

        # 3) ¿Eligió "Casa N"?
        casa_num = None
        m = _CASA_REF_RE.search(last_user_text)
        if m:
            casa_num = int(m.group(1))
        elif not is_question:
            lax = _CASA_REF_LAX_RE.search(text_lower)
            if lax:
                casa_num = int(lax.group(1) or lax.group(2))

        if not casa_num:
            # No es elección clara → dejar pasar al LLM/G_FAQ
            ctx['express_house_turns'] = int(ctx.get('express_house_turns', 0)) + 1
            if ctx['express_house_turns'] >= 5:
                # Tras 5 turnos sin decidir → link sin casa para destrabar
                logger.info(
                    f"G_EXPRESS awaiting_house timeout → link sin casa "
                    f"session={session.id}"
                )
                return _emit_express_link(session, ctx, dni=None, full_name=None, prop=None)
            session.conversation_context = ctx
            session.save(update_fields=['conversation_context'])
            return None

        # Validar que la casa esté en el quote
        draft = ctx.get('express_draft') or {}
        house_names = draft.get('houses_in_quote', []) or []
        in_quote = any(re.search(rf'\b{casa_num}\b', n) for n in house_names)
        if not in_quote:
            names_str = (
                ', '.join(house_names[:-1]) + ' o ' + house_names[-1]
                if len(house_names) > 1 else (house_names[0] if house_names else '')
            )
            return {
                'response': (
                    f"Esa casa no está disponible para esas fechas 😅 "
                    f"Las opciones son: {names_str}. ¿Cuál prefieres? "
                    f"(o dime 'cualquiera' y te envío el link)"
                ),
                'intent': 'guard:express:house_not_in_quote',
                'tool_call_meta': {
                    'name': 'guard', 'guard': 'express',
                    'phase': 'awaiting_house',
                },
            }

        prop = _resolve_property_by_num(casa_num)
        if not prop:
            # Si no se puede resolver, link sin casa
            return _emit_express_link(session, ctx, dni=None, full_name=None, prop=None)

        # Casa elegida → link DIRECTO con esa casa ✅
        logger.info(
            f"G_EXPRESS awaiting_house → link con Casa {casa_num} "
            f"session={session.id} prop={prop.slug}"
        )
        return _emit_express_link(session, ctx, dni=None, full_name=None, prop=prop)

    # Phase desconocida → log + reset
    logger.warning(
        f"G_EXPRESS phase desconocida: {phase!r} session={session.id}"
    )
    _clear_express_state(session)
    return None
