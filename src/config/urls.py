from django.conf import settings
from django.contrib import admin
from django.urls import path, include, re_path
from django.conf.urls.static import static
from django.views.static import serve

from . import apiviews

from rest_framework_simplejwt.views import (
    TokenRefreshView,
)

# Estadísticas comprehensivas
from apps.events.views import ComprehensiveStatsView, UpcomingCheckinsView, SearchTrackingStatsView, IngresosStatsView, MetasIngresosView, IngresosAnalysisView


urlpatterns = [
    path(settings.DJANGO_ADMIN_PATH, admin.site.urls),
    path('api/v1/test/', apiviews.TestApi.as_view()),
    path('api/v1/test/login/', apiviews.TestLogeoApi.as_view(), name='test_token'),
    path('api/v1/login/',  apiviews.CustomTokenObtainPairView.as_view(), name='login_jwt'),
    path('api/v1/token/refresh/', TokenRefreshView.as_view()),
    # urls endpoints
    # path('api/v1/clients/', include('apps.clients.urls')),
    path("api/v1/", include("apps.clients.urls")),
    path("api/v1/", include("apps.reservation.urls")),
    path("api/v1/", include("apps.property.urls")),
    path("api/v1/", include("apps.staff.urls")),
    path("api/v1/", include("apps.dashboard.urls")),
    path("api/v1/events/", include("apps.events.urls")),
    path("api/v1/bot/", include("apps.property.bot_urls")),
    path("api/v1/music/", include("apps.reservation.music_urls")),
    path("api/v1/reniec/", include("apps.reniec.urls")),
    path("api/v1/tv/", include("apps.tv.urls")),
    path("api/v1/app-tv/", include("apps.tv.app_urls")),
    path("api/v1/chatbot/", include("apps.chatbot.urls")),

    # === ANALYTICS ENDPOINTS ===
    path('api/v1/stats/', ComprehensiveStatsView.as_view(), name='comprehensive-stats'),
    path('api/v1/stats/search-tracking/', SearchTrackingStatsView.as_view(), name='stats-search-tracking'),
    path('api/v1/stats/ingresos/', IngresosStatsView.as_view(), name='stats-ingresos'),
    path('api/v1/stats/ingresos/analysis/', IngresosAnalysisView.as_view(), name='stats-ingresos-analysis'),
    path('api/v1/metas/', MetasIngresosView.as_view(), name='stats-ingresos-metas'),
    path('api/v1/upcoming-checkins/', UpcomingCheckinsView.as_view(), name='upcoming-checkins'),
]

# Serve media files in production (using re_path + serve instead of static())
# The static() helper doesn't work when DEBUG=False, so we use serve directly
urlpatterns += [
    re_path(r'^media/(?P<path>.*)$', serve, {'document_root': settings.MEDIA_ROOT}),
]


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