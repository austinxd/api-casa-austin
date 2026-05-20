"""Scoring de oportunidades de intervención manual.

Para cada ChatSession activa, calculamos un score 0-100 que estima
qué tan probable es cerrar la venta si un operador interviene AHORA.
Lo consume /api/v1/chatbot/intervention-opportunities/ (Sprint 1 del
rediseño del modal Negocio de jarvis).

Fórmula (negativa o positiva según el caso):

  +30 magic link CREADO pero no abierto (use_count = 0)
  +25 magic link ABIERTO pero no reservó (use_count > 0, used_at None)
  +20 ≥10 mensajes Y sin avance en última hora (sin nuevo magic link)
  +15 objeción detectada en últimos 5 msgs ("caro", "pensar", "mucho", etc.)
  +10 WhatsApp window < 4h restantes (ventana 24h desde último cliente)
  +10 cliente recurrente (≥1 reserva pagada previa)
  + 5 menciona ocasión especial (cumpleaños / aniversario / evento / boda)
  -20 ya tiene reserva activa este mes (no es lead real)
  -50 detectó "no me interesa" / "lo dejo" / "ya reservé en otro lado"

Si score >= 40 entra a la lista de intervenciones. Si >= 60 es "🔥 caliente".
"""
import re
from dataclasses import dataclass, asdict, field
from datetime import timedelta
from typing import List, Optional

from django.utils import timezone

from .models import ChatSession, ChatMessage


# ─── Patrones de detección por regex sobre el contenido ───
_OBJECTION_PATTERNS = [
    r'\b(muy|demasiado|bastante)\s+caro\b',
    r'\b(es|está|esta)\s+caro\b',
    r'\b(lo|la|me|nos)\s+pens(ar|aré|aremos|amos)\b',
    r'\b(voy a|tengo que)\s+pens',
    r'\bmucho\s+(dinero|presupuesto|para nosotros)\b',
    r'\b(no me alcanza|fuera de presupuesto|nuestro presupuesto)\b',
    r'\b(tenemos|tengo)\s+que\s+ver\b',
]
_LOST_PATTERNS = [
    r'\b(no\s+me|ya\s+no\s+me)\s+interesa\b',
    r'\b(lo|la)\s+dejo\b',
    r'\bya\s+reserv(é|amos|aron)\s+(en|con)\s+otr',
    r'\bcontacté\s+a\s+otr',
    r'\bya\s+encontré\b',
    r'\bcanc(elar|ela|elo)\b',
]
_OCCASION_PATTERNS = [
    r'\bcumple(años)?\b',
    r'\baniversario\b',
    r'\b(boda|matrimonio)\b',
    r'\b(despedid[ao]\s+de\s+solter[ao])\b',
    r'\b(evento|fiesta|reuni[óo]n)\b',
    r'\bbautiz[oa]\b',
    r'\bquincea(ñ|n)era\b',
]


@dataclass
class SuggestedAction:
    id: str
    label: str


@dataclass
class Opportunity:
    session_id: str
    wa_id: str
    client_name: Optional[str]
    client_dni: Optional[str]
    client_photo_b64: Optional[str]
    score: int
    reason: str
    last_message_at: Optional[str]
    last_message_preview: str
    funnel_stage: str  # session | quoted | link_created | link_opened | reserved
    wa_window_hours_remaining: Optional[float]
    property_interested: Optional[str]
    guests: Optional[int]
    quote_check_in: Optional[str]
    quote_check_out: Optional[str]
    quote_price_sol: Optional[float]
    quote_price_usd: Optional[float]
    suggested_actions: List[SuggestedAction] = field(default_factory=list)

    def to_dict(self):
        d = asdict(self)
        d['suggested_actions'] = [asdict(a) for a in self.suggested_actions]
        return d


def _detect_pattern(text, patterns):
    text_lower = (text or "").lower()
    for pattern in patterns:
        if re.search(pattern, text_lower):
            return True
    return False


def _funnel_stage(session, last_magic_link, has_reservation):
    """Determina en qué etapa del funnel está la sesión."""
    if has_reservation:
        return 'reserved'
    if last_magic_link:
        if last_magic_link.used_at:
            return 'reserved'  # consumido = reservó
        if last_magic_link.use_count > 0:
            return 'link_opened'
        return 'link_created'
    if session.quoted_at:
        return 'quoted'
    return 'session'


def _suggested_actions_for_stage(stage, has_objection):
    """Acciones recomendadas según etapa + contexto."""
    actions = []
    if stage in ('quoted', 'link_created', 'link_opened'):
        actions.append(SuggestedAction('send_fresh_link', '💳 Enviar link nuevo'))
    if has_objection:
        actions.append(SuggestedAction('offer_discount_10', '🎁 Ofrecer 10% desc'))
    actions.append(SuggestedAction('ask_objection', '❓ Preguntar objeción'))
    actions.append(SuggestedAction('intervene_human', '👤 Tomar conversación'))
    return actions


def calculate_intervention_score(session, *, recent_messages=None):
    """Calcula score + razón + acciones sugeridas para una ChatSession.

    Args:
        session: ChatSession (debe venir con prefetch_related para perf)
        recent_messages: list opcional de últimos N ChatMessages, evita re-query.

    Returns:
        Opportunity dataclass listo para serializar, o None si la sesión
        no califica (score < 40 o reserva ya cerrada hoy o ai_enabled=False
        intervenido manualmente reciente).
    """
    from apps.clients.magic_link_models import ReservationMagicLink
    from apps.reservation.models import Reservation

    score = 0
    reasons = []

    # Mensajes recientes para detectar objeciones / patrones
    if recent_messages is None:
        recent_messages = list(
            ChatMessage.objects.filter(session=session, deleted=False)
            .order_by('-created')[:10]
        )
    last_5_inbound = [
        m.content for m in recent_messages
        if m.direction == ChatMessage.DirectionChoices.INBOUND
    ][:5]
    full_inbound_text = ' '.join(last_5_inbound)

    has_objection = _detect_pattern(full_inbound_text, _OBJECTION_PATTERNS)
    is_lost = _detect_pattern(full_inbound_text, _LOST_PATTERNS)
    has_occasion = _detect_pattern(full_inbound_text, _OCCASION_PATTERNS)

    # Último magic link de esta sesión
    last_magic_link = (
        ReservationMagicLink.objects.filter(chat_session=session, deleted=False)
        .order_by('-created')
        .first()
    )

    # ¿Ya hay reserva pagada vinculada a este chat / cliente?
    has_paid_reservation = False
    has_active_reservation_this_month = False
    if session.client_id:
        now = timezone.now()
        has_paid_reservation = Reservation.objects.filter(
            client_id=session.client_id, deleted=False, status='approved',
        ).exists()
        has_active_reservation_this_month = Reservation.objects.filter(
            client_id=session.client_id, deleted=False, status='approved',
            check_in_date__year=now.year, check_in_date__month=now.month,
        ).exists()

    stage = _funnel_stage(session, last_magic_link, has_active_reservation_this_month)

    # ─── Aplicar fórmula ───
    if stage == 'quoted' and not last_magic_link:
        score += 30
        reasons.append("cotizó sin link")
    elif stage == 'link_created':
        score += 30
        reasons.append("link creado, no abierto")
    elif stage == 'link_opened':
        score += 25
        reasons.append("link abierto, no reservó")

    # Mensajes >= 10 sin avance en última hora
    if session.total_messages and session.total_messages >= 10:
        last_msg_age = (
            (timezone.now() - session.last_message_at).total_seconds() / 60
            if session.last_message_at else 9999
        )
        if last_msg_age > 60 and stage in ('session', 'quoted'):
            score += 20
            reasons.append(f"{session.total_messages} msgs sin progreso")

    if has_objection:
        score += 15
        reasons.append("objeción detectada")

    # WhatsApp window: 24h desde último mensaje INBOUND del cliente
    wa_hours_remaining = None
    if session.last_customer_message_at:
        delta = timezone.now() - session.last_customer_message_at
        wa_hours_remaining = max(0, 24 - delta.total_seconds() / 3600)
        if 0 < wa_hours_remaining < 4:
            score += 10
            reasons.append(f"WA cierra en {wa_hours_remaining:.1f}h")

    if has_paid_reservation:
        score += 10
        reasons.append("cliente recurrente")

    if has_occasion:
        score += 5
        reasons.append("ocasión especial")

    if has_active_reservation_this_month:
        score -= 20
        reasons.append("ya tiene reserva activa")

    if is_lost:
        score -= 50
        reasons.append("manifestó desinterés")

    # Filtros duros (no incluir aunque score sea alto)
    if score < 40:
        return None
    if session.status == 'closed':
        return None
    if session.status == 'escalated':
        # Ya está siendo atendida manualmente — no recomendar de nuevo
        return None

    last_msg_preview = ''
    last_msg = recent_messages[0] if recent_messages else None
    if last_msg:
        last_msg_preview = (last_msg.content or '')[:200]

    # Datos del cliente desde la última cotización
    prop_name = last_magic_link.property.name if (last_magic_link and last_magic_link.property_id) else None
    guests = last_magic_link.guests if last_magic_link else None
    check_in = last_magic_link.check_in.isoformat() if last_magic_link else None
    check_out = last_magic_link.check_out.isoformat() if last_magic_link else None

    # Precios: leer de la última reserva si existe, sino nada
    quote_price_sol = None
    quote_price_usd = None
    # (Para una versión futura podemos extraer del tool_calls del ChatMessage)

    # Datos del cliente (DNI + foto)
    client_name = session.wa_profile_name or (
        f"{session.client.first_name} {session.client.last_name or ''}".strip()
        if session.client_id else None
    )
    client_dni = None
    client_photo_b64 = None
    if session.client_id and session.client.document_type == 'dni':
        client_dni = session.client.number_doc
        try:
            from apps.reniec.models import DNICache
            cache = DNICache.objects.filter(dni=client_dni).first()
            if cache:
                client_photo_b64 = cache.foto
        except Exception:
            pass

    return Opportunity(
        session_id=str(session.id),
        wa_id=session.wa_id,
        client_name=client_name,
        client_dni=client_dni,
        client_photo_b64=client_photo_b64,
        score=score,
        reason=" · ".join(reasons),
        last_message_at=(
            session.last_message_at.isoformat() if session.last_message_at else None
        ),
        last_message_preview=last_msg_preview,
        funnel_stage=stage,
        wa_window_hours_remaining=(
            round(wa_hours_remaining, 1) if wa_hours_remaining is not None else None
        ),
        property_interested=prop_name,
        guests=guests,
        quote_check_in=check_in,
        quote_check_out=check_out,
        quote_price_sol=quote_price_sol,
        quote_price_usd=quote_price_usd,
        suggested_actions=_suggested_actions_for_stage(stage, has_objection),
    )
