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
| `get_yearly_revenue` | Facturación mensual de los 12 meses de un año. |
| `compare_months_yoy` | Comparar mismo mes en 2 años (year-over-year). |

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
