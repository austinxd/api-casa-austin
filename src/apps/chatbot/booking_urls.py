"""Constructores de URLs parametrizadas para que el chatbot envíe al cliente
links con check-in/check-out/personas/casa pre-llenados (Fase R1.0).

Reglas (acordadas con el equipo):
- Multi-casa o sin casa elegida → /disponibilidad (cliente elige en el listado).
- Casa específica → /reservar (alias comercial de /booking, mismo componente).
- Fechas SIEMPRE en YYYY-MM-DD: /booking lee el query param directo sin convertir.
"""
from datetime import date
from urllib.parse import urlencode


BASE_URL = 'https://casaaustin.pe'


def _format_date(d):
    """Acepta date, datetime o string 'YYYY-MM-DD' y retorna 'YYYY-MM-DD'."""
    if isinstance(d, date):
        return d.strftime('%Y-%m-%d')
    return str(d)


def build_booking_url(property_slug, check_in, check_out, guests, currency='SOL'):
    """Link directo a /reservar (alias de /booking) con casa pre-elegida.

    Uso: una sola casa disponible o el cliente ya seleccionó una casa específica.
    """
    params = {
        'property': property_slug,
        'checkIn': _format_date(check_in),
        'checkOut': _format_date(check_out),
        'guests': int(guests),
        'currency': currency.upper(),
    }
    return f"{BASE_URL}/reservar?{urlencode(params)}"


def build_availability_url(check_in, check_out, guests):
    """Link al listado /disponibilidad con fechas/personas pre-llenadas.

    Uso: varias casas disponibles — el cliente elige cuál separar.
    """
    params = {
        'checkIn': _format_date(check_in),
        'checkOut': _format_date(check_out),
        'guests': int(guests),
    }
    return f"{BASE_URL}/disponibilidad?{urlencode(params)}"


def build_property_url(slug, check_in=None, check_out=None, guests=None):
    """Link a /casas-en-alquiler/<slug> con fechas/personas opcionales.

    Uso: info detallada de una casa específica (galería de fotos).
    """
    base = f"{BASE_URL}/casas-en-alquiler/{slug}"
    if not check_in or not check_out:
        return base
    params = {
        'checkIn': _format_date(check_in),
        'checkOut': _format_date(check_out),
    }
    if guests:
        params['guests'] = int(guests)
    return f"{base}?{urlencode(params)}"
