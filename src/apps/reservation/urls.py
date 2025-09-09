from django.urls import path, include
from rest_framework.routers import DefaultRouter

from .views import ReservationsApiView, DeleteRecipeApiView, GetICSApiView, UpdateICSApiView, ProfitApiView, VistaCalendarioApiView, confirm_reservation, MonthlyReservationsExportAPIView, PropertyCalendarOccupancyAPIView
from .payment_views import ProcessPaymentView, ProcessAdditionalServicesPaymentView
from .homeassistant_views import HomeAssistantReservationView

router = DefaultRouter()

router.register("reservations", ReservationsApiView, basename="reservations")
router.register("vistacalendario", VistaCalendarioApiView, basename="vistacalendario")


urlpatterns = [
    path("", include(router.urls)),
    path("recipt/<int:pk>/", DeleteRecipeApiView.as_view()),
    path("get-ics/", GetICSApiView.as_view()),
    path("update-ics/", UpdateICSApiView.as_view()),
    path("profit/", ProfitApiView.as_view()),
    path("profit-resume/", ProfitApiView.as_view(), name='profit-resume'),
    path('confirm/<str:uuid>/', confirm_reservation, name='confirm_reservation'),
    path('property/<str:property_id>/calendar-occupancy/', PropertyCalendarOccupancyAPIView.as_view(), name='property-calendar-occupancy'),
    path('payment/process/<str:reservation_id>/', ProcessPaymentView.as_view(), name='process-payment'),
    path('payment/additional-services/<str:reservation_id>/', ProcessAdditionalServicesPaymentView.as_view(), name='process-additional-services-payment'),
    path('export/monthly/', MonthlyReservationsExportAPIView.as_view(), name='monthly-reservations-export'),
    path("homeassistant/", HomeAssistantReservationView.as_view(), name="homeassistant-reservation"),
]