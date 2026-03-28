"""
Cliente de Google Search Console para análisis de keywords.

Usa service account para autenticarse y consultar datos de rendimiento
del sitio en Google Search.
"""
import logging
from datetime import date, timedelta

from django.conf import settings
from django.utils import timezone

logger = logging.getLogger('apps')


class SearchConsoleClient:
    """Cliente para la API de Google Search Console."""

    def __init__(self):
        self.site_url = getattr(settings, 'GOOGLE_SEARCH_CONSOLE_SITE_URL', '')
        self.key_file = getattr(settings, 'GOOGLE_SEARCH_CONSOLE_KEY_FILE', '')
        self._service = None

    def _get_service(self):
        """Inicializa el servicio de Search Console con service account."""
        if self._service:
            return self._service

        if not self.key_file:
            raise ValueError(
                "GOOGLE_SEARCH_CONSOLE_KEY_FILE no está configurado. "
                "Configura la ruta al archivo JSON de la service account."
            )

        from google.oauth2 import service_account
        from googleapiclient.discovery import build

        credentials = service_account.Credentials.from_service_account_file(
            self.key_file,
            scopes=['https://www.googleapis.com/auth/webmasters.readonly']
        )
        self._service = build('searchconsole', 'v1', credentials=credentials)
        return self._service

    def _query(self, start_date, end_date, dimensions=None, row_limit=1000, filters=None):
        """Ejecuta una consulta genérica a Search Console."""
        service = self._get_service()

        body = {
            'startDate': start_date.isoformat(),
            'endDate': end_date.isoformat(),
            'dimensions': dimensions or ['query'],
            'rowLimit': row_limit,
        }

        if filters:
            body['dimensionFilterGroups'] = [{
                'filters': filters
            }]

        response = service.searchanalytics().query(
            siteUrl=self.site_url,
            body=body
        ).execute()

        return response.get('rows', [])

    def fetch_keyword_opportunities(self, days=28):
        """
        Busca keywords con oportunidad de mejora:
        - Impresiones > 10 (ya aparece en búsquedas)
        - Posición entre 5-50 (rankea pero puede mejorar)
        - CTR < 5% (oportunidad con contenido dedicado)
        """
        end_date = date.today() - timedelta(days=3)  # SC tiene ~3 días de delay
        start_date = end_date - timedelta(days=days)

        rows = self._query(start_date, end_date, dimensions=['query'])

        opportunities = []
        for row in rows:
            query = row['keys'][0]
            clicks = row.get('clicks', 0)
            impressions = row.get('impressions', 0)
            ctr = row.get('ctr', 0) * 100  # Convertir a porcentaje
            position = row.get('position', 0)

            if impressions > 10 and 5 <= position <= 50 and ctr < 5:
                opportunities.append({
                    'query': query,
                    'clicks': clicks,
                    'impressions': impressions,
                    'ctr': round(ctr, 2),
                    'position': round(position, 1),
                })

        # Ordenar por impresiones (más oportunidad primero)
        opportunities.sort(key=lambda x: x['impressions'], reverse=True)
        return opportunities

    def fetch_top_queries(self, days=28, limit=50):
        """Top keywords actuales del sitio ordenadas por clicks."""
        end_date = date.today() - timedelta(days=3)
        start_date = end_date - timedelta(days=days)

        rows = self._query(start_date, end_date, dimensions=['query'], row_limit=limit)

        queries = []
        for row in rows:
            queries.append({
                'query': row['keys'][0],
                'clicks': row.get('clicks', 0),
                'impressions': row.get('impressions', 0),
                'ctr': round(row.get('ctr', 0) * 100, 2),
                'position': round(row.get('position', 0), 1),
            })

        return queries

    def fetch_blog_performance(self, days=28):
        """Rendimiento específico de URLs /blog/*."""
        end_date = date.today() - timedelta(days=3)
        start_date = end_date - timedelta(days=days)

        rows = self._query(
            start_date,
            end_date,
            dimensions=['query', 'page'],
            filters=[{
                'dimension': 'page',
                'operator': 'contains',
                'expression': '/blog/'
            }]
        )

        results = []
        for row in rows:
            results.append({
                'query': row['keys'][0],
                'page': row['keys'][1],
                'clicks': row.get('clicks', 0),
                'impressions': row.get('impressions', 0),
                'ctr': round(row.get('ctr', 0) * 100, 2),
                'position': round(row.get('position', 0), 1),
            })

        return results

    def sync_to_database(self, days=28):
        """
        Descarga datos de Search Console y los guarda en SearchConsoleData.
        Evita llamar la API en cada ejecución del generador.
        """
        from apps.blog.models import SearchConsoleData

        end_date = date.today() - timedelta(days=3)
        start_date = end_date - timedelta(days=days)

        logger.info(f"Sincronizando Search Console: {start_date} a {end_date}")

        rows = self._query(
            start_date,
            end_date,
            dimensions=['query', 'page'],
            row_limit=5000
        )

        created_count = 0
        updated_count = 0

        for row in rows:
            query = row['keys'][0]
            page_url = row['keys'][1]

            obj, created = SearchConsoleData.objects.update_or_create(
                query=query,
                date_range_start=start_date,
                date_range_end=end_date,
                defaults={
                    'clicks': row.get('clicks', 0),
                    'impressions': row.get('impressions', 0),
                    'ctr': round(row.get('ctr', 0) * 100, 2),
                    'position': round(row.get('position', 0), 1),
                    'page_url': page_url,
                }
            )

            if created:
                created_count += 1
            else:
                updated_count += 1

        logger.info(
            f"Search Console sync completo: {created_count} nuevos, "
            f"{updated_count} actualizados de {len(rows)} filas"
        )

        return {
            'total_rows': len(rows),
            'created': created_count,
            'updated': updated_count,
            'date_range': f"{start_date} a {end_date}",
        }

    @staticmethod
    def get_cached_opportunities():
        """
        Obtiene oportunidades de keyword desde datos cacheados en DB.
        Útil para el generador sin necesidad de llamar la API.
        """
        from apps.blog.models import SearchConsoleData

        # Buscar datos recientes (últimos 7 días de sync)
        recent_cutoff = timezone.now() - timedelta(days=7)

        return SearchConsoleData.objects.filter(
            synced_at__gte=recent_cutoff,
            impressions__gt=10,
            position__gte=5,
            position__lte=50,
            ctr__lt=5,
        ).order_by('-impressions')[:100]
