"""Servicio para extraer datos de vouchers/comprobantes con OpenAI Vision.

Diseñado para llenar los campos `ai_*` de RentalReceipt y permitir que un
analista reconcilie depósitos bancarios contra el estado de cuenta.

Idempotente: si `ai_processed_at` está seteado, no se reprocesa (salvo que
se pase force=True).
"""
import base64
import json
import logging
import os
from datetime import datetime
from decimal import Decimal, InvalidOperation

from django.conf import settings
from django.utils import timezone

logger = logging.getLogger(__name__)


SYSTEM_PROMPT = (
    "Eres un analista contable peruano. Recibes screenshots de "
    "comprobantes de pago/depósitos bancarios (Yape, Plin, Interbank, "
    "BCP, BBVA, Scotiabank, Banco de la Nación, etc.) y extraes los "
    "datos clave para reconciliación bancaria.\n\n"
    "Reglas:\n"
    "- Responde SIEMPRE en JSON estricto con los campos indicados.\n"
    "- Si un campo no se puede leer con seguridad, usa null.\n"
    "- bank_origin: banco/billetera DESDE donde se hizo el pago.\n"
    "- bank_destination: banco/billetera DONDE se recibió el dinero.\n"
    "- destination_account: número o alias de cuenta destino "
    "(últimos dígitos o nombre del titular si aparece).\n"
    "- currency: 'PEN' para soles, 'USD' para dólares. Solo esos.\n"
    "- amount: monto numérico sin símbolo (ej: 1250.50).\n"
    "- deposit_date: fecha real del depósito en formato YYYY-MM-DD. "
    "Es la fecha que figura en el comprobante, NO la fecha de hoy.\n"
    "- description: 1 oración resumen del depósito en español. "
    "Ej: 'Depósito Yape de Juan Perez por S/ 750.00 a cuenta BCP "
    "***1234, 15/04/2025'.\n"
    "- Si la imagen NO es un comprobante de depósito (foto random, "
    "factura, contrato, etc.), devuelve todos los campos null y "
    "description = 'No es un comprobante de pago válido'."
)

USER_PROMPT = (
    "Extrae los datos de este comprobante. Responde SOLO con JSON "
    "con esta estructura exacta:\n"
    "{\n"
    '  "bank_origin": string|null,\n'
    '  "bank_destination": string|null,\n'
    '  "destination_account": string|null,\n'
    '  "currency": "PEN"|"USD"|null,\n'
    '  "amount": number|null,\n'
    '  "deposit_date": "YYYY-MM-DD"|null,\n'
    '  "description": string\n'
    "}"
)


def _file_to_data_url(path: str) -> tuple[str, str] | None:
    """Devuelve (data_url, mime) para una imagen local. Retorna None si
    no se puede leer / no soportado."""
    if not os.path.exists(path):
        return None
    ext = os.path.splitext(path)[1].lower()
    if ext == '.pdf':
        # Convertir primera página del PDF a PNG usando PyMuPDF (fitz).
        try:
            import fitz  # type: ignore
        except ImportError:
            return None
        try:
            doc = fitz.open(path)
            if doc.page_count == 0:
                doc.close()
                return None
            page = doc.load_page(0)
            pix = page.get_pixmap(dpi=200)
            png_bytes = pix.tobytes('png')
            doc.close()
            b64 = base64.b64encode(png_bytes).decode('ascii')
            return f"data:image/png;base64,{b64}", 'image/png'
        except Exception as e:
            logger.warning(f"Error convirtiendo PDF voucher: {e}")
            return None
    mime_map = {
        '.jpg': 'image/jpeg', '.jpeg': 'image/jpeg',
        '.png': 'image/png', '.webp': 'image/webp',
        '.gif': 'image/gif', '.heic': 'image/heic',
    }
    mime = mime_map.get(ext)
    if not mime:
        return None
    try:
        with open(path, 'rb') as fh:
            b64 = base64.b64encode(fh.read()).decode('ascii')
    except Exception as e:
        logger.warning(f"Error leyendo voucher {path}: {e}")
        return None
    return f"data:{mime};base64,{b64}", mime


def _parse_date(value) -> 'datetime.date | None':
    if not value or not isinstance(value, str):
        return None
    try:
        return datetime.strptime(value[:10], '%Y-%m-%d').date()
    except ValueError:
        return None


def _parse_decimal(value) -> 'Decimal | None':
    if value is None or value == '':
        return None
    try:
        return Decimal(str(value))
    except (InvalidOperation, ValueError, TypeError):
        return None


def _parse_currency(value) -> 'str | None':
    if not value or not isinstance(value, str):
        return None
    v = value.strip().upper()
    if v in ('PEN', 'USD'):
        return v
    if v in ('SOL', 'SOLES', 'S/', 'S/.'):
        return 'PEN'
    if v in ('DOLAR', 'DOLARES', '$', 'DOL'):
        return 'USD'
    return None


def analyze_voucher(receipt, force: bool = False, model: str = 'gpt-4o'):
    """Procesa un RentalReceipt con OpenAI Vision y guarda los campos ai_*.

    Si `receipt.ai_processed_at` ya está seteado y `force=False`, no hace
    nada (idempotente). Retorna el `receipt` actualizado.

    Errores se persisten en `receipt.ai_error` y `ai_processed_at` se
    setea igual para no reintentar en bucle (salvo force=True).
    """
    if receipt.ai_processed_at and not force:
        return receipt

    update_fields = [
        'ai_description', 'ai_bank_origin', 'ai_bank_destination',
        'ai_destination_account', 'ai_currency', 'ai_amount',
        'ai_deposit_date', 'ai_processed_at', 'ai_error',
    ]

    api_key = getattr(settings, 'OPENAI_API_KEY', '')
    if not api_key:
        receipt.ai_error = 'OPENAI_API_KEY no configurada'
        receipt.ai_processed_at = timezone.now()
        receipt.save(update_fields=update_fields)
        return receipt

    if not receipt.file or not receipt.file.name:
        receipt.ai_error = 'voucher sin archivo'
        receipt.ai_processed_at = timezone.now()
        receipt.save(update_fields=update_fields)
        return receipt

    path = os.path.join(settings.MEDIA_ROOT, receipt.file.name)
    data = _file_to_data_url(path)
    if not data:
        receipt.ai_error = f'tipo de archivo no soportado o ilegible: {receipt.file.name}'
        receipt.ai_processed_at = timezone.now()
        receipt.save(update_fields=update_fields)
        return receipt
    data_url, _mime = data

    try:
        import openai  # type: ignore
        client = openai.OpenAI(api_key=api_key)
        response = client.chat.completions.create(
            model=model,
            response_format={'type': 'json_object'},
            messages=[
                {'role': 'system', 'content': SYSTEM_PROMPT},
                {
                    'role': 'user',
                    'content': [
                        {'type': 'text', 'text': USER_PROMPT},
                        {
                            'type': 'image_url',
                            'image_url': {'url': data_url, 'detail': 'high'},
                        },
                    ],
                },
            ],
            temperature=0,
            max_tokens=400,
        )
        raw = response.choices[0].message.content or '{}'
        parsed = json.loads(raw)
    except Exception as e:
        logger.error(
            f"Error analizando voucher id={receipt.id}: {e}", exc_info=True,
        )
        receipt.ai_error = f'fallo OpenAI: {str(e)[:300]}'
        receipt.ai_processed_at = timezone.now()
        receipt.save(update_fields=update_fields)
        return receipt

    receipt.ai_bank_origin = (parsed.get('bank_origin') or None)
    receipt.ai_bank_destination = (parsed.get('bank_destination') or None)
    receipt.ai_destination_account = (
        parsed.get('destination_account') or None
    )
    receipt.ai_currency = _parse_currency(parsed.get('currency'))
    receipt.ai_amount = _parse_decimal(parsed.get('amount'))
    receipt.ai_deposit_date = _parse_date(parsed.get('deposit_date'))
    receipt.ai_description = (parsed.get('description') or '').strip() or None
    receipt.ai_error = None
    receipt.ai_processed_at = timezone.now()

    # Truncar strings al max_length del modelo (defensivo)
    if receipt.ai_bank_origin:
        receipt.ai_bank_origin = receipt.ai_bank_origin[:100]
    if receipt.ai_bank_destination:
        receipt.ai_bank_destination = receipt.ai_bank_destination[:100]
    if receipt.ai_destination_account:
        receipt.ai_destination_account = receipt.ai_destination_account[:120]

    receipt.save(update_fields=update_fields)
    logger.info(
        f"Voucher analizado id={receipt.id} "
        f"bank={receipt.ai_bank_destination} amount={receipt.ai_amount} "
        f"date={receipt.ai_deposit_date}"
    )
    return receipt
