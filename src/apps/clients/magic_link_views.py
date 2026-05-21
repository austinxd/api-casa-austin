"""Vistas para el flujo de magic link de reserva.

Endpoints públicos (sin auth previa):
  - POST /api/v1/clients/magic-link/redeem/
    Cuerpo: { "token": "K3M7XQYR9F2BA" }
    Respuesta: JWT acotado + draft de la reserva.

Endpoints con auth de magic JWT:
  - POST /api/v1/clients/magic-link/create-reservation/
    Crea la reserva, validando que property/check_in/check_out/guests
    coincidan con los constraints del JWT.
"""
import logging
from datetime import timedelta

from django.utils import timezone
from rest_framework import serializers as drf_serializers
from rest_framework.permissions import AllowAny
from rest_framework.response import Response
from rest_framework.views import APIView

from .magic_link_auth import (
    HasMagicScope,
    MagicLinkJWTAuthentication,
    emit_magic_jwt,
)
from .magic_link_service import (
    get_valid_magic_link_by_token,
    mark_consumed,
    mark_redeemed,
)
from .magic_link_models import ReservationMagicLink

logger = logging.getLogger(__name__)


def _get_client_ip(request):
    fwd = request.META.get('HTTP_X_FORWARDED_FOR', '')
    if fwd:
        return fwd.split(',')[0].strip()
    return request.META.get('REMOTE_ADDR')


class RedeemMagicLinkView(APIView):
    """Redime un magic link y devuelve un JWT acotado + draft de reserva.

    Solo POST (deliberadamente: WhatsApp/preview hacen GET, no consumen
    el token). One-time: la segunda llamada con el mismo token devuelve
    410 Gone.
    """

    permission_classes = [AllowAny]
    authentication_classes = []

    def post(self, request):
        raw_token = (request.data.get('token') or '').strip()
        if not raw_token:
            return Response(
                {'error': 'missing_token',
                 'message': 'Falta el token.'},
                status=400,
            )

        magic = get_valid_magic_link_by_token(raw_token)
        if not magic:
            return Response(
                {'error': 'invalid_or_expired',
                 'message': 'Este link expiró o ya fue usado.'},
                status=410,
            )

        ip = _get_client_ip(request)
        ua = (request.META.get('HTTP_USER_AGENT') or '')[:255]

        ok = mark_redeemed(magic, ip=ip, user_agent=ua)
        if not ok:
            # Race condition: alguien más lo redimió en el mismo instante.
            return Response(
                {'error': 'already_used',
                 'message': 'Este link ya fue usado.'},
                status=410,
            )

        magic.refresh_from_db()
        prop = magic.property

        # === R4.2: ramificar respuesta por link_type ===
        if magic.link_type == 'guest_express':
            # Sin JWT. El raw_token (que el front ya tiene en la URL) sirve
            # de auth para el siguiente paso (/express-reservation/create/).
            # Devolvemos draft con datos enmascarados para que la pantalla
            # de bienvenida muestre el nombre/DNI parcial sin filtrar al
            # bot/observador externo. El raw del DNI vive solo en BD.
            full_name = (magic.validated_full_name or '').strip()
            dni = magic.document_number or ''
            dni_masked = (dni[:4] + '****') if len(dni) >= 4 else dni
            wa_masked = _mask_wa_id(magic.wa_id)
            logger.info(
                f"MagicLink redeemed (guest_express): id={magic.id} "
                f"dni={dni_masked} ip={ip}"
            )
            # Meta CAPI: 'InitiateCheckout' cuando el cliente abre el link
            try:
                from apps.reservation.signals import send_funnel_event_to_meta
                send_funnel_event_to_meta(
                    event_name='InitiateCheckout',
                    phone=magic.wa_id,
                    first_name=(full_name.split()[0] if full_name else None),
                    last_name=(' '.join(full_name.split()[1:])
                               if full_name and len(full_name.split()) > 1 else None),
                    event_id=f"checkout_magic_{magic.id}",
                    event_source_url=request.META.get('HTTP_REFERER') or None,
                    custom_data={
                        'magic_link_id': str(magic.id),
                        'link_type': 'guest_express',
                        'property_slug': prop.slug if prop else None,
                    },
                )
            except Exception as e:
                logger.warning(f"Meta CAPI InitiateCheckout failed (no-op): {e}")
            return Response({
                'link_type': 'guest_express',
                'requires_confirmation': True,
                'client': {
                    'first_name': (full_name.split() or [''])[0],
                    'full_name': full_name,
                },
                'reservation_draft': {
                    'property_slug': prop.slug if prop else None,
                    'property_name': prop.name if prop else None,
                    'check_in': magic.check_in.isoformat(),
                    'check_out': magic.check_out.isoformat(),
                    'guests': magic.guests,
                    'expires_at': magic.expires_at.isoformat(),
                    'document_type': magic.document_type,
                    'document_number_masked': dni_masked,
                    'wa_id_masked': wa_masked,
                },
            })

        # === Rama existing_client (R4.1, sin cambios) ===
        jwt_token = emit_magic_jwt(magic)
        client = magic.client

        logger.info(
            f"MagicLink redeemed (existing_client): id={magic.id} "
            f"client={client.id} ip={ip}"
        )

        return Response({
            'link_type': 'existing_client',
            'client_token': jwt_token,
            'token_scope': 'magic',
            'client': {
                'id': str(client.id),  # ← necesario para que /booking aplique descuentos
                'first_name': client.first_name,
                'last_name': client.last_name or '',
                'full_name': (
                    f"{client.first_name} {client.last_name or ''}"
                ).strip(),
            },
            'reservation_draft': {
                'property_slug': prop.slug if prop else None,
                'property_name': prop.name if prop else None,
                'check_in': magic.check_in.isoformat(),
                'check_out': magic.check_out.isoformat(),
                'guests': magic.guests,
                'expires_at': magic.expires_at.isoformat(),
            },
        })


def _mask_wa_id(wa_id):
    """'51986607686' → '*** *** 686'. Devuelve los últimos 3 dígitos visibles."""
    if not wa_id:
        return ''
    digits = ''.join(c for c in str(wa_id) if c.isdigit())
    if len(digits) <= 3:
        return digits
    return '*** *** ' + digits[-3:]


class CreateReservationViaMagicLinkView(APIView):
    """Crea una reserva usando un JWT acotado de magic link.

    Validaciones:
      1. JWT debe ser is_magic=True con scope='create_reservation'.
      2. Datos enviados (property, check_in, check_out, guests) DEBEN
         coincidir con los claims del JWT.
      3. Cliente no debe tener reserva pendiente (mismo check que el
         endpoint normal /clients/reservations/create/).
    """

    authentication_classes = [MagicLinkJWTAuthentication]
    permission_classes = [HasMagicScope]
    required_scope = 'create_reservation'

    def post(self, request):
        from apps.property.models import Property
        from apps.reservation.models import Reservation
        from apps.reservation.serializers import (
            ClientReservationSerializer,
            ReservationListSerializer,
        )

        token = request.auth
        client = request.user

        if not client:
            return Response(
                {'error': 'unauthorized'},
                status=401,
            )

        # === 1. Validar que el body coincide con los constraints del JWT ===
        t_property = token.get('property_slug')
        t_check_in = token.get('check_in')
        t_check_out = token.get('check_out')
        t_guests = token.get('guests')

        req_property_value = (
            request.data.get('property')
            or request.data.get('property_slug')
            or request.data.get('property_id')
        )
        req_check_in = (
            request.data.get('check_in_date')
            or request.data.get('checkIn')
            or request.data.get('check_in')
        )
        req_check_out = (
            request.data.get('check_out_date')
            or request.data.get('checkOut')
            or request.data.get('check_out')
        )
        req_guests = request.data.get('guests')

        # Resolver property por slug o id (el JWT trae slug).
        prop = None
        if req_property_value:
            try:
                prop = Property.objects.filter(
                    id=req_property_value, deleted=False,
                ).first() or Property.objects.filter(
                    slug=req_property_value, deleted=False,
                ).first()
            except Exception:
                prop = None

        mismatches = []
        if t_property:
            if not prop or prop.slug != t_property:
                mismatches.append('property')
        if str(req_check_in or '') != str(t_check_in or ''):
            mismatches.append('check_in')
        if str(req_check_out or '') != str(t_check_out or ''):
            mismatches.append('check_out')
        try:
            if int(req_guests or 0) != int(t_guests or 0):
                mismatches.append('guests')
        except (TypeError, ValueError):
            mismatches.append('guests')

        if mismatches:
            logger.warning(
                f"MagicLink create-reservation rejected for client="
                f"{client.id}: mismatch={mismatches}"
            )
            return Response(
                {'error': 'magic_link_constraint_violation',
                 'fields': mismatches,
                 'message': 'Los datos no coinciden con tu link.'},
                status=400,
            )

        # === 2. Bloquear si ya hay reserva pendiente (mismo flujo normal) ===
        pending_statuses = ['incomplete', 'pending', 'under_review']
        existing_pending = Reservation.objects.filter(
            client=client,
            status__in=pending_statuses,
            deleted=False,
        ).first()
        if existing_pending:
            status_messages = {
                'incomplete': 'pendiente de subir comprobante de pago',
                'pending': 'pendiente de aprobación',
                'under_review': 'en revisión',
            }
            status_text = status_messages.get(
                existing_pending.status, 'en proceso',
            )
            return Response({
                'success': False,
                'message': (
                    f'Ya tienes una reserva {status_text}. Debes completarla '
                    f'o esperar su resolución antes de crear otra.'
                ),
                'existing_reservation_id': str(existing_pending.id),
                'existing_reservation_status': existing_pending.status,
            }, status=400)

        # === 3. Crear reserva ===
        # Forzamos property al resuelto desde el JWT para evitar tampering.
        data = dict(request.data)
        data['property'] = str(prop.id) if prop else data.get('property')
        data['check_in_date'] = t_check_in
        data['check_out_date'] = t_check_out
        data['guests'] = t_guests

        serializer = ClientReservationSerializer(
            data=data, context={'request': request},
        )
        if not serializer.is_valid():
            # Construir mensaje legible con el primer error de cada campo
            errs = serializer.errors or {}
            details = []
            if isinstance(errs, dict):
                for field, msgs in errs.items():
                    first = (
                        msgs[0] if isinstance(msgs, list) and msgs
                        else str(msgs)
                    )
                    details.append(f"{field}: {first}")
            friendly = '; '.join(details) if details else 'Error en los datos enviados'
            logger.warning(
                f"MagicLink create-reservation validation failed: {errs} "
                f"(client={client.id})"
            )
            return Response(
                {'success': False,
                 'message': friendly,
                 'errors': errs},
                status=400,
            )

        try:
            payment_deadline = timezone.now() + timedelta(hours=1)
            reservation = serializer.save(
                client=client,
                origin='client',
                status='incomplete',
                payment_voucher_deadline=payment_deadline,
                payment_voucher_uploaded=False,
                payment_confirmed=False,
            )
            # Persistir atribución (utm_*, fbclid, gclid) que el frontend
            # capturó al landear. Se usa en PR 2 para inferir touch_channel.
            from apps.reservation.attribution_helpers import apply_attribution_to_reservation
            apply_attribution_to_reservation(reservation, request.data.get('attribution_data'))
            # Consumir el magic link: bloquea creaciones futuras con el
            # mismo token. El cliente solo puede crear UNA reserva por link.
            magic_link_id = token.get('magic_link_id')
            if magic_link_id:
                try:
                    ml = ReservationMagicLink.objects.filter(
                        id=magic_link_id, deleted=False,
                    ).first()
                    if ml:
                        mark_consumed(ml)
                except Exception as e:
                    logger.warning(
                        f"MagicLink mark_consumed failed (no bloqueante): {e}"
                    )
            logger.info(
                f"MagicLink reservation created: id={reservation.id} "
                f"client={client.id} magic_link_id={magic_link_id}"
            )
            return Response(
                {
                    'success': True,
                    'message': (
                        'Reserva creada exitosamente. Está pendiente de '
                        'aprobación.'
                    ),
                    'reservation': ReservationListSerializer(reservation).data,
                },
                status=201,
            )
        except drf_serializers.ValidationError as ve:
            error_message = str(ve)
            if hasattr(ve, 'detail'):
                if isinstance(ve.detail, dict):
                    first = next(iter(ve.detail.values()), [str(ve)])
                    error_message = first[0] if first else str(ve)
                elif isinstance(ve.detail, list):
                    error_message = ve.detail[0] if ve.detail else str(ve)
            return Response(
                {'success': False, 'message': error_message},
                status=400,
            )
        except Exception as e:
            logger.error(
                f"MagicLink reservation creation error: {e}", exc_info=True,
            )
            return Response(
                {'success': False,
                 'message': 'Error al crear la reserva.'},
                status=500,
            )


# =====================================================================
# R4.2 — Reserva Express para clientes nuevos (link_type='guest_express')
# =====================================================================

class _ExpressValidationError(Exception):
    """Excepción interna para abortar el bloque atómico de creación
    express con un mensaje friendly + dict de errores del serializer.
    Atrapada localmente y convertida en Response 400."""
    def __init__(self, message, errors=None):
        super().__init__(message)
        self.message = message
        self.errors = errors or {}


def _notify_express_conflict(magic_link, reason, details):
    """Dispara notify_team usando el chat_session del magic link.

    No requiere request — el ToolExecutor del chatbot maneja throttle/push
    a admins. Si chat_session no existe (legacy), hacemos log only.
    """
    if not magic_link.chat_session_id:
        logger.warning(
            f"_notify_express_conflict: magic_link {magic_link.id} sin "
            f"chat_session; skip notify. reason={reason} details={details}"
        )
        return
    try:
        from apps.chatbot.tool_executor import ToolExecutor
        executor = ToolExecutor(magic_link.chat_session)
        executor.execute('notify_team', {
            'reason': reason,
            'details': details,
        })
    except Exception as e:
        logger.error(
            f"_notify_express_conflict failed: {e}", exc_info=True,
        )


class CreateExpressReservationView(APIView):
    """Crea Client (si hace falta) + Reservation a partir de un magic link
    guest_express. NO requiere JWT — la auth es el raw token en el body
    (mismo modelo que /redeem/).

    Body:
        {
          "token": "K3M7XQYR9F2BA",
          "confirm_data": true,
          "email": "opcional@ejemplo.com"
        }

    Casos manejados (alineados al diagnóstico R4.2):
      A. DNI no existe en Clients → crear nuevo Client + Reservation.
      B. DNI existe y tel_number coincide con wa_id → usar ese Client.
      C. DNI existe pero tel_number distinto al wa_id → BLOQUEAR + notify.
      D. tel_number/wa_id existe en otro Client con otro DNI → BLOQUEAR + notify.

    Si link_type != 'guest_express' → 400 (usar /magic-link/create-reservation/).
    """

    permission_classes = [AllowAny]
    authentication_classes = []

    def post(self, request):
        from datetime import timedelta
        from django.conf import settings
        from django.db import transaction
        from django.utils import timezone as _tz

        from apps.clients.models import Clients
        from apps.reservation.models import Reservation
        from apps.reservation.serializers import (
            ClientReservationSerializer,
            ReservationListSerializer,
        )
        from .magic_link_service import (
            _normalize_phone,
            get_valid_magic_link_by_token,
            mark_consumed,
        )

        raw_token = (request.data.get('token') or '').strip()
        confirm = bool(request.data.get('confirm_data'))
        email = (request.data.get('email') or '').strip() or None
        # El frontend puede mandar tipo + número de documento + names
        # cuando el magic link es "anónimo" (no traen DNI precargado).
        # Tipos permitidos: 'dni' (default), 'pas', 'cex'.
        body_doc_type = (request.data.get('document_type') or '').strip().lower() or 'dni'
        if body_doc_type not in ('dni', 'pas', 'cex'):
            body_doc_type = 'dni'
        body_doc_number = (request.data.get('document_number') or '').strip()
        body_first_name = (request.data.get('first_name') or '').strip()
        body_last_name = (request.data.get('last_name') or '').strip()
        body_property_slug = (request.data.get('property_slug') or '').strip()
        body_full_name = (request.data.get('full_name') or '').strip()
        # Compat con código viejo del front
        body_dni = body_doc_number if body_doc_type == 'dni' else ''

        if not raw_token:
            return Response(
                {'error': 'missing_token', 'message': 'Falta el token.'},
                status=400,
            )
        if not confirm:
            return Response(
                {'error': 'confirmation_required',
                 'message': 'Debes confirmar los datos para continuar.'},
                status=400,
            )

        magic = get_valid_magic_link_by_token(raw_token)
        if not magic:
            return Response(
                {'error': 'invalid_or_expired',
                 'message': 'Este link expiró o ya fue usado.'},
                status=410,
            )

        if magic.link_type != 'guest_express':
            return Response(
                {'error': 'wrong_link_type',
                 'message': 'Este endpoint es solo para reservas express.'},
                status=400,
            )

        # === Si el magic link NO trae documento (modo anónimo), pedirlo
        # al body. Solo DNI: para PAS/CEX derivamos a WhatsApp (mismo
        # patrón que el registro normal de la web — no creamos cuenta
        # de extranjeros automático sin contacto previo). ===
        if not magic.document_number:
            if body_doc_type != 'dni':
                support_wa_link = (
                    f"https://wa.me/{getattr(settings, 'RESERVATION_SUPPORT_WHATSAPP', '51999902992')}"
                    f"?text=Hola,%20quiero%20registrar%20una%20cuenta%20con%20"
                    f"{'Carnet%20de%20Extranjería' if body_doc_type == 'cex' else 'Pasaporte'}"
                )
                return Response({
                    'error': 'foreign_doc_not_supported',
                    'message': (
                        'Para registrar una cuenta con '
                        + ('Carnet de Extranjería' if body_doc_type == 'cex' else 'Pasaporte')
                        + ', contáctanos por WhatsApp.'
                    ),
                    'whatsapp_url': support_wa_link,
                }, status=400)

            if not body_doc_number or not body_doc_number.isdigit() or len(body_doc_number) != 8:
                return Response(
                    {'error': 'dni_required',
                     'message': 'Ingresa tu DNI de 8 dígitos para continuar.'},
                    status=400,
                )
            # Validar con RENIEC
            from apps.reniec.service import ReniecService
            from apps.chatbot.guards import _build_full_name_from_reniec
            ok, data = ReniecService.lookup(
                dni=body_doc_number,
                source_app='express_form',
                source_ip=_get_client_ip(request),
                user_agent=(request.META.get('HTTP_USER_AGENT') or '')[:255],
                include_photo=True,  # cacheamos la foto desde la creación
            )
            full_name = _build_full_name_from_reniec(data) if ok else ''
            if not ok or not full_name:
                return Response(
                    {'error': 'dni_invalid',
                     'message': 'No pudimos validar ese DNI. Revisa el número.'},
                    status=400,
                )
            magic.document_type = 'dni'
            magic.document_number = body_doc_number
            magic.validated_full_name = full_name
            magic.dni_validated_at = _tz.now()
            magic.save(update_fields=[
                'document_type', 'document_number',
                'validated_full_name', 'dni_validated_at',
            ])
            logger.info(
                f"Express DNI from form: magic={magic.id} "
                f"dni={body_doc_number[:4]}**** name={full_name}"
            )

        # === Si el magic link NO trae property, pedirla al body. ===
        if not magic.property_id:
            if not body_property_slug:
                return Response(
                    {'error': 'property_required',
                     'message': 'Selecciona la casa que deseas reservar.'},
                    status=400,
                )
            from apps.property.models import Property
            prop_from_body = Property.objects.filter(
                slug=body_property_slug, deleted=False,
            ).first()
            if not prop_from_body:
                return Response(
                    {'error': 'property_invalid',
                     'message': 'La casa seleccionada no existe.'},
                    status=400,
                )
            magic.property = prop_from_body
            magic.save(update_fields=['property'])
            logger.info(
                f"Express property from form: magic={magic.id} "
                f"prop={prop_from_body.slug}"
            )

        # === Resolver conflictos DNI/tel (casos A/B/C/D del spec) ===
        wa_norm = _normalize_phone(magic.wa_id)
        if not wa_norm:
            return Response(
                {'error': 'wa_id_invalid', 'message': 'WhatsApp no válido.'},
                status=400,
            )

        support_wa = getattr(
            settings, 'RESERVATION_SUPPORT_WHATSAPP', '51999902992',
        )
        manual_url = f"https://wa.me/{support_wa}"

        # ¿Hay Client con este documento? (mismo tipo + número)
        client_by_doc = Clients.objects.filter(
            document_type=magic.document_type or 'dni',
            number_doc=magic.document_number,
            deleted=False,
        ).first()

        # ¿Hay Client con este wa_id?
        client_by_phone = Clients.objects.filter(
            tel_number=magic.wa_id,
            deleted=False,
        ).first()
        # Búsqueda más laxa por si el formato difiere
        if not client_by_phone:
            for variant in (wa_norm, f'+51{wa_norm}', f'51{wa_norm}'):
                client_by_phone = Clients.objects.filter(
                    tel_number=variant, deleted=False,
                ).first()
                if client_by_phone:
                    break

        # --- Caso C: DNI existe + tel del Client NO coincide con wa_id ---
        if client_by_doc:
            client_tel_norm = _normalize_phone(client_by_doc.tel_number)
            if client_tel_norm and client_tel_norm != wa_norm:
                logger.warning(
                    f"Express case C: DNI {magic.document_number} pertenece "
                    f"a client {client_by_doc.id} con tel "
                    f"{client_by_doc.tel_number}, distinto al wa_id "
                    f"{magic.wa_id}. Bloqueado."
                )
                _notify_express_conflict(
                    magic,
                    'express_booking_document_phone_mismatch',
                    f"DNI {magic.document_number} ya está registrado con "
                    f"otro teléfono. Cliente intentó reservar express desde "
                    f"wa_id={magic.wa_id}. "
                    f"client_id={client_by_doc.id}. "
                    f"Reserva: {magic.check_in}→{magic.check_out}, "
                    f"{magic.guests} pers.",
                )
                return Response({
                    'error': 'document_phone_mismatch',
                    'message': (
                        "Este documento ya está registrado. Para proteger "
                        "tu cuenta, comunícate con nuestro equipo por "
                        "WhatsApp para continuar."
                    ),
                    'whatsapp_url': manual_url,
                }, status=409)

            # Caso B: DNI existe + tel coincide → usar ese Client.
            client = client_by_doc

        else:
            # No existe Client con este DNI.
            # --- Caso D: wa_id existe en otro Client con DNI distinto ---
            if client_by_phone and client_by_phone.number_doc != magic.document_number:
                logger.warning(
                    f"Express case D: wa_id {magic.wa_id} pertenece a "
                    f"client {client_by_phone.id} con DNI "
                    f"{client_by_phone.number_doc!r}, no al DNI "
                    f"ingresado {magic.document_number}. Bloqueado."
                )
                _notify_express_conflict(
                    magic,
                    'express_booking_phone_document_mismatch',
                    f"WhatsApp {magic.wa_id} ya está registrado con DNI "
                    f"{client_by_phone.number_doc} (client_id="
                    f"{client_by_phone.id}). Cliente quiso reservar express "
                    f"con DNI {magic.document_number}. "
                    f"Reserva: {magic.check_in}→{magic.check_out}, "
                    f"{magic.guests} pers.",
                )
                return Response({
                    'error': 'phone_document_mismatch',
                    'message': (
                        "Detectamos información que no coincide. Para "
                        "continuar de forma segura, comunícate con nuestro "
                        "equipo por WhatsApp."
                    ),
                    'whatsapp_url': manual_url,
                }, status=409)

            # --- Caso A: marcar para crear Client dentro del bloque atómico ---
            # En este punto magic.document_type es 'dni' siempre: bloqueamos
            # PAS/CEX más arriba con foreign_doc_not_supported.
            client = None  # sentinel — se crea dentro de transaction.atomic más abajo

        # === Crear Reservation (atómico) ===
        # Bloquear si el cliente EXISTENTE (caso B) ya tiene una pendiente.
        # Caso A: el client aún no existe, no aplica.
        if client is not None:
            pending_statuses = ['incomplete', 'pending', 'under_review']
            existing_pending = Reservation.objects.filter(
                client=client,
                status__in=pending_statuses,
                deleted=False,
            ).first()
            if existing_pending:
                return Response({
                    'success': False,
                    'message': (
                        'Ya tienes una reserva en proceso. Termina esa primero o '
                        'contáctanos por WhatsApp para ayudarte.'
                    ),
                    'existing_reservation_id': str(existing_pending.id),
                    'whatsapp_url': manual_url,
                }, status=400)

        # === Construir data de la reserva ===
        # El cliente puede editar property/fechas/guests en /booking. Si el
        # body los envía, se usan; si no, fallback a los valores del magic
        # link. El serializer de reserva valida disponibilidad y constraints.
        from apps.property.models import Property

        body_property_value = (
            request.data.get('property')
            or request.data.get('property_id')
            or body_property_slug
        )
        body_check_in = (
            request.data.get('check_in_date')
            or request.data.get('checkIn')
            or request.data.get('check_in')
        )
        body_check_out = (
            request.data.get('check_out_date')
            or request.data.get('checkOut')
            or request.data.get('check_out')
        )
        body_guests = request.data.get('guests')

        # Resolver property: el body puede traer id o slug
        property_to_use = None
        if body_property_value:
            property_to_use = Property.objects.filter(
                id=body_property_value, deleted=False,
            ).first() or Property.objects.filter(
                slug=body_property_value, deleted=False,
            ).first()
        if not property_to_use:
            property_to_use = magic.property

        if not property_to_use:
            return Response({
                'error': 'property_required',
                'message': 'Debes elegir una casa para reservar.',
            }, status=400)

        check_in_to_use = body_check_in or (
            magic.check_in.isoformat() if magic.check_in else None
        )
        check_out_to_use = body_check_out or (
            magic.check_out.isoformat() if magic.check_out else None
        )
        try:
            guests_to_use = int(body_guests) if body_guests else int(magic.guests or 0)
        except (TypeError, ValueError):
            guests_to_use = int(magic.guests or 0)

        if not check_in_to_use or not check_out_to_use or guests_to_use < 1:
            return Response({
                'error': 'reservation_data_incomplete',
                'message': 'Faltan datos de la reserva (fechas o cantidad de huéspedes).',
            }, status=400)

        # Datos opcionales editables (mismo set que /booking normal).
        body_currency = (
            (request.data.get('advance_payment_currency') or '')
            .strip().lower()
        )
        if body_currency not in ('sol', 'usd'):
            body_currency = 'sol'

        data = {
            'property': str(property_to_use.id),
            'check_in_date': check_in_to_use,
            'check_out_date': check_out_to_use,
            'guests': guests_to_use,
            'tel_contact_number': magic.wa_id,
            'origin': 'client',
            'advance_payment_currency': body_currency,
            # Express siempre es venta directa por la web — seller 14
            # ("Casa Austin / cliente"). Lo seteamos explícito para no
            # depender del fallback del serializer.
            'seller': 14,
        }
        # Pasar precios y servicios adicionales si los manda el body.
        for opt_key in (
            'price_usd', 'price_sol', 'advance_payment',
            'comentarios_reservas', 'additional_services',
            'temperature_pool', 'late_checkout',
            'discount_code',
        ):
            if opt_key in request.data and request.data.get(opt_key) is not None:
                data[opt_key] = request.data.get(opt_key)

        # === Bloque atómico: Client (caso A) + Reservation ===
        # Si cualquier paso falla, transaction.atomic() hace rollback de
        # TODO lo creado dentro — incluyendo el Client. Las notificaciones
        # del signal post_save están dentro de transaction.on_commit, así
        # que solo se mandan si el commit ocurre.
        try:
            with transaction.atomic():
                # Caso A: crear Client ahora, dentro del atomic.
                if client is None:
                    full_name = (magic.validated_full_name or '').strip()
                    parts = full_name.split()
                    first_name = parts[0] if parts else 'Cliente'
                    last_name = ' '.join(parts[1:]) if len(parts) > 1 else ''
                    client = Clients.objects.create(
                        document_type=magic.document_type or 'dni',
                        number_doc=magic.document_number,
                        first_name=first_name[:30],
                        last_name=last_name[:40] or None,
                        email=email,
                        tel_number=magic.wa_id,
                        is_password_set=False,
                    )
                    logger.info(
                        f"Express Client created: id={client.id} "
                        f"dni={magic.document_number} wa_id={magic.wa_id}"
                    )

                # Inyectar request.user para el serializer
                fake_request = type(
                    'FakeReq', (), {'user': client, 'data': data},
                )()
                serializer = ClientReservationSerializer(
                    data=data, context={'request': fake_request},
                )
                if not serializer.is_valid():
                    errs = serializer.errors or {}
                    details = []
                    if isinstance(errs, dict):
                        for field, msgs in errs.items():
                            first = (
                                msgs[0] if isinstance(msgs, list) and msgs
                                else str(msgs)
                            )
                            details.append(f"{field}: {first}")
                    friendly = '; '.join(details) if details else 'Error en los datos.'
                    logger.warning(
                        f"Express reservation validation failed: {errs} "
                        f"client={client.id}"
                    )
                    # Levantar excepción → atomic rollback → Client (case A)
                    # se borra automáticamente + ningún signal post_commit.
                    raise _ExpressValidationError(friendly, errs)

                payment_deadline = _tz.now() + timedelta(hours=1)
                reservation = serializer.save(
                    client=client,
                    origin='client',
                    status='incomplete',
                    payment_voucher_deadline=payment_deadline,
                    payment_voucher_uploaded=False,
                    payment_confirmed=False,
                    chatbot_session=magic.chat_session,
                )
                # Persistir atribución (utm_*, fbclid, gclid) que el frontend
                # capturó al landear. Se usa en PR 2 para inferir touch_channel.
                from apps.reservation.attribution_helpers import apply_attribution_to_reservation
                apply_attribution_to_reservation(reservation, request.data.get('attribution_data'))
                # Vincular el magic link al client (claims del JWT) y consumirlo.
                if magic.client_id is None:
                    magic.client = client
                    magic.save(update_fields=['client'])
                mark_consumed(magic)
                logger.info(
                    f"Express reservation created: id={reservation.id} "
                    f"client={client.id} magic_link_id={magic.id}"
                )
                # JWT para los siguientes pasos (voucher/pago)
                jwt_token = emit_magic_jwt(magic)
        except _ExpressValidationError as ve:
            return Response(
                {'success': False, 'message': ve.message, 'errors': ve.errors},
                status=400,
            )
        except Exception as e:
            logger.error(
                f"Express reservation save error: {e}", exc_info=True,
            )
            return Response({
                'success': False,
                'message': f'No pudimos crear tu reserva: {str(e)[:300]}',
                'error_detail': str(e)[:1000],
                'whatsapp_url': manual_url,
            }, status=500)

        # === Post-commit: notificación al equipo ===
        # Fuera del atomic para que el envío no haga rollback de la reserva
        # si fallase la notificación.
        edited_note = ''
        if (
            str(magic.check_in) != str(reservation.check_in_date)
            or str(magic.check_out) != str(reservation.check_out_date)
            or int(magic.guests or 0) != int(reservation.guests or 0)
            or (magic.property_id and magic.property_id != reservation.property_id)
        ):
            edited_note = (
                f" [⚠️ cliente editó datos: link era "
                f"{magic.property.name if magic.property_id else '?'} "
                f"{magic.check_in}→{magic.check_out}, {magic.guests} pers]"
            )
        try:
            _notify_express_conflict(
                magic,
                'express_booking_created',
                f"Cliente {client.first_name} {client.last_name or ''} "
                f"(DNI {magic.document_number}, wa_id {magic.wa_id}) creó "
                f"reserva express en {reservation.property.name} "
                f"{reservation.check_in_date}→{reservation.check_out_date}, "
                f"{reservation.guests} pers.{edited_note} "
                f"Pendiente de subir voucher.",
            )
        except Exception as e:
            logger.warning(f"Notificación express_booking_created falló: {e}")

        return Response({
            'success': True,
            'message': (
                'Reserva creada exitosamente. Está pendiente de '
                'aprobación.'
            ),
            'reservation': ReservationListSerializer(reservation).data,
            'reservation_id': str(reservation.id),
            'client_token': jwt_token,
            'token_scope': 'magic',
            'client': {
                'id': str(client.id),
                'first_name': client.first_name,
                'last_name': client.last_name or '',
                'full_name': (
                    f"{client.first_name} {client.last_name or ''}"
                ).strip(),
            },
        }, status=201)
