"""Atribución automática de reservas al chatbot.

Caso de uso: el bot cotiza al cliente, le manda magic link, pero el
cliente termina creando la reserva por otra vía (web directa, voucher
manual subido, link de cotización pública, etc.). Sin atribución, la
reserva queda con `chatbot_session=NULL` y NO se cuenta en el funnel
del bot, aunque el bot fue claramente quien convirtió.

Regla: si hay una `ChatSession` del mismo cliente con `quoted_at` en
las últimas 72 horas, se atribuye esa sesión a la reserva nueva.

Disparadores:
1. Signal `post_save` en `Reservation`: al crearse, intenta atribuir.
   Si el cliente acaba de hacer la reserva post-cotización, se linkea.
2. Management command `backfill_chatbot_attribution`: recorre reservas
   históricas (default últimos 30 días) y atribuye las que matcheen.

Ventana de 72h: balance entre cubrir reservas "del bot pero hechas
por otro path" y evitar falsos positivos (cliente que cotizó hace
semanas y reserva por algo no relacionado).
"""
import logging
from datetime import timedelta
from django.utils import timezone

logger = logging.getLogger(__name__)

# Ventana temporal: cuántas horas atrás buscar ChatSession con cotización.
# Si la cotización del bot fue dentro de este rango, atribuimos.
ATTRIBUTION_WINDOW_HOURS = 72


def attribute_to_chatbot_if_applicable(reservation, force=False):
    """Si hay ChatSession reciente del cliente, vincula la reserva.

    Args:
        reservation: instancia de Reservation.
        force: si True, sobrescribe aunque ya tenga chatbot_session.

    Returns:
        ChatSession atribuida, o None si no se atribuyó.
    """
    if not reservation:
        return None
    # Ya atribuida (a menos que force=True)
    if reservation.chatbot_session_id and not force:
        return reservation.chatbot_session

    if not reservation.client_id:
        return None

    # Importar acá para evitar circulares
    from apps.chatbot.models import ChatSession

    cutoff = timezone.now() - timedelta(hours=ATTRIBUTION_WINDOW_HOURS)

    # Buscar la sesión MÁS RECIENTE del cliente que haya cotizado dentro
    # de la ventana de atribución. quoted_at se setea cuando el bot llama
    # check_availability y muestra precios al cliente.
    session = (
        ChatSession.objects
        .filter(
            client_id=reservation.client_id,
            deleted=False,
            quoted_at__gte=cutoff,
        )
        .order_by('-quoted_at')
        .first()
    )

    if not session:
        return None

    reservation.chatbot_session = session
    reservation.save(update_fields=['chatbot_session', 'updated'])
    logger.info(
        f"Reservation {reservation.id} atribuida a ChatSession {session.id} "
        f"(cliente {reservation.client_id}, quoted_at={session.quoted_at})"
    )
    return session
