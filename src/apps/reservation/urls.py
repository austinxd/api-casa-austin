from django.urls import include, path
from rest_framework.routers import DefaultRouter

from .views import (
    ReservationsApiView,
    DeleteRecipeApiView,
    GetICSApiView,
    UpdateICSApiView,
    ProfitApiView,
    VistaCalendarioApiView,
    confirm_reservation,
    PropertyCalendarOccupancyAPIView
)
from .payment_views import ProcessPaymentView

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
    path('<uuid:reservation_id>/process-payment/', ProcessPaymentView.as_view(), name='process-payment'),
]