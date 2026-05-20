# AI Billing MCP

MCP server para consultar uso y costos de las APIs de **Anthropic** y **OpenAI** desde Claude Desktop.

⚠️ Cubre **solo uso de API** (pay-as-you-go). NO cubre suscripciones de ChatGPT Plus/Team/Enterprise (no hay API pública para eso).

## Tools

| Tool | Para qué |
|------|----------|
| `get_anthropic_usage` | Tokens consumidos por modelo (claude-opus, sonnet, haiku) |
| `get_anthropic_cost` | Costo USD en Anthropic por rango |
| `get_openai_usage` | Tokens y requests por modelo (gpt-4o, etc.) — solo completions |
| `get_openai_cost` | Costo USD total OpenAI (incluye embeddings, audio, images) |
| `get_combined_spend` | Suma Anthropic + OpenAI con % de cada uno |
| `get_today_spend` | Atajo: gasto del día de hoy |

## Setup

### 1) Crear Admin API keys

**Anthropic:**
1. https://console.anthropic.com → **Settings → Admin Keys**.
2. Create key → copiá la que empieza con `sk-ant-admin01-...`.
3. Esa key es distinta de la API key normal — solo sirve para endpoints de organización.

**OpenAI:**
1. https://platform.openai.com → **Settings → Organization → Admin keys**.
2. Create new key → copiá la que empieza con `sk-admin-...`.
3. Requiere que tu cuenta sea **Owner** de la organización.

### 2) Configurar Claude Desktop

Editar `~/Library/Application Support/Claude/claude_desktop_config.json`:

```json
{
  "mcpServers": {
    "ai-billing": {
      "command": "node",
      "args": ["/Users/austin/Proyectos/Casa Austin/api-casa-austin/mcp/ai-billing-mcp/index.js"],
      "env": {
        "ANTHROPIC_ADMIN_KEY": "sk-ant-admin01-...",
        "OPENAI_ADMIN_KEY": "sk-admin-...",
        "OPENAI_ORG_ID": "org-..."
      }
    }
  }
}
```

`OPENAI_ORG_ID` es **opcional** — solo necesario si tu cuenta tiene varias organizaciones.

Cmd+Q a Claude Desktop y reabrir.

## Ejemplos de uso

```
¿Cuánto gasté hoy en APIs de IA?
¿Cuánto va el mes en Claude?
¿Cuánto gasté la semana pasada en OpenAI?
Compará gasto Anthropic vs OpenAI de mayo
Tokens usados por modelo de Claude este mes
¿Qué modelo de GPT estoy usando más?
```

Claude elige la tool correcta según el intent.

## Endpoints que usa el MCP

- Anthropic: `GET /v1/organizations/usage_report/messages` + `GET /v1/organizations/cost_report`
- OpenAI: `GET /v1/organization/usage/completions` + `GET /v1/organization/costs`

Auth:
- Anthropic: header `x-api-key` + `anthropic-version: 2023-06-01`
- OpenAI: header `Authorization: Bearer ...` + opcional `OpenAI-Organization`

## Limitaciones

- **Granularidad mínima**: Anthropic permite 1m/1h/1d; OpenAI permite 1m/1h/1d en usage pero **1d en costs**.
- **Latencia de datos**: Anthropic actualiza con ~1h de delay; OpenAI con hasta 24h. Para "hoy" puede que el dato del día actual esté incompleto.
- **OpenAI usage de completions**: cubre `chat.completions`. Para embeddings/audio/images hay endpoints aparte (`/usage/embeddings`, `/usage/audio_speeches`, etc.) — fáciles de agregar si los necesitás.
- **Multi-cuenta**: el MCP actual asume 1 cuenta por proveedor. Para varias hay que extender con un parámetro `account_name` y dict de keys.

## Troubleshooting

- **"401 Unauthorized" Anthropic**: la admin key creada no es válida o se revocó. Recrear.
- **"Insufficient permissions" OpenAI**: tu admin key no tiene scope de billing. En OpenAI, las admin keys tienen scopes — al crearla activá "billing/usage read".
- **HTTP 429**: rate limit del endpoint. Esperar 30s.
- **Datos vacíos**: el día actual puede aún no estar agregado en el dashboard del proveedor. Probá con días anteriores.
