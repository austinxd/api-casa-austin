import asyncio
from typing import Optional
from music_assistant_client import MusicAssistantClient


class MusicAssistantSingleton:
    """
    Singleton para manejar una única instancia del cliente de Music Assistant.
    Mantiene la conexión WebSocket persistente durante la vida del servidor.
    """
    _instance: Optional['MusicAssistantSingleton'] = None
    _client: Optional[MusicAssistantClient] = None
    _connection_task: Optional[asyncio.Task] = None
    _lock = asyncio.Lock()
    
    def __new__(cls):
        if cls._instance is None:
            cls._instance = super().__new__(cls)
        return cls._instance
    
    async def get_client(self) -> MusicAssistantClient:
        """
        Obtiene el cliente de Music Assistant, creando la conexión si no existe.
        """
        async with self._lock:
            if self._client is None or not self._client.connected:
                await self._connect()
            return self._client
    
    async def _connect(self):
        """
        Establece la conexión con el servidor de Music Assistant.
        """
        try:
            # Cerrar conexión previa si existe
            if self._client is not None:
                try:
                    await self._client.disconnect()
                except:
                    pass
            
            # Crear nueva conexión
            self._client = MusicAssistantClient("wss://music.casaaustin.pe/ws", None)
            await self._client.connect()
            
            print("✅ Conectado a Music Assistant")
            
        except Exception as e:
            print(f"❌ Error al conectar con Music Assistant: {e}")
            self._client = None
            raise
    
    async def disconnect(self):
        """
        Cierra la conexión con Music Assistant.
        """
        async with self._lock:
            if self._client is not None:
                try:
                    await self._client.disconnect()
                    print("🔌 Desconectado de Music Assistant")
                except Exception as e:
                    print(f"Error al desconectar: {e}")
                finally:
                    self._client = None
    
    @property
    def is_connected(self) -> bool:
        """
        Verifica si hay una conexión activa.
        """
        return self._client is not None and self._client.connected


# Instancia global
music_assistant = MusicAssistantSingleton()


async def get_music_client() -> MusicAssistantClient:
    """
    Helper function para obtener el cliente de Music Assistant.
    """
    return await music_assistant.get_client()
