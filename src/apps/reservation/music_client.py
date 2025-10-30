import requests
import logging
from typing import Dict, List, Optional, Any

logger = logging.getLogger(__name__)


class MusicAPIClient:
    """
    Cliente HTTP para la nueva API de música de Casa Austin.
    Reemplaza la conexión WebSocket de Music Assistant.
    """
    
    def __init__(self, base_url: str = "https://music.casaaustin.pe"):
        self.base_url = base_url
        self.timeout = 10  # Timeout de 10 segundos para requests
    
    def _make_request(self, method: str, endpoint: str, **kwargs) -> Dict[str, Any]:
        """
        Realiza una petición HTTP a la API de música.
        
        Args:
            method: HTTP method (GET, POST, DELETE, etc.)
            endpoint: API endpoint (e.g., "/status", "/house/1/play")
            **kwargs: Argumentos adicionales para requests (json, params, etc.)
        
        Returns:
            Response JSON como diccionario
        
        Raises:
            requests.exceptions.RequestException: Si hay error en la petición
        """
        url = f"{self.base_url}{endpoint}"
        
        try:
            response = requests.request(
                method=method,
                url=url,
                timeout=self.timeout,
                **kwargs
            )
            response.raise_for_status()
            
            # Manejar respuestas vacías o 204 No Content
            if response.status_code == 204 or not response.content:
                return {"success": True}
            
            return response.json()
        
        except requests.exceptions.Timeout:
            logger.error(f"Timeout al llamar a {url}")
            raise
        except requests.exceptions.RequestException as e:
            logger.error(f"Error en request a {url}: {str(e)}")
            raise
    
    # ==================== STATUS ====================
    
    def get_all_status(self) -> Dict[str, Any]:
        """
        GET /status
        Obtiene el estado de todas las casas.
        """
        return self._make_request("GET", "/status")
    
    def get_house_status(self, house_id: int) -> Dict[str, Any]:
        """
        GET /house/{house_id}/status
        Obtiene el estado de una casa específica.
        """
        return self._make_request("GET", f"/house/{house_id}/status")
    
    # ==================== PLAYBACK CONTROL ====================
    
    def play(self, house_id: int, track_id: Optional[str] = None) -> Dict[str, Any]:
        """
        POST /house/{house_id}/play
        Reproduce una canción o resume la reproducción.
        
        Args:
            house_id: ID de la casa (1-4)
            track_id: ID de la canción de Deezer (opcional)
        """
        body = {"track_id": track_id} if track_id else {}
        return self._make_request("POST", f"/house/{house_id}/play", json=body)
    
    def pause(self, house_id: int) -> Dict[str, Any]:
        """
        POST /house/{house_id}/pause
        Pausa la reproducción.
        """
        return self._make_request("POST", f"/house/{house_id}/pause")
    
    def stop(self, house_id: int) -> Dict[str, Any]:
        """
        POST /house/{house_id}/stop
        Detiene completamente la reproducción.
        """
        return self._make_request("POST", f"/house/{house_id}/stop")
    
    def next_track(self, house_id: int) -> Dict[str, Any]:
        """
        POST /house/{house_id}/next
        Salta a la siguiente canción.
        """
        return self._make_request("POST", f"/house/{house_id}/next")
    
    def previous_track(self, house_id: int) -> Dict[str, Any]:
        """
        POST /house/{house_id}/previous
        Vuelve a la canción anterior.
        """
        return self._make_request("POST", f"/house/{house_id}/previous")
    
    def set_volume(self, house_id: int, level: int) -> Dict[str, Any]:
        """
        POST /house/{house_id}/volume
        Ajusta el volumen (0-100).
        
        Args:
            house_id: ID de la casa (1-4)
            level: Nivel de volumen (0-100)
        """
        return self._make_request("POST", f"/house/{house_id}/volume", json={"level": level})
    
    def toggle_mute(self, house_id: int) -> Dict[str, Any]:
        """
        POST /house/{house_id}/mute
        Alterna el estado de mute.
        """
        return self._make_request("POST", f"/house/{house_id}/mute")
    
    def set_power(self, house_id: int, state: str) -> Dict[str, Any]:
        """
        POST /house/{house_id}/power
        Enciende o apaga el sistema.
        
        Args:
            house_id: ID de la casa (1-4)
            state: "on" o "off"
        """
        return self._make_request("POST", f"/house/{house_id}/power", json={"state": state})
    
    # ==================== QUEUE MANAGEMENT ====================
    
    def get_queue(self, house_id: int) -> Dict[str, Any]:
        """
        GET /house/{house_id}/queue
        Obtiene la cola de reproducción.
        """
        return self._make_request("GET", f"/house/{house_id}/queue")
    
    def add_to_queue(self, house_id: int, track_id: str) -> Dict[str, Any]:
        """
        POST /house/{house_id}/queue
        Agrega una canción a la cola.
        
        Args:
            house_id: ID de la casa (1-4)
            track_id: ID de la canción de Deezer
        """
        return self._make_request("POST", f"/house/{house_id}/queue", json={"track_id": track_id})
    
    def remove_from_queue(self, house_id: int, index: int) -> Dict[str, Any]:
        """
        DELETE /house/{house_id}/queue/{index}
        Elimina una canción de la cola por índice.
        
        Args:
            house_id: ID de la casa (1-4)
            index: Índice de la canción en la cola
        """
        return self._make_request("DELETE", f"/house/{house_id}/queue/{index}")
    
    def clear_queue(self, house_id: int) -> Dict[str, Any]:
        """
        DELETE /house/{house_id}/queue/clear
        Limpia toda la cola de reproducción.
        """
        return self._make_request("DELETE", f"/house/{house_id}/queue/clear")
    
    # ==================== SEARCH ====================
    
    def search_tracks(self, query: str, limit: int = 20) -> Dict[str, Any]:
        """
        POST /search
        Busca canciones en Deezer.
        
        Args:
            query: Término de búsqueda
            limit: Número máximo de resultados (default: 20)
        """
        return self._make_request("POST", "/search", json={"query": query, "limit": limit})
    
    # ==================== CHARTS ====================
    
    def get_charts(self) -> Dict[str, Any]:
        """
        GET /charts
        Obtiene las canciones más populares (charts de Deezer).
        """
        return self._make_request("GET", "/charts")


# Instancia global del cliente
_music_client = None


def get_music_client() -> MusicAPIClient:
    """
    Obtiene la instancia global del cliente de música.
    Crea una nueva instancia si no existe.
    """
    global _music_client
    if _music_client is None:
        _music_client = MusicAPIClient()
    return _music_client
