from django.urls import path, include
from rest_framework.routers import DefaultRouter

from .views import (
    PeriodViewSet, StaffViewSet,
    ExpenseCategoryViewSet, ExpenseItemViewSet,
    ExpenseViewSet, CleaningViewSet,
    SalaryPaymentViewSet, ReimbursementViewSet,
    PeriodSummaryView,
)


router = DefaultRouter()
router.register(r'periods', PeriodViewSet, basename='logistica-period')
router.register(r'staff', StaffViewSet, basename='logistica-staff')
router.register(r'expense-categories', ExpenseCategoryViewSet, basename='logistica-category')
router.register(r'expense-items', ExpenseItemViewSet, basename='logistica-item')
router.register(r'expenses', ExpenseViewSet, basename='logistica-expense')
router.register(r'cleanings', CleaningViewSet, basename='logistica-cleaning')
router.register(r'salary-payments', SalaryPaymentViewSet, basename='logistica-salary')
router.register(r'reimbursements', ReimbursementViewSet, basename='logistica-reimbursement')


urlpatterns = [
    path('', include(router.urls)),
    path('summary/', PeriodSummaryView.as_view(), name='logistica-summary'),
]
