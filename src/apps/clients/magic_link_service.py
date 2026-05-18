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
# Duración real del magic link: 90 min (1.5h).
# Al cliente le decimos "1 hora" en el mensaje del bot para crear urgencia,
# pero internamente dejamos 30 min de buffer para que si tarda un poco más
# en abrir/completar, todavía funcione.
DEFAULT_EXPIRY_MINUTES = 90
# Rate limit: protege contra abuso/scripts, NO contra clientes reales.
# Un cliente iterando con el bot puede generar 5-10 cotizaciones distintas
# (fechas, personas, casa), así que el límite debe ser laxo. 20/hora = 1
# cada 3 minutos, bloquea spam pero deja espacio para uso natural.
RATE_LIMIT_PER_CLIENT_PER_HOUR = 20


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
    chat_session,
    wa_id,
    check_in,
    check_out,
    guests,
    property=None,
    client=None,
    link_type='existing_client',
    document_type=None,
    document_number=None,
    validated_full_name=None,
    expiry_minutes=DEFAULT_EXPIRY_MINUTES,
    created_ip=None,
):
    """Busca un magic link vigente para los mismos parámetros; si existe lo
    reutiliza. Si no, crea uno nuevo. Aplica rate limit.

    Soporta DOS tipos (R4.2):
      - link_type='existing_client' (default, R4.1): requiere `client` con
        tel_number == wa_id (security check).
      - link_type='guest_express' (R4.2): requiere DNI 8 dígitos validado
        + validated_full_name. `client` es None — se creará al confirmar.

    Returns:
        (magic_link, raw_token, was_reused)

    Raises:
        MagicLinkSecurityError: validaciones de seguridad fallaron.
        ValueError: rate limit u otro problema.
    """
    if not chat_session:
        raise ValueError("chat_session is required.")

    wa_norm = _normalize_phone(wa_id)
    if not wa_norm:
        raise MagicLinkSecurityError(
            'wa_id_invalid',
            f"wa_id no normalizable a 9 dígitos: {wa_id!r}",
        )

    # === Validaciones por tipo de link ===
    if link_type == 'existing_client':
        if not client:
            raise ValueError("client is required for link_type='existing_client'.")
        # Phone match (R4.1)
        client_tel_norm = _normalize_phone(getattr(client, 'tel_number', None))
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
    elif link_type == 'guest_express':
        # R4.2 — guest_express soporta 2 modos:
        #   (a) DNI prevalidado: document_number + validated_full_name → form
        #       prellenado. Permite que el cliente solo confirme y pague.
        #   (b) ANÓNIMO: sin DNI ni nombre. Form completo en el frontend.
        #       Útil cuando el cliente no quiere/no puede dar DNI por chat.
        if client is not None:
            raise MagicLinkSecurityError(
                'client_must_be_null_for_express',
                "Para guest_express, client debe ser None (se crea al confirmar).",
            )
        if document_number:
            # Modo (a): si trae DNI, validamos formato y nombre
            if document_type != 'dni':
                raise MagicLinkSecurityError(
                    'invalid_document_type',
                    "R4.2 express con DNI solo soporta document_type='dni'.",
                )
            if not document_number.isdigit() or len(document_number) != 8:
                raise MagicLinkSecurityError(
                    'invalid_dni',
                    f"DNI debe ser 8 dígitos numéricos. Recibido: {document_number!r}",
                )
            if not validated_full_name or not validated_full_name.strip():
                raise MagicLinkSecurityError(
                    'missing_validated_name',
                    "Si pasas document_number, validated_full_name es requerido.",
                )
    else:
        raise ValueError(
            f"link_type inválido: {link_type!r}. "
            "Esperado: 'existing_client' o 'guest_express'."
        )

    now = timezone.now()

    # === 1. Reuso PRIMERO ===
    # Match por params del draft. Para existing_client matchea por client.
    # Para guest_express matchea por document_number (no hay client aún).
    reuse_filter = dict(
        chat_session=chat_session,
        property=property,
        check_in=check_in,
        check_out=check_out,
        guests=guests,
        used_at__isnull=True,
        expires_at__gt=now,
        deleted=False,
        link_type=link_type,
    )
    if link_type == 'existing_client':
        reuse_filter['client'] = client
    else:
        reuse_filter['document_number'] = document_number
    reuse = ReservationMagicLink.objects.filter(
        **reuse_filter,
    ).order_by('-created').first()
    if reuse:
        logger.info(
            f"MagicLink reuse: id={reuse.id} link_type={link_type} "
            f"expires_at={reuse.expires_at}"
        )
        return reuse, None, True

    # === 2. Rate limit (solo aplica cuando vamos a CREAR uno nuevo) ===
    # existing_client: por cliente.
    # guest_express: por wa_id (no hay client aún).
    last_hour = now - timedelta(hours=1)
    if link_type == 'existing_client':
        recent_count = ReservationMagicLink.objects.filter(
            client=client,
            created__gte=last_hour,
            deleted=False,
        ).count()
        rate_key = f"client {client.id}"
    else:
        recent_count = ReservationMagicLink.objects.filter(
            link_type='guest_express',
            wa_id=wa_id,
            created__gte=last_hour,
            deleted=False,
        ).count()
        rate_key = f"wa_id {wa_id}"
    if recent_count >= RATE_LIMIT_PER_CLIENT_PER_HOUR:
        raise ValueError(
            f"Rate limit: {rate_key} ya generó "
            f"{recent_count} magic links en la última hora."
        )

    # === 3. Crear nuevo. Retry hasta 3 veces si hay colisión de hash. ===
    last_error = None
    for _ in range(3):
        raw, token_hash = generate_token()
        try:
            kwargs = dict(
                token_hash=token_hash,
                property=property,
                check_in=check_in,
                check_out=check_out,
                guests=guests,
                chat_session=chat_session,
                wa_id=wa_id,
                expires_at=now + timedelta(minutes=expiry_minutes),
                created_ip=created_ip,
                link_type=link_type,
            )
            if link_type == 'existing_client':
                kwargs['client'] = client
            else:
                # guest_express puede ser anónimo (sin DNI) o pre-validado.
                # Solo persistimos los campos DNI si llegaron del caller;
                # si es anónimo, quedan null y el cliente los llenará en
                # el formulario web.
                if document_number:
                    kwargs['document_type'] = document_type
                    kwargs['document_number'] = document_number
                    kwargs['validated_full_name'] = (
                        (validated_full_name or '').strip() or None
                    )
                    kwargs['dni_validated_at'] = now
            magic = ReservationMagicLink.objects.create(**kwargs)
            logger.info(
                f"MagicLink created: id={magic.id} link_type={link_type} "
                f"expires_at={magic.expires_at}"
            )
            return magic, raw, False
        except Exception as e:
            last_error = e
            continue
    raise RuntimeError(f"Failed to create MagicLink after retries: {last_error}")


def create_express_magic_link(
    *,
    chat_session,
    wa_id,
    check_in,
    check_out,
    guests,
    property=None,
    document_number=None,
    validated_full_name=None,
    created_ip=None,
):
    """Convenience wrapper para crear/reusar magic links express (R4.2).

    Soporta 2 modos:
      (a) DNI prevalidado: pasar document_number + validated_full_name
          (deben venir de RENIEC + confirmación del cliente en chat).
          El form en frontend queda prellenado.
      (b) Anónimo: omitir document_number. El cliente completará todos
          los datos en el formulario web.

    Property también es opcional. Si se omite, el frontend muestra
    selector de casa.
    """
    return find_or_create_magic_link(
        chat_session=chat_session,
        wa_id=wa_id,
        check_in=check_in,
        check_out=check_out,
        guests=guests,
        property=property,
        client=None,
        link_type='guest_express',
        document_type='dni' if document_number else None,
        document_number=document_number,
        validated_full_name=validated_full_name,
        created_ip=created_ip,
    )


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
    """Registra un GET/redeem de /r/<token>.

    IMPORTANTE: NO consume el link. El cliente puede abrir el link varias
    veces dentro de la ventana de vigencia (1h). Solo `mark_consumed`
    (llamado al crear la reserva) consume definitivamente.

    Lo que SÍ hace este método:
    - Incrementa use_count (auditoría — cuántas veces se abrió).
    - Guarda redeemed_ip / redeemed_user_agent del PRIMER redeem
      (solo si no había info previa).

    Returns True si el link aún es válido al momento de la llamada
    (no consumido, no expirado), False si ya estaba consumido/expirado.
    """
    now = timezone.now()
    # Solo procesa si todavía es válido (no consumido, no expirado).
    qs = ReservationMagicLink.objects.filter(
        id=magic_link.id,
        deleted=False,
        used_at__isnull=True,
        expires_at__gt=now,
    )
    # Si es el primer redeem, también guardamos ip/UA. En subsecuentes,
    # solo incrementamos el contador. Hacemos dos updates separados para
    # mantener atomicidad simple sin transaction.
    updated = qs.update(use_count=F('use_count') + 1)
    if updated and ip:
        ReservationMagicLink.objects.filter(
            id=magic_link.id,
            redeemed_ip__isnull=True,
        ).update(
            redeemed_ip=ip,
            redeemed_user_agent=(user_agent or '')[:255],
        )
    return updated > 0


def mark_consumed(magic_link):
    """Consume el magic link DEFINITIVAMENTE. Se llama después de crear
    exitosamente la reserva vía /magic-link/create-reservation/.

    Setea used_at = now. A partir de ese momento, is_valid=False y el
    link no acepta más redeems.

    Returns True si fue consumido por esta llamada, False si ya estaba
    consumido (race condition entre dos creates).
    """
    now = timezone.now()
    rows = ReservationMagicLink.objects.filter(
        id=magic_link.id,
        deleted=False,
        used_at__isnull=True,
        expires_at__gt=now,
    ).update(used_at=now)
    return rows > 0
