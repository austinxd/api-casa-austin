"""Helpers para persistir datos de atribución en Reservation.

Se llama desde las vistas de creación de reserva (express, magic-link,
regular) después de crear la Reservation, con el `attribution_data`
recibido del frontend.

`attribution_data` es un dict con UTMs + click IDs capturados al landear:
    {
        "utm_source": "google",
        "utm_medium": "cpc",
        "utm_campaign": "verano2026",
        "fbclid": "...",
        "gclid": "...",
        "captured_at": 1738598400000,
        "landing_page": "/disponibilidad?...",
        "referrer": "https://google.com/..."
    }

Esta capa SOLO persiste — la inferencia del `touch_channel` y el set
del `acquisition_channel` se hacen en `apps/chatbot/channel_attribution.py`
(PR 2 — lógica de atribución).
"""
import logging

logger = logging.getLogger(__name__)


def apply_attribution_to_reservation(reservation, attribution_data):
    """Persiste el `attribution_data` recibido del frontend en la reserva.

    - Llena los campos UTM/fbclid estándar si vienen vacíos (no sobrescribe).
    - Guarda el payload completo en `touch_data` (incluye landing_page,
      referrer, gclid, etc. — todo lo que enviemos desde el frontend).

    No infiere `touch_channel` ni toca `acquisition_channel` — eso es
    lógica de atribución, va en PR 2.
    """
    if not attribution_data or not isinstance(attribution_data, dict):
        return
    try:
        # Standard UTM/click-id fields (ya existían en Reservation)
        for field in ('utm_source', 'utm_medium', 'utm_campaign', 'fbclid'):
            val = attribution_data.get(field)
            if val and not getattr(reservation, field, None):
                setattr(reservation, field, str(val)[:255])
        # Raw snapshot completo
        reservation.touch_data = attribution_data
        reservation.save(update_fields=[
            'utm_source', 'utm_medium', 'utm_campaign', 'fbclid',
            'touch_data', 'updated',
        ])
        logger.info(
            f"Atribución guardada — reserva {reservation.id}, "
            f"utm_source={reservation.utm_source}, fbclid={bool(reservation.fbclid)}"
        )
    except Exception as e:
        logger.error(f"Error guardando atribución en reserva {reservation.id}: {e}")
