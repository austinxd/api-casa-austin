"""
Endpoints REST para el módulo Logística.

Permisos: requiere autenticación (JWT). La visibilidad por superuser
se hace en frontend — backend permite a cualquier usuario autenticado
para no acoplar lógica de roles ahora.
"""
from collections import defaultdict
from datetime import date, datetime
from decimal import Decimal

from django.db.models import Sum, Q
from django.utils import timezone
from rest_framework import viewsets, filters, status
from rest_framework.decorators import action
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from .models import (
    Period, Staff, ExpenseCategory, ExpenseItem,
    Expense, Cleaning, SalaryPayment, Reimbursement,
)
from .serializers import (
    PeriodSerializer, StaffSerializer,
    ExpenseCategorySerializer, ExpenseItemSerializer,
    ExpenseSerializer, CleaningSerializer,
    SalaryPaymentSerializer, ReimbursementSerializer,
    PeriodSummarySerializer,
)


# ============================================================================
# CRUD básicos (ModelViewSet)
# ============================================================================

def _quincena_range_for_date(d):
    """Dada una fecha, devuelve (start, end, label) de la quincena que la contiene.

    Quincena 1: día 1 al 15 del mes
    Quincena 2: día 16 al último día del mes
    """
    import calendar as cal
    months_es = {
        1: 'enero', 2: 'febrero', 3: 'marzo', 4: 'abril', 5: 'mayo', 6: 'junio',
        7: 'julio', 8: 'agosto', 9: 'septiembre', 10: 'octubre',
        11: 'noviembre', 12: 'diciembre',
    }
    if d.day <= 15:
        start = d.replace(day=1)
        end = d.replace(day=15)
        label = f"1–15 {months_es[d.month]} {d.year}"
    else:
        start = d.replace(day=16)
        last_day = cal.monthrange(d.year, d.month)[1]
        end = d.replace(day=last_day)
        label = f"16–{last_day} {months_es[d.month]} {d.year}"
    return start, end, label


class PeriodViewSet(viewsets.ModelViewSet):
    queryset = Period.objects.filter(deleted=False).order_by('-start_date')
    serializer_class = PeriodSerializer
    permission_classes = [IsAuthenticated]

    @action(detail=False, methods=['get'], url_path='current')
    def current(self, request):
        """Devuelve la quincena actual auto-creándola si no existe."""
        today = date.today()
        start, end, label = _quincena_range_for_date(today)
        period, _ = Period.objects.get_or_create(
            start_date=start, end_date=end,
            deleted=False,
            defaults={'label': label},
        )
        return Response(PeriodSerializer(period).data)

    @action(detail=False, methods=['post'], url_path='ensure')
    def ensure(self, request):
        """Auto-crea (o devuelve) el Period que contiene la fecha dada.

        Body: {date: "YYYY-MM-DD"}  ← cualquier fecha del mes
        Devuelve el Period (creado o existente) según la quincena calculada.
        """
        from datetime import datetime as dt
        date_str = request.data.get('date')
        if not date_str:
            return Response({'detail': 'date es obligatorio'}, status=400)
        try:
            d = dt.strptime(date_str, '%Y-%m-%d').date()
        except ValueError:
            return Response({'detail': 'Formato de fecha inválido (usa YYYY-MM-DD)'}, status=400)

        start, end, label = _quincena_range_for_date(d)
        period, created = Period.objects.get_or_create(
            start_date=start, end_date=end,
            deleted=False,
            defaults={'label': label},
        )
        return Response(
            PeriodSerializer(period).data,
            status=201 if created else 200,
        )


class StaffViewSet(viewsets.ModelViewSet):
    queryset = Staff.objects.filter(deleted=False).order_by('staff_type', 'name')
    serializer_class = StaffSerializer
    permission_classes = [IsAuthenticated]
    filter_backends = [filters.SearchFilter]
    search_fields = ['name', 'phone']

    def get_queryset(self):
        qs = super().get_queryset()
        staff_type = self.request.query_params.get('staff_type')
        is_active = self.request.query_params.get('is_active')
        if staff_type:
            qs = qs.filter(staff_type=staff_type)
        if is_active is not None:
            qs = qs.filter(is_active=is_active.lower() in ('1', 'true', 'yes'))
        return qs


class ExpenseCategoryViewSet(viewsets.ModelViewSet):
    queryset = ExpenseCategory.objects.filter(deleted=False).order_by('name')
    serializer_class = ExpenseCategorySerializer
    permission_classes = [IsAuthenticated]


class ExpenseItemViewSet(viewsets.ModelViewSet):
    queryset = ExpenseItem.objects.filter(deleted=False).select_related('category').order_by('category__name', 'name')
    serializer_class = ExpenseItemSerializer
    permission_classes = [IsAuthenticated]
    filter_backends = [filters.SearchFilter]
    search_fields = ['name', 'category__name']

    def get_queryset(self):
        qs = super().get_queryset()
        category = self.request.query_params.get('category')
        if category:
            qs = qs.filter(category_id=category)
        return qs


class ExpenseViewSet(viewsets.ModelViewSet):
    queryset = Expense.objects.filter(deleted=False).select_related(
        'period', 'item', 'property', 'paid_by_staff', 'reimbursement',
    ).order_by('-date', '-created')
    serializer_class = ExpenseSerializer
    permission_classes = [IsAuthenticated]
    filter_backends = [filters.SearchFilter]
    search_fields = ['description', 'card_label', 'notes']

    def get_queryset(self):
        qs = super().get_queryset()
        period = self.request.query_params.get('period')
        property_id = self.request.query_params.get('property')
        status_f = self.request.query_params.get('status')
        payment_method = self.request.query_params.get('payment_method')
        paid_by_staff = self.request.query_params.get('paid_by_staff')
        category = self.request.query_params.get('category')
        unreimbursed = self.request.query_params.get('unreimbursed_only')
        if period:
            qs = qs.filter(period_id=period)
        if property_id:
            if property_id == 'shared':
                qs = qs.filter(property__isnull=True)
            else:
                qs = qs.filter(property_id=property_id)
        if status_f:
            qs = qs.filter(status=status_f)
        if payment_method:
            qs = qs.filter(payment_method=payment_method)
        if paid_by_staff:
            qs = qs.filter(paid_by_staff_id=paid_by_staff)
        if category:
            qs = qs.filter(item__category_id=category)
        if unreimbursed and unreimbursed.lower() in ('1', 'true', 'yes'):
            qs = qs.filter(
                payment_method=Expense.PaymentMethod.OWN_MONEY,
                reimbursed_at__isnull=True,
            )
        return qs

    @action(detail=True, methods=['post'], url_path='mark-paid')
    def mark_paid(self, request, pk=None):
        expense = self.get_object()
        expense.status = Expense.Status.PAID
        expense.paid_at = timezone.now()
        expense.save(update_fields=['status', 'paid_at', 'updated'])
        return Response(ExpenseSerializer(expense).data)

    @action(detail=True, methods=['post'], url_path='mark-pending')
    def mark_pending(self, request, pk=None):
        expense = self.get_object()
        expense.status = Expense.Status.PENDING
        expense.paid_at = None
        expense.save(update_fields=['status', 'paid_at', 'updated'])
        return Response(ExpenseSerializer(expense).data)


class CleaningViewSet(viewsets.ModelViewSet):
    queryset = Cleaning.objects.filter(deleted=False).select_related(
        'period', 'property', 'cleaner',
    ).order_by('-date')
    serializer_class = CleaningSerializer
    permission_classes = [IsAuthenticated]
    filter_backends = [filters.SearchFilter]
    search_fields = ['cleaner__name', 'notes']

    def get_queryset(self):
        qs = super().get_queryset()
        period = self.request.query_params.get('period')
        property_id = self.request.query_params.get('property')
        status_f = self.request.query_params.get('status')
        cleaner = self.request.query_params.get('cleaner')
        if period:
            qs = qs.filter(period_id=period)
        if property_id:
            qs = qs.filter(property_id=property_id)
        if status_f:
            qs = qs.filter(status=status_f)
        if cleaner:
            qs = qs.filter(cleaner_id=cleaner)
        return qs

    @action(detail=True, methods=['post'], url_path='mark-paid')
    def mark_paid(self, request, pk=None):
        cleaning = self.get_object()
        cleaning.status = Cleaning.Status.PAID
        cleaning.paid_at = timezone.now()
        cleaning.save(update_fields=['status', 'paid_at', 'updated'])
        return Response(CleaningSerializer(cleaning).data)


class SalaryPaymentViewSet(viewsets.ModelViewSet):
    queryset = SalaryPayment.objects.filter(deleted=False).select_related(
        'period', 'staff',
    ).order_by('-period__start_date', 'staff__name')
    serializer_class = SalaryPaymentSerializer
    permission_classes = [IsAuthenticated]

    def get_queryset(self):
        qs = super().get_queryset()
        period = self.request.query_params.get('period')
        staff = self.request.query_params.get('staff')
        status_f = self.request.query_params.get('status')
        if period:
            qs = qs.filter(period_id=period)
        if staff:
            qs = qs.filter(staff_id=staff)
        if status_f:
            qs = qs.filter(status=status_f)
        return qs

    @action(detail=True, methods=['post'], url_path='mark-paid')
    def mark_paid(self, request, pk=None):
        payment = self.get_object()
        payment.status = SalaryPayment.Status.PAID
        payment.paid_at = timezone.now()
        payment.save(update_fields=['status', 'paid_at', 'updated'])
        return Response(SalaryPaymentSerializer(payment).data)

    @action(detail=False, methods=['post'], url_path='generate-for-period')
    def generate_for_period(self, request):
        """Genera SalaryPayments pendientes para un period y todos los Staff fixed activos.

        Body: {period_id: <uuid>, payment_type: 'quincena'|'fin_de_mes'}
        Crea registros con amount = monthly_salary / 2, status='pending'.
        Usa get_or_create para idempotencia (no duplica si ya existen).
        """
        period_id = request.data.get('period_id')
        payment_type = request.data.get('payment_type')
        if not period_id or not payment_type:
            return Response(
                {'detail': 'period_id y payment_type son obligatorios'},
                status=400,
            )
        if payment_type not in ('quincena', 'fin_de_mes'):
            return Response(
                {'detail': 'payment_type debe ser quincena o fin_de_mes'},
                status=400,
            )
        try:
            period = Period.objects.get(id=period_id, deleted=False)
        except Period.DoesNotExist:
            return Response({'detail': 'Period no encontrado'}, status=404)

        created = []
        for staff in Staff.objects.filter(
            staff_type=Staff.StaffType.FIXED,
            is_active=True,
            deleted=False,
        ):
            amount = (staff.monthly_salary or Decimal('0')) / Decimal('2')
            obj, was_created = SalaryPayment.objects.get_or_create(
                period=period,
                staff=staff,
                payment_type=payment_type,
                deleted=False,
                defaults={
                    'amount': amount,
                    'status': SalaryPayment.Status.PENDING,
                },
            )
            if was_created:
                created.append(SalaryPaymentSerializer(obj).data)
        return Response({
            'created': len(created),
            'payments': created,
        }, status=201 if created else 200)


class ReimbursementViewSet(viewsets.ModelViewSet):
    queryset = Reimbursement.objects.filter(deleted=False).select_related(
        'period', 'to_staff',
    ).prefetch_related('expenses').order_by('-paid_at')
    serializer_class = ReimbursementSerializer
    permission_classes = [IsAuthenticated]

    def get_queryset(self):
        qs = super().get_queryset()
        period = self.request.query_params.get('period')
        to_staff = self.request.query_params.get('to_staff')
        if period:
            qs = qs.filter(period_id=period)
        if to_staff:
            qs = qs.filter(to_staff_id=to_staff)
        return qs

    @action(detail=False, methods=['get'], url_path='pending-by-staff')
    def pending_by_staff(self, request):
        """Calcula cuánto se le debe a cada staff (gastos own_money sin reimbursed_at).

        Query params:
            period: filtrar a una quincena específica (opcional)
        """
        period_id = request.query_params.get('period')
        qs = Expense.objects.filter(
            deleted=False,
            payment_method=Expense.PaymentMethod.OWN_MONEY,
            reimbursed_at__isnull=True,
            paid_by_staff__isnull=False,
        )
        if period_id:
            qs = qs.filter(period_id=period_id)

        results = (
            qs.values('paid_by_staff_id', 'paid_by_staff__name')
              .annotate(total=Sum('total'), count=models_count('id'))
              .order_by('-total')
        )
        return Response(list(results))

    @action(detail=False, methods=['post'], url_path='pay')
    def pay_reimbursement(self, request):
        """Crea un Reimbursement y marca los Expenses asociados como reembolsados.

        Body:
            to_staff_id: <uuid>
            period_id: <uuid>
            expense_ids: [<uuid>, ...]   ← gastos a marcar
            paid_at: ISO datetime (optional, default now)
            notes: string (opcional)
        """
        to_staff_id = request.data.get('to_staff_id')
        period_id = request.data.get('period_id')
        expense_ids = request.data.get('expense_ids', [])
        paid_at_str = request.data.get('paid_at')
        notes = request.data.get('notes', '')

        if not to_staff_id or not period_id or not expense_ids:
            return Response(
                {'detail': 'to_staff_id, period_id y expense_ids son obligatorios'},
                status=400,
            )

        try:
            staff = Staff.objects.get(id=to_staff_id, deleted=False)
            period = Period.objects.get(id=period_id, deleted=False)
        except (Staff.DoesNotExist, Period.DoesNotExist):
            return Response({'detail': 'Staff o Period no encontrado'}, status=404)

        expenses = Expense.objects.filter(
            id__in=expense_ids,
            deleted=False,
            paid_by_staff=staff,
            reimbursed_at__isnull=True,
            payment_method=Expense.PaymentMethod.OWN_MONEY,
        )
        if not expenses.exists():
            return Response(
                {'detail': 'No hay gastos válidos para reembolsar'},
                status=400,
            )

        amount = sum((e.total for e in expenses), Decimal('0'))
        paid_at = timezone.now()
        if paid_at_str:
            try:
                paid_at = datetime.fromisoformat(paid_at_str.replace('Z', '+00:00'))
            except ValueError:
                pass

        reimb = Reimbursement.objects.create(
            period=period,
            to_staff=staff,
            amount=amount,
            paid_at=paid_at,
            notes=notes,
        )
        # Marcar expenses
        expenses.update(
            reimbursed_at=paid_at,
            reimbursement=reimb,
        )
        return Response(ReimbursementSerializer(reimb).data, status=201)


# ============================================================================
# Resumen quincena (dashboard)
# ============================================================================

class PeriodSummaryView(APIView):
    """GET /api/v1/logistica/summary/?period=<uuid>

    Si no se pasa period, usa la quincena actual (la que contiene hoy).
    """
    permission_classes = [IsAuthenticated]

    def get(self, request):
        period_id = request.query_params.get('period')
        if period_id:
            try:
                period = Period.objects.get(id=period_id, deleted=False)
            except Period.DoesNotExist:
                return Response({'detail': 'Period no encontrado'}, status=404)
        else:
            today = date.today()
            period = Period.objects.filter(
                deleted=False,
                start_date__lte=today,
                end_date__gte=today,
            ).first()
            if not period:
                return Response(
                    {'detail': 'No hay quincena activa para hoy'},
                    status=404,
                )

        # Totales
        expenses_qs = Expense.objects.filter(period=period, deleted=False)
        cleanings_qs = Cleaning.objects.filter(period=period, deleted=False)
        salaries_qs = SalaryPayment.objects.filter(period=period, deleted=False)
        reimbs_qs = Reimbursement.objects.filter(period=period, deleted=False)

        total_expenses = expenses_qs.aggregate(s=Sum('total'))['s'] or Decimal('0')
        total_cleanings = cleanings_qs.aggregate(s=Sum('amount'))['s'] or Decimal('0')
        total_salaries = salaries_qs.aggregate(s=Sum('amount'))['s'] or Decimal('0')
        total_reimbursements = reimbs_qs.aggregate(s=Sum('amount'))['s'] or Decimal('0')

        expenses_pending = expenses_qs.filter(status='pending').aggregate(s=Sum('total'))['s'] or Decimal('0')
        expenses_paid = expenses_qs.filter(status='paid').aggregate(s=Sum('total'))['s'] or Decimal('0')

        salaries_pending = salaries_qs.filter(status='pending').aggregate(s=Sum('amount'))['s'] or Decimal('0')
        salaries_paid = salaries_qs.filter(status='paid').aggregate(s=Sum('amount'))['s'] or Decimal('0')

        # Reembolsos pendientes por staff
        owed_by_staff = defaultdict(lambda: Decimal('0'))
        owed_qs = Expense.objects.filter(
            deleted=False,
            period=period,
            payment_method=Expense.PaymentMethod.OWN_MONEY,
            reimbursed_at__isnull=True,
            paid_by_staff__isnull=False,
        ).values('paid_by_staff_id', 'paid_by_staff__name', 'total')
        for row in owed_qs:
            key = str(row['paid_by_staff_id'])
            owed_by_staff[key] += row['total']
        # Convertir defaultdict a dict normal con nombre
        owed_dict = {}
        names_qs = Staff.objects.filter(
            id__in=owed_by_staff.keys()
        ).values_list('id', 'name')
        names_map = {str(i): n for i, n in names_qs}
        for k, v in owed_by_staff.items():
            owed_dict[names_map.get(k, k)] = float(v)

        grand_total = total_expenses + total_cleanings + total_salaries

        data = {
            'period_id': str(period.id),
            'label': period.label,
            'start_date': period.start_date,
            'end_date': period.end_date,
            'total_expenses': total_expenses,
            'total_cleanings': total_cleanings,
            'total_salaries': total_salaries,
            'total_reimbursements': total_reimbursements,
            'grand_total': grand_total,
            'expenses_pending': expenses_pending,
            'expenses_paid': expenses_paid,
            'salaries_pending': salaries_pending,
            'salaries_paid': salaries_paid,
            'reimbursements_owed': owed_dict,
        }
        return Response(PeriodSummarySerializer(data).data)


# Helpers
def models_count(field='id'):
    """Helper para Count en aggregate sin import circular."""
    from django.db.models import Count
    return Count(field)
