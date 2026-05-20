# Casa Austin MCP

MCP server local para Claude Desktop. Expone consultas de:

1. Disponibilidad y precios (públicos).
2. Análisis del chatbot Austin Assistant (autenticadas).
3. Operaciones, ocupación e ingresos (autenticadas).

## Tools

### 🔵 Cotización / disponibilidad (no requieren auth)

| Tool | USAR PARA |
|------|-----------|
| `check_availability` | Saber si hay casas LIBRES en fechas futuras (sin importar precio ni huéspedes). |
| `get_pricing` | Cotizar precios para fechas + cantidad de huéspedes específicos. |
| `list_properties` | Info estática de las 4 casas: capacidad, dormitorios, precio mínimo. |

### 💬 Chatbot Austin Assistant (requieren admin)

| Tool | USAR PARA |
|------|-----------|
| `get_chat_sessions` | Listar conversaciones del bot (con filtros). |
| `get_chat_session` | Mensajes completos de una sesión específica. |
| `get_chat_analytics` | Stats del bot: volumen, response time, escalamiento. |
| `get_funnel` | Funnel conversación → cotización → magic link → reserva. |
| `get_unresolved_questions` | Preguntas que el bot no pudo resolver. |
| `get_frequent_questions` | Preguntas más comunes detectadas. |
| `get_followup_opportunities` | Clientes que cotizaron pero no reservaron. |

### 📊 Operaciones / ingresos (requieren admin)

| Tool | USAR PARA |
|------|-----------|
| `get_monthly_operations` | TODO de un mes: noches libres por casa, ocupación, facturación, vendedores. |
| `get_active_today` | Casas ocupadas AHORA + check-ins programados para hoy. |
| `get_yearly_revenue` | Facturación mensual de los 12 meses de un año. |
| `compare_months_yoy` | Comparar mismo mes en 2 años (year-over-year). |

### 🏠 Home Assistant (control de dispositivos en las casas)

| Tool | USAR PARA |
|------|-----------|
| `ha_list_devices` | Listar dispositivos (luces, switches, climate). Filtrar por casa o tipo. |
| `ha_control_device` | Prender/apagar/togglear con búsqueda en lenguaje natural (`query`). |
| `ha_test_connection` | Verificar que Home Assistant esté vivo. |

**Ejemplos de comandos naturales que funcionan:**

- *"Apaga el garaje de Casa Austin 3"*
- *"Prende todas las luces del 2do piso de Casa Austin 3"*
- *"¿Qué dispositivos hay encendidos en Casa Austin 4?"*
- *"Apaga todo en Casa Austin 3"* (matchea el switch "Apagar Todo")
- *"Sube el brillo de la luz X al 50%"* (brightness 128)
- *"¿Está conectado Home Assistant?"*

Si una búsqueda es ambigua (matchea varios dispositivos con mismo score), el MCP devuelve la lista para que aclares con `device_id` o seas más específico.

## ⚡ Performance

El endpoint `/ha/admin/devices/` en frío tarda ~12s (Home Assistant remoto). Optimizaciones del MCP:

- **Pre-warm al startup**: si hay credenciales, el MCP hace login + fetch de devices al arrancar (en background, sin bloquear). Tu primer comando responde en ~300ms en vez de 12s.
- **Cache local 30s**: lista de devices se cachea localmente. Comandos consecutivos en menos de 30s son instantáneos.
- **Invalidación al controlar**: después de cualquier `ha_control_device`, se invalida el cache para que el próximo list traiga el estado fresco.
- **Cache de properties 5min**: la lista de las 4 casas se cachea casi indefinidamente.

Si percibís lentitud después del startup, espera 10-15 segundos y reintenta — está terminando de pre-cargar.

## Setup

```bash
cd mcp/casa-austin-mcp
npm install
```

Registrar en `~/Library/Application Support/Claude/claude_desktop_config.json`:

```json
{
  "mcpServers": {
    "casa-austin": {
      "command": "node",
      "args": ["/ruta/absoluta/a/api-casa-austin/mcp/casa-austin-mcp/index.js"],
      "env": {
        "CASA_AUSTIN_ADMIN_USERNAME": "tu_admin_user",
        "CASA_AUSTIN_ADMIN_PASSWORD": "tu_password"
      }
    }
  }
}
```

Reiniciar Claude Desktop.

## Auth — cómo funciona

- Las tools privadas requieren `CASA_AUSTIN_ADMIN_USERNAME` y `CASA_AUSTIN_ADMIN_PASSWORD`.
- El MCP hace `POST /api/v1/login/` al primer llamado, guarda `access` + `refresh` en memoria.
- Si `access` expira (401), intenta `POST /api/v1/token/refresh/`.
- Si `refresh` también expira, hace re-login con credenciales.

## Diseño: ¿por qué tools separadas y no una sola?

Cada tool tiene un nombre y una descripción específica con prefijo "USAR PARA…". Claude (el LLM) elige automáticamente la correcta según el intent del usuario. Una sola tool monolítica obligaría a meter un LLM dentro del MCP, lo cual es complejo y duplicado.

Para evitar confusión entre tools similares, cada descripción incluye:
- "USAR PARA…" (caso de uso positivo)
- "NO usar para…" (lo que NO cubre, redirigiendo a otra tool)

## Ejemplos de uso en Claude Desktop

**Cotización**:
- "¿Hay disponibilidad del 15 al 18 de junio?"
- "Cotizar Casa Austin 3 para 6 personas el primer fin de semana de agosto"

**Chatbot**:
- "¿Cómo viene el funnel del bot este mes?"
- "Top preguntas que el bot no respondió"
- "Lista clientes que cotizaron y no reservaron"

**Operaciones**:
- "¿Cuánto facturamos este mes y cómo viene la ocupación?"
- "Compará mayo 2026 con mayo 2025"
- "Dame la facturación mensual de 2025"
- "¿Qué casa tuvo más noches libres este mes?"

## Variables de entorno

| Variable | Default | Para qué |
|----------|---------|----------|
| `CASA_AUSTIN_API_BASE` | `https://api.casaaustin.pe` | Base URL del API. |
| `CASA_AUSTIN_ADMIN_USERNAME` | (vacío) | Username admin (login Django). |
| `CASA_AUSTIN_ADMIN_PASSWORD` | (vacío) | Password admin. |
