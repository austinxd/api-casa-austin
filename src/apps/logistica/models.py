"""
Módulo de Logística — control financiero y operativo de Casa Austin.

Reemplaza el Excel quincenal de gastos, sueldos, limpiezas extras
y reembolsos a personal que paga de su bolsillo.

Auditoría: simple_history registra automáticamente created_by/updated_by
vía el middleware CustomHistoryRequestMiddleware (ya configurado en core).

Sin acoplamiento al chatbot. Solo accesible desde la sección Logística
de la web admin y la app mobile (visibilidad por superuser, validada en
frontend — backend no impone permiso por ahora).
"""
from django.conf import settings
from django.db import models
from simple_history.models import HistoricalRecords

from apps.core.models import BaseModel
from apps.property.models import Property


# ============================================================================
# Helpers para upload paths
# ============================================================================

def expense_voucher_path(instance, filename):
    return f'logistica/vouchers/expenses/{instance.id}/{filename}'

def cleaning_voucher_path(instance, filename):
    return f'logistica/vouchers/cleanings/{instance.id}/{filename}'

def salary_voucher_path(instance, filename):
    return f'logistica/vouchers/salaries/{instance.id}/{filename}'

def reimbursement_voucher_path(instance, filename):
    return f'logistica/vouchers/reimbursements/{instance.id}/{filename}'


# ============================================================================
# Period — Quincena
# ============================================================================

class Period(BaseModel):
    """Quincena: 1–15 o 16–fin del mes.

    Auto-generadas para los próximos 6 meses por un signal o management
    command (Fase C). En Fase A se crean manualmente desde admin.
    """
    start_date = models.DateField(help_text="Primer día de la quincena")
    end_date = models.DateField(help_text="Último día de la quincena")
    label = models.CharField(
        max_length=100,
        help_text="Ej: '1–15 mayo 2026'",
    )
    closed_at = models.DateTimeField(
        null=True, blank=True,
        help_text="Cuándo se cerró el período (no se aceptan más cambios)",
    )

    history = HistoricalRecords()

    class Meta:
        verbose_name = '📅 Quincena'
        verbose_name_plural = '📅 Quincenas'
        ordering = ['-start_date']
        unique_together = ['start_date', 'end_date']

    def __str__(self):
        return self.label or f"{self.start_date} → {self.end_date}"


# ============================================================================
# Staff — Personal (fijo o externo)
# ============================================================================

class Staff(BaseModel):
    """Personal de Casa Austin.

    type=fixed:    empleado con sueldo mensual (Michael, Luis, Paty, Carmen).
                   Genera SalaryPayment cada quincena (50/50 del sueldo).
    type=external: limpiador externo contratado por trabajo (Yoisy).
                   No tiene sueldo fijo, cobra por limpieza puntual.
    """

    class StaffType(models.TextChoices):
        FIXED = 'fixed', 'Fijo (sueldo mensual)'
        EXTERNAL = 'external', 'Externo (por trabajo)'

    class AccountType(models.TextChoices):
        YAPE = 'yape', 'Yape'
        PLIN = 'plin', 'Plin'
        BANK = 'bank', 'Cuenta bancaria'
        OTHER = 'other', 'Otro'

    name = models.CharField(max_length=120)
    staff_type = models.CharField(
        max_length=10, choices=StaffType.choices,
        default=StaffType.FIXED,
    )
    monthly_salary = models.DecimalField(
        max_digits=10, decimal_places=2,
        null=True, blank=True,
        help_text="Solo para staff_type=fixed. Se divide 50/50 por quincena.",
    )
    can_pay_for_expenses = models.BooleanField(
        default=False,
        help_text="Si paga gastos con su dinero y la empresa le reembolsa",
    )
    phone = models.CharField(max_length=30, blank=True, default='')

    # === Datos para pago ===
    account_type = models.CharField(
        max_length=10, choices=AccountType.choices,
        blank=True, default='',
        help_text="Forma de pago preferida",
    )
    account_number = models.CharField(
        max_length=50, blank=True, default='',
        help_text="Número de Yape/Plin (teléfono) o número de cuenta bancaria",
    )
    bank_name = models.CharField(
        max_length=80, blank=True, default='',
        help_text="Solo si account_type=bank. Ej: BCP, BBVA, Interbank",
    )

    notes = models.TextField(blank=True, default='')
    is_active = models.BooleanField(default=True)
    start_date = models.DateField(null=True, blank=True)

    history = HistoricalRecords()

    class Meta:
        verbose_name = '👤 Personal'
        verbose_name_plural = '👤 Personal'
        ordering = ['staff_type', 'name']

    def __str__(self):
        return f"{self.name} ({self.get_staff_type_display()})"


# ============================================================================
# ExpenseCategory + ExpenseItem — Catálogo
# ============================================================================

class ExpenseCategory(BaseModel):
    """Categoría de gasto: Limpieza, Ferretería, Transporte, Mantenimiento, etc."""
    name = models.CharField(max_length=80, unique=True)
    is_active = models.BooleanField(default=True)
    history = HistoricalRecords()

    class Meta:
        verbose_name = '🏷️ Categoría de gasto'
        verbose_name_plural = '🏷️ Categorías de gasto'
        ordering = ['name']

    def __str__(self):
        return self.name


class ExpenseItem(BaseModel):
    """Catálogo de productos recurrentes.

    Permite autocomplete al cargar gastos y reportes tipo
    'cuánto gastaste en Cloro Granulado este año'.
    """

    class Scope(models.TextChoices):
        SHARED = 'shared', 'Compartido entre casas'
        SPECIFIC = 'specific', 'Específico de una casa'

    category = models.ForeignKey(
        ExpenseCategory, on_delete=models.PROTECT,
        related_name='items',
    )
    name = models.CharField(max_length=120)
    default_unit_price = models.DecimalField(
        max_digits=10, decimal_places=2,
        null=True, blank=True,
        help_text="Precio sugerido al cargar un gasto con este item",
    )
    default_scope = models.CharField(
        max_length=10, choices=Scope.choices, default=Scope.SHARED,
    )
    is_active = models.BooleanField(default=True)

    history = HistoricalRecords()

    class Meta:
        verbose_name = '📦 Item de gasto'
        verbose_name_plural = '📦 Items de gasto'
        ordering = ['category__name', 'name']
        unique_together = ['category', 'name']

    def __str__(self):
        return f"{self.category.name} · {self.name}"


# ============================================================================
# Expense — Gasto individual
# ============================================================================

class Expense(BaseModel):
    """Gasto puntual de una quincena.

    Puede estar vinculado a un ExpenseItem del catálogo (autocomplete) o
    ser texto libre. property=NULL significa compartido entre todas las casas.
    """

    class PaymentMethod(models.TextChoices):
        OWN_MONEY = 'own_money', 'Dinero propio del staff (requiere reembolso)'
        COMPANY_CARD = 'company_card', 'Tarjeta de empresa'
        COMPANY_TRANSFER = 'company_transfer', 'Transferencia de empresa'
        COMPANY_CASH = 'company_cash', 'Caja chica'

    class Status(models.TextChoices):
        PENDING = 'pending', 'Pendiente de pago'
        PAID = 'paid', 'Pagado'

    period = models.ForeignKey(
        Period, on_delete=models.PROTECT,
        related_name='expenses',
    )
    date = models.DateField()
    item = models.ForeignKey(
        ExpenseItem, on_delete=models.SET_NULL,
        null=True, blank=True,
        help_text="Item del catálogo (opcional). Si NULL, usar 'description'.",
    )
    description = models.CharField(
        max_length=200,
        help_text="Texto libre o nombre del item. Se autopuebla desde 'item' si aplica.",
    )
    quantity = models.DecimalField(max_digits=10, decimal_places=2, default=1)
    unit_price = models.DecimalField(max_digits=10, decimal_places=2)
    total = models.DecimalField(
        max_digits=10, decimal_places=2,
        help_text="Auto-calculado: quantity * unit_price",
    )
    property = models.ForeignKey(
        Property, on_delete=models.SET_NULL,
        null=True, blank=True,
        related_name='logistica_expenses',
        help_text="NULL = compartido entre todas las casas",
    )

    # === Pago ===
    paid_by_staff = models.ForeignKey(
        Staff, on_delete=models.SET_NULL,
        null=True, blank=True,
        help_text="Quién físicamente compró. NULL = pagado directo por la empresa",
    )
    payment_method = models.CharField(
        max_length=20, choices=PaymentMethod.choices,
        default=PaymentMethod.COMPANY_TRANSFER,
    )
    card_label = models.CharField(
        max_length=80, blank=True, default='',
        help_text="Solo si payment_method=company_card. Ej: 'Adicional Michael'",
    )

    # === Estado ===
    status = models.CharField(
        max_length=10, choices=Status.choices,
        default=Status.PENDING,
    )
    paid_at = models.DateTimeField(null=True, blank=True)

    # === Reembolso (solo aplica si payment_method=own_money) ===
    reimbursed_at = models.DateTimeField(
        null=True, blank=True,
        help_text="Cuándo se reembolsó al staff que pagó con su plata",
    )
    reimbursement = models.ForeignKey(
        'Reimbursement', on_delete=models.SET_NULL,
        null=True, blank=True, related_name='expenses',
    )

    voucher = models.FileField(
        upload_to=expense_voucher_path,
        null=True, blank=True,
        help_text="Foto/archivo del voucher o boleta del gasto",
    )

    notes = models.TextField(blank=True, default='')

    history = HistoricalRecords()

    class Meta:
        verbose_name = '💸 Gasto'
        verbose_name_plural = '💸 Gastos'
        ordering = ['-date', '-created']

    def __str__(self):
        return f"{self.date} · {self.description} · S/{self.total}"

    def save(self, *args, **kwargs):
        # Auto-calcular total
        if self.quantity is not None and self.unit_price is not None:
            self.total = self.quantity * self.unit_price
        super().save(*args, **kwargs)


# ============================================================================
# Cleaning — Limpieza extra
# ============================================================================

class Cleaning(BaseModel):
    """Limpieza extra de una casa, hecha por personal externo."""

    class Status(models.TextChoices):
        PENDING = 'pending', 'Pendiente de pago'
        PAID = 'paid', 'Pagado'

    period = models.ForeignKey(
        Period, on_delete=models.PROTECT,
        related_name='cleanings',
    )
    date = models.DateField()
    property = models.ForeignKey(
        Property, on_delete=models.PROTECT,
        related_name='logistica_cleanings',
        help_text="Casa que fue limpiada (obligatorio)",
    )
    cleaner = models.ForeignKey(
        Staff, on_delete=models.SET_NULL,
        null=True, blank=True,
        limit_choices_to={'staff_type': 'external'},
        help_text="Personal externo que hizo la limpieza",
    )
    amount = models.DecimalField(max_digits=10, decimal_places=2)

    status = models.CharField(
        max_length=10, choices=Status.choices,
        default=Status.PENDING,
    )
    paid_at = models.DateTimeField(null=True, blank=True)
    voucher = models.FileField(
        upload_to=cleaning_voucher_path,
        null=True, blank=True,
        help_text="Foto/archivo del voucher de pago",
    )
    notes = models.TextField(blank=True, default='')

    history = HistoricalRecords()

    class Meta:
        verbose_name = '🧹 Limpieza extra'
        verbose_name_plural = '🧹 Limpiezas extras'
        ordering = ['-date']

    def __str__(self):
        cleaner_name = self.cleaner.name if self.cleaner else 'Sin asignar'
        return f"{self.date} · {self.property.name} · {cleaner_name} · S/{self.amount}"


# ============================================================================
# SalaryPayment — Pago de sueldo quincenal
# ============================================================================

class SalaryPayment(BaseModel):
    """Pago de sueldo quincenal a un empleado fijo.

    Por convención: 50/50 del monthly_salary.
        - quincena   → día 15
        - fin_de_mes → último día del mes

    Auto-generado al crear un Period (Fase C). En Fase A se crea manual.
    """

    class PaymentType(models.TextChoices):
        QUINCENA = 'quincena', 'Quincena (día 15)'
        FIN_DE_MES = 'fin_de_mes', 'Fin de mes (último día)'

    class Status(models.TextChoices):
        PENDING = 'pending', 'Pendiente'
        PAID = 'paid', 'Pagado'

    period = models.ForeignKey(
        Period, on_delete=models.PROTECT,
        related_name='salary_payments',
    )
    staff = models.ForeignKey(
        Staff, on_delete=models.PROTECT,
        related_name='salary_payments',
        limit_choices_to={'staff_type': 'fixed'},
    )
    payment_type = models.CharField(
        max_length=15, choices=PaymentType.choices,
    )
    amount = models.DecimalField(
        max_digits=10, decimal_places=2,
        help_text="Default: monthly_salary / 2. Editable.",
    )
    status = models.CharField(
        max_length=10, choices=Status.choices,
        default=Status.PENDING,
    )
    paid_at = models.DateTimeField(null=True, blank=True)
    voucher = models.FileField(
        upload_to=salary_voucher_path,
        null=True, blank=True,
        help_text="Foto/archivo del voucher de transferencia/pago",
    )
    notes = models.TextField(blank=True, default='')

    history = HistoricalRecords()

    class Meta:
        verbose_name = '💼 Pago de sueldo'
        verbose_name_plural = '💼 Pagos de sueldos'
        ordering = ['-period__start_date', 'staff__name']
        unique_together = ['period', 'staff', 'payment_type']

    def __str__(self):
        return f"{self.staff.name} · {self.period.label} · {self.get_payment_type_display()}"


# ============================================================================
# Reimbursement — Reembolso a staff
# ============================================================================

class Reimbursement(BaseModel):
    """Reembolso a un staff por gastos que pagó con su dinero (own_money).

    Agrupa los Expenses pendientes de reembolso para ese staff y los marca
    como reimbursed al pagar el reembolso.
    """
    period = models.ForeignKey(
        Period, on_delete=models.PROTECT,
        related_name='reimbursements',
    )
    to_staff = models.ForeignKey(
        Staff, on_delete=models.PROTECT,
        related_name='reimbursements_received',
    )
    amount = models.DecimalField(
        max_digits=10, decimal_places=2,
        help_text="Monto total reembolsado (suma de los expenses cubiertos)",
    )
    paid_at = models.DateTimeField()
    voucher = models.FileField(
        upload_to=reimbursement_voucher_path,
        null=True, blank=True,
        help_text="Foto/archivo del voucher de transferencia/pago",
    )
    notes = models.TextField(blank=True, default='')

    history = HistoricalRecords()

    class Meta:
        verbose_name = '↩️ Reembolso'
        verbose_name_plural = '↩️ Reembolsos'
        ordering = ['-paid_at']

    def __str__(self):
        return f"{self.to_staff.name} · S/{self.amount} · {self.paid_at:%d-%m-%Y}"
