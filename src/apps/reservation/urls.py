from django.urls import path
from .views import (
    ReservationViewSet, 
    ClientReservationViewSet, 
    ReservationListByPropertyView,
    ClientReservationDetailView,
    ReservationPropertyAvailabilityView,
    ReservationCreateView,
    ClientReservationsView,
    BulkUpdateReservationStatusView,
    ReservationExportView,
    ReservationAllView,
    ReservationDashboardStats,
)
from .payment_views import ProcessPaymentView, TestMercadoPagoCredentialsView
from rest_framework.routers import DefaultRouter

router = DefaultRouter()
router.register(r'reservations', ReservationViewSet, basename='reservation')
router.register(r'client-reservations', ClientReservationViewSet, basename='client-reservation')

urlpatterns = [
    path('reservations/property/<int:property_id>/', ReservationListByPropertyView.as_view(), name='reservations-by-property'),
    path('client-reservations/<uuid:reservation_id>/', ClientReservationDetailView.as_view(), name='client-reservation-detail'),
    path('reservations/availability/<int:property_id>/', ReservationPropertyAvailabilityView.as_view(), name='property-availability'),
    path('reservations/create/', ReservationCreateView.as_view(), name='reservation-create'),
    path('reservations/client/', ClientReservationsView.as_view(), name='client-reservations'),
    path('reservations/bulk-update-status/', BulkUpdateReservationStatusView.as_view(), name='bulk-update-status'),
    path('reservations/export/', ReservationExportView.as_view(), name='reservation-export'),
    path('reservations/all/', ReservationAllView.as_view(), name='reservations-all'),
    path('reservations/dashboard/stats/', ReservationDashboardStats.as_view(), name='reservation-dashboard-stats'),
    path('payment/process/<uuid:reservation_id>/', ProcessPaymentView.as_view(), name='process-payment'),
    path('payment/test-credentials/', TestMercadoPagoCredentialsView.as_view(), name='test-mercadopago-credentials'),
] + router.urls