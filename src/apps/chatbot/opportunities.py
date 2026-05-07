"""
Oportunidades por fecha — Fase A read-only.

Cruza ChatSession + SearchTracking + Reservation + SpecialDatePricing +
PromoDateSent para encontrar leads que pueden ayudar a llenar el calendario.

Solo lectura: NO genera descuentos, NO envía mensajes, NO escribe en BD.

Entry point: get_opportunities(filters: dict) -> dict
"""
import re
import logging
from collections import defaultdict
from datetime import date, datetime, timedelta
from decimal import Decimal

from django.db.models import Q
from django.utils import timezone

from .models import ChatSession, ChatMessage, PromoDateConfig, PromoDateSent
from .guards import _QUOTE_PRICE_RE  # reusamos el extractor

logger = logging.getLogger(__name__)


# ============================================================================
# Patrones de detección de señales
# ============================================================================

LINK_PATTERNS = [
    r'\benv[ií]a(?:me)?\s+(?:el\s+)?(?:link|enlace)',
    r'\b(?:dame|p[aá]same|manda(?:me)?|m[aá]ndame)\s+(?:el\s+)?(?:link|enlace)\b',
    r'\bp[aá]same\s+(?:el\s+)?link\b',
]

PAYMENT_PATTERNS = [
    r'\b(?:bcp|bbva|interbank|scotiabank|banbif|pichincha)\b',
    r'\byape\b',
    r'\bplin\b',
    r'\bcuenta\s+(?:bancaria|de|del)\b',
    r'\bn[uú]mero\s+de\s+cuenta\b',
    r'\bd[oó]nde\s+(?:dep[oó]sito|deposito|transfiero|pago|transferir)\b',
    r'\bya\s+(?:pagu[eé]|transfer[ií]|dep[oó]sit[eé])\b',
    r'\bya\s+sub[ií]\s+el\s+voucher\b',
    r'\bvoucher\b',
    r'\baceptan?\s+tarjeta\b',
    r'\bc[oó]mo\s+pago\b',
]

WANTS_TO_BOOK_PATTERNS = [
    r'\bquiero\s+(?:pagar|reservar|confirmar|separar)\b',
    r'\bdeseo\s+(?:pagar|reservar|confirmar|alquilar)\b',
    r'\bme\s+anim[oa]\b',
    r'\blist[oa]\s+(?:para\s+)?(?:pagar|reservar)\b',
    r'\bvamos\s+a\s+reservar\b',
    r'\bya\s+voy\s+a\s+(?:pagar|reservar)\b',
    r'\bc[oó]mo\s+(?:reservo|separo|hago\s+la\s+reserva)\b',
]

LOCATION_PATTERNS = [
    r'\bdirecci[oó]n\b',
    r'\bubicaci[oó]n\b',
    r'\bd[oó]nde\s+(?:queda|est[aá])\b',
    r'\bfotos?\b',
    r'\bcheck[\s\-]?in\b',
]

CONSULTING_GROUP_PATTERNS = [
    r'\blo\s+(?:consulto|hablo|veo)\s+con\b',
    r'\b(?:hablo|consulto)\s+con\s+(?:mi|los|el|la)\b',
    r'\bvoy\s+a\s+(?:pensar|consultar|hablar)\b',
    r'\b(?:luego|despu[eé]s)\s+te\s+(?:aviso|confirmo|digo)\b',
    r'\blo\s+pienso\b',
]

LINK_RE = re.compile('|'.join(LINK_PATTERNS), re.IGNORECASE)
PAYMENT_RE = re.compile('|'.join(PAYMENT_PATTERNS), re.IGNORECASE)
WANTS_RE = re.compile('|'.join(WANTS_TO_BOOK_PATTERNS), re.IGNORECASE)
LOCATION_RE = re.compile('|'.join(LOCATION_PATTERNS), re.IGNORECASE)
CONSULTING_RE = re.compile('|'.join(CONSULTING_GROUP_PATTERNS), re.IGNORECASE)


# ============================================================================
# Helpers
# ============================================================================

MONTHS_ES = {
    1: 'enero', 2: 'febrero', 3: 'marzo', 4: 'abril', 5: 'mayo', 6: 'junio',
    7: 'julio', 8: 'agosto', 9: 'septiembre', 10: 'octubre', 11: 'noviembre',
    12: 'diciembre',
}


def _format_dates_es(check_in, check_out):
    """'30 de mayo' o '30 al 31 de mayo' o '30 de mayo al 1 de junio'."""
    if check_in == check_out or check_out is None:
        return f"{check_in.day} de {MONTHS_ES[check_in.month]}"
    if check_in.month == check_out.month:
        return f"{check_in.day} al {check_out.day} de {MONTHS_ES[check_in.month]}"
    return (
        f"{check_in.day} de {MONTHS_ES[check_in.month]} "
        f"al {check_out.day} de {MONTHS_ES[check_out.month]}"
    )


def _select_best_search(searches):
    """De varias búsquedas del mismo cliente, elige la mejor combinación de
    personas y check_out. Misma heurística que send_promo_dates."""
    if not searches:
        return None
    guest_counts = set(s.guests for s in searches)
    counts_gt1 = sorted(g for g in guest_counts if g > 1)
    selected_guests = counts_gt1[0] if counts_gt1 else 1
    matching = [s for s in searches if s.guests == selected_guests]
    return max(matching, key=lambda s: s.search_timestamp)


def _resolve_date_filter(date_filter, today):
    """Convierte el filtro de rango a (start, end) inclusive."""
    if date_filter == 'weekend':
        # Sábado/domingo más cercano
        weekday = today.weekday()  # 0=Lun, 5=Sab, 6=Dom
        if weekday <= 4:  # Lun-Vie → próximo sábado
            days_to_sat = 5 - weekday
        else:  # Sáb/Dom → este finde
            days_to_sat = 0 if weekday == 5 else -1
        sat = today + timedelta(days=days_to_sat)
        return sat, sat + timedelta(days=1)
    if date_filter == 'next_3_days':
        return today, today + timedelta(days=3)
    if date_filter == 'next_7_days':
        return today, today + timedelta(days=7)
    if date_filter == 'next_15_days':
        return today, today + timedelta(days=15)
    # Default
    return today, today + timedelta(days=15)


def _parse_quote_from_messages(messages):
    """Busca la última cotización (property, usd, sol) en los mensajes
    outbound_ai con tool_calls."""
    for msg in messages:
        if msg.direction not in ('outbound_ai', 'outbound_human'):
            continue
        for tc in (msg.tool_calls or []):
            if tc.get('name') not in ('check_availability', 'check_late_checkout'):
                continue
            args = tc.get('arguments') or {}
            blob = (tc.get('result_preview') or '') + '\n' + (msg.content or '')
            m = _QUOTE_PRICE_RE.search(blob)
            if not m:
                continue
            usd_str, sol_str = m.group(1), m.group(2)
            try:
                usd = Decimal(usd_str.replace(',', '.'))
                sol = Decimal(sol_str.replace(',', '.'))
            except Exception:
                continue
            prop_name = args.get('property_name')
            if not prop_name:
                m2 = re.search(r'Casa\s+Austin\s+\d', blob, re.IGNORECASE)
                prop_name = m2.group(0) if m2 else None
            return {
                'property': prop_name or 'la casa cotizada',
                'usd': usd,
                'sol': sol,
            }
    return None


# ============================================================================
# Scoring
# ============================================================================

def _build_signals(messages, search, last_quote, followup_count):
    """Extrae señales binarias del historial de mensajes."""
    inbound_text = ' '.join(
        (m.content or '') for m in messages
        if m.direction == 'inbound'
    ).lower()

    signals = {
        'gave_date': search is not None,
        'gave_guests': search is not None and search.guests >= 2,
        'received_quote': last_quote is not None,
        'asked_for_link': bool(LINK_RE.search(inbound_text)),
        'asked_for_payment': bool(PAYMENT_RE.search(inbound_text)),
        'wants_to_book': bool(WANTS_RE.search(inbound_text)),
        'picked_property': search is not None and search.property_id is not None,
        'asked_for_location': bool(LOCATION_RE.search(inbound_text)),
        'consulting_group': bool(CONSULTING_RE.search(inbound_text)),
        'received_followup': followup_count > 0,
    }

    # ¿Respondió después del follow-up?
    # Buscamos el último OUTBOUND_AI con intent 'followup' o similar y
    # vemos si hay INBOUND posterior. Si followup_count > 0 pero no hay
    # respuesta inbound posterior al último outbound, marcamos negativo.
    if followup_count > 0:
        last_out = next((m for m in messages if m.direction in ('outbound_ai', 'outbound_human')), None)
        if last_out:
            has_inbound_after = any(
                m.direction == 'inbound' and m.created > last_out.created
                for m in messages
            )
            signals['responded_after_followup'] = has_inbound_after
        else:
            signals['responded_after_followup'] = False
    else:
        signals['responded_after_followup'] = False

    return signals


def _compute_lead_score(signals):
    score = 0
    if signals['gave_date']: score += 15
    if signals['gave_guests']: score += 10
    if signals['received_quote']: score += 20
    if signals['asked_for_link']: score += 25
    if signals['asked_for_payment']: score += 15
    if signals['wants_to_book']: score += 20
    if signals['picked_property']: score += 5
    if signals['asked_for_location']: score += 5
    if signals['consulting_group']: score -= 5
    if signals['received_followup'] and not signals['responded_after_followup']:
        score -= 10
    return max(0, min(100, score))


def _compute_date_score(check_in, today, has_available, is_weekend, is_special, preferred_avail):
    if check_in is None or check_in < today:
        return 0
    days_until = (check_in - today).days
    score = 0
    if has_available:
        if days_until <= 3: score += 40
        elif days_until <= 7: score += 25
        elif days_until <= 15: score += 10
    weekday = check_in.weekday()
    is_weekday = weekday in [0, 1, 2, 3, 6]  # Lun-Jue, Dom (negocio: dom-jue=semana)
    if is_weekday:
        score += 15
    if is_weekend and not is_special:
        score += 10
    if is_weekend and is_special:
        score -= 20
    if preferred_avail:
        score += 10
    return max(0, min(100, score))


def _compute_ticket_score(guests, last_quote_usd, nights, is_casa3):
    score = 0
    if guests is None:
        guests = 0
    if guests >= 30: score += 30
    elif guests >= 20: score += 20
    elif guests >= 10: score += 10
    if is_casa3:
        score += 20
    if last_quote_usd is not None:
        usd_f = float(last_quote_usd)
        if usd_f > 1000: score += 25
        elif usd_f > 500: score += 15
    if nights and nights >= 2:
        score += 10
    return max(0, min(100, score))


def _compute_priority(lead, date_s, ticket):
    return round(0.4 * lead + 0.4 * date_s + 0.2 * ticket)


# ============================================================================
# Suggested action / can_offer_benefit / urgency_reason
# ============================================================================

def _suggested_action(priority, has_active_reservation, fecha_disponible,
                     ticket_s, date_s, days_until):
    """Devuelve la acción sugerida.

    Umbrales (ajuste 2026-05-07):
        priority >= 70 → Contactar hoy
        priority >= 50 → Follow-up personalizado
        priority >= 35 → Seguimiento suave
        priority <  35 → Baja prioridad

    Override por ticket alto:
        ticket >= 60 AND check-in dentro de 0-3 días → Contactar hoy
        ticket >= 50 AND date >= 50 → mínimo Follow-up personalizado
    """
    if has_active_reservation:
        return "No contactar: ya reservó"
    if not fecha_disponible:
        return "No contactar: fecha no disponible"

    # Override #1: ticket muy alto + fecha muy cercana
    if ticket_s >= 60 and days_until is not None and 0 <= days_until <= 3:
        return "Contactar hoy"

    # Override #2: ticket+date suficientes para empujar a "Follow-up"
    if ticket_s >= 50 and date_s >= 50:
        if priority >= 70:
            return "Contactar hoy"
        return "Follow-up personalizado"

    # Default por priority
    if priority >= 70: return "Contactar hoy"
    if priority >= 50: return "Follow-up personalizado"
    if priority >= 35: return "Seguimiento suave"
    return "Baja prioridad"


def _can_offer_benefit(lead_s, date_s, ticket_s, fecha_disponible, is_special,
                       in_cooldown, has_active_reservation):
    """Determina si se puede sugerir beneficio especial.

    Reglas (ajuste 2026-05-07):
        Bloqueado si:
            - tiene reserva activa
            - fecha no disponible
            - SpecialDatePricing (fecha alta demanda)
            - cooldown de promo reciente
            - lead_score >= 80 (muy caliente, no quemar margen)

        Permitido si:
            - date_score >= 50, O
            - ticket_score >= 50 AND date_score >= 50 (override de ticket alto)
    """
    blocked_reasons = []
    if has_active_reservation:
        blocked_reasons.append("active_reservation")
    if not fecha_disponible:
        blocked_reasons.append("date_unavailable")
    if is_special:
        blocked_reasons.append("special_date")
    if in_cooldown:
        blocked_reasons.append("recent_promo")
    if lead_s >= 80:
        blocked_reasons.append("high_lead_score")

    # Excepción de ticket alto: bypassa el bloqueo por low_date_score
    high_ticket_override = (ticket_s >= 50 and date_s >= 50)
    if not high_ticket_override and date_s < 50:
        blocked_reasons.append("low_date_score")

    if blocked_reasons:
        return False, blocked_reasons[0]
    return True, None


def _urgency_reason(check_in, today, signals, search, has_available,
                    preferred_avail, is_weekend, is_special, last_quote,
                    ticket_s):
    days_until = (check_in - today).days if check_in else 999
    guests = search.guests if search else None

    candidates = []

    # === Top priority: ticket alto + fecha cercana ===
    if ticket_s >= 60 and days_until <= 3 and has_available:
        if guests and guests >= 20:
            candidates.append(f"Fecha cercana + grupo {guests} personas + ticket alto")
        else:
            candidates.append("Ticket alto + fecha cercana")
    elif ticket_s >= 50 and days_until <= 7 and has_available:
        if guests and guests >= 20:
            candidates.append(f"Fecha cercana + casa disponible + grupo {guests}+")

    # === Señales de cierre ===
    if (signals['asked_for_link'] or signals['asked_for_payment']) and has_available:
        candidates.append("Pidió pago/link + fecha disponible")
    if signals['wants_to_book'] and has_available:
        candidates.append("Quiere reservar + fecha disponible")

    # === Urgencia por fecha ===
    if days_until <= 3 and has_available:
        candidates.append("Fecha cercana + casa disponible")

    # === Volumen / valor ===
    if search and guests and guests >= 20 and last_quote:
        candidates.append("Grupo 20+ + cotización reciente")

    # === Match exacto casa preferida ===
    if preferred_avail:
        candidates.append("Casa consultada sigue disponible")

    # === Fin de semana vacío ===
    if is_weekend and not is_special and has_available and last_quote:
        candidates.append("Fin de semana vacío + lead cotizado")

    if candidates:
        return candidates[0]
    if last_quote:
        return "Lead cotizado sin reserva"
    if search:
        return "Lead con fecha consultada"
    return "Lead activo reciente"


# ============================================================================
# Recommended message
# ============================================================================

def _build_recommended_message(name, search, last_quote, signals, priority,
                               can_offer_benefit, fecha_disponible):
    """Mensaje sugerido corto (NUNCA enviado automáticamente).

    Formato:
        Línea 1: saludo + intro + precio por persona en SOL (si hay).
        Línea blanco.
        Línea 2: CTA (link / cotización / beneficio según prioridad).
        Línea blanco (opcional).
        Línea 3: oferta de beneficio si can_offer_benefit=True.
    """
    if not name:
        name = 'amig@'
    name = name.split()[0] if ' ' in name else name

    fechas_str = ''
    if search:
        fechas_str = _format_dates_es(search.check_in_date, search.check_out_date)

    guests = search.guests if search else None
    per_person_sol = None
    if last_quote and guests:
        try:
            per_person_sol = round(float(last_quote['sol']) / guests)
        except Exception:
            pass

    # === Línea 1: saludo + intro + precio ===
    intro_parts = [f"Hola {name} 😊"]
    if fechas_str:
        intro_parts.append(f"Vi que consultaste para el {fechas_str}.")
    if per_person_sol:
        intro_parts.append(f"La opción salía desde S/{per_person_sol} por persona.")
    intro = " ".join(intro_parts)

    # === Línea 2: CTA ===
    if priority >= 70 and (signals['asked_for_link'] or signals['wants_to_book']):
        cta = "Te paso el link para separarla con el 50% desde casaaustin.pe."
    elif priority >= 35:
        cta = "Si aún te interesa, te paso el link para separarla con el 50%."
    else:
        cta = "Te dejo a la mano la cotización por si la estás revisando con tu grupo."

    msg = f"{intro}\n\n{cta}"

    # === Línea 3 opcional: beneficio especial ===
    if can_offer_benefit:
        msg += "\n\nTambién puedo consultar si aplica algún beneficio especial para esa fecha."

    return msg


# ============================================================================
# Availability map
# ============================================================================

def _build_availability_map(reservations, properties, date_start, date_end):
    """Para cada (property_id, check_in, check_out) en el rango, computa el
    estado de disponibilidad. Se computa al vuelo en _availability_status_for
    consultando la lista de reservas."""
    # Indexar por property_id para búsquedas rápidas
    by_prop = defaultdict(list)
    for r in reservations:
        by_prop[r['property_id']].append(r)
    return by_prop


def _availability_status_for(property_id, check_in, check_out, reservations_by_prop):
    """Devuelve el primer estado de bloqueo encontrado, o 'available'.
    Prioridad: approved > under_review > pending > incomplete."""
    if check_in is None or check_out is None:
        return 'unknown'
    conflicts = []
    for r in reservations_by_prop.get(property_id, []):
        # Conflict logic: existing.check_in < new.check_out AND existing.effective_checkout > new.check_in
        eff_checkout = r['check_out_date']
        if r.get('late_check_out_date') and r['late_check_out_date'] > r['check_out_date']:
            eff_checkout = r['late_check_out_date']
        if r['check_in_date'] < check_out and eff_checkout > check_in:
            conflicts.append(r['status'])
    if not conflicts:
        return 'available'
    # Prioridad
    for status in ('approved', 'under_review', 'pending', 'incomplete'):
        if status in conflicts:
            return f'blocked_{status}'
    return 'blocked_unknown'


# ============================================================================
# Main entry point
# ============================================================================

def get_opportunities(filters=None):
    """Cruza ChatSession + SearchTracking + Reservation para devolver
    oportunidades comerciales scoreadas y ordenadas por priority.

    filters: dict con keys opcionales:
        date_filter: 'weekend' | 'next_3_days' | 'next_7_days' | 'next_15_days'
        min_guests: int
        property_id: UUID
        availability_only: bool
        quoted_no_reservation: bool
        min_score: int
        last_message_from: 'bot' | 'customer' | 'all'
        inactive_hours: int
        page: int
        page_size: int

    Returns:
        dict {count, results, page, page_size, computed_at}
    """
    from apps.property.models import Property
    from apps.property.pricing_models import SpecialDatePricing
    from apps.reservation.models import Reservation
    from apps.clients.models import SearchTracking

    filters = filters or {}
    today = date.today()
    now = timezone.now()

    started_at = timezone.now()

    # === Resolver filtro de fecha ===
    date_filter = filters.get('date_filter') or 'next_15_days'
    date_start, date_end = _resolve_date_filter(date_filter, today)

    page = max(1, int(filters.get('page') or 1))
    page_size = min(50, max(1, int(filters.get('page_size') or 25)))
    inactive_hours = filters.get('inactive_hours')
    last_message_from = (filters.get('last_message_from') or 'all').lower()

    # === 1. Sessions candidatas (SQL filter ligero) ===
    activity_cutoff = now - timedelta(days=30)
    sessions_qs = ChatSession.objects.filter(
        deleted=False,
        last_customer_message_at__gte=activity_cutoff,
    ).select_related('client').order_by('-last_customer_message_at')[:500]

    sessions = list(sessions_qs)
    if not sessions:
        return _empty_response(page, page_size, started_at)

    session_ids = [s.id for s in sessions]
    client_ids = [s.client_id for s in sessions if s.client_id]
    wa_ids = [s.wa_id for s in sessions]

    # === 2. SearchTracking en rango ===
    chatbot_session_keys = [f'chatbot_{w}' for w in wa_ids]
    search_qs = SearchTracking.objects.filter(
        Q(client_id__in=client_ids) | Q(session_key__in=chatbot_session_keys),
        check_in_date__gte=date_start,
        check_in_date__lte=date_end,
    ).select_related('property').order_by('-search_timestamp')

    # Agrupar
    search_by_client = defaultdict(list)
    search_by_session_key = defaultdict(list)
    for st in search_qs:
        if st.client_id:
            search_by_client[st.client_id].append(st)
        if st.session_key:
            search_by_session_key[st.session_key].append(st)

    # === 3. Mensajes recientes (para signals + last_quote) ===
    recent_msgs = ChatMessage.objects.filter(
        session_id__in=session_ids,
        deleted=False,
    ).only('session_id', 'direction', 'content', 'created', 'tool_calls').order_by(
        'session_id', '-created',
    )
    msgs_by_session = defaultdict(list)
    for m in recent_msgs:
        if len(msgs_by_session[m.session_id]) < 30:
            msgs_by_session[m.session_id].append(m)

    # === 4. Active reservations (availability map) ===
    reservations = list(Reservation.objects.filter(
        deleted=False,
        status__in=['approved', 'pending', 'incomplete', 'under_review'],
        check_in_date__lte=date_end + timedelta(days=2),
        check_out_date__gte=date_start,
    ).values('property_id', 'check_in_date', 'check_out_date',
             'late_check_out_date', 'status', 'client_id'))

    avail_by_prop = _build_availability_map(reservations, None, date_start, date_end)

    # === 5. Properties ===
    properties = list(Property.objects.filter(deleted=False).order_by('player_id'))
    casa3_ids = {
        p.id for p in properties
        if (p.player_id or '').lower() == 'ca3' or 'austin 3' in (p.name or '').lower()
    }

    # === 6. Special dates por (month, day, property_id) ===
    special_dates_qs = SpecialDatePricing.objects.filter(
        is_active=True, deleted=False,
    ).values('property_id', 'month', 'day')
    special_set = set(
        (sd['month'], sd['day'], sd['property_id']) for sd in special_dates_qs
    )
    # Set sin property (cualquier propiedad)
    special_any_property = set(
        (sd['month'], sd['day']) for sd in special_dates_qs
    )

    # === 7. Cooldown (PromoDateConfig) ===
    cooldown_days = 7
    try:
        promo_config = PromoDateConfig.objects.first()
        if promo_config:
            cooldown_days = max(0, int(getattr(promo_config, 'cooldown_days', 7) or 7))
    except Exception:
        pass

    cooldown_cutoff = now - timedelta(days=cooldown_days)
    clients_in_cooldown = set()
    if cooldown_days > 0:
        clients_in_cooldown = set(
            PromoDateSent.objects.filter(
                created__gte=cooldown_cutoff,
                deleted=False,
                client_id__isnull=False,
            ).values_list('client_id', flat=True)
        )

    # === 8. Reservas activas por cliente (para "ya reservó esa fecha") ===
    client_active_reservations = defaultdict(list)
    for r in reservations:
        if r.get('client_id'):
            client_active_reservations[r['client_id']].append(r)

    # === 9. Iterar sessions y construir candidatos ===
    results = []
    for session in sessions:
        candidate = _build_candidate(
            session=session,
            search_by_client=search_by_client,
            search_by_session_key=search_by_session_key,
            msgs_by_session=msgs_by_session,
            properties=properties,
            avail_by_prop=avail_by_prop,
            casa3_ids=casa3_ids,
            special_set=special_set,
            special_any_property=special_any_property,
            client_active_reservations=client_active_reservations,
            clients_in_cooldown=clients_in_cooldown,
            today=today,
            now=now,
        )
        if candidate is None:
            continue
        results.append(candidate)

    # === 10. Aplicar filtros post-scoring ===
    min_guests = filters.get('min_guests')
    property_id_filter = filters.get('property_id')
    availability_only = filters.get('availability_only', False)
    quoted_no_reservation = filters.get('quoted_no_reservation', False)
    min_score = filters.get('min_score')

    def passes(c):
        if min_guests and (c['search'] is None or c['search']['guests'] < int(min_guests)):
            return False
        if property_id_filter:
            if c['search'] is None or str(c['search'].get('property_id') or '') != str(property_id_filter):
                return False
        if availability_only and not c['_fecha_disponible']:
            return False
        if quoted_no_reservation:
            if c['last_quote'] is None or c['_has_active_reservation']:
                return False
        if min_score is not None and c['scores']['priority'] < int(min_score):
            return False
        if last_message_from in ('bot', 'customer'):
            target = 'outbound_ai' if last_message_from == 'bot' else 'inbound'
            if c['_last_message_direction'] != target:
                return False
            # Si filtramos por bot, agregar también outbound_human (caso humano respondió)
            if last_message_from == 'bot' and c['_last_message_direction'] == 'inbound':
                return False
        if inactive_hours is not None:
            cutoff = now - timedelta(hours=int(inactive_hours))
            if c['_last_inbound_at'] is None:
                return False
            if c['_last_inbound_at'] >= cutoff:
                return False
        return True

    filtered = [c for c in results if passes(c)]

    # === 11. Ordenar por priority desc + last_message desc (tiebreak) ===
    filtered.sort(
        key=lambda c: (
            -c['scores']['priority'],
            -(c['_last_message_at'].timestamp() if c['_last_message_at'] else 0),
        )
    )

    # === 12. Paginar ===
    total = len(filtered)
    offset = (page - 1) * page_size
    page_items = filtered[offset:offset + page_size]

    # Limpiar campos privados (los que empiezan con _)
    cleaned = []
    for c in page_items:
        cleaned.append({k: v for k, v in c.items() if not k.startswith('_')})

    elapsed_ms = (timezone.now() - started_at).total_seconds() * 1000

    return {
        'count': total,
        'page': page,
        'page_size': page_size,
        'date_filter': date_filter,
        'date_start': date_start.isoformat(),
        'date_end': date_end.isoformat(),
        'elapsed_ms': round(elapsed_ms, 1),
        'results': cleaned,
    }


def _empty_response(page, page_size, started_at):
    elapsed_ms = (timezone.now() - started_at).total_seconds() * 1000
    return {
        'count': 0, 'page': page, 'page_size': page_size,
        'elapsed_ms': round(elapsed_ms, 1), 'results': [],
    }


def _build_candidate(session, search_by_client, search_by_session_key,
                     msgs_by_session, properties, avail_by_prop, casa3_ids,
                     special_set, special_any_property,
                     client_active_reservations, clients_in_cooldown,
                     today, now):
    """Arma un candidate dict con todos los campos esperados o devuelve None
    si no califica como oportunidad."""
    # === Resolver SearchTracking del cliente o sesión ===
    searches = []
    if session.client_id:
        searches = search_by_client.get(session.client_id, [])
    if not searches:
        searches = search_by_session_key.get(f'chatbot_{session.wa_id}', [])

    best_search = _select_best_search(searches)
    msgs = msgs_by_session.get(session.id, [])
    last_quote = _parse_quote_from_messages(msgs)

    # Sin SearchTracking en rango Y sin cotización → no es oportunidad
    if not best_search and not last_quote:
        return None

    check_in = best_search.check_in_date if best_search else None
    check_out = best_search.check_out_date if best_search else None
    guests = best_search.guests if best_search else None
    nights = (check_out - check_in).days if check_in and check_out else None

    # Excluir fecha pasada
    if check_in and check_in < today:
        return None

    # === Reserva activa del cliente para esa fecha ===
    has_active_reservation = False
    if session.client_id and check_in and check_out:
        for r in client_active_reservations.get(session.client_id, []):
            if r['check_in_date'] < check_out and r['check_out_date'] > check_in:
                has_active_reservation = True
                break

    # === Disponibilidad por propiedad ===
    available_properties = []
    fecha_disponible = False
    preferred_avail = False
    preferred_property_id = best_search.property_id if best_search else None

    if check_in and check_out:
        for p in properties:
            status = _availability_status_for(p.id, check_in, check_out, avail_by_prop)
            avail = (status == 'available')
            available_properties.append({
                'id': str(p.id),
                'name': p.name,
                'available': avail,
                'availability_status': status,
            })
            if avail:
                fecha_disponible = True
                if preferred_property_id and p.id == preferred_property_id:
                    preferred_avail = True

    # === SpecialDatePricing ===
    is_special = False
    if check_in:
        if (check_in.month, check_in.day) in special_any_property:
            is_special = True

    # === Weekend? ===
    is_weekend = False
    if check_in:
        is_weekend = check_in.weekday() in [4, 5]  # Vie, Sáb (negocio)

    # === Signals ===
    signals = _build_signals(msgs, best_search, last_quote, session.followup_count)

    # === Scores ===
    is_casa3 = preferred_property_id in casa3_ids if preferred_property_id else False
    last_quote_usd = last_quote['usd'] if last_quote else None

    lead_s = _compute_lead_score(signals)
    date_s = _compute_date_score(
        check_in, today, fecha_disponible, is_weekend, is_special, preferred_avail,
    )
    ticket_s = _compute_ticket_score(guests, last_quote_usd, nights, is_casa3)
    priority = _compute_priority(lead_s, date_s, ticket_s)

    # === can_offer_benefit ===
    in_cooldown = session.client_id in clients_in_cooldown if session.client_id else False
    can_offer, blocked_reason = _can_offer_benefit(
        lead_s, date_s, ticket_s, fecha_disponible, is_special,
        in_cooldown, has_active_reservation,
    )

    # === Suggested action ===
    days_until = (check_in - today).days if check_in else None
    action = _suggested_action(
        priority, has_active_reservation, fecha_disponible,
        ticket_s, date_s, days_until,
    )

    # === Lead stage ===
    if has_active_reservation:
        stage = 'customer'
    elif lead_s >= 70:
        stage = 'hot'
    elif lead_s >= 40:
        stage = 'warm'
    else:
        stage = 'cold'

    # === Urgency reason ===
    urgency = _urgency_reason(
        check_in, today, signals, best_search, fecha_disponible,
        preferred_avail, is_weekend, is_special, last_quote, ticket_s,
    )

    # === Recommended message ===
    name = (session.client.first_name if session.client else None) or session.wa_profile_name
    recommended = _build_recommended_message(
        name, best_search, last_quote, signals, priority,
        can_offer, fecha_disponible,
    )

    # === Last message ===
    last_msg = msgs[0] if msgs else None
    last_msg_dir = last_msg.direction if last_msg else None
    last_msg_at = last_msg.created if last_msg else session.last_message_at
    last_inbound = next(
        (m for m in msgs if m.direction == 'inbound'), None,
    )
    last_inbound_at = last_inbound.created if last_inbound else None

    # === Per-person SOL ===
    per_person_sol = None
    if last_quote and guests:
        try:
            per_person_sol = round(float(last_quote['sol']) / guests)
        except Exception:
            pass

    # === Build response dict ===
    last_quote_out = None
    if last_quote:
        last_quote_out = {
            'property': last_quote['property'],
            'usd': str(last_quote['usd']),
            'sol': str(last_quote['sol']),
            'per_person_sol': per_person_sol,
        }

    return {
        'session_id': str(session.id),
        'client': {
            'id': str(session.client.id) if session.client else None,
            'first_name': session.client.first_name if session.client else None,
            'last_name': session.client.last_name if session.client else None,
            'tel_number': session.client.tel_number if session.client else None,
        } if session.client else None,
        'channel': session.channel,
        'wa_id': session.wa_id,
        'wa_profile_name': session.wa_profile_name,
        'search': {
            'check_in': check_in.isoformat() if check_in else None,
            'check_out': check_out.isoformat() if check_out else None,
            'guests': guests,
            'property_id': str(best_search.property_id) if best_search and best_search.property_id else None,
            'property_name': best_search.property.name if best_search and best_search.property else None,
            'search_timestamp': best_search.search_timestamp.isoformat() if best_search else None,
        } if best_search else None,
        'available_properties': available_properties,
        'preferred_property_available': preferred_avail if preferred_property_id else None,
        'last_quote': last_quote_out,
        'last_message_at': last_msg_at.isoformat() if last_msg_at else None,
        'last_message_from': last_msg_dir,
        'lead_stage': stage,
        'scores': {
            'lead': lead_s,
            'date': date_s,
            'ticket': ticket_s,
            'priority': priority,
        },
        'signals': signals,
        'suggested_action': action,
        'urgency_reason': urgency,
        'can_offer_benefit': can_offer,
        'benefit_blocked_reason': blocked_reason,
        'recommended_message': recommended,
        'wa_link': f"https://wa.me/{session.wa_id}" if session.channel == 'whatsapp' else None,
        # Privados (filtrar antes de devolver):
        '_fecha_disponible': fecha_disponible,
        '_has_active_reservation': has_active_reservation,
        '_last_message_at': last_msg_at,
        '_last_message_direction': last_msg_dir,
        '_last_inbound_at': last_inbound_at,
    }
