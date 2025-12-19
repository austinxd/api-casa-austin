import logging
import requests
import time
from datetime import datetime
from typing import Optional, Dict, Any, Tuple
from django.conf import settings
from django.utils import timezone

from .models import DNICache, DNIQueryLog

logger = logging.getLogger(__name__)


class ReniecService:
    """
    Servicio centralizado para consultas de DNI a RENIEC.
    - Consulta primero el cache local
    - Si no está en cache, consulta la API externa (Leder)
    - Guarda el resultado en cache
    - Registra todas las consultas para auditoría
    """

    # Configuración de la API externa
    API_URL = getattr(settings, 'RENIEC_API_URL', 'https://leder-data-api.ngrok.dev/v1.7/persona/reniec')
    API_TOKEN = getattr(settings, 'RENIEC_API_TOKEN', '')

    @classmethod
    def lookup(
        cls,
        dni: str,
        source_app: str,
        source_ip: str = None,
        user=None,
        client=None,
        user_agent: str = None,
        include_photo: bool = False,
        include_full_data: bool = False
    ) -> Tuple[bool, Dict[str, Any]]:
        """
        Consulta un DNI.

        Args:
            dni: Número de DNI (8 dígitos)
            source_app: Identificador de la aplicación que hace la consulta
            source_ip: IP del cliente
            user: Usuario autenticado (admin/staff)
            client: Cliente autenticado
            user_agent: User agent del request
            include_photo: Incluir foto en la respuesta
            include_full_data: Incluir datos completos

        Returns:
            Tuple[bool, Dict]: (success, data/error)
        """
        start_time = time.time()

        # Validar DNI
        if not dni or not dni.isdigit() or len(dni) != 8:
            cls._log_query(
                dni=dni or '',
                source_app=source_app,
                source_ip=source_ip,
                user=user,
                client=client,
                user_agent=user_agent,
                success=False,
                from_cache=False,
                error_message="DNI inválido",
                response_time_ms=int((time.time() - start_time) * 1000)
            )
            return False, {"error": "DNI inválido. Debe ser un número de 8 dígitos."}

        # Buscar en cache
        cached = DNICache.get_or_none(dni)
        if cached:
            logger.info(f"DNI {dni} encontrado en cache")
            data = cls._format_response(cached, include_photo, include_full_data)
            data['source'] = 'cache'

            cls._log_query(
                dni=dni,
                source_app=source_app,
                source_ip=source_ip,
                user=user,
                client=client,
                user_agent=user_agent,
                success=True,
                from_cache=True,
                response_time_ms=int((time.time() - start_time) * 1000)
            )
            return True, data

        # Consultar API externa
        logger.info(f"DNI {dni} no está en cache, consultando API externa")
        success, api_result = cls._query_external_api(dni)

        if not success:
            cls._log_query(
                dni=dni,
                source_app=source_app,
                source_ip=source_ip,
                user=user,
                client=client,
                user_agent=user_agent,
                success=False,
                from_cache=False,
                error_message=api_result.get('error', 'Error desconocido'),
                response_time_ms=int((time.time() - start_time) * 1000)
            )
            return False, api_result

        # Guardar en cache
        cached = cls._save_to_cache(dni, api_result)

        # Formatear respuesta
        data = cls._format_response(cached, include_photo, include_full_data)
        data['source'] = 'api'

        cls._log_query(
            dni=dni,
            source_app=source_app,
            source_ip=source_ip,
            user=user,
            client=client,
            user_agent=user_agent,
            success=True,
            from_cache=False,
            response_time_ms=int((time.time() - start_time) * 1000)
        )

        return True, data

    @classmethod
    def _query_external_api(cls, dni: str) -> Tuple[bool, Dict[str, Any]]:
        """Consulta la API externa de Leder"""
        if not cls.API_TOKEN:
            logger.error("RENIEC_API_TOKEN no configurado")
            return False, {"error": "Servicio no configurado"}

        try:
            payload = {
                "dni": dni,
                "source": "database",
                "token": cls.API_TOKEN
            }

            response = requests.post(
                cls.API_URL,
                json=payload,
                headers={'Content-Type': 'application/json'},
                timeout=30
            )

            if response.status_code != 200:
                logger.error(f"API RENIEC error: {response.status_code} - {response.text}")
                return False, {"error": "Error en la consulta a RENIEC"}

            data = response.json()

            if not data or 'result' not in data:
                logger.error(f"API RENIEC respuesta inválida: {data}")
                return False, {"error": "No se encontró información para este DNI"}

            return True, data['result']

        except requests.Timeout:
            logger.error("API RENIEC timeout")
            return False, {"error": "Tiempo de espera agotado"}
        except requests.RequestException as e:
            logger.error(f"API RENIEC error: {str(e)}")
            return False, {"error": "Error de conexión con RENIEC"}
        except Exception as e:
            logger.error(f"API RENIEC error inesperado: {str(e)}")
            return False, {"error": "Error interno"}

    @classmethod
    def _parse_date(cls, date_str: str) -> Optional[datetime]:
        """Convierte fecha de formato DD/MM/YYYY a date"""
        if not date_str:
            return None
        try:
            return datetime.strptime(date_str, '%d/%m/%Y').date()
        except ValueError:
            return None

    @classmethod
    def _capitalize_name(cls, name: str) -> str:
        """Capitaliza nombres correctamente"""
        if not name:
            return ''
        return ' '.join(word.capitalize() for word in name.lower().split())

    @classmethod
    def _save_to_cache(cls, dni: str, api_data: Dict[str, Any]) -> DNICache:
        """Guarda los datos de la API en cache"""
        ubicacion = api_data.get('ubicacion', {})
        imagenes = api_data.get('imagenes', {})

        cache_data = {
            'dni': dni,
            'nombres': cls._capitalize_name(api_data.get('preNombres', '')),
            'apellido_paterno': cls._capitalize_name(api_data.get('apePaterno', '')),
            'apellido_materno': cls._capitalize_name(api_data.get('apeMaterno', '')),
            'apellido_casada': cls._capitalize_name(api_data.get('apCasada', '')),
            'fecha_nacimiento': cls._parse_date(api_data.get('feNacimiento')),
            'sexo': (api_data.get('sexo', '') or '').upper()[:1],
            'estado_civil': api_data.get('estadoCivil'),
            'departamento': api_data.get('departamento'),
            'provincia': api_data.get('provincia'),
            'distrito': api_data.get('distrito'),
            'departamento_direccion': api_data.get('depaDireccion'),
            'provincia_direccion': api_data.get('provDireccion'),
            'distrito_direccion': api_data.get('distDireccion'),
            'direccion': api_data.get('desDireccion'),
            'fecha_emision': cls._parse_date(api_data.get('feEmision')),
            'fecha_caducidad': cls._parse_date(api_data.get('feCaducidad')),
            'digito_verificacion': api_data.get('digitoVerificacion'),
            'ubigeo_reniec': ubicacion.get('ubigeo_reniec'),
            'ubigeo_inei': ubicacion.get('ubigeo_inei'),
            'foto': imagenes.get('foto'),
            'raw_data': api_data,
            'source': 'api'
        }

        # Crear o actualizar
        cache, created = DNICache.objects.update_or_create(
            dni=dni,
            defaults=cache_data
        )

        logger.info(f"DNI {dni} {'creado' if created else 'actualizado'} en cache")
        return cache

    @classmethod
    def _format_response(
        cls,
        cache: DNICache,
        include_photo: bool = False,
        include_full_data: bool = False
    ) -> Dict[str, Any]:
        """Formatea la respuesta según los permisos"""
        data = {
            'dni': cache.dni,
            'nombres': cache.nombres,
            'apellido_paterno': cache.apellido_paterno,
            'apellido_materno': cache.apellido_materno,
            'nombre_completo': cache.nombre_completo,
            'fecha_nacimiento': cache.fecha_nacimiento.isoformat() if cache.fecha_nacimiento else None,
            'sexo': cache.sexo,
            'digito_verificacion': cache.digito_verificacion,
        }

        if include_full_data:
            data.update({
                'apellido_casada': cache.apellido_casada,
                'estado_civil': cache.estado_civil,
                'departamento': cache.departamento,
                'provincia': cache.provincia,
                'distrito': cache.distrito,
                'departamento_direccion': cache.departamento_direccion,
                'provincia_direccion': cache.provincia_direccion,
                'distrito_direccion': cache.distrito_direccion,
                'direccion': cache.direccion,
                'fecha_emision': cache.fecha_emision.isoformat() if cache.fecha_emision else None,
                'fecha_caducidad': cache.fecha_caducidad.isoformat() if cache.fecha_caducidad else None,
                'ubigeo_reniec': cache.ubigeo_reniec,
                'ubigeo_inei': cache.ubigeo_inei,
            })

        if include_photo and cache.foto:
            data['foto'] = cache.foto

        return {'data': data}

    @classmethod
    def _log_query(
        cls,
        dni: str,
        source_app: str,
        source_ip: str = None,
        user=None,
        client=None,
        user_agent: str = None,
        success: bool = False,
        from_cache: bool = False,
        error_message: str = None,
        response_time_ms: int = None
    ):
        """Registra la consulta para auditoría"""
        try:
            DNIQueryLog.objects.create(
                dni=dni,
                source_app=source_app,
                source_ip=source_ip,
                user=user,
                client=client,
                user_agent=user_agent,
                success=success,
                from_cache=from_cache,
                error_message=error_message,
                response_time_ms=response_time_ms
            )
        except Exception as e:
            logger.error(f"Error guardando log de consulta DNI: {str(e)}")
