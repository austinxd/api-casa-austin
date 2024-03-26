from .views import ReservationsApiView, DeleteRecipeApiView


from django.urls import include, path
from rest_framework.routers import DefaultRouter

router = DefaultRouter()

router.register("reservations", ReservationsApiView, basename="reservations")

urlpatterns = [
    path("", include(router.urls)),
    path("delete-recipe/<uuid:pk>/", DeleteRecipeApiView.as_view()),
]
