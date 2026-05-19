# Casa Austin MCP

MCP server local que expone a Claude Desktop:

1. Consultas públicas de disponibilidad y precios.
2. Análisis del chatbot Austin Assistant (autenticadas).

## Tools

### Públicas (no requieren auth)

| Tool | Args | Para qué |
|------|------|----------|
| `check_availability` | `check_in`, `check_out` | SOLO disponibilidad (sin precios). |
| `get_pricing` | `check_in`, `check_out`, `guests`, `property_slug?` | Disponibilidad + precios para N huéspedes. |
| `list_properties` | — | Las 4 casas con capacidad y precio mínimo. |

### Privadas (requieren admin credentials)

| Tool | Args | Para qué |
|------|------|----------|
| `get_chat_sessions` | `date_from?`, `date_to?`, `status?`, `limit?` | Lista de conversaciones del chatbot. |
| `get_chat_session` | `session_id` | Detalle + mensajes de una sesión. |
| `get_chat_analytics` | `period?` | Stats agregadas (volumen, response time, etc). |
| `get_funnel` | `month`, `year` | Funnel conversación → cotización → magic link → reserva. |
| `get_unresolved_questions` | `limit?` | Preguntas que el bot no pudo resolver. |
| `get_frequent_questions` | `limit?` | Preguntas más comunes detectadas. |
| `get_followup_opportunities` | — | Clientes que cotizaron pero no reservaron. |

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
        "CASA_AUSTIN_ADMIN_PASSWORD": "tu_admin_password"
      }
    }
  }
}
```

Reiniciar Claude Desktop. Listo.

## Auth — cómo funciona

- Las tools privadas requieren `CASA_AUSTIN_ADMIN_USERNAME` y `CASA_AUSTIN_ADMIN_PASSWORD`.
- En la primera llamada, el MCP hace `POST /api/v1/login/` y guarda `access` + `refresh` en memoria.
- Si una request devuelve 401 (access expirado), intenta `POST /api/v1/token/refresh/`.
- Si el refresh también expira, hace re-login con credenciales.
- Las credenciales viven solo en `claude_desktop_config.json` (archivo local del usuario).

## Variables de entorno

| Variable | Default | Para qué |
|----------|---------|----------|
| `CASA_AUSTIN_API_BASE` | `https://api.casaaustin.pe` | Base URL del API. Cambiar a `http://localhost:8000` para dev. |
| `CASA_AUSTIN_ADMIN_USERNAME` | (vacío) | User admin para tools privadas. |
| `CASA_AUSTIN_ADMIN_PASSWORD` | (vacío) | Password admin. |

## Ejemplos de uso en Claude Desktop

**Disponibilidad / cotización**:
- "¿Hay disponibilidad del 15 al 18 de junio?"
- "¿Cuánto sale Casa Austin 3 para 6 personas?"

**Análisis del chatbot**:
- "Dame un resumen de las conversaciones de esta semana"
- "¿Cómo viene el funnel del bot este mes?"
- "¿Qué preguntas comunes no está respondiendo bien el bot?"
- "Lista las top 20 preguntas frecuentes"
- "¿A qué clientes deberíamos hacer follow-up que cotizaron pero no reservaron?"
- "Analiza la sesión 1a2b3c4d-..."
