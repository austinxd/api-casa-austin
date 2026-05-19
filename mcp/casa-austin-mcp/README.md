# Casa Austin MCP

MCP server local que expone a Claude Desktop consultas de disponibilidad y precios
del API de Casa Austin.

## Tools

| Tool | Args | Endpoint |
|------|------|----------|
| `check_availability` | `check_in`, `check_out`, `guests` | `GET /api/v1/properties/calculate-pricing/` |
| `list_properties` | — | `GET /api/v1/property/` |

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

- "¿Hay disponibilidad del 15 al 18 de junio para 4 personas?"
- "¿Cuánto sale Casa Austin 3 el primer fin de semana de agosto?"
- "Compara los precios de las 4 casas del 25 al 27 de julio para 6 personas"
