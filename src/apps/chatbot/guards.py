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
