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

        jwt_token = emit_magic_jwt(magic)
        client = magic.client
        prop = magic.property

        logger.info(
            f"MagicLink redeemed: id={magic.id} client={client.id} ip={ip}"
        )

        return Response({
            'client_token': jwt_token,
            'token_scope': 'magic',
            'client': {
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
