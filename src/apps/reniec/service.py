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

        # Buscar en cache Django
        cached = DNICache.get_or_none(dni)
        if cached:
            logger.info(f"DNI {dni} encontrado en cache Django")
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

        # Buscar en base de datos externa (rutificador_bd) - cache legacy
        legacy_data = cls._query_legacy_database(dni)
        if legacy_data:
            logger.info(f"DNI {dni} encontrado en cache legacy (rutificador_bd)")
            # Guardar en cache Django para futuras consultas
            cached = cls._save_to_cache(dni, legacy_data)
            data = cls._format_response(cached, include_photo, include_full_data)
            data['source'] = 'cache_legacy'

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
    def _query_legacy_database(cls, dni: str) -> Optional[Dict[str, Any]]:
        """
        Consulta la base de datos legacy (rutificador_bd.dni_info).
        Retorna los datos en formato compatible con la API de Leder.
        """
        import MySQLdb

        # Configuración de la BD legacy
        legacy_db_config = {
            'host': getattr(settings, 'RENIEC_LEGACY_DB_HOST', 'localhost'),
            'user': getattr(settings, 'RENIEC_LEGACY_DB_USER', 'rutificador'),
            'passwd': getattr(settings, 'RENIEC_LEGACY_DB_PASSWORD', '!Rutificador123'),
            'db': getattr(settings, 'RENIEC_LEGACY_DB_NAME', 'rutificador_bd'),
            'charset': 'utf8mb4',
        }

        try:
            conn = MySQLdb.connect(**legacy_db_config)
            cursor = conn.cursor(MySQLdb.cursors.DictCursor)

            cursor.execute("SELECT * FROM dni_info WHERE dni = %s", (dni,))
            result = cursor.fetchone()

            cursor.close()
            conn.close()

            if not result:
                return None

            # Convertir formato de BD legacy a formato de API Leder
            def format_date(date_val):
                if date_val:
                    if hasattr(date_val, 'strftime'):
                        return date_val.strftime('%d/%m/%Y')
                    return str(date_val)
                return None

            legacy_data = {
                'preNombres': result.get('preNombres'),
                'apePaterno': result.get('apePaterno'),
                'apeMaterno': result.get('apeMaterno'),
                'apCasada': result.get('apCasada'),
                'feNacimiento': format_date(result.get('feNacimiento')),
                'sexo': result.get('sexo'),
                'estadoCivil': result.get('estadoCivil'),
                'departamento': result.get('departamento'),
                'provincia': result.get('provincia'),
                'distrito': result.get('distrito'),
                'depaDireccion': result.get('depaDireccion'),
                'provDireccion': result.get('provDireccion'),
                'distDireccion': result.get('distDireccion'),
                'desDireccion': result.get('desDireccion'),
                'feEmision': format_date(result.get('feEmision')),
                'feCaducidad': format_date(result.get('feCaducidad')),
                'digitoVerificacion': result.get('digitoVerificacion'),
                'ubicacion': {
                    'ubigeo_reniec': result.get('ubigeo_reniec'),
                    'ubigeo_inei': result.get('ubigeo_inei'),
                },
                'imagenes': {
                    'foto': result.get('imagen_foto'),
                },
            }

            logger.info(f"DNI {dni} encontrado en BD legacy")
            return legacy_data

        except ImportError:
            logger.warning("MySQLdb no instalado, no se puede consultar BD legacy")
            return None
        except Exception as e:
            logger.error(f"Error consultando BD legacy: {str(e)}")
            return None

    @classmethod
    def _query_external_api(cls, dni: str) -> Tuple[bool, Dict[str, Any]]:
        """Consulta la API externa de Leder"""
        # Re-leer configuración desde settings (por si cambió)
        api_token = getattr(settings, 'RENIEC_API_TOKEN', '') or cls.API_TOKEN
        api_url = getattr(settings, 'RENIEC_API_URL', cls.API_URL)

        if not api_token:
            logger.error("RENIEC_API_TOKEN no configurado")
            return False, {"error": "Servicio no configurado. Falta RENIEC_API_TOKEN"}

        logger.info(f"🔍 Consultando API RENIEC: {api_url} para DNI {dni}")

        try:
            payload = {
                "dni": dni,
                "source": "database",
                "token": api_token
            }

            response = requests.post(
                api_url,
                json=payload,
                headers={'Content-Type': 'application/json'},
                timeout=30
            )

            logger.info(f"📡 API RENIEC respuesta: status={response.status_code}")

            if response.status_code != 200:
                logger.error(f"API RENIEC error: {response.status_code} - {response.text[:500]}")
                # Intentar obtener mensaje de error de la respuesta
                try:
                    error_data = response.json()
                    error_msg = error_data.get('message') or error_data.get('error') or f"Error {response.status_code}"
                except:
                    error_msg = f"Error {response.status_code} en la consulta a RENIEC"
                return False, {"error": error_msg, "status_code": response.status_code}

            data = response.json()

            if not data or 'result' not in data:
                logger.error(f"API RENIEC respuesta inválida: {data}")
                return False, {"error": "No se encontró información para este DNI"}

            logger.info(f"✅ API RENIEC consulta exitosa para DNI {dni}")
            return True, data['result']

        except requests.Timeout:
            logger.error("API RENIEC timeout")
            return False, {"error": "Tiempo de espera agotado"}
        except requests.RequestException as e:
            logger.error(f"API RENIEC error de conexión: {str(e)}")
            return False, {"error": f"Error de conexión: {str(e)}"}
        except Exception as e:
            logger.error(f"API RENIEC error inesperado: {str(e)}")
            return False, {"error": f"Error interno: {str(e)}"}

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
