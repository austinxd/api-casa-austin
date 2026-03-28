from rest_framework import viewsets, filters
from rest_framework.permissions import AllowAny

from apps.core.paginator import CustomPagination
from .models import BlogCategory, BlogPost
from .serializers import (
    BlogCategorySerializer,
    BlogPostListSerializer,
    BlogPostDetailSerializer,
)


class BlogPostViewSet(viewsets.ReadOnlyModelViewSet):
    """API pública de posts del blog."""
    permission_classes = [AllowAny]
    pagination_class = CustomPagination
    lookup_field = 'slug'
    filter_backends = [filters.SearchFilter]
    search_fields = ['title', 'excerpt']

    def get_queryset(self):
        qs = BlogPost.objects.filter(
            deleted=False,
            status='published',
        ).select_related('category')

        category_slug = self.request.query_params.get('category')
        if category_slug:
            qs = qs.filter(category__slug=category_slug)

        return qs

    def get_serializer_class(self):
        if self.action == 'retrieve':
            return BlogPostDetailSerializer
        return BlogPostListSerializer


class BlogCategoryViewSet(viewsets.ReadOnlyModelViewSet):
    """API pública de categorías del blog."""
    permission_classes = [AllowAny]
    serializer_class = BlogCategorySerializer
    queryset = BlogCategory.objects.filter(deleted=False)
    pagination_class = None
