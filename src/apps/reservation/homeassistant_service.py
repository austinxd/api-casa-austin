import os
import requests
import logging
from typing import Dict, Any, Optional, List
from django.conf import settings

logger = logging.getLogger(__name__)


class HomeAssistantService:
    """
    Servicio para interactuar con la API REST de Home Assistant
    Usa token de larga duración para autenticación
    """
    
    def __init__(self):
        self.base_url = os.getenv('HOME_ASSISTANT_URL')
        self.token = os.getenv('HOME_ASSISTANT_TOKEN')
        
        if not self.base_url:
            raise ValueError(
                "HOME_ASSISTANT_URL no está configurada. "
                "Por favor configura esta variable de entorno."
            )
        
        if not self.token:
            raise ValueError(
                "HOME_ASSISTANT_TOKEN no está configurado. "
                "Por favor configura este secret en Replit."
            )
        
        self.headers = {
            'Authorization': f'Bearer {self.token}',
            'Content-Type': 'application/json'
        }
    
    def _make_request(self, method: str, endpoint: str, data: Optional[Dict] = None) -> Any:
        """
        Método interno para hacer peticiones HTTP a Home Assistant
        
        Args:
            method: GET, POST, etc.
            endpoint: endpoint de la API (sin el base_url)
            data: datos JSON para enviar (opcional)
            
        Returns:
            Respuesta JSON de Home Assistant
            
        Raises:
            requests.exceptions.RequestException: Si hay error en la petición
        """
        url = f"{self.base_url}{endpoint}"
        response = None
        
        # Log de la petición
        logger.info("=" * 80)
        logger.info(f"🔵 HOME ASSISTANT REQUEST - {method.upper()}")
        logger.info(f"URL: {url}")
        logger.info(f"Token configurado: {'✓ Sí' if self.token else '✗ No'}")
        if self.token:
            logger.info(f"Token preview: {self.token[:20]}...{self.token[-10:]}")
        if data:
            logger.info(f"Datos enviados: {data}")
        
        try:
            if method.upper() == 'GET':
                response = requests.get(url, headers=self.headers, timeout=10)
            elif method.upper() == 'POST':
                response = requests.post(url, headers=self.headers, json=data, timeout=10)
            else:
                raise ValueError(f"Método HTTP no soportado: {method}")
            
            # Log de la respuesta exitosa
            logger.info(f"✅ Respuesta HTTP {response.status_code}")
            response_json = response.json()
            logger.info(f"Respuesta completa: {response_json}")
            logger.info("=" * 80)
            
            response.raise_for_status()
            return response_json
            
        except requests.exceptions.Timeout:
            logger.error("❌ TIMEOUT al conectar con Home Assistant")
            logger.error("=" * 80)
            raise Exception("Timeout al conectar con Home Assistant")
        except requests.exceptions.ConnectionError as e:
            logger.error(f"❌ ERROR DE CONEXIÓN con Home Assistant: {str(e)}")
            logger.error("=" * 80)
            raise Exception("Error de conexión con Home Assistant")
        except requests.exceptions.HTTPError:
            if response:
                logger.error(f"❌ ERROR HTTP {response.status_code}")
                logger.error(f"Respuesta: {response.text}")
                logger.error("=" * 80)
                raise Exception(f"Error HTTP {response.status_code}: {response.text}")
            logger.error("❌ ERROR HTTP en petición (sin respuesta)")
            logger.error("=" * 80)
            raise Exception("Error HTTP en petición")
        except requests.exceptions.RequestException as e:
            logger.error(f"❌ ERROR en petición a Home Assistant: {str(e)}")
            logger.error("=" * 80)
            raise Exception(f"Error en petición a Home Assistant: {str(e)}")
    
    def test_connection(self) -> Dict[str, Any]:
        """
        Prueba la conexión con Home Assistant
        
        Returns:
            Diccionario con información de la API
        """
        return self._make_request('GET', '/api/')
    
    def get_all_states(self) -> List[Dict[str, Any]]:
        """
        Obtiene el estado de todas las entidades en Home Assistant
        
        Returns:
            Lista de diccionarios con información de cada entidad
        """
        return self._make_request('GET', '/api/states')
    
    def get_entity_state(self, entity_id: str) -> Dict[str, Any]:
        """
        Obtiene el estado de una entidad específica
        
        Args:
            entity_id: ID de la entidad (ej: "light.living_room")
            
        Returns:
            Diccionario con el estado de la entidad
        """
        return self._make_request('GET', f'/api/states/{entity_id}')
    
    def call_service(self, domain: str, service: str, entity_id: str, **kwargs) -> List[Dict[str, Any]]:
        """
        Llama a un servicio de Home Assistant (turn_on, turn_off, etc.)
        
        Args:
            domain: Dominio del servicio (light, switch, climate, etc.)
            service: Nombre del servicio (turn_on, turn_off, set_temperature, etc.)
            entity_id: ID de la entidad a controlar
            **kwargs: Parámetros adicionales del servicio (brightness, temperature, etc.)
            
        Returns:
            Lista con los estados actualizados de las entidades afectadas
            
        Example:
            # Encender una luz con brillo 50%
            service.call_service('light', 'turn_on', 'light.living_room', brightness=128)
            
            # Apagar un switch
            service.call_service('switch', 'turn_off', 'switch.pool_heater')
            
            # Ajustar temperatura
            service.call_service('climate', 'set_temperature', 'climate.ac', temperature=22)
        """
        logger.info(f"🎯 Llamando servicio: {domain}.{service} para {entity_id}")
        if kwargs:
            logger.info(f"   Parámetros adicionales: {kwargs}")
        
        data = {
            'entity_id': entity_id,
            **kwargs
        }
        
        result = self._make_request('POST', f'/api/services/{domain}/{service}', data)
        
        logger.info(f"✅ Servicio ejecutado - Entidades afectadas: {len(result) if isinstance(result, list) else 'N/A'}")
        
        return result
    
    def turn_on(self, entity_id: str, **kwargs) -> List[Dict[str, Any]]:
        """
        Enciende un dispositivo (luz, switch, etc.)
        
        Args:
            entity_id: ID de la entidad
            **kwargs: Parámetros adicionales (brightness, color, etc.)
            
        Returns:
            Estado actualizado de la entidad
        """
        domain = entity_id.split('.')[0]
        return self.call_service(domain, 'turn_on', entity_id, **kwargs)
    
    def turn_off(self, entity_id: str) -> List[Dict[str, Any]]:
        """
        Apaga un dispositivo (luz, switch, etc.)
        
        Args:
            entity_id: ID de la entidad
            
        Returns:
            Estado actualizado de la entidad
        """
        domain = entity_id.split('.')[0]
        return self.call_service(domain, 'turn_off', entity_id)
    
    def toggle(self, entity_id: str) -> List[Dict[str, Any]]:
        """
        Alterna el estado de un dispositivo (on <-> off)
        
        Args:
            entity_id: ID de la entidad
            
        Returns:
            Estado actualizado de la entidad
        """
        domain = entity_id.split('.')[0]
        return self.call_service(domain, 'toggle', entity_id)
    
    def set_light_brightness(self, entity_id: str, brightness: int) -> List[Dict[str, Any]]:
        """
        Ajusta el brillo de una luz (0-255)
        
        Args:
            entity_id: ID de la luz
            brightness: Nivel de brillo (0-255)
            
        Returns:
            Estado actualizado de la luz
        """
        return self.call_service('light', 'turn_on', entity_id, brightness=brightness)
    
    def set_climate_temperature(self, entity_id: str, temperature: float) -> List[Dict[str, Any]]:
        """
        Ajusta la temperatura de un dispositivo de clima
        
        Args:
            entity_id: ID del dispositivo de clima
            temperature: Temperatura deseada
            
        Returns:
            Estado actualizado del dispositivo
        """
        return self.call_service('climate', 'set_temperature', entity_id, temperature=temperature)
    
    def get_devices_by_type(self, device_type: str) -> List[Dict[str, Any]]:
        """
        Filtra dispositivos por tipo (light, switch, climate, etc.)
        
        Args:
            device_type: Tipo de dispositivo (light, switch, climate, sensor, etc.)
            
        Returns:
            Lista de dispositivos que coinciden con el tipo
        """
        all_states = self.get_all_states()
        return [
            device for device in all_states 
            if device['entity_id'].startswith(f'{device_type}.')
        ]
    
    def search_devices(self, search_term: str) -> List[Dict[str, Any]]:
        """
        Busca dispositivos por nombre o entity_id
        
        Args:
            search_term: Término de búsqueda (en entity_id o friendly_name)
            
        Returns:
            Lista de dispositivos que coinciden con la búsqueda
        """
        all_states = self.get_all_states()
        search_lower = search_term.lower()
        
        return [
            device for device in all_states
            if search_lower in device['entity_id'].lower() or
               search_lower in device.get('attributes', {}).get('friendly_name', '').lower()
        ]
