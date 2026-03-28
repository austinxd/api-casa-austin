from django.urls import include, path
from rest_framework.routers import DefaultRouter

from .views import BlogPostViewSet, BlogCategoryViewSet, blog_sitemap

router = DefaultRouter()
router.register("blog/posts", BlogPostViewSet, basename="blog-posts")
router.register("blog/categories", BlogCategoryViewSet, basename="blog-categories")

urlpatterns = [
    path("blog/sitemap.xml", blog_sitemap, name="blog-sitemap"),
    path("", include(router.urls)),
]
