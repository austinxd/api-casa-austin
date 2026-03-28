from django.urls import include, path
from rest_framework.routers import DefaultRouter

from .views import BlogPostViewSet, BlogCategoryViewSet

router = DefaultRouter()
router.register("blog/posts", BlogPostViewSet, basename="blog-posts")
router.register("blog/categories", BlogCategoryViewSet, basename="blog-categories")

urlpatterns = [
    path("", include(router.urls)),
]
