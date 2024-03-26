from django.conf import settings

from django.contrib import admin
from django.urls import path, include

from django.conf.urls.static import static

from . import apiviews

from rest_framework_simplejwt.views import (
    TokenObtainPairView,
    TokenRefreshView,
)


urlpatterns = [
    path(settings.DJANGO_ADMIN_PATH, admin.site.urls),
    path('api/v1/test/', apiviews.TestApi.as_view()),
    path('api/v1/test/login/', apiviews.TestLogeoApi.as_view()),
    path('api/v1/login/',  TokenObtainPairView.as_view(),),
    path('api/v1/token/refresh/', TokenRefreshView.as_view()),
    # urls endpoints
    # path('api/v1/clients/', include('apps.clients.urls')),
    path("api/v1/", include("apps.clients.urls")),
    path("api/v1/", include("apps.reservation.urls")),
    path("api/v1/", include("apps.property.urls")),
] + static(settings.MEDIA_URL, document_root=settings.MEDIA_ROOT)


if settings.DEBUG:
    from drf_spectacular.views import SpectacularAPIView, SpectacularSwaggerView

    urlpatterns += [

        # API Docs
        path("api/v1/schema/", SpectacularAPIView.as_view(), name="schema"),
        path(
            "api/v1/schema/docs/",
            SpectacularSwaggerView.as_view(url_name="schema"),
            name="swagger-ui",
        ),
    ]
