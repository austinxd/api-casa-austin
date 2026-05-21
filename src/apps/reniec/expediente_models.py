"""Modelos del expediente extendido por DNI.

Cada modelo es una tabla SEPARADA de DNICache (que queda intacta) y se
relaciona vía FK por el campo `dni`. Todos son resultado de consultar
endpoints específicos de Leder:

    PersonPhone           ← /telefonia/numero (input phone, output DNI titular)
    PersonFamilyRelation  ← /persona/arbol-genealogico + /persona/familia-1
    PersonSalaryRecord    ← /persona/sueldos
    PersonMarriage        ← /persona/matrimonios
    PersonAddress         ← /persona/direcciones (con dedupe inteligente)
    PersonPoliceRecord    ← /persona/denuncias-policiales-dni
    PersonExpedienteMeta  ← tabla 1:1 con TTLs de refresh por endpoint

Política de cache:
- Cada modelo se popula desde el service correspondiente.
- PersonExpedienteMeta.{fetched_at} controla si refrescar o no.
- Familiares: lazy-creación de DNICache con info mínima + lookup completo
  en background (no bloquea la respuesta del /full/<dni>/).
"""
from django.db import models
from django.utils import timezone

from apps.core.models import BaseModel
from .expediente_helpers import (
    classify_tipificacion,
    normalize_address,
    normalize_phone,
    POLICE_CATEGORY_CHOICES,
)


# ─── 1) Telefonía: titularidad de un número ─────────────────────────────

class PersonPhone(BaseModel):
    """Titularidad de un número telefónico según operadores.

    Leder devuelve varias coincidencias por número (una por operador/periodo).
    Nosotros conservamos solo la MÁS RECIENTE por (phone, operator) — no nos
    interesa el historial intermedio del mismo operador. Si el teléfono cambió
    de titular (DNI distinto en consulta nueva), se agrega un row nuevo.
    """
    dni = models.ForeignKey(
        'reniec.DNICache', to_field='dni', db_column='dni',
        on_delete=models.CASCADE, related_name='phones',
        help_text="DNI titular del teléfono (según Leder)",
    )
    phone = models.CharField(
        max_length=15, db_index=True,
        help_text="Número normalizado (últimos 9 dígitos Perú)",
    )
    operator = models.CharField(
        max_length=30, blank=True,
        help_text="MOVISTAR / ENTEL / CLARO / BITEL / etc.",
    )
    plan = models.CharField(max_length=100, blank=True)
    period = models.DateField(
        null=True, blank=True,
        help_text="Periodo de la titularidad (parseado de Leder)",
    )
    source = models.CharField(
        max_length=50, blank=True,
        help_text="Fuente original tal cual vino (MOVISTAR / CLARO POSTPAGO / etc.)",
    )

    class Meta:
        verbose_name = '📱 Titularidad teléfono'
        verbose_name_plural = '📱 Titularidades teléfono'
        unique_together = ('phone', 'operator', 'dni')
        indexes = [
            models.Index(fields=['phone']),
            models.Index(fields=['dni', '-period']),
        ]

    def save(self, *args, **kwargs):
        # Normaliza phone antes de guardar
        if self.phone:
            self.phone = normalize_phone(self.phone)
        super().save(*args, **kwargs)

    def __str__(self):
        return f"📱 {self.phone} → {self.dni_id} ({self.operator}, {self.period})"


# ─── 2) Familiares (árbol genealógico + familia-1) ──────────────────────

class PersonFamilyRelation(BaseModel):
    """Relación familiar entre 2 personas en DNICache.

    Origen: /persona/arbol-genealogico (consanguíneos) o /persona/familia-1
    (cohabitantes del hogar según censo). Ambos van a la misma tabla con
    `source` distinto — si un familiar aparece en ambos, son 2 rows.

    Los campos cached_* permiten mostrar info básica del familiar mientras
    se hace el lookup completo en background (que enriquece DNICache).
    """

    class RelationSource(models.TextChoices):
        ARBOL = 'arbol_genealogico', 'Árbol Genealógico'
        FAMILIA = 'familia_1', 'Familia-1 (Censo)'

    class Verification(models.TextChoices):
        ALTA = 'ALTA', 'Alta'
        MEDIA = 'MEDIA', 'Media'
        BAJA = 'BAJA', 'Baja'
        DESCONOCIDA = '', 'Desconocida'

    dni = models.ForeignKey(
        'reniec.DNICache', to_field='dni', db_column='dni',
        on_delete=models.CASCADE, related_name='family_relations',
        help_text="Persona consultada (el 'titular' del expediente)",
    )
    relative_dni = models.ForeignKey(
        'reniec.DNICache', to_field='dni', db_column='relative_dni',
        on_delete=models.CASCADE, related_name='inverse_family_relations',
        help_text="Familiar relacionado (en DNICache, lazy-creado)",
    )
    relation_type = models.CharField(
        max_length=40, db_index=True,
        help_text="PADRE / MADRE / HERMANO / TIO_PATERNO / COHABITANTE / etc.",
    )
    verification = models.CharField(
        max_length=15, blank=True, choices=Verification.choices,
        help_text="Solo para arbol_genealogico — confianza de la relación según Leder",
    )
    source = models.CharField(
        max_length=20, choices=RelationSource.choices,
        help_text="De qué endpoint Leder vino esta relación",
    )

    # Cached del response (para no esperar el lookup completo del familiar)
    cached_name = models.CharField(max_length=200, blank=True)
    cached_gender = models.CharField(max_length=15, blank=True)
    cached_age_at_query = models.IntegerField(null=True, blank=True)
    cached_birthday = models.DateField(null=True, blank=True)

    class Meta:
        verbose_name = '👥 Relación familiar'
        verbose_name_plural = '👥 Relaciones familiares'
        unique_together = ('dni', 'relative_dni', 'source')
        indexes = [
            models.Index(fields=['dni', 'relation_type']),
            models.Index(fields=['relative_dni']),
        ]

    def __str__(self):
        return f"👥 {self.dni_id} → {self.relation_type} → {self.relative_dni_id}"


# ─── 3) Sueldos históricos ──────────────────────────────────────────────

class PersonSalaryRecord(BaseModel):
    """Sueldo declarado por una empresa para una persona en un periodo.

    Leder suele devolver muchos registros (>50 es común). Guardamos todo el
    histórico. El dedupe lo hace el unique_together — si re-consultamos y
    aparecen los mismos registros, no se duplican.
    """

    class Situation(models.TextChoices):
        ACTIVO = 'A', 'Activo'
        BAJA = 'B', 'Baja'
        SUSPENDIDO = 'S', 'Suspendido'
        OTRO = 'O', 'Otro'

    dni = models.ForeignKey(
        'reniec.DNICache', to_field='dni', db_column='dni',
        on_delete=models.CASCADE, related_name='salaries',
    )
    ruc = models.CharField(max_length=11, db_index=True)
    company_name = models.CharField(max_length=255, blank=True)
    situation = models.CharField(
        max_length=2, blank=True,
        help_text="Estado de la relación laboral según Leder (A/B/...)",
    )
    salary_pen = models.DecimalField(
        max_digits=12, decimal_places=2, null=True, blank=True,
        help_text="Monto declarado en Soles",
    )
    period = models.DateField(
        help_text="Periodo declarado (parseado de YYYYMM o equivalente)",
    )

    class Meta:
        verbose_name = '💼 Sueldo declarado'
        verbose_name_plural = '💼 Sueldos declarados'
        unique_together = ('dni', 'ruc', 'period')
        indexes = [
            models.Index(fields=['dni', '-period']),
            models.Index(fields=['ruc']),
        ]

    def __str__(self):
        return f"💼 {self.dni_id} @ {self.company_name[:30]} ({self.period}) S/{self.salary_pen}"


# ─── 4) Matrimonios ─────────────────────────────────────────────────────

class PersonMarriage(BaseModel):
    """Acta de matrimonio. Si Leder devuelve `result: {}` significa que la
    persona no está registrada como casada — no se crea row."""

    dni = models.ForeignKey(
        'reniec.DNICache', to_field='dni', db_column='dni',
        on_delete=models.CASCADE, related_name='marriages',
    )
    spouse_dni = models.ForeignKey(
        'reniec.DNICache', to_field='dni', db_column='spouse_dni',
        on_delete=models.SET_NULL, null=True, blank=True,
        related_name='inverse_marriages',
        help_text="DNI del cónyuge (lazy-creado en DNICache)",
    )
    spouse_name = models.CharField(
        max_length=200, blank=True,
        help_text="Nombre del cónyuge (fallback si no hay DNI matcheable)",
    )
    marriage_date = models.DateField(null=True, blank=True)
    divorce_date = models.DateField(null=True, blank=True)
    location = models.CharField(max_length=200, blank=True)
    source_raw = models.JSONField(
        default=dict, blank=True,
        help_text="JSON crudo de Leder para no perder info",
    )

    class Meta:
        verbose_name = '💍 Matrimonio'
        verbose_name_plural = '💍 Matrimonios'

    def __str__(self):
        return f"💍 {self.dni_id} ⇄ {self.spouse_dni_id or self.spouse_name} ({self.marriage_date})"


# ─── 5) Direcciones ─────────────────────────────────────────────────────

class PersonAddress(BaseModel):
    """Dirección histórica de una persona. Dedupe inteligente por normalización.

    Leder devuelve direcciones de varias fuentes (RENIEC 2017/2021/2023,
    SUNAT, INMUEBLES, FUENTE INTERNA). Cuando 2 direcciones normalizadas son
    iguales, se actualiza `last_seen` en vez de crear row nueva.

    `is_current_best`: 1 sola por persona, la que el sistema considera la
    dirección actual (calculado por job según source_year y last_seen).
    """
    dni = models.ForeignKey(
        'reniec.DNICache', to_field='dni', db_column='dni',
        on_delete=models.CASCADE, related_name='addresses',
    )
    address_raw = models.CharField(max_length=500)
    address_norm = models.CharField(
        max_length=500, db_index=True,
        help_text="Normalizada para dedupe (uppercase, sin abreviaciones)",
    )
    ubicacion = models.CharField(
        max_length=200, blank=True,
        help_text="LIMA - LIMA - SAN LUIS / etc.",
    )
    source = models.CharField(
        max_length=50, blank=True,
        help_text="RENIEC 2023 / SUNAT / INMUEBLES / FUENTE INTERNA",
    )
    source_year = models.IntegerField(
        null=True, blank=True,
        help_text="Año extraído de la fuente (ej. RENIEC 2023 → 2023)",
    )
    first_seen = models.DateField(
        default=timezone.now,
        help_text="Cuándo apareció esta dirección por primera vez en nuestras consultas",
    )
    last_seen = models.DateField(
        default=timezone.now,
        help_text="Última vez que Leder devolvió esta dirección",
    )
    is_current_best = models.BooleanField(
        default=False, db_index=True,
        help_text="1 sola dirección por persona — la más probable de ser la actual",
    )

    class Meta:
        verbose_name = '🏠 Dirección registrada'
        verbose_name_plural = '🏠 Direcciones registradas'
        unique_together = ('dni', 'address_norm')
        indexes = [
            models.Index(fields=['dni', '-last_seen']),
            models.Index(fields=['dni', 'is_current_best']),
        ]

    def save(self, *args, **kwargs):
        # Re-normalizar siempre que se cambie raw
        if self.address_raw and not self.address_norm:
            self.address_norm = normalize_address(self.address_raw)
        # Extraer año de la fuente si es RENIEC YYYY
        if self.source and not self.source_year:
            import re
            m = re.search(r'(20\d{2}|19\d{2})', self.source)
            if m:
                self.source_year = int(m.group(1))
        super().save(*args, **kwargs)

    def __str__(self):
        return f"🏠 {self.dni_id}: {self.address_raw[:60]}"


# ─── 6) Denuncias policiales ────────────────────────────────────────────

class PersonPoliceRecord(BaseModel):
    """Denuncia policial registrada para un DNI.

    `category` se calcula automáticamente desde `tipificacion_raw` usando
    classify_tipificacion(). Permite agrupar/contar por tipo:
    ROBO / VIOLENCIA / PERDIDA / ACCIDENTE / FRAUDE / AMENAZAS / FAMILIAR /
    VEHICULAR / OTROS.

    `rol_dni`: rol del DNI consultado en esta denuncia. CRÍTICO para no
    confundir víctimas con acusados. Valores:
        DENUNCIANTE | DENUNCIADO | AGRAVIADO | TESTIGO | INVESTIGADO |
        IMPUTADO | OTRO | DESCONOCIDO
    """

    class RolDni(models.TextChoices):
        DENUNCIANTE = 'DENUNCIANTE', 'Denunciante (presentó la denuncia)'
        DENUNCIADO = 'DENUNCIADO', 'Denunciado (acusado)'
        AGRAVIADO = 'AGRAVIADO', 'Agraviado (víctima)'
        TESTIGO = 'TESTIGO', 'Testigo'
        INVESTIGADO = 'INVESTIGADO', 'Investigado'
        IMPUTADO = 'IMPUTADO', 'Imputado'
        OTRO = 'OTRO', 'Otro'
        DESCONOCIDO = 'DESCONOCIDO', 'Desconocido'

    dni = models.ForeignKey(
        'reniec.DNICache', to_field='dni', db_column='dni',
        on_delete=models.CASCADE, related_name='police_records',
    )
    nro_denuncia = models.CharField(max_length=30, db_index=True)
    clave = models.CharField(max_length=30, blank=True)
    codigo_ruva = models.CharField(max_length=30, blank=True)

    region_policial = models.CharField(max_length=100, blank=True)
    comisaria = models.CharField(max_length=100, blank=True)

    denuncia_type = models.CharField(
        max_length=30, blank=True,
        help_text="DENUNCIA / OFICIO / ATESTADO según Leder",
    )
    formalidad = models.CharField(
        max_length=30, blank=True,
        help_text="VERBAL / ESCRITA",
    )
    condicion = models.CharField(max_length=200, blank=True)

    category = models.CharField(
        max_length=20, choices=POLICE_CATEGORY_CHOICES, db_index=True,
        default='OTROS',
        help_text="Categoría derivada de tipificacion (clasificador automático)",
    )
    tipificacion_raw = models.TextField(
        blank=True,
        help_text="Tipificación textual cruda de Leder",
    )

    # CRÍTICO: rol del DNI consultado en esta denuncia
    rol_dni = models.CharField(
        max_length=20, choices=RolDni.choices, db_index=True,
        default=RolDni.DESCONOCIDO,
        help_text="Rol del DNI consultado: denunciante / denunciado / testigo / etc.",
    )
    nombre_denunciante = models.CharField(
        max_length=200, blank=True,
        help_text="Quién presentó la denuncia (puede no ser el DNI consultado)",
    )
    personas_raw = models.JSONField(
        default=list, blank=True,
        help_text="Array completo de personas involucradas con su situación (de Leder)",
    )

    fecha_hecho = models.DateTimeField(null=True, blank=True, db_index=True)
    fecha_registro = models.DateTimeField(null=True, blank=True)
    lugar_hecho = models.CharField(max_length=300, blank=True)
    contenido = models.TextField(
        blank=True,
        help_text="Descripción completa de los hechos (texto largo)",
    )
    qr_valor = models.CharField(max_length=255, blank=True)

    class Meta:
        verbose_name = '🚨 Denuncia policial'
        verbose_name_plural = '🚨 Denuncias policiales'
        unique_together = ('dni', 'nro_denuncia')
        indexes = [
            models.Index(fields=['dni', '-fecha_hecho']),
            models.Index(fields=['dni', 'category']),
        ]

    def save(self, *args, **kwargs):
        # Auto-clasificar si tenemos tipificacion_raw y no se setear category manual
        if self.tipificacion_raw and (not self.category or self.category == 'OTROS'):
            self.category = classify_tipificacion(self.tipificacion_raw)
        super().save(*args, **kwargs)

    def __str__(self):
        return f"🚨 {self.dni_id} #{self.nro_denuncia} {self.category} ({self.fecha_hecho.date() if self.fecha_hecho else '?'})"


# ─── 7) Meta: TTLs de refresh ──────────────────────────────────────────

class PersonExpedienteMeta(models.Model):
    """Tabla 1:1 con DNICache que guarda cuándo se consultó cada endpoint
    de Leder por última vez.

    Política de cache: PERMANENTE. Una vez que se consulta un endpoint para
    un DNI, los datos quedan cacheados indefinidamente. Solo se re-consulta
    a Leder si:
      1. Nunca se consultó (fetched_at IS NULL para ese campo).
      2. El caller pasa force=True / force_refresh=True explícitamente.

    No hereda de BaseModel porque usa `dni` como PK (no necesita UUID extra).
    """

    dni = models.OneToOneField(
        'reniec.DNICache', to_field='dni', db_column='dni',
        on_delete=models.CASCADE, primary_key=True,
        related_name='expediente_meta',
    )

    # Campos heredados de BaseModel a mano (no podemos heredar porque
    # BaseModel ya define `id` UUID como PK):
    created = models.DateTimeField(
        "created at", auto_now_add=True,
        help_text="When the instance was created.",
    )
    updated = models.DateTimeField(
        "updated at", auto_now=True,
        help_text="The last time at the instance was modified.",
    )
    deleted = models.BooleanField(
        default=False,
        help_text="It can be set to false, usefull to simulate deletion",
    )

    phones_fetched_at = models.DateTimeField(null=True, blank=True)
    family_tree_fetched_at = models.DateTimeField(null=True, blank=True)
    family_household_fetched_at = models.DateTimeField(null=True, blank=True)
    salaries_fetched_at = models.DateTimeField(null=True, blank=True)
    marriages_fetched_at = models.DateTimeField(null=True, blank=True)
    addresses_fetched_at = models.DateTimeField(null=True, blank=True)
    police_fetched_at = models.DateTimeField(null=True, blank=True)

    last_full_refresh_at = models.DateTimeField(
        null=True, blank=True,
        help_text="Última vez que se llamó /full/<dni>/ con refresh completo",
    )

    class Meta:
        verbose_name = '📋 Expediente meta (TTLs)'
        verbose_name_plural = '📋 Expedientes meta (TTLs)'

    def needs_refresh(self, field: str) -> bool:
        """¿Se debe re-consultar este endpoint?

        SOLO si NUNCA se consultó (fetched_at es NULL). No hay TTL automático
        — el cache es permanente. Para forzar refresh, el caller debe pasar
        force=True directamente (no se chequea acá).
        """
        fetched_at = getattr(self, f'{field}_fetched_at', None)
        return fetched_at is None

    def mark_fetched(self, field: str):
        """Marca que acabamos de refrescar este endpoint."""
        setattr(self, f'{field}_fetched_at', timezone.now())
        self.save(update_fields=[f'{field}_fetched_at', 'updated'])

    def __str__(self):
        return f"📋 Meta {self.dni_id}"
