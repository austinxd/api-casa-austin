from .views import (
    PropertyApiView, 
    ProfitPropertyApiView, 
    CheckAvaiblePorperty, 
    PropertyPhotoViewSet,
    CalculatePricingAPIView,
    GenerateDynamicDiscountAPIView,
    GenerateSimpleDiscountAPIView,
    AutomaticDiscountDetailAPIView
)

from django.urls import include, path
from rest_framework.routers import DefaultRouter
from .bulk_views import BulkSpecialDateView, PropertySpecialDatesView

router = DefaultRouter()

router.register("property", PropertyApiView, basename="property")
router.register("profit", ProfitPropertyApiView, basename="profit")
router.register("photos", PropertyPhotoViewSet, basename="property-photos")

urlpatterns = [
    path("", include(router.urls)),
    path("prop/check-avaible/", CheckAvaiblePorperty.as_view()),
    path('properties/<int:property_id>/photos/', PropertyPhotoViewSet.as_view({'get': 'list', 'post': 'create'}), name='property-photos'),
    # Endpoint para calcular precios
    path('properties/calculate-pricing/', CalculatePricingAPIView.as_view(), name='calculate-pricing'),
    path('properties/generate-simple-discount/', GenerateSimpleDiscountAPIView.as_view(), name='generate-simple-discount'),
    # Endpoint para generar códigos dinámicos
    path('properties/generate-discount/', GenerateDynamicDiscountAPIView.as_view(), name='generate-discount'),
    # Endpoint para obtener detalles de descuento automático
    path('property/automaticdiscount/<str:discount_id>/', AutomaticDiscountDetailAPIView.as_view(), name='automatic-discount-detail'),
    path('admin/bulk-special-dates/', BulkSpecialDateView.as_view(), name='bulk-special-dates'),
    path('admin/special-dates-manager/', PropertySpecialDatesView.as_view(), name='special-dates-manager'),
    path('admin/special-dates-manager/<int:property_id>/', PropertySpecialDatesView.as_view(), name='special-dates-manager'),
]