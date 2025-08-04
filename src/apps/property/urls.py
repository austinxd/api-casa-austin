from .views import PropertyApiView, ProfitPropertyApiView, CheckAvaiblePorperty, PropertyPhotoViewSet


from django.urls import include, path
from rest_framework.routers import DefaultRouter

router = DefaultRouter()

router.register("property", PropertyApiView, basename="property")
router.register("profit", ProfitPropertyApiView, basename="profit")
router.register("photos", PropertyPhotoViewSet, basename="property-photos")

urlpatterns = [
    path("", include(router.urls)),
    path("prop/check-avaible/", CheckAvaiblePorperty.as_view()),
    # Opcional: Ruta personalizada para slug
    # path("property/slug/<str:slug>/", PropertyDetailBySlugView.as_view(), name="property-by-slug"),
]