from .views import ReservationsApiView, DeleteRecipeApiView, GetICSApiView, UpdateICSApiView, ProfitApiView


from django.urls import include, path
from rest_framework.routers import DefaultRouter

router = DefaultRouter()

router.register("reservations", ReservationsApiView, basename="reservations")

urlpatterns = [
    path("", include(router.urls)),
    path("delete-recipe/<uuid:pk>/", DeleteRecipeApiView.as_view()),
    path("get-ics/", GetICSApiView.as_view()),
    path("update-ics/", UpdateICSApiView.as_view()),
    path("profit-resume/", ProfitApiView.as_view())
]
