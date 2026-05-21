"""Funciones puras usadas por los modelos del expediente.

Aisladas de Django/DB para que sean fáciles de testear:
- normalize_address: dedupe de direcciones (AV ≡ AVENIDA, mayúsculas, espacios)
- classify_tipificacion: mapea texto largo de denuncias a categoría simple
- parse_period: parsea periodos en formato inconsistente (str/int/datetime)
- normalize_phone: deja últimos 9 dígitos (Perú)
"""
import re
from datetime import date, datetime
from typing import Optional


# ─── Direcciones ─────────────────────────────────────────────────────────

_ADDRESS_NORM_RULES = [
    # Palabra → forma corta
    (r'\bAV(\.|\s+)+', 'AV '),
    (r'\bAVENIDA(\.|\s+)+', 'AV '),
    (r'\bJR(\.|\s+)+', 'JR '),
    (r'\bJIRON(\.|\s+)+', 'JR '),
    (r'\bCALLE(\.|\s+)+', 'CL '),
    (r'\bCL(\.|\s+)+', 'CL '),
    (r'\bPSJ(\.|\s+)+', 'PJ '),
    (r'\bPASAJE(\.|\s+)+', 'PJ '),
    (r'\bMZA(\.|\s+)+', 'MZ '),
    (r'\bMZ(\.|\s+)+', 'MZ '),
    (r'\bLT(\.|\s+)+', 'LT '),
    (r'\bLOTE(\.|\s+)+', 'LT '),
    (r'\bINT(\.|\s+)+', 'INT '),
    (r'\bNRO(\.|\s+)+', 'NRO '),
    (r'\bNUMERO(\.|\s+)+', 'NRO '),
    (r'\bN[°º](\s+)+', 'NRO '),
    (r'\bURB(\.|\s+)+', 'URB '),
    (r'\bURBANIZACION(\.|\s+)+', 'URB '),
    (r'\bDPTO(\.|\s+)+', 'DPTO '),
    (r'\bDEPARTAMENTO(\.|\s+)+', 'DPTO '),
    (r'\bPISO(\.|\s+)+', 'PISO '),
]


def normalize_address(address: str) -> str:
    """Normaliza una dirección para dedupe.

    Aplica:
    - uppercase + strip
    - colapsa espacios múltiples
    - reemplaza variantes (AV. / AVENIDA / AV → AV)
    - quita signos de puntuación extra

    Ej: "AV.ERNESTO DIEZ CANSECO 285 INT.8"
        "AVENIDA ERNESTO DIEZ CANSECO 285 INT. 8"
        "  Av. Ernesto Diez Canseco 285 int 8  "
        → todas devuelven "AV ERNESTO DIEZ CANSECO 285 INT 8"
    """
    if not address:
        return ''
    s = address.upper().strip()
    # Quitar puntos sueltos al final de palabras y dobles espacios
    for pattern, replacement in _ADDRESS_NORM_RULES:
        s = re.sub(pattern, replacement, s, flags=re.IGNORECASE)
    # Colapsar puntuación residual y espacios
    s = re.sub(r'[.,;:]', ' ', s)
    s = re.sub(r'\s+', ' ', s).strip()
    return s


# ─── Periodos (formato inconsistente de Leder) ──────────────────────────

def parse_period(value) -> Optional[date]:
    """Convierte el campo `periodo` de Leder a date.

    Acepta:
    - int 202110     → date(2021, 10, 1)
    - str "202410"   → date(2024, 10, 1)
    - str "2021-12-17 00:00:00" → date(2021, 12, 17)
    - str "2021-12-17" → date(2021, 12, 17)
    - None / ''      → None
    """
    if value is None or value == '':
        return None
    s = str(value).strip()
    # YYYY-MM-DD (con o sin hora)
    m = re.match(r'^(\d{4})-(\d{2})-(\d{2})', s)
    if m:
        try:
            return date(int(m.group(1)), int(m.group(2)), int(m.group(3)))
        except ValueError:
            return None
    # YYYYMM (string o int)
    m = re.match(r'^(\d{4})(\d{2})$', s)
    if m:
        try:
            return date(int(m.group(1)), int(m.group(2)), 1)
        except ValueError:
            return None
    # DD/MM/YYYY (formato Reniec/Leder común)
    m = re.match(r'^(\d{2})/(\d{2})/(\d{4})', s)
    if m:
        try:
            return date(int(m.group(3)), int(m.group(2)), int(m.group(1)))
        except ValueError:
            return None
    return None


def parse_datetime_leder(value) -> Optional[datetime]:
    """Parsea datetime de Leder. Formato típico: '12/02/2012 16:09:27 Hrs.'"""
    if not value:
        return None
    s = str(value).strip().replace('Hrs.', '').strip()
    for fmt in ['%d/%m/%Y %H:%M:%S', '%d/%m/%Y %H:%M', '%d/%m/%Y', '%Y-%m-%d %H:%M:%S']:
        try:
            return datetime.strptime(s, fmt)
        except ValueError:
            continue
    return None


# ─── Teléfono ────────────────────────────────────────────────────────────

def normalize_phone(phone: str) -> str:
    """Deja únicamente los últimos 9 dígitos (móvil Perú).

    "+51 986 607 686" → "986607686"
    "986-607-686"     → "986607686"
    """
    if not phone:
        return ''
    digits = re.sub(r'\D', '', phone)
    return digits[-9:] if len(digits) >= 9 else digits


# ─── Clasificación de denuncias ──────────────────────────────────────────

# Cada categoría es (label, [palabras clave en la tipificacion / contenido])
_POLICE_CATEGORIES = [
    ('ROBO', [r'\bROBO\b', r'HURTO', r'ARREBATO']),
    ('VIOLENCIA', [r'VIOLENCIA', r'AGRESION', r'LESIONES']),
    ('PERDIDA', [r'PERDIDA\s+DE\s+DOCUMENTO', r'EXTRAVIO', r'PERDIDA']),
    ('ACCIDENTE', [r'ACCIDENTE', r'CHOQUE', r'COLISION']),
    ('FRAUDE', [r'ESTAFA', r'FRAUDE', r'SUPLANTACION']),
    ('AMENAZAS', [r'AMENAZA', r'COACCION', r'HOSTIGAMIENTO']),
    ('FAMILIAR', [r'VIOLENCIA\s+FAMILIAR', r'MALTRATO\s+FAMILIAR']),
    ('VEHICULAR', [r'VEHICUL', r'TRANSITO']),
]

POLICE_CATEGORY_OTROS = 'OTROS'


def classify_tipificacion(tipificacion_text: str) -> str:
    """Mapea la tipificación cruda de Leder a una categoría simple.

    Ejemplos:
    "HECHOS DE INTERES POLICIAL/INTERVENCION POLICIALES/OBRA COMO CONSTANCIA"
        → "OTROS"
    "HECHOS DE INTERES POLICIAL/DENUNCIAS ESPECIALES/PERDIDA DE DOCUMENTO"
        → "PERDIDA"
    "DELITOS CONTRA EL PATRIMONIO/ROBO AGRAVADO"
        → "ROBO"
    """
    if not tipificacion_text:
        return POLICE_CATEGORY_OTROS
    text = tipificacion_text.upper()
    for label, patterns in _POLICE_CATEGORIES:
        for pat in patterns:
            if re.search(pat, text):
                return label
    return POLICE_CATEGORY_OTROS


POLICE_CATEGORY_CHOICES = [(c[0], c[0].title()) for c in _POLICE_CATEGORIES] + [
    (POLICE_CATEGORY_OTROS, 'Otros'),
]
