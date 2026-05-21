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


# ─── Clasificación de relaciones familiares ──────────────────────────────

def _strip_accents(s: str) -> str:
    import unicodedata
    return ''.join(
        c for c in unicodedata.normalize('NFD', s)
        if unicodedata.category(c) != 'Mn'
    )


def classify_relation(raw_type: str) -> dict:
    """Clasifica un relation_type crudo de Leder en campos derivados.

    Input: "TIO PATERNO", "ABUELA MATERNA", "PADRE", "HERMANO", etc.

    Output dict con:
        category: PADRE | MADRE | HERMANO | HIJO | CONYUGE
                | ABUELO | ABUELA | TIO | TIA
                | PRIMO | PRIMA | SOBRINO | SOBRINA
                | OTRO
        line: PATERNAL | MATERNAL | DIRECT | NONE
        gender_inferred: M | F | U
        generation: -2 (abuelos) | -1 (padres/tíos) | 0 (mismo: hermanos, cónyuge, primos)
                  | +1 (hijos, sobrinos) | +2 (nietos)
        canonical_label: forma humana en español
    """
    if not raw_type:
        return {
            'category': 'OTRO', 'line': 'NONE',
            'gender_inferred': 'U', 'generation': 0,
            'canonical_label': '',
        }
    t = _strip_accents(raw_type).upper().strip()

    # ── Padres / madres ──
    if t == 'PADRE':
        return {'category': 'PADRE', 'line': 'PATERNAL', 'gender_inferred': 'M',
                'generation': -1, 'canonical_label': 'Padre'}
    if t == 'MADRE':
        return {'category': 'MADRE', 'line': 'MATERNAL', 'gender_inferred': 'F',
                'generation': -1, 'canonical_label': 'Madre'}

    # ── Cónyuge ──
    if t in ('CONYUGE', 'ESPOSO', 'ESPOSA', 'PAREJA'):
        gender = 'M' if t == 'ESPOSO' else 'F' if t == 'ESPOSA' else 'U'
        return {'category': 'CONYUGE', 'line': 'NONE', 'gender_inferred': gender,
                'generation': 0, 'canonical_label': 'Cónyuge'}

    # ── Hermanos ──
    if t.startswith('HERMAN'):
        gender = 'F' if t.startswith('HERMANA') else 'M' if t.startswith('HERMANO') else 'U'
        return {'category': 'HERMANO', 'line': 'DIRECT', 'gender_inferred': gender,
                'generation': 0, 'canonical_label': 'Hermano/a'}

    # ── Hijos ──
    if t.startswith('HIJO') or t.startswith('HIJA'):
        gender = 'F' if t.startswith('HIJA') else 'M'
        return {'category': 'HIJO', 'line': 'DIRECT', 'gender_inferred': gender,
                'generation': 1, 'canonical_label': 'Hijo/a'}

    # ── Nietos ──
    if t.startswith('NIET'):
        gender = 'F' if t.startswith('NIETA') else 'M' if t.startswith('NIETO') else 'U'
        return {'category': 'NIETO', 'line': 'DIRECT', 'gender_inferred': gender,
                'generation': 2, 'canonical_label': 'Nieto/a'}

    # ── Abuelos ──
    if 'ABUEL' in t:
        is_female = 'ABUELA' in t
        is_maternal = 'MATERN' in t
        if is_female:
            label = 'Abuela ' + ('materna' if is_maternal else 'paterna')
        else:
            label = 'Abuelo ' + ('materno' if is_maternal else 'paterno')
        return {
            'category': 'ABUELA' if is_female else 'ABUELO',
            'line': 'MATERNAL' if is_maternal else 'PATERNAL',
            'gender_inferred': 'F' if is_female else 'M',
            'generation': -2,
            'canonical_label': label,
        }

    # ── Tíos / tías ──
    if t.startswith('TIA') or t.startswith('TIO'):
        is_female = t.startswith('TIA')
        is_maternal = 'MATERN' in t
        if is_female:
            label = 'Tía ' + ('materna' if is_maternal else 'paterna')
        else:
            label = 'Tío ' + ('materno' if is_maternal else 'paterno')
        return {
            'category': 'TIA' if is_female else 'TIO',
            'line': 'MATERNAL' if is_maternal else 'PATERNAL',
            'gender_inferred': 'F' if is_female else 'M',
            'generation': -1,
            'canonical_label': label,
        }

    # ── Primos ──
    if t.startswith('PRIM'):
        is_female = t.startswith('PRIMA')
        return {
            'category': 'PRIMA' if is_female else 'PRIMO',
            'line': 'NONE',
            'gender_inferred': 'F' if is_female else 'M',
            'generation': 0,
            'canonical_label': 'Prima' if is_female else 'Primo',
        }

    # ── Sobrinos ──
    if t.startswith('SOBRIN'):
        is_female = t.startswith('SOBRINA')
        return {
            'category': 'SOBRINA' if is_female else 'SOBRINO',
            'line': 'DIRECT',
            'gender_inferred': 'F' if is_female else 'M',
            'generation': 1,
            'canonical_label': 'Sobrina' if is_female else 'Sobrino',
        }

    # ── Otros (cuñados, suegros, políticos, etc.) ──
    return {
        'category': 'OTRO', 'line': 'NONE',
        'gender_inferred': 'U', 'generation': 0,
        'canonical_label': raw_type.title(),
    }
