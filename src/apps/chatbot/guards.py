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
