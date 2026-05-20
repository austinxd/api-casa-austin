"""Acciones rápidas (botones) que dispara el modal Negocio de jarvis.

Cada acción es una función pura: recibe ChatSession + params opcionales,
ejecuta el efecto (mandar mensaje, regenerar link, registrar descuento,
escalar a humano) y devuelve un dict serializable {success, message_sent,
result_detail}.

Las acciones son registradas en QUICK_ACTIONS y se invocan desde la view
AdminQuickActionView via /api/v1/chatbot/quick-actions/.

Para agregar una nueva acción:
    1. Definir función _action_xxx(session, **kwargs) → dict.
    2. Registrar en QUICK_ACTIONS = {'action_id': _action_xxx}.
    3. Si querés que aparezca como botón, agregarla también en
       scoring._suggested_actions_for_stage().
"""
import logging
import secrets
import string
from datetime import timedelta

from django.conf import settings
from django.utils import timezone

from .models import ChatMessage, ChatSession
from .channel_sender import get_sender

logger = logging.getLogger(__name__)


def _send_message(session, text, intent='manual_action'):
    """Envía mensaje por el canal correcto y guarda ChatMessage."""
    sender = get_sender(session.channel)
    wa_message_id = sender.send_text_message(session.wa_id, text)
    msg = ChatMessage.objects.create(
        session=session,
        direction=ChatMessage.DirectionChoices.OUTBOUND_AI,
        message_type=ChatMessage.MessageTypeChoices.TEXT,
        content=text,
        wa_message_id=wa_message_id,
        intent_detected=intent,
    )
    # Actualizar metadata de la sesión
    now = timezone.now()
    session.last_message_at = now
    session.total_messages = (session.total_messages or 0) + 1
    session.ai_messages = (session.ai_messages or 0) + 1
    session.save(update_fields=['last_message_at', 'total_messages', 'ai_messages'])
    return wa_message_id, msg


def _action_send_fresh_link(session, **kwargs):
    """Regenera magic link basándose en la última cotización y lo envía."""
    from apps.clients.magic_link_models import ReservationMagicLink
    from apps.clients.magic_link_service import (
        find_or_create_magic_link,
        create_express_magic_link,
        MagicLinkSecurityError,
    )

    last_quote = (
        ReservationMagicLink.objects.filter(chat_session=session, deleted=False)
        .order_by('-created').first()
    )
    if not last_quote or not last_quote.property_id:
        return {
            'success': False,
            'error': 'no_previous_quote',
            'result_detail': 'No hay cotización previa con propiedad para regenerar el link.',
        }

    fresh_url = None
    try:
        if session.client_id and getattr(settings, 'MAGIC_LINK_ENABLED', False):
            _m, raw, _ = find_or_create_magic_link(
                chat_session=session, wa_id=session.wa_id,
                client=session.client,
                check_in=last_quote.check_in,
                check_out=last_quote.check_out,
                guests=last_quote.guests,
                property=last_quote.property,
            )
            if raw:
                fresh_url = f"https://casaaustin.pe/r/{raw}"
        elif not session.client_id and getattr(settings, 'EXPRESS_RESERVATION_ENABLED', False):
            _m, raw, _ = create_express_magic_link(
                chat_session=session, wa_id=session.wa_id,
                check_in=last_quote.check_in,
                check_out=last_quote.check_out,
                guests=last_quote.guests,
                property=last_quote.property,
            )
            if raw:
                fresh_url = f"https://casaaustin.pe/r/{raw}"
    except MagicLinkSecurityError as e:
        return {'success': False, 'error': 'security_check_failed', 'result_detail': e.reason}
    except Exception as e:
        logger.exception("send_fresh_link error")
        return {'success': False, 'error': 'generation_failed', 'result_detail': str(e)}

    if not fresh_url:
        return {
            'success': False, 'error': 'no_link_generated',
            'result_detail': 'No se pudo generar magic link (config deshabilitada o falta info).',
        }

    text = (
        f"{last_quote.property.name} · {last_quote.check_in.strftime('%d/%m')} "
        f"al {last_quote.check_out.strftime('%d/%m')} · {last_quote.guests} personas\n\n"
        f"💳 Reservar y pagar ahora (link válido 1h):\n{fresh_url}"
    )
    _send_message(session, text, intent='manual_fresh_link')
    return {
        'success': True,
        'message_sent': text,
        'result_detail': f"Magic link nuevo enviado: {fresh_url}",
    }


def _generate_discount_code(prefix='WAJV'):
    """Código de 8 chars únicos."""
    alphabet = string.ascii_uppercase + string.digits
    suffix = ''.join(secrets.choice(alphabet) for _ in range(4))
    return f"{prefix}{suffix}"


def _action_offer_discount_10(session, **kwargs):
    """Crea un DiscountCode de 10% válido 48h y se lo manda al cliente."""
    from apps.property.pricing_models import DiscountCode

    code = _generate_discount_code()
    today = timezone.now().date()
    try:
        DiscountCode.objects.create(
            code=code,
            description=f"Descuento manual ofrecido por intervención (sesión {session.id})",
            discount_type=DiscountCode.DiscountType.PERCENTAGE,
            discount_value=10,
            max_discount_usd=200,
            start_date=today,
            end_date=today + timedelta(days=2),
            usage_limit=1,
            is_active=True,
        )
    except Exception as e:
        logger.exception("offer_discount_10 create code error")
        return {'success': False, 'error': 'discount_create_failed', 'result_detail': str(e)}

    text = (
        f"🎁 Te ofrecemos un descuento del *10%* exclusivo para vos.\n\n"
        f"Tu código: *{code}*\n"
        f"Válido por 48h. Aplícalo al separar tu reserva.\n\n"
        f"¿Te animás? 😊"
    )
    _send_message(session, text, intent='manual_discount_offer')
    return {
        'success': True,
        'message_sent': text,
        'result_detail': f"Código {code} creado (10% off, válido 48h) y enviado.",
    }


def _action_intervene_human(session, **kwargs):
    """Pausa el AI, marca sesión como escalada — el operador toma control."""
    now = timezone.now()
    session.ai_enabled = False
    session.ai_paused_at = now
    session.status = 'escalated'
    session.save(update_fields=['ai_enabled', 'ai_paused_at', 'status', 'updated'])
    return {
        'success': True,
        'message_sent': None,
        'result_detail': (
            f"Sesión {session.id} marcada como escalada. "
            f"El AI está pausado, el operador puede responder manualmente."
        ),
    }


def _action_ask_objection(session, **kwargs):
    """Manda un mensaje plantilla preguntando objeción específica."""
    text = (
        "Para ayudarte mejor, ¿hay algo puntual que te frene en este momento? "
        "¿Es el precio, la fecha, la capacidad, o algo de la casa? "
        "Si me cuentas, te armo una alternativa 😊"
    )
    _send_message(session, text, intent='manual_ask_objection')
    return {
        'success': True,
        'message_sent': text,
        'result_detail': "Mensaje de indagación de objeción enviado.",
    }


# ─── Registry de acciones disponibles ───
QUICK_ACTIONS = {
    'send_fresh_link': _action_send_fresh_link,
    'offer_discount_10': _action_offer_discount_10,
    'intervene_human': _action_intervene_human,
    'ask_objection': _action_ask_objection,
}


def execute_action(action_id, session, **kwargs):
    """Dispatcher principal — usado por la view."""
    fn = QUICK_ACTIONS.get(action_id)
    if not fn:
        return {
            'success': False,
            'error': 'unknown_action',
            'result_detail': f"Acción '{action_id}' no existe. Disponibles: {list(QUICK_ACTIONS.keys())}",
        }
    try:
        return fn(session, **kwargs)
    except Exception as e:
        logger.exception(f"quick_action {action_id} failed")
        return {
            'success': False,
            'error': 'execution_failed',
            'result_detail': str(e),
        }
