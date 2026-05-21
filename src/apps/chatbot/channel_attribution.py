"""Lógica de inferencia de canal de atribución.

Decide cuál es el `touch_channel` de una reserva (canal del touchpoint
inmediato que la trajo) y, si es la primera reserva pagada del cliente,
setea su `acquisition_channel` (canal de adquisición — inmutable).

Modelo conceptual:
- **touch_channel** (per reserva): puede repetirse o cambiar entre
  reservas del mismo cliente. Mide retención por canal.
- **acquisition_channel** (per cliente): se setea UNA SOLA VEZ en la
  primera reserva aprobada del cliente. Mide adquisición.

Orden de prioridad para inferir `touch_channel`:
1. Si `reservation.chatbot_session.referral_source` tiene source_type=ad
   → 'meta_ad' (alta confianza — Meta nos dijo explícitamente)
2. Si touch_data trae utm_source=facebook/meta/fb O fbclid → 'meta_ad'
3. Si touch_data trae utm_source=google O gclid → 'google'
4. Si touch_data trae utm_source distinto y reconocible → ese
5. Si tiene chatbot_session vinculada → 'organic_wa' (entró por WhatsApp
   sin venir de un anuncio CTW conocido — orgánico/marca/saved contact)
6. Si tiene touch_data (UTMs cualquier) → 'web_direct'
7. Si client.referred_by → 'referral'
8. Default → 'unknown'
"""
import logging
from typing import Tuple

from apps.core.channel_choices import ChannelChoice

logger = logging.getLogger(__name__)


# Aprobada = cuenta como adquisición. Statuses intermedios no.
ACQUISITION_TRIGGER_STATUS = 'approved'


def infer_touch_channel(reservation) -> Tuple[str, dict]:
    """Infiere el canal de la reserva basándose en signals disponibles.

    Devuelve (channel, data_dict). El data_dict es lo que se guarda en
    `touch_data` — incluye un breve resumen del razonamiento más toda
    la data raw disponible.
    """
    data = dict(reservation.touch_data or {})
    chatbot_session = getattr(reservation, 'chatbot_session', None)

    # 1. Meta CTW capturado en webhook → alta confianza
    if chatbot_session and chatbot_session.referral_source:
        ref = chatbot_session.referral_source
        if isinstance(ref, dict) and ref.get('source_type') == 'ad':
            data['_attribution_reason'] = 'meta_ctw_referral'
            data['_ad_id'] = ref.get('source_id')
            data['_ctwa_clid'] = ref.get('ctwa_clid')
            return ChannelChoice.META_AD, data

    # 2. UTM/fbclid apuntan a Meta
    utm_source = (data.get('utm_source') or '').lower()
    fbclid = data.get('fbclid')
    if fbclid or utm_source in ('facebook', 'meta', 'fb', 'instagram', 'ig'):
        data['_attribution_reason'] = 'utm_or_fbclid_meta'
        return ChannelChoice.META_AD, data

    # 3. UTM/gclid apuntan a Google
    gclid = data.get('gclid')
    if gclid or utm_source in ('google', 'google_ads', 'adwords'):
        data['_attribution_reason'] = 'utm_or_gclid_google'
        return ChannelChoice.GOOGLE, data

    # 4. UTM con source reconocible pero no Meta/Google
    if utm_source:
        data['_attribution_reason'] = f'utm_source:{utm_source}'
        # Lo guardamos como web_direct con utm_source en data —
        # el dashboard puede mostrarlo desglosado por utm_source.
        return ChannelChoice.WEB_DIRECT, data

    # 5. Sesión de chatbot sin referral → WhatsApp orgánico
    if chatbot_session:
        data['_attribution_reason'] = 'chatbot_session_without_referral'
        return ChannelChoice.ORGANIC_WA, data

    # 6. Hay touch_data pero sin UTM_SOURCE reconocible → web directa
    if data and any(k.startswith('utm_') or k in ('fbclid', 'gclid') for k in data.keys()):
        data['_attribution_reason'] = 'touch_data_no_utm_source'
        return ChannelChoice.WEB_DIRECT, data

    # 7. Cliente referido por otro cliente
    if reservation.client_id and reservation.client and reservation.client.referred_by_id:
        data['_attribution_reason'] = 'client_referred_by'
        data['_referred_by'] = str(reservation.client.referred_by_id)
        return ChannelChoice.REFERRAL, data

    # 8. Default
    data['_attribution_reason'] = 'no_signals'
    return ChannelChoice.UNKNOWN, data


def apply_touch_channel(reservation, force: bool = False) -> str:
    """Infiere y persiste el touch_channel en la reserva.

    Solo lo setea si no estaba ya (a menos que force=True). No toca
    otros campos. Retorna el canal aplicado (o el existente si ya tenía).
    """
    if reservation.touch_channel and not force:
        return reservation.touch_channel
    try:
        channel, data = infer_touch_channel(reservation)
        reservation.touch_channel = channel
        reservation.touch_data = data
        reservation.save(update_fields=['touch_channel', 'touch_data', 'updated'])
        logger.info(
            f"Touch channel inferido para reserva {reservation.id}: "
            f"{channel} (reason={data.get('_attribution_reason')})"
        )
        return channel
    except Exception as e:
        logger.error(
            f"Error inferiendo touch_channel para reserva {reservation.id}: {e}",
            exc_info=True,
        )
        return ChannelChoice.UNKNOWN


def maybe_set_acquisition(reservation) -> bool:
    """Si esta es la primera reserva aprobada del cliente, setea su
    `acquisition_channel` (inmutable). Retorna True si se seteó.

    Reglas:
    - Solo se setea si client.acquisition_channel está vacío.
    - Solo si la reserva está en status='approved' (cuenta como pagada).
    - Solo si no hay reserva previa aprobada del mismo cliente.

    Esto se llama desde el signal cuando status cambia a 'approved' O
    cuando una reserva se crea ya en approved (admin path).
    """
    if not reservation.client_id:
        return False
    if reservation.status != ACQUISITION_TRIGGER_STATUS:
        return False

    client = reservation.client
    if client.acquisition_channel:
        return False  # ya tiene canal de adquisición — inmutable

    # Verificar que no haya reserva previa aprobada (esta debe ser la primera)
    from apps.reservation.models import Reservation
    prior_approved_exists = Reservation.objects.filter(
        client_id=client.id,
        deleted=False,
        status=ACQUISITION_TRIGGER_STATUS,
        created__lt=reservation.created,
    ).exists()
    if prior_approved_exists:
        return False  # no es adquisición — es retención

    # Si esta reserva no tiene touch_channel todavía, inferirlo ahora.
    touch_channel = reservation.touch_channel or apply_touch_channel(reservation)

    try:
        client.acquisition_channel = touch_channel
        client.acquisition_data = dict(reservation.touch_data or {})
        client.acquired_at = reservation.created
        client.save(update_fields=[
            'acquisition_channel', 'acquisition_data', 'acquired_at', 'updated',
        ])
        logger.info(
            f"Adquisición registrada — client {client.id} via {touch_channel} "
            f"(reservation {reservation.id})"
        )
        return True
    except Exception as e:
        logger.error(
            f"Error seteando acquisition_channel para client {client.id}: {e}",
            exc_info=True,
        )
        return False
