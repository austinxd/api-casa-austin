import logging
from rest_framework.views import APIView
from rest_framework.response import Response
from rest_framework import status
from rest_framework.permissions import IsAuthenticated, AllowAny
from django.utils import timezone

from .models import APIKey, DNIQueryLog
from .service import ReniecService

logger = logging.getLogger(__name__)


class APIKeyAuthentication:
    """
    Autenticación por API Key para aplicaciones externas.
    La API Key debe enviarse en el header X-API-Key.
    """

    @staticmethod
    def authenticate(request) -> tuple:
        """
        Autentica la solicitud usando API Key.
        Returns: (api_key_instance, error_message)
        """
        api_key = request.headers.get('X-API-Key')

        if not api_key:
            return None, "API Key requerida"

        try:
            key_obj = APIKey.objects.get(key=api_key)
        except APIKey.DoesNotExist:
            return None, "API Key inválida"

        if not key_obj.is_active:
            return None, "API Key inactiva"

        return key_obj, None


class RateLimiter:
    """
    Rate limiter basado en los límites configurados en el API Key.
    """

    @staticmethod
    def check_rate_limit(api_key: APIKey, source_ip: str) -> tuple:
        """
        Verifica si la solicitud está dentro de los límites.
        Returns: (allowed, error_message)
        """
        # Verificar límite por minuto (por IP)
        queries_last_minute = DNIQueryLog.count_queries_last_minute(source_ip)
        if queries_last_minute >= api_key.rate_limit_per_minute:
            return False, f"Límite por minuto excedido ({api_key.rate_limit_per_minute}/min)"

        # Verificar límite diario (por app)
        queries_today = DNIQueryLog.count_queries_today(source_app=api_key.name)
        if queries_today >= api_key.rate_limit_per_day:
            return False, f"Límite diario excedido ({api_key.rate_limit_per_day}/día)"

        return True, None


def get_client_ip(request):
    """Obtiene la IP real del cliente"""
    x_forwarded_for = request.META.get('HTTP_X_FORWARDED_FOR')
    if x_forwarded_for:
        ip = x_forwarded_for.split(',')[0].strip()
    else:
        ip = request.META.get('REMOTE_ADDR')
    return ip


class DNILookupView(APIView):
    """
    Endpoint para consultar DNI - Compatible con el formato del PHP original.

    POST /api/v1/reniec/lookup/

    Headers:
        X-API-Key: tu_api_key

    Body:
        {
            "dni": "12345678"
        }

    Response (éxito):
        {
            "source": "database",
            "data": {
                "dni": "12345678",
                "preNombres": "Juan Carlos",
                "apePaterno": "Perez",
                ...
            }
        }

    Response (error):
        {
            "error": "DNI inválido o no enviado"
        }
    """
    permission_classes = [AllowAny]  # Usamos autenticación por API Key

    def get(self, request):
        """Soporte para GET (como el PHP original)"""
        return self._handle_lookup(request, request.GET.get('dni', '').strip())

    def post(self, request):
        """Soporte para POST"""
        return self._handle_lookup(request, request.data.get('dni', '').strip())

    def _handle_lookup(self, request, dni):
        # Autenticar con API Key
        api_key, error = APIKeyAuthentication.authenticate(request)
        if error:
            return Response({'error': error}, status=status.HTTP_401_UNAUTHORIZED)

        # Obtener IP del cliente
        source_ip = get_client_ip(request)

        # Verificar rate limit
        allowed, error = RateLimiter.check_rate_limit(api_key, source_ip)
        if not allowed:
            return Response({'error': error}, status=status.HTTP_429_TOO_MANY_REQUESTS)

        # Validar DNI (igual que PHP)
        if not dni or len(dni) != 8 or not dni.isdigit():
            return Response({'error': 'DNI inválido o no enviado'}, status=status.HTTP_400_BAD_REQUEST)

        # Actualizar último uso del API Key
        api_key.update_last_used()

        # Consultar DNI
        success, result = ReniecService.lookup(
            dni=dni,
            source_app=api_key.name,
            source_ip=source_ip,
            user_agent=request.headers.get('User-Agent'),
            include_photo=api_key.can_view_photo,
            include_full_data=api_key.can_view_full_data
        )

        if success:
            # Formato igual al PHP: {"source": "database|api", "data": {...}}
            return Response({
                'source': result.get('source', 'database'),
                'data': result.get('data', {})
            })
        else:
            # Formato de error igual al PHP: {"error": "mensaje"}
            return Response({
                'error': result.get('error', 'Error en la consulta')
            }, status=status.HTTP_404_NOT_FOUND)


class DNILookupAuthenticatedView(APIView):
    """
    Endpoint para consultar DNI con autenticación JWT (para admin/staff).
    Mismo formato de respuesta que el PHP.

    POST /api/v1/reniec/lookup/auth/

    Headers:
        Authorization: Bearer <token>

    Body:
        {
            "dni": "12345678"
        }
    """
    permission_classes = [IsAuthenticated]

    def post(self, request):
        # Verificar que es admin o staff
        if not (request.user.is_staff or request.user.is_superuser):
            return Response({'error': 'No tiene permisos para esta operación'}, status=status.HTTP_403_FORBIDDEN)

        # Obtener IP del cliente
        source_ip = get_client_ip(request)

        # Obtener DNI del body
        dni = request.data.get('dni', '').strip()

        # Validar DNI
        if not dni or len(dni) != 8 or not dni.isdigit():
            return Response({'error': 'DNI inválido o no enviado'}, status=status.HTTP_400_BAD_REQUEST)

        # Consultar DNI (staff siempre tiene acceso completo)
        success, result = ReniecService.lookup(
            dni=dni,
            source_app='admin_panel',
            source_ip=source_ip,
            user=request.user,
            user_agent=request.headers.get('User-Agent'),
            include_photo=True,
            include_full_data=True
        )

        if success:
            return Response({
                'source': result.get('source', 'database'),
                'data': result.get('data', {})
            })
        else:
            return Response({
                'error': result.get('error', 'Error en la consulta')
            }, status=status.HTTP_404_NOT_FOUND)


class DNILookupPublicView(APIView):
    """
    Endpoint PÚBLICO para consultar DNI - Para registro de clientes.
    NO requiere autenticación pero tiene rate limit estricto por IP.

    GET /api/v1/reniec/lookup/public/?dni=12345678

    Respuesta igual al PHP original.
    Solo devuelve datos básicos (sin foto, sin datos sensibles).
    """
    permission_classes = [AllowAny]

    def get(self, request):
        dni = request.GET.get('dni', '').strip()
        return self._handle_lookup(request, dni)

    def post(self, request):
        dni = request.data.get('dni', '').strip()
        return self._handle_lookup(request, dni)

    def _handle_lookup(self, request, dni):
        source_ip = get_client_ip(request)

        # Rate limit estricto para endpoint público: 5 consultas por minuto por IP
        queries_last_minute = DNIQueryLog.count_queries_last_minute(source_ip)
        if queries_last_minute >= 5:
            return Response({'error': 'Demasiadas consultas. Intente en un minuto.'}, status=status.HTTP_429_TOO_MANY_REQUESTS)

        # Validar DNI
        if not dni or len(dni) != 8 or not dni.isdigit():
            return Response({'error': 'DNI inválido o no enviado'}, status=status.HTTP_400_BAD_REQUEST)

        # Consultar DNI (sin foto ni datos completos)
        success, result = ReniecService.lookup(
            dni=dni,
            source_app='public_web',
            source_ip=source_ip,
            user_agent=request.headers.get('User-Agent'),
            include_photo=False,
            include_full_data=False  # Solo datos básicos
        )

        if success:
            return Response({
                'source': result.get('source', 'database'),
                'data': result.get('data', {})
            })
        else:
            return Response({
                'error': result.get('error', 'Error en la consulta')
            }, status=status.HTTP_404_NOT_FOUND)


class DNIStatsView(APIView):
    """
    Endpoint para ver estadísticas de consultas (solo admin).

    GET /api/v1/reniec/stats/
    """
    permission_classes = [IsAuthenticated]

    def get(self, request):
        if not (request.user.is_staff or request.user.is_superuser):
            return Response({'error': 'No tiene permisos para esta operación'}, status=status.HTTP_403_FORBIDDEN)

        today_start = timezone.now().replace(hour=0, minute=0, second=0, microsecond=0)

        # Estadísticas del día
        queries_today = DNIQueryLog.objects.filter(created__gte=today_start)

        stats = {
            'total_queries_today': queries_today.count(),
            'successful_queries_today': queries_today.filter(success=True).count(),
            'cache_hits_today': queries_today.filter(from_cache=True).count(),
            'api_calls_today': queries_today.filter(from_cache=False, success=True).count(),
            'errors_today': queries_today.filter(success=False).count(),
        }

        # Por aplicación
        from django.db.models import Count
        by_app = queries_today.values('source_app').annotate(
            count=Count('id')
        ).order_by('-count')

        stats['by_app'] = list(by_app)

        return Response(stats)
