"""Service layer para ReservationMagicLink.

- generate_token(): token raw + hash sha256.
- find_or_create_magic_link(): reutiliza link vigente o crea nuevo. Aplica
  rate limit por cliente/hora. **Bloquea generación si client.tel_number
  no coincide con wa_id** (defensa en profundidad: el guard del chatbot
  ya filtra, pero shell/scripts pueden saltarlo).
- get_valid_magic_link_by_token(): busca por hash, valida vigencia.
"""
import base64
import hashlib
import logging
import re
import secrets
from datetime import timedelta

from django.db.models import F
from django.utils import timezone

from .magic_link_models import ReservationMagicLink

logger = logging.getLogger(__name__)


# Defaults
DEFAULT_EXPIRY_MINUTES = 60
RATE_LIMIT_PER_CLIENT_PER_HOUR = 3


# === Custom exception para que el caller distinga errores de seguridad ===
class MagicLinkSecurityError(ValueError):
    """Se lanza cuando find_or_create_magic_link bloquea por seguridad
    (teléfono del client no coincide con wa_id, etc.). Subclase de
    ValueError para que callers existentes (que ya hacen except ValueError)
    sigan funcionando, pero permite distinguir el caso si se necesita.
    """
    def __init__(self, reason, message):
        super().__init__(f"{reason}: {message}")
        self.reason = reason


def _normalize_phone(value):
    """Devuelve los 9 dígitos finales del teléfono peruano normalizado.
    Strip country code '51' si está. Retorna None si <9 dígitos.

    Idéntico al helper en apps/chatbot/reservation_lookup.py pero
    duplicado aquí para no crear dependencia inversa (clients → chatbot).
    """
    if not value:
        return None
    digits = re.sub(r'\D', '', str(value))
    if not digits:
        return None
    if digits.startswith('51') and len(digits) >= 11:
        digits = digits[2:]
    return digits[-9:] if len(digits) >= 9 else None


def generate_token():
    """Devuelve (raw_token, token_hash).

    Token raw: 13 caracteres RFC base32 (A-Z, 2-7). 64 bits de entropía =
    1.8×10¹⁹ combinaciones. Sin caracteres ambiguos (0,1,8,9,O,I,L no están
    en base32 estándar).

    Token hash: sha256 hex de 64 chars. Es lo único que persiste en BD.
    """
    raw_bytes = secrets.token_bytes(8)
    raw = base64.b32encode(raw_bytes).decode('ascii').rstrip('=')
    token_hash = hashlib.sha256(raw.encode('utf-8')).hexdigest()
    return raw, token_hash


def hash_token(raw_token):
    """sha256 hex del token raw. Comparar contra token_hash en BD."""
    if not raw_token:
        return None
    return hashlib.sha256(raw_token.strip().encode('utf-8')).hexdigest()


def find_or_create_magic_link(
    *,
    client,
    chat_session,
    wa_id,
    check_in,
    check_out,
    guests,
    property=None,
    expiry_minutes=DEFAULT_EXPIRY_MINUTES,
    created_ip=None,
):
    """Busca un magic link vigente para los mismos parámetros; si existe lo
    reutiliza. Si no, crea uno nuevo. Aplica rate limit por cliente.

    Returns:
        (magic_link, raw_token, was_reused)

    Notas:
        - raw_token solo viene poblado cuando el link es NUEVO. Si fue
          reutilizado, el raw NO está en BD (solo hash), así que se devuelve
          None. El caller debe haber guardado el raw en conversation_context
          cuando lo creó originalmente.

    Raises:
        ValueError: si excede rate limit.
    """
    if not client or not chat_session:
        raise ValueError("client and chat_session are required.")

    # === SECURITY: verificar que el teléfono del cliente coincida con
    # el wa_id que generará el link. Esto evita que un caller (shell,
    # script, futuro código) genere un magic link para un cliente cuyo
    # WhatsApp NO le pertenece. ===
    client_tel_norm = _normalize_phone(getattr(client, 'tel_number', None))
    wa_norm = _normalize_phone(wa_id)
    if not wa_norm:
        raise MagicLinkSecurityError(
            'wa_id_invalid',
            f"wa_id no normalizable a 9 dígitos: {wa_id!r}",
        )
    if not client_tel_norm:
        logger.warning(
            f"MagicLink BLOQUEADO (sin tel_number): client_id={client.id} "
            f"wa_id={wa_id}"
        )
        raise MagicLinkSecurityError(
            'client_phone_missing',
            f"cliente {client.id} sin tel_number registrado; "
            "no se genera magic link por seguridad.",
        )
    if client_tel_norm != wa_norm:
        logger.warning(
            f"MagicLink BLOQUEADO (mismatch): client_id={client.id} "
            f"client_tel={client_tel_norm} wa_id={wa_norm}"
        )
        raise MagicLinkSecurityError(
            'client_phone_mismatch',
            f"client.tel_number ({client_tel_norm}) != wa_id ({wa_norm}); "
            "no se genera magic link por seguridad.",
        )

    now = timezone.now()

    # Rate limit por cliente
    last_hour = now - timedelta(hours=1)
    recent_count = ReservationMagicLink.objects.filter(
        client=client,
        created__gte=last_hour,
        deleted=False,
    ).count()
    if recent_count >= RATE_LIMIT_PER_CLIENT_PER_HOUR:
        raise ValueError(
            f"Rate limit: cliente {client.id} ya generó "
            f"{recent_count} magic links en la última hora."
        )

    # Buscar link vigente con MISMOS parámetros (reuso)
    reuse = ReservationMagicLink.objects.filter(
        client=client,
        chat_session=chat_session,
        property=property,
        check_in=check_in,
        check_out=check_out,
        guests=guests,
        used_at__isnull=True,
        expires_at__gt=now,
        deleted=False,
    ).order_by('-created').first()
    if reuse:
        logger.info(
            f"MagicLink reuse: id={reuse.id} client={client.id} "
            f"expires_at={reuse.expires_at}"
        )
        return reuse, None, True

    # Crear nuevo. Retry hasta 3 veces si hay colisión de hash (improbable).
    last_error = None
    for _ in range(3):
        raw, token_hash = generate_token()
        try:
            magic = ReservationMagicLink.objects.create(
                client=client,
                token_hash=token_hash,
                property=property,
                check_in=check_in,
                check_out=check_out,
                guests=guests,
                chat_session=chat_session,
                wa_id=wa_id,
                expires_at=now + timedelta(minutes=expiry_minutes),
                created_ip=created_ip,
            )
            logger.info(
                f"MagicLink created: id={magic.id} client={client.id} "
                f"expires_at={magic.expires_at}"
            )
            return magic, raw, False
        except Exception as e:
            last_error = e
            # Colisión de hash → retry
            continue
    # Si llegamos acá, fallaron 3 retries
    raise RuntimeError(f"Failed to create MagicLink after retries: {last_error}")


def get_valid_magic_link_by_token(raw_token):
    """Busca un magic link por su token raw. Retorna None si no existe
    o no es vigente."""
    h = hash_token(raw_token)
    if not h:
        return None
    try:
        magic = ReservationMagicLink.objects.select_related(
            'client', 'property', 'chat_session',
        ).get(token_hash=h, deleted=False)
    except ReservationMagicLink.DoesNotExist:
        return None
    if not magic.is_valid:
        return None
    return magic


def mark_redeemed(magic_link, *, ip=None, user_agent=''):
    """Marca el magic link como redimido. Atomic update sobre use_count.

    Returns True si fue marcado exitosamente; False si ya había alcanzado
    max_uses (race condition).
    """
    now = timezone.now()
    rows = ReservationMagicLink.objects.filter(
        id=magic_link.id,
        deleted=False,
        use_count__lt=F('max_uses'),
        expires_at__gt=now,
    ).update(
        use_count=F('use_count') + 1,
        used_at=now,
        redeemed_ip=ip,
        redeemed_user_agent=(user_agent or '')[:255],
    )
    return rows > 0
