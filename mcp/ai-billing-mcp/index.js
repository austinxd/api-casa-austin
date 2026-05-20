#!/usr/bin/env node
/**
 * MCP server para consultar uso y costos de las APIs de Anthropic y OpenAI.
 *
 * Tools:
 *   - get_anthropic_usage(start_date?, end_date?, bucket_width?)
 *   - get_anthropic_cost(start_date?, end_date?, bucket_width?)
 *   - get_openai_usage(start_date?, end_date?, bucket_width?)
 *   - get_openai_cost(start_date?, end_date?, bucket_width?)
 *   - get_combined_spend(start_date?, end_date?)
 *   - get_today_spend()
 *
 * Variables de entorno requeridas:
 *   ANTHROPIC_ADMIN_KEY  → sk-ant-admin01-...
 *   OPENAI_ADMIN_KEY     → sk-admin-...
 *   OPENAI_ORG_ID        → org-... (opcional, solo si tenés varias orgs)
 *
 * Notas:
 * - Las API Admin de ambos proveedores devuelven datos agregados por buckets
 *   de tiempo (1m, 1h, 1d). El default es "1d".
 * - Los costos vienen en USD.
 * - Para suscripciones ChatGPT (consumer) NO hay API — solo cubre uso de la API.
 */
import { Server } from "@modelcontextprotocol/sdk/server/index.js";
import { StdioServerTransport } from "@modelcontextprotocol/sdk/server/stdio.js";
import {
    CallToolRequestSchema,
    ListToolsRequestSchema,
} from "@modelcontextprotocol/sdk/types.js";

const ANTHROPIC_KEY = process.env.ANTHROPIC_ADMIN_KEY || "";
const OPENAI_KEY = process.env.OPENAI_ADMIN_KEY || "";
const OPENAI_ORG = process.env.OPENAI_ORG_ID || "";

const DEFAULT_TIMEOUT_MS = 15_000;

// ─── Helpers ───

async function fetchWithTimeout(url, opts = {}, timeoutMs = DEFAULT_TIMEOUT_MS) {
    const controller = new AbortController();
    const timer = setTimeout(() => controller.abort(), timeoutMs);
    try {
        return await fetch(url, { ...opts, signal: controller.signal });
    } catch (err) {
        if (err.name === "AbortError") {
            throw new Error(`Timeout (${timeoutMs}ms) llamando ${url}`);
        }
        throw err;
    } finally {
        clearTimeout(timer);
    }
}

/** YYYY-MM-DD → ISO 8601 UTC (00:00 del mismo día) */
function dateToIsoStart(d) {
    if (!d) return null;
    if (/^\d{4}-\d{2}-\d{2}$/.test(d)) return `${d}T00:00:00Z`;
    return d; // ya está en ISO
}

/** YYYY-MM-DD → ISO 8601 UTC del DÍA SIGUIENTE a las 00:00.
 *  Las APIs de billing (Anthropic + OpenAI) tratan el rango como
 *  [starting_at, ending_at) exclusivo. Para incluir el día d completo
 *  hay que mandar ending_at = d+1 a las 00:00 UTC. Si mandás 23:59:59
 *  del mismo día y start=00:00 del mismo día, da error
 *  "ending date must be after starting date" porque comparten bucket.
 */
function dateToIsoEnd(d) {
    if (!d) return null;
    if (/^\d{4}-\d{2}-\d{2}$/.test(d)) {
        const dt = new Date(`${d}T00:00:00Z`);
        dt.setUTCDate(dt.getUTCDate() + 1);
        return dt.toISOString().replace(".000", "");
    }
    return d;
}

/** YYYY-MM-DD → unix timestamp (segundos).
 *  Con endOfDay=true devuelve el unix del día SIGUIENTE a las 00:00,
 *  por el mismo motivo que dateToIsoEnd: ranges exclusivos.
 */
function dateToUnix(d, endOfDay = false) {
    if (!d) return null;
    const dt = new Date(`${d}T00:00:00Z`);
    if (endOfDay) dt.setUTCDate(dt.getUTCDate() + 1);
    return Math.floor(dt.getTime() / 1000);
}

function todayUtc() {
    return new Date().toISOString().slice(0, 10);
}

/** Defaults: si no pasan fechas, usamos último mes hasta hoy. */
function resolveDateRange(start_date, end_date) {
    const end = end_date || todayUtc();
    let start = start_date;
    if (!start) {
        const d = new Date(end);
        d.setUTCDate(d.getUTCDate() - 30);
        start = d.toISOString().slice(0, 10);
    }
    return { start, end };
}

function fmtUsd(n) {
    if (n == null || isNaN(n)) return "$0.00";
    return `$${Number(n).toFixed(2)}`;
}

function fmtNum(n) {
    if (n == null || isNaN(n)) return "0";
    return Number(n).toLocaleString("en-US");
}

// ─── Anthropic ───

async function anthropicGet(path, params) {
    if (!ANTHROPIC_KEY) {
        throw new Error("Falta ANTHROPIC_ADMIN_KEY en env vars.");
    }
    const qs = new URLSearchParams(params).toString();
    const url = `https://api.anthropic.com${path}?${qs}`;
    const resp = await fetchWithTimeout(url, {
        method: "GET",
        headers: {
            "x-api-key": ANTHROPIC_KEY,
            "anthropic-version": "2023-06-01",
            "content-type": "application/json",
        },
    });
    if (!resp.ok) {
        const txt = await resp.text();
        throw new Error(`Anthropic API ${path} → HTTP ${resp.status}: ${txt.slice(0, 400)}`);
    }
    return resp.json();
}

async function anthropicUsage({ start, end, bucket_width = "1d" }) {
    const params = {
        starting_at: dateToIsoStart(start),
        ending_at: dateToIsoEnd(end),
        bucket_width,
        "group_by[]": "model",
    };
    return anthropicGet("/v1/organizations/usage_report/messages", params);
}

async function anthropicCost({ start, end, bucket_width = "1d" }) {
    // Anthropic NO procesa el día en curso — solo buckets completos cerrados.
    // Si end (date string YYYY-MM-DD) es hoy o futuro, recortamos a ayer
    // automáticamente para no recibir HTTP 400. El llamador puede saber esto
    // mirando el campo `note` que agregamos al summary.
    const today = todayUtc();
    let effectiveEnd = end;
    let trimmed = false;
    if (end >= today) {
        const d = new Date(`${today}T00:00:00Z`);
        d.setUTCDate(d.getUTCDate() - 1);
        effectiveEnd = d.toISOString().slice(0, 10);
        trimmed = true;
    }
    // Si después de recortar start > end, no hay rango válido
    if (start > effectiveEnd) {
        return { data: [], _note: "Anthropic no procesa el día en curso. No hay buckets completos en este rango." };
    }
    const params = {
        starting_at: dateToIsoStart(start),
        ending_at: dateToIsoEnd(effectiveEnd),
    };
    const result = await anthropicGet("/v1/organizations/cost_report", params);
    if (trimmed) {
        result._note = `Anthropic no procesa hoy. Datos hasta ${effectiveEnd} (ayer).`;
    }
    return result;
}

function summarizeAnthropicCost(data) {
    let total = 0;
    const byBucket = [];
    for (const bucket of data?.data || []) {
        let bucketTotal = 0;
        for (const r of bucket?.results || []) {
            bucketTotal += Number(r?.amount?.amount || 0);
        }
        total += bucketTotal;
        byBucket.push({
            start: bucket.starting_at,
            end: bucket.ending_at,
            cost_usd: Number(bucketTotal.toFixed(4)),
        });
    }
    return { total_usd: Number(total.toFixed(2)), by_bucket: byBucket };
}

function summarizeAnthropicUsage(data) {
    let totalInput = 0, totalOutput = 0, totalCacheRead = 0, totalCacheWrite = 0;
    const byModel = {};
    for (const bucket of data?.data || []) {
        for (const r of bucket?.results || []) {
            const model = r?.model || "unknown";
            const inT = Number(r?.uncached_input_tokens || 0);
            const outT = Number(r?.output_tokens || 0);
            const crT = Number(r?.cache_read_input_tokens || 0);
            const cwT = Number(r?.cache_creation_input_tokens || 0);
            totalInput += inT; totalOutput += outT; totalCacheRead += crT; totalCacheWrite += cwT;
            if (!byModel[model]) {
                byModel[model] = { input: 0, output: 0, cache_read: 0, cache_write: 0 };
            }
            byModel[model].input += inT;
            byModel[model].output += outT;
            byModel[model].cache_read += crT;
            byModel[model].cache_write += cwT;
        }
    }
    return {
        total: {
            input_tokens: totalInput,
            output_tokens: totalOutput,
            cache_read_input_tokens: totalCacheRead,
            cache_creation_input_tokens: totalCacheWrite,
            all_tokens: totalInput + totalOutput + totalCacheRead + totalCacheWrite,
        },
        by_model: byModel,
    };
}

// ─── OpenAI ───

async function openaiGet(path, params) {
    if (!OPENAI_KEY) {
        throw new Error("Falta OPENAI_ADMIN_KEY en env vars.");
    }
    const qs = new URLSearchParams(params).toString();
    const url = `https://api.openai.com${path}?${qs}`;
    const headers = {
        Authorization: `Bearer ${OPENAI_KEY}`,
        "content-type": "application/json",
    };
    if (OPENAI_ORG) headers["OpenAI-Organization"] = OPENAI_ORG;
    const resp = await fetchWithTimeout(url, { method: "GET", headers });
    if (!resp.ok) {
        const txt = await resp.text();
        throw new Error(`OpenAI API ${path} → HTTP ${resp.status}: ${txt.slice(0, 400)}`);
    }
    return resp.json();
}

async function openaiUsage({ start, end, bucket_width = "1d" }) {
    const params = {
        start_time: dateToUnix(start),
        end_time: dateToUnix(end, true),
        bucket_width,
        limit: 31,
        "group_by[]": "model",
    };
    return openaiGet("/v1/organization/usage/completions", params);
}

async function openaiCost({ start, end, bucket_width = "1d" }) {
    const params = {
        start_time: dateToUnix(start),
        end_time: dateToUnix(end, true),
        bucket_width,
        limit: 31,
    };
    return openaiGet("/v1/organization/costs", params);
}

function summarizeOpenaiCost(data) {
    let total = 0;
    const byBucket = [];
    for (const bucket of data?.data || []) {
        let bucketTotal = 0;
        for (const r of bucket?.results || []) {
            bucketTotal += Number(r?.amount?.value || 0);
        }
        total += bucketTotal;
        byBucket.push({
            start: bucket.start_time ? new Date(bucket.start_time * 1000).toISOString() : null,
            end: bucket.end_time ? new Date(bucket.end_time * 1000).toISOString() : null,
            cost_usd: Number(bucketTotal.toFixed(4)),
        });
    }
    return { total_usd: Number(total.toFixed(2)), by_bucket: byBucket };
}

function summarizeOpenaiUsage(data) {
    let totalInput = 0, totalOutput = 0, totalRequests = 0;
    const byModel = {};
    for (const bucket of data?.data || []) {
        for (const r of bucket?.results || []) {
            const model = r?.model || "unknown";
            const inT = Number(r?.input_tokens || 0);
            const outT = Number(r?.output_tokens || 0);
            const reqs = Number(r?.num_model_requests || 0);
            totalInput += inT; totalOutput += outT; totalRequests += reqs;
            if (!byModel[model]) byModel[model] = { input: 0, output: 0, requests: 0 };
            byModel[model].input += inT;
            byModel[model].output += outT;
            byModel[model].requests += reqs;
        }
    }
    return {
        total: {
            input_tokens: totalInput,
            output_tokens: totalOutput,
            all_tokens: totalInput + totalOutput,
            requests: totalRequests,
        },
        by_model: byModel,
    };
}

// ─── MCP server ───

const server = new Server(
    { name: "ai-billing", version: "0.1.0" },
    { capabilities: { tools: {} } },
);

server.setRequestHandler(ListToolsRequestSchema, async () => ({
    tools: [
        {
            name: "get_anthropic_usage",
            description:
                "USAR PARA: ver tokens consumidos en la API de Anthropic (Claude) por rango de fechas. Devuelve totales y breakdown por modelo (claude-opus, claude-sonnet, claude-haiku). Si no pasás fechas, usa últimos 30 días.",
            inputSchema: {
                type: "object",
                properties: {
                    start_date: { type: "string", description: "YYYY-MM-DD (default: hace 30 días)" },
                    end_date: { type: "string", description: "YYYY-MM-DD (default: hoy)" },
                    bucket_width: { type: "string", enum: ["1m", "1h", "1d"], description: "Granularidad (default 1d)" },
                },
            },
        },
        {
            name: "get_anthropic_cost",
            description:
                "USAR PARA: ver costo en USD de la API de Anthropic por rango de fechas. Más rápido que usage si solo querés el monto. Default: últimos 30 días.",
            inputSchema: {
                type: "object",
                properties: {
                    start_date: { type: "string", description: "YYYY-MM-DD" },
                    end_date: { type: "string", description: "YYYY-MM-DD" },
                    bucket_width: { type: "string", enum: ["1d"], description: "Anthropic solo soporta 1d para costos" },
                },
            },
        },
        {
            name: "get_openai_usage",
            description:
                "USAR PARA: ver tokens consumidos en la API de OpenAI (GPT) por rango de fechas. Devuelve totales y breakdown por modelo (gpt-4o, gpt-4o-mini, etc.). Solo cubre /v1/chat/completions (no embeddings/imágenes — esos tienen tools aparte).",
            inputSchema: {
                type: "object",
                properties: {
                    start_date: { type: "string", description: "YYYY-MM-DD" },
                    end_date: { type: "string", description: "YYYY-MM-DD" },
                    bucket_width: { type: "string", enum: ["1m", "1h", "1d"], description: "Granularidad" },
                },
            },
        },
        {
            name: "get_openai_cost",
            description:
                "USAR PARA: ver costo en USD de la API de OpenAI por rango de fechas. Suma todos los productos (completions, embeddings, audio, imágenes). Default: últimos 30 días.",
            inputSchema: {
                type: "object",
                properties: {
                    start_date: { type: "string", description: "YYYY-MM-DD" },
                    end_date: { type: "string", description: "YYYY-MM-DD" },
                    bucket_width: { type: "string", enum: ["1d"], description: "Granularidad (1d)" },
                },
            },
        },
        {
            name: "get_combined_spend",
            description:
                "USAR PARA: ver el gasto TOTAL en APIs de IA (Anthropic + OpenAI sumados) en USD. Devuelve la distribución porcentual entre ambos proveedores. Ideal para preguntas tipo '¿cuánto gasté este mes en APIs?' o 'compará gasto Claude vs GPT'.",
            inputSchema: {
                type: "object",
                properties: {
                    start_date: { type: "string", description: "YYYY-MM-DD" },
                    end_date: { type: "string", description: "YYYY-MM-DD" },
                },
            },
        },
        {
            name: "get_today_spend",
            description:
                "USAR PARA: atajo de gasto del día de HOY (UTC) en ambos proveedores. Equivale a get_combined_spend con start=end=hoy.",
            inputSchema: { type: "object", properties: {} },
        },
    ],
}));

server.setRequestHandler(CallToolRequestSchema, async (request) => {
    const { name, arguments: args } = request.params;
    try {
        if (name === "get_anthropic_usage") {
            const { start_date, end_date, bucket_width } = args || {};
            const { start, end } = resolveDateRange(start_date, end_date);
            const raw = await anthropicUsage({ start, end, bucket_width });
            const summary = summarizeAnthropicUsage(raw);
            const result = { proveedor: "Anthropic", rango: `${start} → ${end}`, ...summary };
            return { content: [{ type: "text", text: JSON.stringify(result, null, 2) }] };
        }

        if (name === "get_anthropic_cost") {
            const { start_date, end_date, bucket_width } = args || {};
            const { start, end } = resolveDateRange(start_date, end_date);
            const raw = await anthropicCost({ start, end, bucket_width });
            const summary = summarizeAnthropicCost(raw);
            const result = {
                proveedor: "Anthropic",
                rango: `${start} → ${end}`,
                total_usd: summary.total_usd,
                desglose_diario: summary.by_bucket,
            };
            if (raw._note) result.nota = raw._note;
            return { content: [{ type: "text", text: JSON.stringify(result, null, 2) }] };
        }

        if (name === "get_openai_usage") {
            const { start_date, end_date, bucket_width } = args || {};
            const { start, end } = resolveDateRange(start_date, end_date);
            const raw = await openaiUsage({ start, end, bucket_width });
            const summary = summarizeOpenaiUsage(raw);
            const result = { proveedor: "OpenAI", rango: `${start} → ${end}`, ...summary };
            return { content: [{ type: "text", text: JSON.stringify(result, null, 2) }] };
        }

        if (name === "get_openai_cost") {
            const { start_date, end_date, bucket_width } = args || {};
            const { start, end } = resolveDateRange(start_date, end_date);
            const raw = await openaiCost({ start, end, bucket_width });
            const summary = summarizeOpenaiCost(raw);
            const result = {
                proveedor: "OpenAI",
                rango: `${start} → ${end}`,
                total_usd: summary.total_usd,
                desglose_diario: summary.by_bucket,
            };
            return { content: [{ type: "text", text: JSON.stringify(result, null, 2) }] };
        }

        if (name === "get_combined_spend") {
            const { start_date, end_date } = args || {};
            const { start, end } = resolveDateRange(start_date, end_date);

            const [aRaw, oRaw] = await Promise.allSettled([
                anthropicCost({ start, end }),
                openaiCost({ start, end }),
            ]);

            const aCost = aRaw.status === "fulfilled" ? summarizeAnthropicCost(aRaw.value).total_usd : 0;
            const oCost = oRaw.status === "fulfilled" ? summarizeOpenaiCost(oRaw.value).total_usd : 0;
            const total = Number((aCost + oCost).toFixed(2));
            const aPct = total > 0 ? Number(((aCost / total) * 100).toFixed(1)) : 0;
            const oPct = total > 0 ? Number(((oCost / total) * 100).toFixed(1)) : 0;

            const result = {
                rango: `${start} → ${end}`,
                total_usd: total,
                anthropic_usd: aCost,
                openai_usd: oCost,
                anthropic_pct: aPct,
                openai_pct: oPct,
                resumen: `Total ${fmtUsd(total)} (Anthropic ${fmtUsd(aCost)} · ${aPct}% | OpenAI ${fmtUsd(oCost)} · ${oPct}%)`,
                errores: {
                    anthropic: aRaw.status === "rejected" ? String(aRaw.reason).slice(0, 200) : null,
                    openai: oRaw.status === "rejected" ? String(oRaw.reason).slice(0, 200) : null,
                },
            };
            return { content: [{ type: "text", text: JSON.stringify(result, null, 2) }] };
        }

        if (name === "get_today_spend") {
            const today = todayUtc();
            const [aRaw, oRaw] = await Promise.allSettled([
                anthropicCost({ start: today, end: today }),
                openaiCost({ start: today, end: today }),
            ]);
            const aCost = aRaw.status === "fulfilled" ? summarizeAnthropicCost(aRaw.value).total_usd : 0;
            const oCost = oRaw.status === "fulfilled" ? summarizeOpenaiCost(oRaw.value).total_usd : 0;
            const total = Number((aCost + oCost).toFixed(2));
            const result = {
                fecha: today,
                total_usd_hoy: total,
                anthropic_usd: aCost,
                openai_usd: oCost,
                nota_anthropic: (
                    aRaw.status === "fulfilled" && aRaw.value._note
                        ? aRaw.value._note
                        : "Anthropic procesa con 24h de delay — el dato de hoy probablemente esté en 0 hasta mañana."
                ),
                resumen: `Hoy: ${fmtUsd(total)} (Anthropic ${fmtUsd(aCost)} | OpenAI ${fmtUsd(oCost)})`,
                errores: {
                    anthropic: aRaw.status === "rejected" ? String(aRaw.reason).slice(0, 200) : null,
                    openai: oRaw.status === "rejected" ? String(oRaw.reason).slice(0, 200) : null,
                },
            };
            return { content: [{ type: "text", text: JSON.stringify(result, null, 2) }] };
        }

        throw new Error(`Tool desconocida: ${name}`);
    } catch (err) {
        return {
            content: [{ type: "text", text: `Error: ${err.message}` }],
            isError: true,
        };
    }
});

const transport = new StdioServerTransport();
await server.connect(transport);
