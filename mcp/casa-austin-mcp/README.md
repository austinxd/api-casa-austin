# Casa Austin MCP

MCP server local que expone a Claude Desktop consultas de disponibilidad y precios
del API de Casa Austin.

## Tools

| Tool | Args | Para qué |
|------|------|----------|
| `check_availability` | `check_in`, `check_out` | SOLO disponibilidad (sin precios). "¿Hay casas libres del 15 al 18?" |
| `get_pricing` | `check_in`, `check_out`, `guests`, `property_slug?` | Disponibilidad + precios. "¿Cuánto sale para 6 personas?" |
| `list_properties` | — | Lista las 4 casas con capacidad y precio mínimo. |

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
      "args": ["/ruta/absoluta/al/repo/api-casa-austin/mcp/casa-austin-mcp/index.js"]
    }
  }
}
```

Reiniciar Claude Desktop. Listo.

## Variables de entorno

- `CASA_AUSTIN_API_BASE` (opcional) — base URL de la API. Default: `https://api.casaaustin.pe`.

Para apuntar a un backend local:

```json
"env": { "CASA_AUSTIN_API_BASE": "http://localhost:8000" }
```

## Ejemplos de uso en Claude Desktop

**Disponibilidad sin precios** (`check_availability`):
- "¿Hay disponibilidad del 15 al 18 de junio?"
- "¿Qué casas están libres este fin de semana?"

**Cotización con precios** (`get_pricing`):
- "¿Cuánto sale Casa Austin 3 para 6 personas del 15 al 18 de junio?"
- "Compara los precios de las 4 casas del 25 al 27 de julio para 8 personas"
- "Cotizar 4 personas el primer fin de semana de agosto"

**Información** (`list_properties`):
- "¿Cuáles son las 4 casas de Casa Austin?"
- "¿Cuál es la casa con mayor capacidad?"
