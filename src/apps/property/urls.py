from .views import (PropertyApiView, ProfitPropertyApiView, CheckAvaiblePorperty as CheckAvailabilityApiView, PropertyPhotoViewSet as PropertyPhotoApiView, CalculatePricingAPIView)


from django.urls import include, path
from rest_framework.routers import DefaultRouter
from .bulk_views import BulkSpecialDateView

router = DefaultRouter()

router.register("property", PropertyApiView, basename="property")
router.register("profit", ProfitPropertyApiView, basename="profit")
router.register("photos", PropertyPhotoApiView, basename="property-photos")

urlpatterns = [
    path("", include(router.urls)),
    path("prop/check-avaible/", CheckAvailabilityApiView.as_view()),
    path('properties/<int:property_id>/photos/', PropertyPhotoApiView.as_view({'get': 'list', 'post': 'create'}), name='property-photos'),
    path('properties/calculate-pricing/', CalculatePricingAPIView.as_view(), name='calculate-pricing'),
    path('admin/bulk-special-dates/', BulkSpecialDateView.as_view(), name='bulk-special-dates'),
]