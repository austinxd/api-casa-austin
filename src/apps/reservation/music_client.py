import asyncio
from typing import Optional
from music_assistant_client.client import MusicAssistantClient


class MusicAssistantSingleton:
    """
    Singleton para manejar una única instancia del cliente de Music Assistant.
    Mantiene la conexión WebSocket persistente durante la vida del servidor.
    """
    _instance: Optional['MusicAssistantSingleton'] = None
    _client: Optional[MusicAssistantClient] = None
    _connection_task: Optional[asyncio.Task] = None
    _health_check_task: Optional[asyncio.Task] = None
    _lock = asyncio.Lock()
    _last_health_check: float = 0
    
    def __new__(cls):
        if cls._instance is None:
            cls._instance = super().__new__(cls)
        return cls._instance
    
    async def get_client(self) -> MusicAssistantClient:
        """
        Obtiene el cliente de Music Assistant, creando la conexión si no existe.
        """
        async with self._lock:
            # Verificar si el cliente existe y tiene conexión activa
            if self._client is None:
                await self._connect()
            elif not await self._is_connection_alive():
                # Reconectar si la conexión se perdió
                print("⚠️ Conexión perdida, reconectando...")
                await self._connect()
            else:
                # Verificar periódicamente (cada 30 segundos)
                import time
                current_time = time.time()
                if current_time - self._last_health_check > 30:
                    self._last_health_check = current_time
                    # Health check en background (no bloqueante)
                    asyncio.create_task(self._periodic_health_check())
            
            return self._client
    
    async def _periodic_health_check(self):
        """
        Health check periódico en background.
        Intenta acceder a los reproductores para verificar que la conexión funciona.
        """
        try:
            if self._client is not None and hasattr(self._client, 'players'):
                # Intentar acceder a los reproductores (operación ligera)
                _ = list(self._client.players)
        except Exception as e:
            print(f"⚠️ Health check falló: {e}. Marcando para reconexión...")
            # Marcar cliente como None para forzar reconexión en próxima petición
            self._client = None
    
    async def _is_connection_alive(self) -> bool:
        """
        Verifica si la conexión está realmente activa.
        """
        if self._client is None:
            return False
        
        # Verificar si el objeto de conexión existe
        if not hasattr(self._client, 'connection') or self._client.connection is None:
            return False
        
        # Verificar si el WebSocket está abierto
        try:
            if hasattr(self._client.connection, 'closed') and self._client.connection.closed:
                return False
        except:
            return False
        
        return True
    
    async def _connect(self):
        """
        Establece la conexión con el servidor de Music Assistant con reintentos.
        """
        max_connection_attempts = 3
        
        for attempt in range(max_connection_attempts):
            try:
                # Cerrar conexión previa si existe
                if self._client is not None:
                    try:
                        await self._client.disconnect()
                    except:
                        pass
                
                print(f"🔄 Conectando a Music Assistant (intento {attempt + 1}/{max_connection_attempts})...")
                
                # Crear nueva conexión
                self._client = MusicAssistantClient("wss://music.casaaustin.pe/ws", None)
                
                # Conectar con timeout
                await asyncio.wait_for(self._client.connect(), timeout=10.0)
                
                # Iniciar escucha de eventos para sincronizar reproductores
                asyncio.create_task(self._client.start_listening())
                
                # Esperar a que el módulo de música esté disponible
                max_wait = 10  # 10 intentos
                for i in range(max_wait):
                    if hasattr(self._client, 'music') and self._client.music is not None:
                        break
                    await asyncio.sleep(0.5)
                
                print("✅ Conectado a Music Assistant exitosamente")
                import time
                self._last_health_check = time.time()
                return
                
            except asyncio.TimeoutError:
                print(f"⏱️ Timeout al conectar (intento {attempt + 1})")
                if attempt < max_connection_attempts - 1:
                    await asyncio.sleep(2)  # Esperar antes de reintentar
                    continue
            except Exception as e:
                print(f"❌ Error al conectar (intento {attempt + 1}): {e}")
                if attempt < max_connection_attempts - 1:
                    await asyncio.sleep(2)  # Esperar antes de reintentar
                    continue
        
        # Si llega aquí, todos los intentos fallaron
        print("❌ No se pudo conectar a Music Assistant después de todos los intentos")
        self._client = None
        raise ConnectionError("No se pudo establecer conexión con Music Assistant")
    
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
        return self._client is not None and self._client.connection is not None


# Instancia global
music_assistant = MusicAssistantSingleton()


async def get_music_client() -> MusicAssistantClient:
    """
    Helper function para obtener el cliente de Music Assistant.
    """
    return await music_assistant.get_client()


async def execute_with_retry(func, *args, max_retries=2, **kwargs):
    """
    Ejecuta una función con reintentos automáticos en caso de error de conexión.
    Si falla, intenta reconectar y ejecutar de nuevo.
    """
    for attempt in range(max_retries):
        try:
            client = await get_music_client()
            return await func(client, *args, **kwargs)
        except Exception as e:
            error_msg = str(e).lower()
            # Detectar errores de conexión
            if any(keyword in error_msg for keyword in ['connection', 'websocket', 'not connected', 'closed']):
                if attempt < max_retries - 1:
                    print(f"🔄 Intento {attempt + 1}/{max_retries}: Error de conexión, reconectando...")
                    # Forzar reconexión
                    music_assistant._client = None
                    await asyncio.sleep(1)  # Esperar antes de reintentar
                    continue
            # Si no es error de conexión o último intento, lanzar error
            raise
