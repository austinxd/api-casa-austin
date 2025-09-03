from django.urls import path
from .views import (
    ReservationsApiView, 
    VistaCalendarioApiView, 
    DeleteRecipeApiView,
    GetICSApiView,
    UpdateICSApiView,
    ProfitApiView,
    PropertyCalendarOccupancyAPIView,
)
from .payment_views import ProcessPaymentView, TestMercadoPagoCredentialsView
from rest_framework.routers import DefaultRouter

router = DefaultRouter()
router.register(r'reservations', ReservationsApiView, basename='reservation')
router.register(r'calendar', VistaCalendarioApiView, basename='calendar')

urlpatterns = [
    path('calendar/property/<str:property_id>/', PropertyCalendarOccupancyAPIView.as_view(), name='property-calendar'),
    path('ics/', GetICSApiView.as_view(), name='get-ics'),
    path('ics/update/', UpdateICSApiView.as_view(), name='update-ics'),
    path('profit/', ProfitApiView.as_view(), name='profit'),
    path('payment/process/<uuid:reservation_id>/', ProcessPaymentView.as_view(), name='process-payment'),
    path('payment/test-credentials/', TestMercadoPagoCredentialsView.as_view(), name='test-mercadopago-credentials'),
] + router.urls