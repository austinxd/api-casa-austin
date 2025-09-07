from django.urls import path, include
from rest_framework.routers import DefaultRouter

from . import views
from . import payment_views

router = DefaultRouter()
router.register(r'reservations', views.ReservationsApiView, basename='reservations')
router.register(r'calendar', views.VistaCalendarioApiView, basename='calendar')

urlpatterns = [
    path('', include(router.urls)),
    path('receipts/<int:pk>/', views.DeleteRecipeApiView.as_view(), name='receipt-delete'),
    path('ics/', views.GetICSApiView.as_view(), name='ics'),
    path('updateics/', views.UpdateICSApiView.as_view(), name='update-ics'),
    path('profit/', views.ProfitApiView.as_view(), name='profit'),
    path('confirm/<str:uuid>/', views.confirm_reservation, name='confirm-reservation'),

    # Export URLs
    path('export/monthly/', views.MonthlyReservationsExportAPIView.as_view(), name='monthly-reservations-export'),

    # Payment URLs
    path('payment/create-token/', payment_views.CreatePaymentTokenView.as_view(), name='create-payment-token'),
    path('payment/openpay/', payment_views.OpenPayView.as_view(), name='openpay-payment'),
    path('payment/mercadopago/', payment_views.MercadoPagoView.as_view(), name='mercadopago-payment'),
    path('payment/verify/<str:token>/', payment_views.VerifyPaymentTokenView.as_view(), name='verify-payment-token'),

    # Property calendar occupancy
    path('property/<str:property_id>/calendar/', views.PropertyCalendarOccupancyAPIView.as_view(), name='property-calendar'),
]