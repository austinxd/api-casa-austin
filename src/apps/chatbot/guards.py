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
