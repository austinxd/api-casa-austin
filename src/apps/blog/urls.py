from django.urls import include, path
from rest_framework.routers import DefaultRouter

from .views import BlogPostViewSet, BlogCategoryViewSet, BlogPostAdminViewSet, SearchConsoleStatsView, blog_sitemap

router = DefaultRouter()
router.register("blog/posts", BlogPostViewSet, basename="blog-posts")
router.register("blog/categories", BlogCategoryViewSet, basename="blog-categories")
router.register("blog/admin/posts", BlogPostAdminViewSet, basename="blog-admin-posts")

urlpatterns = [
    path("blog/search-console/stats/", SearchConsoleStatsView.as_view(), name="search-console-stats"),
    path("blog/sitemap.xml", blog_sitemap, name="blog-sitemap"),
    path("", include(router.urls)),
]
