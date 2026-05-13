"""Helpers para localizar reservas desde el chatbot (R3.1).

Permite encontrar la reserva relevante de una sesión sin pedir DNI cuando
el teléfono del WhatsApp coincide con datos existentes en la base. Incluye
un cross-check de seguridad: si el cliente da un DNI cuyo Client tiene un
teléfono distinto al wa_id actual, NO se revelan datos de la reserva.
"""
import re
from datetime import timedelta

from django.db.models import Q
from django.utils import timezone


# Reservas "vivas" para el flujo de claim.
RESERVATION_ACTIVE_STATUSES = (
    'incomplete', 'pending', 'under_review', 'approved',
)
# Estados que sí buscamos (para info al cliente) pero no son "activos".
RESERVATION_INFO_STATUSES = ('cancelled', 'rejected')
RESERVATION_SEARCHABLE_STATUSES = (
    RESERVATION_ACTIVE_STATUSES + RESERVATION_INFO_STATUSES
)


def normalize_phone(value):
    """Normaliza un teléfono peruano a 9 dígitos.

    Ejemplos:
        '+51 999 123 456' → '999123456'
        '51999123456'     → '999123456'
        '999123456'       → '999123456'
        '999-123-456'     → '999123456'
        None / ''         → None
        '123'             → None  (muy corto)
    """
    if not value:
        return None
    digits = re.sub(r'\D', '', str(value))
    if not digits:
        return None
    # Strip country code Perú si está
    if digits.startswith('51') and len(digits) >= 11:
        digits = digits[2:]
    if len(digits) < 9:
        return None
    return digits[-9:]


def client_phone_matches_wa_id(client, wa_id):
    """Cross-check de seguridad para R3.3 (parcial en R3.1).

    Retorna True si:
        - El cliente NO tiene tel_number registrado (fail-open).
        - El tel_number normalizado coincide con el wa_id normalizado.
    Retorna False si hay un tel_number distinto al wa_id (mismatch real).
    """
    if not client or not wa_id:
        return True
    client_tel = (getattr(client, 'tel_number', None) or '').strip()
    if not client_tel:
        return True
    return normalize_phone(client_tel) == normalize_phone(wa_id)


def find_active_reservation_for_session(session, recent_minutes=60):
    """Busca la reserva más relevante para esta sesión.

    Orden:
      1. Reservation.chatbot_session = session  (atribución directa)
      2. session.client (si está vinculado)
      3. wa_id normalizado ↔ Reservation.tel_contact_number

    Cada path filtra por status válidos y por
    (check_out_date >= today  OR  created >= now - recent_minutes).
    Dentro de cada path, prioriza ACTIVE_STATUSES sobre cancelled/rejected,
    luego la más cercana por check_in_date.

    Returns:
        dict | None: {'reservation': <Reservation>, 'match_type': str}
    """
    from apps.reservation.models import Reservation

    if not session:
        return None

    today = timezone.now().date()
    recent_cutoff = timezone.now() - timedelta(minutes=recent_minutes)

    # === 1. chatbot_session (atribución directa de la conversación) ===
    r = Reservation.objects.filter(
        chatbot_session=session,
        deleted=False,
        status__in=RESERVATION_SEARCHABLE_STATUSES,
    ).select_related('property').order_by('-created').first()
    if r:
        return {'reservation': r, 'match_type': 'chatbot_session'}

    # === 2. session.client (verified link) ===
    if session.client:
        client_rs = list(
            Reservation.objects.filter(
                client=session.client,
                deleted=False,
                status__in=RESERVATION_SEARCHABLE_STATUSES,
            ).filter(
                Q(check_out_date__gte=today) | Q(created__gte=recent_cutoff)
            ).select_related('property').order_by('check_in_date')
        )
        actives = [x for x in client_rs if x.status in RESERVATION_ACTIVE_STATUSES]
        if actives:
            return {'reservation': actives[0], 'match_type': 'session_client'}
        if client_rs:
            return {'reservation': client_rs[0], 'match_type': 'session_client'}

    # === 3. wa_id ↔ tel_contact_number ===
    wa_norm = normalize_phone(getattr(session, 'wa_id', None))
    if wa_norm:
        candidates = Reservation.objects.filter(
            deleted=False,
            status__in=RESERVATION_SEARCHABLE_STATUSES,
        ).exclude(
            tel_contact_number__isnull=True
        ).exclude(
            tel_contact_number=''
        ).filter(
            Q(check_out_date__gte=today) | Q(created__gte=recent_cutoff)
        ).select_related('property').order_by('check_in_date')[:200]

        actives_match, info_match = [], []
        for r in candidates:
            if normalize_phone(r.tel_contact_number) == wa_norm:
                if r.status in RESERVATION_ACTIVE_STATUSES:
                    actives_match.append(r)
                else:
                    info_match.append(r)
        if actives_match:
            actives_match.sort(key=lambda x: x.check_in_date)
            return {'reservation': actives_match[0], 'match_type': 'wa_id_tel'}
        if info_match:
            info_match.sort(key=lambda x: x.created, reverse=True)
            return {'reservation': info_match[0], 'match_type': 'wa_id_tel'}

    return None


def scenario_from_reservation(r):
    """Mapea Reservation → (scenario, copy, needs_notify, notify_reason).

    Returns dict | None.
    """
    if not r:
        return None

    if r.status == 'rejected':
        return {
            'scenario': 'rejected',
            'copy': (
                "Gracias 😊 Ya avisé al equipo para que pueda revisar tu caso."
            ),
            'needs_notify': True,
            'notify_reason': 'reservation_claimed_rejected',
        }

    if r.status == 'cancelled':
        return {
            'scenario': 'cancelled',
            'copy': (
                "Veo que esa reserva está cancelada. Si quieres armar una "
                "nueva, te ayudo a cotizar 😊"
            ),
            'needs_notify': False,
            'notify_reason': None,
        }

    if r.status == 'approved':
        if r.full_payment:
            return {
                'scenario': 'approved_full',
                'copy': (
                    "Perfecto 😊 Tu reserva ya figura confirmada. Te "
                    "enviaremos/recordaremos los detalles de ingreso antes "
                    "de tu llegada."
                ),
                'needs_notify': False,
                'notify_reason': None,
            }
        return {
            'scenario': 'approved_with_advance',
            'copy': (
                "Tu reserva está confirmada con el adelanto 😊 Recuerda que "
                "el saldo se completa antes del check-in."
            ),
            'needs_notify': False,
            'notify_reason': None,
        }

    if r.status in ('pending', 'under_review'):
        return {
            'scenario': 'pending_or_review',
            'copy': (
                "Perfecto 😊 Veo tu reserva registrada. El equipo validará "
                "el pago/voucher y te confirmará por este medio."
            ),
            'needs_notify': True,
            'notify_reason': 'reservation_claimed_pending',
        }

    if r.status == 'incomplete':
        if r.payment_voucher_uploaded:
            return {
                'scenario': 'incomplete_with_voucher',
                'copy': (
                    "Perfecto 😊 Veo tu voucher recibido. El equipo lo "
                    "validará y te confirmará por este medio."
                ),
                'needs_notify': True,
                'notify_reason': 'reservation_claimed_voucher_uploaded',
            }
        return {
            'scenario': 'incomplete_no_voucher',
            'copy': (
                "Veo una reserva iniciada, pero aún no figura como separada. "
                "Si ya realizaste el pago o subiste voucher, el equipo lo "
                "validará."
            ),
            'needs_notify': True,
            'notify_reason': 'reservation_claimed_incomplete',
        }

    return None
