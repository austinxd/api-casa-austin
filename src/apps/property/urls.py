from .views import (
    PropertyApiView, 
    ProfitPropertyApiView, 
    CheckAvaiblePorperty, 
    PropertyPhotoViewSet,
    CalculatePricingAPIView,
    GenerateDynamicDiscountAPIView
)

from django.urls import include, path
from rest_framework.routers import DefaultRouter
from .bulk_views import BulkSpecialDateView, PropertySpecialDatesView

router = DefaultRouter()

router.register("property", PropertyApiView, basename="property")
router.register("profit", ProfitPropertyApiView, basename="profit")
router.register("photos", PropertyPhotoApiView, basename="property-photos")

urlpatterns = [
    path("", include(router.urls)),
    path("prop/check-avaible/", CheckAvailabilityApiView.as_view()),
    path('properties/<int:property_id>/photos/', PropertyPhotoApiView.as_view({'get': 'list', 'post': 'create'}), name='property-photos'),
    # Endpoint para calcular precios
    path('calculate-pricing/', CalculatePricingAPIView.as_view(), name='calculate-pricing'),

    # Endpoint para generar códigos dinámicos
    path('generate-discount/', GenerateDynamicDiscountAPIView.as_view(), name='generate-discount'),
    path('admin/bulk-special-dates/', BulkSpecialDateView.as_view(), name='bulk-special-dates'),
    path('admin/special-dates-manager/', PropertySpecialDatesView.as_view(), name='special-dates-manager'),
    path('admin/special-dates-manager/<int:property_id>/', PropertySpecialDatesView.as_view(), name='special-dates-manager'),
]