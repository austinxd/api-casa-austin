from datetime import timedelta

from django.db.models import Sum, Avg, Count
from django.http import HttpResponse
from django.utils import timezone
from rest_framework import viewsets, filters, status
from rest_framework.decorators import api_view, permission_classes as perm_classes, action
from rest_framework.permissions import AllowAny, IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.core.paginator import CustomPagination
from .models import BlogCategory, BlogPost, SearchConsoleData
from .serializers import (
    BlogCategorySerializer,
    BlogPostListSerializer,
    BlogPostDetailSerializer,
    BlogPostAdminSerializer,
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


class BlogPostAdminViewSet(viewsets.ModelViewSet):
    """API admin para gestión de posts del blog."""
    permission_classes = [IsAuthenticated]
    serializer_class = BlogPostAdminSerializer
    pagination_class = CustomPagination
    filter_backends = [filters.SearchFilter]
    search_fields = ['title', 'excerpt']

    def get_queryset(self):
        qs = BlogPost.objects.filter(deleted=False).select_related('category').order_by('-created')
        status_filter = self.request.query_params.get('status')
        if status_filter in ('draft', 'published'):
            qs = qs.filter(status=status_filter)
        return qs

    @action(detail=True, methods=['post'])
    def publish(self, request, pk=None):
        post = self.get_object()
        post.status = 'published'
        post.published_date = timezone.now()
        post.save(update_fields=['status', 'published_date'])
        return Response(BlogPostAdminSerializer(post, context={'request': request}).data)

    @action(detail=True, methods=['post'])
    def unpublish(self, request, pk=None):
        post = self.get_object()
        post.status = 'draft'
        post.published_date = None
        post.save(update_fields=['status', 'published_date'])
        return Response(BlogPostAdminSerializer(post, context={'request': request}).data)


class SearchConsoleStatsView(APIView):
    """Estadísticas agregadas de Search Console para el dashboard."""
    permission_classes = [IsAuthenticated]

    def get(self, request):
        qs = SearchConsoleData.objects.filter(deleted=False)

        # Filtro por días: ?days=7|30|90 (default: todos)
        days = request.query_params.get('days')
        if days and days.isdigit():
            cutoff = timezone.now().date() - timedelta(days=int(days))
            qs = qs.filter(date_range_end__gte=cutoff)

        if not qs.exists():
            return Response({
                'totals': {'clicks': 0, 'impressions': 0, 'avg_ctr': 0, 'avg_position': 0},
                'top_keywords': [],
                'top_pages': [],
                'opportunities': [],
                'last_synced': None,
            })

        # Totales
        totals = qs.aggregate(
            clicks=Sum('clicks'),
            impressions=Sum('impressions'),
            avg_ctr=Avg('ctr'),
            avg_position=Avg('position'),
        )
        totals['avg_ctr'] = round(totals['avg_ctr'] or 0, 2)
        totals['avg_position'] = round(totals['avg_position'] or 0, 1)

        # Top 15 keywords por impresiones
        top_keywords = list(
            qs.order_by('-impressions').values(
                'query', 'clicks', 'impressions', 'ctr', 'position'
            )[:15]
        )

        # Top 10 páginas por clicks
        top_pages = list(
            qs.exclude(page_url='').values('page_url')
            .annotate(clicks=Sum('clicks'), impressions=Sum('impressions'))
            .order_by('-clicks')[:10]
        )

        # Oportunidades: alta impresión + bajo CTR (posición > 10 = margen de mejora)
        opportunities = list(
            qs.filter(impressions__gte=100, ctr__lt=2.0, position__gt=10)
            .order_by('-impressions')
            .values('query', 'impressions', 'ctr', 'position')[:10]
        )

        last_synced = qs.order_by('-synced_at').values_list('synced_at', flat=True).first()

        return Response({
            'totals': totals,
            'top_keywords': top_keywords,
            'top_pages': top_pages,
            'opportunities': opportunities,
            'last_synced': last_synced,
        })


@api_view(['GET'])
@perm_classes([AllowAny])
def blog_sitemap(request):
    """Genera sitemap XML dinámico con todos los blog posts publicados."""
    posts = BlogPost.objects.filter(
        deleted=False, status='published'
    ).order_by('-published_date').values_list('slug', 'updated')

    urls = []
    for slug, updated in posts:
        lastmod = updated.strftime('%Y-%m-%d') if updated else ''
        urls.append(
            f'  <url>\n'
            f'    <loc>https://casaaustin.pe/blog/{slug}</loc>\n'
            f'    <lastmod>{lastmod}</lastmod>\n'
            f'    <changefreq>monthly</changefreq>\n'
            f'    <priority>0.7</priority>\n'
            f'  </url>'
        )

    xml = (
        '<?xml version="1.0" encoding="UTF-8"?>\n'
        '<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">\n'
        + '\n'.join(urls) + '\n'
        '</urlset>'
    )
    return HttpResponse(xml, content_type='application/xml')
