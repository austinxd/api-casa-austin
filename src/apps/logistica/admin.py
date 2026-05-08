from django.contrib import admin
from simple_history.admin import SimpleHistoryAdmin

from .models import (
    Period, Staff, ExpenseCategory, ExpenseItem,
    Expense, Cleaning, SalaryPayment, Reimbursement,
)


@admin.register(Period)
class PeriodAdmin(SimpleHistoryAdmin):
    list_display = ('label', 'start_date', 'end_date', 'closed_at')
    list_filter = ('closed_at',)
    search_fields = ('label',)
    ordering = ('-start_date',)


@admin.register(Staff)
class StaffAdmin(SimpleHistoryAdmin):
    list_display = ('name', 'staff_type', 'monthly_salary',
                    'can_pay_for_expenses', 'account_type', 'is_active')
    list_filter = ('staff_type', 'is_active', 'can_pay_for_expenses', 'account_type')
    search_fields = ('name', 'phone', 'account_number')
    ordering = ('staff_type', 'name')


@admin.register(ExpenseCategory)
class ExpenseCategoryAdmin(SimpleHistoryAdmin):
    list_display = ('name', 'is_active')
    list_filter = ('is_active',)
    search_fields = ('name',)


@admin.register(ExpenseItem)
class ExpenseItemAdmin(SimpleHistoryAdmin):
    list_display = ('name', 'category', 'default_unit_price',
                    'default_scope', 'is_active')
    list_filter = ('category', 'default_scope', 'is_active')
    search_fields = ('name', 'category__name')
    ordering = ('category__name', 'name')


@admin.register(Expense)
class ExpenseAdmin(SimpleHistoryAdmin):
    list_display = ('date', 'description', 'total', 'property',
                    'paid_by_staff', 'payment_method', 'status', 'period')
    list_filter = ('status', 'payment_method', 'period', 'property',
                   'paid_by_staff')
    search_fields = ('description', 'card_label', 'notes')
    raw_id_fields = ('item', 'property', 'paid_by_staff', 'reimbursement', 'period')
    ordering = ('-date',)
    readonly_fields = ('total',)


@admin.register(Cleaning)
class CleaningAdmin(SimpleHistoryAdmin):
    list_display = ('date', 'property', 'cleaner', 'amount', 'status', 'period')
    list_filter = ('status', 'property', 'period', 'cleaner')
    search_fields = ('cleaner__name', 'notes')
    raw_id_fields = ('property', 'cleaner', 'period')
    ordering = ('-date',)


@admin.register(SalaryPayment)
class SalaryPaymentAdmin(SimpleHistoryAdmin):
    list_display = ('staff', 'period', 'payment_type', 'amount', 'status', 'paid_at')
    list_filter = ('status', 'payment_type', 'period', 'staff')
    search_fields = ('staff__name', 'notes')
    raw_id_fields = ('staff', 'period')
    ordering = ('-period__start_date', 'staff__name')


@admin.register(Reimbursement)
class ReimbursementAdmin(SimpleHistoryAdmin):
    list_display = ('to_staff', 'period', 'amount', 'paid_at')
    list_filter = ('period', 'to_staff')
    search_fields = ('to_staff__name', 'notes')
    raw_id_fields = ('to_staff', 'period')
    ordering = ('-paid_at',)
