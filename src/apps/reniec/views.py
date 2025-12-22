import logging
from rest_framework.views import APIView
from rest_framework.response import Response
from rest_framework import status
from rest_framework.permissions import IsAuthenticated, AllowAny
from django.utils import timezone
from django.core.cache import cache

from .models import APIKey, DNIQueryLog, RateLimitConfig
from .service import ReniecService

logger = logging.getLogger(__name__)


# ============================================================================
# Rate Limiting con Cache para endpoint público
# ============================================================================
class PublicRateLimiter:
    """
    Rate limiter basado en cache para endpoints públicos.
    Usa operaciones atómicas (incr) para evitar race conditions.
    Los límites se leen desde RateLimitConfig (configurable en admin).
    """

    @classmethod
    def _atomic_increment(cls, key: str, window: int) -> int:
        """
        Incrementa un contador de forma atómica.
        Si la clave no existe, la crea con valor 1.
        Returns: el nuevo valor del contador
        """
        try:
            # Intentar incrementar atómicamente (funciona con Redis)
            count = cache.incr(key)
        except ValueError:
            # Si la clave no existe, cache.incr falla
            # Crear la clave con valor 1
            cache.set(key, 1, window)
            count = 1
        return count

    @classmethod
    def is_enabled(cls) -> bool:
        """Verifica si el endpoint público está habilitado."""
        config = RateLimitConfig.get_config()
        return config['is_enabled']

    @classmethod
    def check_and_increment(cls, ip: str, dni: str) -> tuple:
        """
        Verifica rate limits e incrementa atómicamente ANTES de verificar.
        Esto previene race conditions en requests concurrentes.
        Returns: (allowed: bool, error_message: str)
        """
        # Obtener configuración desde el admin (con cache de 60s)
        config = RateLimitConfig.get_config()

        # Si está deshabilitado, bloquear todo
        if not config['is_enabled']:
            logger.warning(f"RENIEC endpoint público DESHABILITADO - bloqueando request desde {ip}")
            return False, "Servicio temporalmente no disponible."

        ip_key = f"reniec_rate_ip_{ip}"
        dni_key = f"reniec_rate_dni_{dni}"
        global_key = "reniec_rate_global"

        # Incrementar PRIMERO (atómico), luego verificar
        # Esto evita que múltiples requests pasen el límite al mismo tiempo
        ip_count = cls._atomic_increment(ip_key, config['ip_window'])
        if ip_count > config['ip_limit']:
            logger.warning(f"RENIEC rate limit por IP excedido: {ip} ({ip_count}/{config['ip_limit']})")
            return False, "Demasiadas consultas desde tu ubicación. Intenta en unos minutos."

        dni_count = cls._atomic_increment(dni_key, config['dni_window'])
        if dni_count > config['dni_limit']:
            logger.warning(f"RENIEC rate limit por DNI excedido: ***{dni[-4:]} ({dni_count}/{config['dni_limit']})")
            return False, "Este DNI ya fue consultado recientemente. Intenta más tarde."

        global_count = cls._atomic_increment(global_key, config['global_window'])
        if global_count > config['global_limit']:
            logger.warning(f"RENIEC rate limit GLOBAL excedido: {global_count}/{config['global_limit']}")
            return False, "Servicio temporalmente no disponible. Intenta más tarde."

        logger.info(f"RENIEC rate limit OK - IP: {ip_count}/{config['ip_limit']}, DNI: {dni_count}/{config['dni_limit']}, Global: {global_count}/{config['global_limit']}")

        return True, ""


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


def get_referrer(request):
    """Obtiene el referrer de la consulta"""
    return request.META.get('HTTP_REFERER') or request.headers.get('Referer')


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
            referrer=get_referrer(request),
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
            referrer=get_referrer(request),
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
    NO requiere autenticación pero tiene rate limit estricto.

    GET /api/v1/reniec/lookup/public/?dni=12345678

    Rate limits (basados en cache, no DB):
    - Por IP: 5 consultas cada 10 minutos
    - Por DNI: 3 consultas cada hora
    - Global: 100 consultas cada hora

    Respuesta igual al PHP original.
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

        # Validar DNI primero (antes del rate limit para no consumir límites)
        if not dni or len(dni) != 8 or not dni.isdigit():
            return Response({'error': 'DNI inválido o no enviado'}, status=status.HTTP_400_BAD_REQUEST)

        # Rate limit con cache (más robusto que DB)
        allowed, error_message = PublicRateLimiter.check_and_increment(source_ip, dni)
        if not allowed:
            return Response({'error': error_message}, status=status.HTTP_429_TOO_MANY_REQUESTS)

        # Consultar DNI (toda la información incluyendo foto)
        success, result = ReniecService.lookup(
            dni=dni,
            source_app='public_web',
            source_ip=source_ip,
            user_agent=request.headers.get('User-Agent'),
            referrer=get_referrer(request),
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
