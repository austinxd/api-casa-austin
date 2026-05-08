from rest_framework import serializers

from .models import (
    Period, Staff, ExpenseCategory, ExpenseItem,
    Expense, Cleaning, SalaryPayment, Reimbursement,
)


# ============================================================================
# Period
# ============================================================================

class PeriodSerializer(serializers.ModelSerializer):
    class Meta:
        model = Period
        fields = ['id', 'start_date', 'end_date', 'label', 'closed_at',
                  'created', 'updated']
        read_only_fields = ['created', 'updated']


# ============================================================================
# Staff
# ============================================================================

class StaffSerializer(serializers.ModelSerializer):
    staff_type_display = serializers.CharField(source='get_staff_type_display', read_only=True)

    class Meta:
        model = Staff
        fields = ['id', 'name', 'staff_type', 'staff_type_display',
                  'monthly_salary', 'can_pay_for_expenses',
                  'phone', 'notes', 'is_active', 'start_date',
                  'created', 'updated']
        read_only_fields = ['created', 'updated']


# ============================================================================
# Catálogo
# ============================================================================

class ExpenseCategorySerializer(serializers.ModelSerializer):
    class Meta:
        model = ExpenseCategory
        fields = ['id', 'name', 'is_active', 'created', 'updated']
        read_only_fields = ['created', 'updated']


class ExpenseItemSerializer(serializers.ModelSerializer):
    category_name = serializers.CharField(source='category.name', read_only=True)
    default_scope_display = serializers.CharField(source='get_default_scope_display', read_only=True)

    class Meta:
        model = ExpenseItem
        fields = ['id', 'category', 'category_name', 'name',
                  'default_unit_price', 'default_scope', 'default_scope_display',
                  'is_active', 'created', 'updated']
        read_only_fields = ['created', 'updated']


# ============================================================================
# Expense
# ============================================================================

class ExpenseSerializer(serializers.ModelSerializer):
    item_name = serializers.CharField(source='item.name', read_only=True)
    property_name = serializers.CharField(source='property.name', read_only=True)
    paid_by_staff_name = serializers.CharField(source='paid_by_staff.name', read_only=True)
    payment_method_display = serializers.CharField(source='get_payment_method_display', read_only=True)
    status_display = serializers.CharField(source='get_status_display', read_only=True)
    period_label = serializers.CharField(source='period.label', read_only=True)

    class Meta:
        model = Expense
        fields = [
            'id', 'period', 'period_label', 'date',
            'item', 'item_name', 'description',
            'quantity', 'unit_price', 'total',
            'property', 'property_name',
            'paid_by_staff', 'paid_by_staff_name',
            'payment_method', 'payment_method_display', 'card_label',
            'status', 'status_display', 'paid_at',
            'reimbursed_at', 'reimbursement',
            'notes', 'created', 'updated',
        ]
        read_only_fields = ['total', 'created', 'updated', 'reimbursed_at',
                            'reimbursement']


# ============================================================================
# Cleaning
# ============================================================================

class CleaningSerializer(serializers.ModelSerializer):
    property_name = serializers.CharField(source='property.name', read_only=True)
    cleaner_name = serializers.CharField(source='cleaner.name', read_only=True)
    status_display = serializers.CharField(source='get_status_display', read_only=True)
    period_label = serializers.CharField(source='period.label', read_only=True)

    class Meta:
        model = Cleaning
        fields = [
            'id', 'period', 'period_label', 'date',
            'property', 'property_name',
            'cleaner', 'cleaner_name',
            'amount', 'status', 'status_display', 'paid_at',
            'notes', 'created', 'updated',
        ]
        read_only_fields = ['created', 'updated']


# ============================================================================
# SalaryPayment
# ============================================================================

class SalaryPaymentSerializer(serializers.ModelSerializer):
    staff_name = serializers.CharField(source='staff.name', read_only=True)
    payment_type_display = serializers.CharField(source='get_payment_type_display', read_only=True)
    status_display = serializers.CharField(source='get_status_display', read_only=True)
    period_label = serializers.CharField(source='period.label', read_only=True)

    class Meta:
        model = SalaryPayment
        fields = [
            'id', 'period', 'period_label', 'staff', 'staff_name',
            'payment_type', 'payment_type_display',
            'amount', 'status', 'status_display', 'paid_at',
            'notes', 'created', 'updated',
        ]
        read_only_fields = ['created', 'updated']


# ============================================================================
# Reimbursement
# ============================================================================

class ReimbursementSerializer(serializers.ModelSerializer):
    to_staff_name = serializers.CharField(source='to_staff.name', read_only=True)
    period_label = serializers.CharField(source='period.label', read_only=True)
    expenses_count = serializers.IntegerField(source='expenses.count', read_only=True)

    class Meta:
        model = Reimbursement
        fields = [
            'id', 'period', 'period_label', 'to_staff', 'to_staff_name',
            'amount', 'paid_at', 'notes',
            'expenses_count', 'created', 'updated',
        ]
        read_only_fields = ['created', 'updated', 'expenses_count']


# ============================================================================
# Resumen quincena (read-only — para el dashboard)
# ============================================================================

class PeriodSummarySerializer(serializers.Serializer):
    """Resumen agregado de una quincena para el dashboard."""
    period_id = serializers.UUIDField()
    label = serializers.CharField()
    start_date = serializers.DateField()
    end_date = serializers.DateField()

    total_expenses = serializers.DecimalField(max_digits=12, decimal_places=2)
    total_cleanings = serializers.DecimalField(max_digits=12, decimal_places=2)
    total_salaries = serializers.DecimalField(max_digits=12, decimal_places=2)
    total_reimbursements = serializers.DecimalField(max_digits=12, decimal_places=2)
    grand_total = serializers.DecimalField(max_digits=12, decimal_places=2)

    expenses_pending = serializers.DecimalField(max_digits=12, decimal_places=2)
    expenses_paid = serializers.DecimalField(max_digits=12, decimal_places=2)

    salaries_pending = serializers.DecimalField(max_digits=12, decimal_places=2)
    salaries_paid = serializers.DecimalField(max_digits=12, decimal_places=2)

    reimbursements_owed = serializers.DictField(
        help_text="Por staff: {staff_id: amount} pendiente de reembolsar",
    )
