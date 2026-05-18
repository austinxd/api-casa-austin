"""Endpoint para exportar reservas + datos de vouchers a Excel.

Diseñado para reconciliación bancaria: el analista descarga el Excel,
una fila por depósito (voucher), con info extraída por IA del comprobante.

Reservas con origin=AIR no tienen voucher subido — se genera 1 fila
sintética con la regla:
    banco_destino = 'Interbank'
    fecha_deposito = check_in_date + 1 día
"""
import calendar
import logging
from datetime import datetime, timedelta

from django.db.models import Q
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from .models import RentalReceipt, Reservation
from .voucher_ai_service import analyze_voucher

logger = logging.getLogger(__name__)

# Banco destino y regla de fecha para reservas AIR.
AIR_BANK_DESTINATION = 'Interbank'
AIR_DEPOSIT_OFFSET_DAYS = 1


def _serialize_reservation_base(r: Reservation) -> dict:
    """Datos comunes que se repiten en cada fila (por voucher o sintética)."""
    client = r.client
    return {
        'reservation_id': str(r.id),
        'property': r.property.name if r.property else '',
        'origin': r.origin or '',
        'origin_label': {
            'air': 'AirBnB', 'aus': 'Casa Austin', 'man': 'Mantenimiento',
            'client': 'Cliente', 'book': 'Booking',
        }.get(r.origin, r.origin or ''),
        'client_name': (
            f"{client.first_name or ''} {client.last_name or ''}".strip()
            if client else ''
        ),
        'client_doc': (client.number_doc if client else '') or '',
        'client_phone': (
            r.tel_contact_number
            or (client.tel_number if client else '')
            or ''
        ),
        'check_in': (
            r.check_in_date.isoformat() if r.check_in_date else ''
        ),
        'check_out': (
            r.check_out_date.isoformat() if r.check_out_date else ''
        ),
        'guests': r.guests or 0,
        'price_usd': (
            str(r.price_usd) if r.price_usd is not None else ''
        ),
        'price_sol': (
            str(r.price_sol) if r.price_sol is not None else ''
        ),
        'advance_payment': (
            str(r.advance_payment) if r.advance_payment is not None else ''
        ),
        'advance_payment_currency': r.advance_payment_currency or '',
        'full_payment': bool(r.full_payment),
        'status': r.status or '',
        'comentarios': r.comentarios_reservas or '',
    }


def _row_from_voucher(base: dict, receipt: RentalReceipt) -> dict:
    """Combina base de la reserva con datos AI del voucher."""
    row = dict(base)
    row.update({
        'voucher_id': str(receipt.id),
        'voucher_uploaded_at': (
            receipt.created.isoformat() if receipt.created else ''
        ),
        'voucher_description': receipt.ai_description or '',
        'voucher_bank_origin': receipt.ai_bank_origin or '',
        'voucher_bank_destination': receipt.ai_bank_destination or '',
        'voucher_destination_account': receipt.ai_destination_account or '',
        'voucher_currency': receipt.ai_currency or '',
        'voucher_amount': (
            str(receipt.ai_amount)
            if receipt.ai_amount is not None else ''
        ),
        'voucher_deposit_date': (
            receipt.ai_deposit_date.isoformat()
            if receipt.ai_deposit_date else ''
        ),
        'voucher_ai_error': receipt.ai_error or '',
        'is_synthetic_air': False,
    })
    return row


def _row_synthetic_air(base: dict, r: Reservation) -> dict:
    """Fila sintética para AIR: Interbank + check_in + N días."""
    deposit_date = None
    if r.check_in_date:
        deposit_date = r.check_in_date + timedelta(days=AIR_DEPOSIT_OFFSET_DAYS)
    deposit_iso = deposit_date.isoformat() if deposit_date else ''
    desc = (
        f"Depósito de Airbnb en cuenta {AIR_BANK_DESTINATION}, "
        f"fecha {deposit_iso}"
    ) if deposit_iso else (
        f"Depósito de Airbnb en cuenta {AIR_BANK_DESTINATION} "
        f"(fecha no determinada)"
    )
    row = dict(base)
    row.update({
        'voucher_id': '',
        'voucher_uploaded_at': '',
        'voucher_description': desc,
        'voucher_bank_origin': 'Airbnb',
        'voucher_bank_destination': AIR_BANK_DESTINATION,
        'voucher_destination_account': '',
        'voucher_currency': '',
        'voucher_amount': '',
        'voucher_deposit_date': deposit_iso,
        'voucher_ai_error': '',
        'is_synthetic_air': True,
    })
    return row


def _row_no_voucher(base: dict) -> dict:
    """Fila para reservas no-AIR que aún no tienen voucher subido."""
    row = dict(base)
    row.update({
        'voucher_id': '',
        'voucher_uploaded_at': '',
        'voucher_description': '(Sin voucher subido)',
        'voucher_bank_origin': '',
        'voucher_bank_destination': '',
        'voucher_destination_account': '',
        'voucher_currency': '',
        'voucher_amount': '',
        'voucher_deposit_date': '',
        'voucher_ai_error': '',
        'is_synthetic_air': False,
    })
    return row


class VoucherExportAPIView(APIView):
    """Devuelve filas JSON listas para Excel — 1 por voucher (o 1 sintética
    AIR / sin voucher). Procesa con IA los vouchers no analizados.

    GET /api/v1/reservation/export/vouchers/?year=2025&month=4

    Filtra por check_in_date dentro del mes solicitado.
    """

    permission_classes = [IsAuthenticated]

    def get(self, request):
        try:
            year = int(request.query_params.get('year') or 0)
            month = int(request.query_params.get('month') or 0)
        except (TypeError, ValueError):
            return Response(
                {'error': 'year y month requeridos como enteros'},
                status=400,
            )
        if year < 2000 or month < 1 or month > 12:
            return Response(
                {'error': 'year/month fuera de rango'}, status=400,
            )

        last_day = calendar.monthrange(year, month)[1]
        start = datetime(year, month, 1)
        end = datetime(year, month, last_day, 23, 59, 59)

        # Excluimos man (mantenimiento) — no entran al Excel de ingresos.
        reservations = (
            Reservation.objects
            .filter(deleted=False, check_in_date__range=(start, end))
            .exclude(origin='man')
            .select_related('client', 'property')
            .order_by('check_in_date', 'id')
        )

        # Prefetch de receipts para evitar N+1.
        reservation_ids = [r.id for r in reservations]
        receipts_by_reservation: dict = {}
        for receipt in RentalReceipt.objects.filter(
            reservation_id__in=reservation_ids, deleted=False,
        ).order_by('created'):
            receipts_by_reservation.setdefault(
                receipt.reservation_id, [],
            ).append(receipt)

        # === Procesar con IA los vouchers no analizados ===
        # (Hacemos esto antes de armar filas para que las filas ya traigan
        # los datos. Si OpenAI falla en un voucher, queda con ai_error.)
        processed_count = 0
        for receipts in receipts_by_reservation.values():
            for receipt in receipts:
                if receipt.ai_processed_at:
                    continue
                try:
                    analyze_voucher(receipt)
                    processed_count += 1
                except Exception as e:
                    # No bloqueamos el export por un voucher
                    logger.error(
                        f"Voucher {receipt.id} análisis falló: {e}",
                        exc_info=True,
                    )

        # === Armar filas ===
        rows = []
        for r in reservations:
            base = _serialize_reservation_base(r)
            if r.origin == 'air':
                rows.append(_row_synthetic_air(base, r))
                continue
            receipts = receipts_by_reservation.get(r.id, [])
            if not receipts:
                rows.append(_row_no_voucher(base))
                continue
            for receipt in receipts:
                rows.append(_row_from_voucher(base, receipt))

        return Response({
            'period': f"{year}-{month:02d}",
            'count_reservations': reservations.count(),
            'count_rows': len(rows),
            'count_vouchers_processed_now': processed_count,
            'rows': rows,
        })
