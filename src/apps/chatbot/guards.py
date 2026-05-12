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
    executor = ToolExecutor(session)

    scenario = 'unknown'
    if ident['type'] == 'document':
        try:
            executor.execute('identify_client', {'document_number': ident['value']})
            session.refresh_from_db()
        except Exception as e:
            logger.error(f"G4 identify_client failed: {e}", exc_info=True)

        if session.client:
            try:
                check_text = executor.execute('check_reservations', {})
            except Exception as e:
                logger.error(f"G4 check_reservations failed: {e}", exc_info=True)
                check_text = ''
            if 'CONFIRMADA' in check_text:
                scenario = 'approved'
            elif "estado 'pending'" in check_text or "estado 'under_review'" in check_text:
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

    if scenario == 'approved':
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
    if session.client:
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
