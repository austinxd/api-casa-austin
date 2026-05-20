#!/usr/bin/env node
/**
 * MCP server de Casa Austin: tools de disponibilidad/precios (públicos) +
 * análisis de conversaciones del chatbot Austin Assistant (autenticadas).
 *
 * Tools públicas (no requieren auth):
 *   check_availability(check_in, check_out)
 *   get_pricing(check_in, check_out, guests, property_slug?)
 *   list_properties()
 *
 * Tools privadas (requieren CASA_AUSTIN_ADMIN_USERNAME + CASA_AUSTIN_ADMIN_PASSWORD):
 *   get_chat_sessions(date_from?, date_to?, status?, limit?)
 *   get_chat_session(session_id)
 *   get_chat_analytics(period?)
 *   get_funnel(month, year)
 *   get_unresolved_questions(limit?)
 *   get_frequent_questions(limit?)
 *   get_followup_opportunities()
 *
 * Auth: hace login con username/password al primer call autenticado, guarda
 * access+refresh en memoria. Si access expira, intenta refresh; si refresh
 * expira, re-login.
 */
import { Server } from "@modelcontextprotocol/sdk/server/index.js";
import { StdioServerTransport } from "@modelcontextprotocol/sdk/server/stdio.js";
import {
    CallToolRequestSchema,
    ListToolsRequestSchema,
} from "@modelcontextprotocol/sdk/types.js";

const API_BASE = process.env.CASA_AUSTIN_API_BASE || "https://api.casaaustin.pe";
const ADMIN_USERNAME = process.env.CASA_AUSTIN_ADMIN_USERNAME || "";
const ADMIN_PASSWORD = process.env.CASA_AUSTIN_ADMIN_PASSWORD || "";

// ─── Auth state (en memoria; el proceso vive lo que dure Claude Desktop) ───
let tokenAccess = null;
let tokenRefresh = null;

// ─── fetch con timeout (AbortController) ───
// Sin esto, si el backend cuelga (HA remoto caído, red lenta) el MCP queda
// esperando indefinidamente y Claude Desktop queda "colgado". El timeout
// rompe el fetch y deja que el llamador decida el siguiente paso.
const DEFAULT_TIMEOUT_MS = 15_000;
const HA_DEVICES_TIMEOUT_MS = 35_000; // HA en frío puede tardar ~30s

async function fetchWithTimeout(url, opts = {}, timeoutMs = DEFAULT_TIMEOUT_MS) {
    const controller = new AbortController();
    const timer = setTimeout(() => controller.abort(), timeoutMs);
    try {
        return await fetch(url, { ...opts, signal: controller.signal });
    } catch (err) {
        if (err.name === "AbortError") {
            throw new Error(
                `Timeout (${timeoutMs}ms) llamando ${url.replace(API_BASE, "")} — backend no respondió a tiempo.`,
            );
        }
        throw err;
    } finally {
        clearTimeout(timer);
    }
}

// ─── Caches locales del MCP ───
// El endpoint /ha/admin/devices/ tarda ~12s en frío (Home Assistant remoto
// responde lento). El backend tiene cache de 8s. Agregamos cache local de
// 30s para amortizar más todavía y absorber comandos rápidos consecutivos.
const HA_DEVICES_TTL_MS = 30_000;
const PROPERTIES_TTL_MS = 5 * 60_000; // properties cambian raro
let haDevicesCache = { data: null, expiresAt: 0, inflight: null };
let propertiesCache = { data: null, expiresAt: 0, inflight: null };

function _now() { return Date.now(); }

async function getHaDevicesCached(forceRefresh = false) {
    if (!forceRefresh && haDevicesCache.data && haDevicesCache.expiresAt > _now()) {
        return haDevicesCache.data;
    }
    // Si hay un fetch en curso, esperamos al mismo (evita stampede)
    if (haDevicesCache.inflight) return haDevicesCache.inflight;
    haDevicesCache.inflight = (async () => {
        try {
            const data = await authedJson(`/api/v1/ha/admin/devices/`, { _timeoutMs: HA_DEVICES_TIMEOUT_MS });
            haDevicesCache.data = data;
            haDevicesCache.expiresAt = _now() + HA_DEVICES_TTL_MS;
            return data;
        } finally {
            haDevicesCache.inflight = null;
        }
    })();
    return haDevicesCache.inflight;
}

function invalidateHaDevicesCache() {
    haDevicesCache.data = null;
    haDevicesCache.expiresAt = 0;
}

async function getPropertiesCached() {
    if (propertiesCache.data && propertiesCache.expiresAt > _now()) {
        return propertiesCache.data;
    }
    if (propertiesCache.inflight) return propertiesCache.inflight;
    propertiesCache.inflight = (async () => {
        try {
            const resp = await fetchWithTimeout(`${API_BASE}/api/v1/property/`, {
                headers: { Accept: "application/json" },
            });
            if (!resp.ok) throw new Error(`Properties HTTP ${resp.status}`);
            const data = await resp.json();
            const items = data.results || data || [];
            propertiesCache.data = Array.isArray(items) ? items : [];
            propertiesCache.expiresAt = _now() + PROPERTIES_TTL_MS;
            return propertiesCache.data;
        } finally {
            propertiesCache.inflight = null;
        }
    })();
    return propertiesCache.inflight;
}

/** Normaliza para fuzzy match: lowercase + sin tildes. */
function _norm(s) {
    return (s || "")
        .toLowerCase()
        .normalize("NFD")
        .replace(/[̀-ͯ]/g, "")
        .trim();
}

async function loginFresh() {
    if (!ADMIN_USERNAME || !ADMIN_PASSWORD) {
        throw new Error(
            "Falta configurar CASA_AUSTIN_ADMIN_USERNAME y CASA_AUSTIN_ADMIN_PASSWORD en el MCP config (claude_desktop_config.json).",
        );
    }
    // El backend de Casa Austin usa `email` como USERNAME_FIELD del modelo
    // CustomUser. Mandamos ambos campos por compatibilidad.
    const resp = await fetchWithTimeout(`${API_BASE}/api/v1/login/`, {
        method: "POST",
        headers: { "Content-Type": "application/json", Accept: "application/json" },
        body: JSON.stringify({
            email: ADMIN_USERNAME,
            username: ADMIN_USERNAME,
            password: ADMIN_PASSWORD,
        }),
    }, 10_000);
    if (!resp.ok) {
        const txt = await resp.text();
        throw new Error(`Login falló (HTTP ${resp.status}): ${txt.slice(0, 300)}`);
    }
    const data = await resp.json();
    tokenAccess = data.access;
    tokenRefresh = data.refresh;
}

async function refreshAccess() {
    if (!tokenRefresh) {
        await loginFresh();
        return;
    }
    const resp = await fetchWithTimeout(`${API_BASE}/api/v1/token/refresh/`, {
        method: "POST",
        headers: { "Content-Type": "application/json", Accept: "application/json" },
        body: JSON.stringify({ refresh: tokenRefresh }),
    }, 10_000);
    if (!resp.ok) {
        // refresh inválido → re-login limpio
        tokenAccess = null;
        tokenRefresh = null;
        await loginFresh();
        return;
    }
    const data = await resp.json();
    tokenAccess = data.access;
    if (data.refresh) tokenRefresh = data.refresh;
}

async function authedFetch(path, opts = {}) {
    if (!tokenAccess) await loginFresh();
    const url = path.startsWith("http") ? path : `${API_BASE}${path}`;
    // _timeoutMs es una opción interna nuestra — la extraemos antes de pasarle
    // las opts a fetch para no contaminar la request.
    const { _timeoutMs, ...fetchOpts } = opts;
    const timeoutMs = _timeoutMs || DEFAULT_TIMEOUT_MS;
    const doFetch = () =>
        fetchWithTimeout(url, {
            ...fetchOpts,
            headers: {
                Accept: "application/json",
                ...(fetchOpts.headers || {}),
                Authorization: `Bearer ${tokenAccess}`,
            },
        }, timeoutMs);
    let resp = await doFetch();
    if (resp.status === 401) {
        await refreshAccess();
        resp = await doFetch();
    }
    return resp;
}

async function authedJson(path, opts) {
    const resp = await authedFetch(path, opts);
    if (!resp.ok) {
        const txt = await resp.text();
        throw new Error(`API ${path} → HTTP ${resp.status}: ${txt.slice(0, 300)}`);
    }
    return resp.json();
}

// ─── Públicos: pricing ───
function pricingUrl({ check_in, check_out, guests }) {
    const params = new URLSearchParams({
        check_in_date: String(check_in),
        check_out_date: String(check_out),
        guests: String(guests),
    });
    return `${API_BASE}/api/v1/properties/calculate-pricing/?${params.toString()}`;
}

async function publicJson(url) {
    const resp = await fetchWithTimeout(url, {
        method: "GET",
        headers: { Accept: "application/json" },
    });
    const data = await resp.json();
    if (data && data.error && data.error !== 0) {
        const msg = data.error_message || data.detail || "sin mensaje";
        throw new Error(`Error de la API (code ${data.error}): ${msg}`);
    }
    return data;
}

// ─── MCP Server ───
const server = new Server(
    { name: "casa-austin", version: "0.3.0" },
    { capabilities: { tools: {} } },
);

server.setRequestHandler(ListToolsRequestSchema, async () => ({
    tools: [
        // ── Disponibilidad / precios (públicos) ──
        {
            name: "check_availability",
            description:
                "USAR PARA: saber si hay casas libres en fechas FUTURAS sin importar precio ni cantidad de huéspedes. Devuelve la lista de casas disponibles con su capacidad máxima. NO usar para estadísticas mensuales operacionales (eso es get_monthly_operations) ni para cotizar precios (eso es get_pricing).",
            inputSchema: {
                type: "object",
                properties: {
                    check_in: { type: "string", description: "Check-in YYYY-MM-DD." },
                    check_out: { type: "string", description: "Check-out YYYY-MM-DD." },
                },
                required: ["check_in", "check_out"],
            },
        },
        {
            name: "get_pricing",
            description:
                "USAR PARA: cotizar PRECIOS de estadías futuras en Casa Austin para fechas + cantidad de huéspedes específicos. Devuelve precio total en soles y dólares por cada casa disponible, con descuentos. NO usar para estadísticas pasadas (eso es get_monthly_operations o get_yearly_revenue).",
            inputSchema: {
                type: "object",
                properties: {
                    check_in: { type: "string", description: "Check-in YYYY-MM-DD." },
                    check_out: { type: "string", description: "Check-out YYYY-MM-DD." },
                    guests: { type: "number", description: "Cantidad de huéspedes (mín 1)." },
                    property_slug: {
                        type: "string",
                        description: "Opcional: casa-austin-1, casa-austin-2, casa-austin-3 o casa-austin-4.",
                    },
                },
                required: ["check_in", "check_out", "guests"],
            },
        },
        {
            name: "list_properties",
            description:
                "Lista las 4 casas de Casa Austin: nombre, slug, capacidad máxima, dormitorios, baños, precio mínimo.",
            inputSchema: { type: "object", properties: {} },
        },

        // ── Análisis del chatbot Austin Assistant (autenticadas) ──
        {
            name: "get_chat_sessions",
            description:
                "Lista sesiones de conversación del chatbot Austin Assistant en WhatsApp. Permite filtrar por rango de fechas, estado y limitar resultados. Devuelve sesiones con wa_id, nombre, estado, total de mensajes y última actividad. Usar para preguntas tipo '¿cuántas conversaciones hubo esta semana?' o 'dame las últimas 20 conversaciones'.",
            inputSchema: {
                type: "object",
                properties: {
                    date_from: { type: "string", description: "Fecha desde YYYY-MM-DD (opcional)." },
                    date_to: { type: "string", description: "Fecha hasta YYYY-MM-DD (opcional)." },
                    status: {
                        type: "string",
                        description: "Filtrar por estado: active, ai_paused, closed, escalated.",
                    },
                    limit: { type: "number", description: "Cantidad máxima (default 50, max 200)." },
                },
            },
        },
        {
            name: "get_chat_session",
            description:
                "Detalle de una sesión específica del chatbot, incluyendo TODOS los mensajes intercambiados. Usar cuando el usuario menciona un session_id concreto o quiere analizar una conversación puntual.",
            inputSchema: {
                type: "object",
                properties: {
                    session_id: { type: "string", description: "UUID de la sesión." },
                },
                required: ["session_id"],
            },
        },
        {
            name: "get_chat_analytics",
            description:
                "Estadísticas agregadas del chatbot: volumen de conversaciones, tiempo promedio de respuesta del AI, total de mensajes, tasa de escalamiento a humano, etc.",
            inputSchema: {
                type: "object",
                properties: {
                    period: {
                        type: "string",
                        description: "Período: today, week, month, year (opcional).",
                    },
                },
            },
        },
        {
            name: "get_funnel",
            description:
                "Funnel de conversión del chatbot para un mes: conversaciones iniciadas → cotización → magic link generado → magic link abierto → reserva creada. Útil para analizar dónde se cae la conversión.",
            inputSchema: {
                type: "object",
                properties: {
                    month: { type: "number", description: "Mes 1-12." },
                    year: { type: "number", description: "Año (ej: 2026)." },
                },
                required: ["month", "year"],
            },
        },
        {
            name: "get_unresolved_questions",
            description:
                "Preguntas que el bot NO pudo resolver (escaladas a humano o sin respuesta clara). Útil para descubrir gaps de conocimiento del bot y mejorar su system prompt o contenido.",
            inputSchema: {
                type: "object",
                properties: {
                    limit: { type: "number", description: "Cantidad (default 50)." },
                },
            },
        },
        {
            name: "get_frequent_questions",
            description:
                "Preguntas frecuentes detectadas por análisis de patrones en las conversaciones. Útil para identificar qué temas dominan y crear FAQs o mejorar el bot.",
            inputSchema: {
                type: "object",
                properties: {
                    limit: { type: "number", description: "Cantidad (default 50)." },
                },
            },
        },
        {
            name: "get_followup_opportunities",
            description:
                "Oportunidades de seguimiento: clientes que cotizaron por el bot pero no reservaron, candidatos para reactivación. Devuelve wa_id, último mensaje, fecha de cotización, propiedad consultada, etc.",
            inputSchema: { type: "object", properties: {} },
        },

        // ── Operaciones (ocupación, ingresos, comparación YoY) ──
        {
            name: "get_monthly_operations",
            description:
                "USAR PARA: estadísticas operacionales de un MES específico — noches LIBRES por casa, noches ocupadas, facturación total, dinero por cobrar, mejores vendedores, puntos canjeados. Devuelve TODO en una sola consulta. NO usar esta tool para precios futuros (eso es get_pricing) ni para disponibilidad presente sin contexto operacional (eso es check_availability).",
            inputSchema: {
                type: "object",
                properties: {
                    month: { type: "number", description: "Mes 1-12." },
                    year: { type: "number", description: "Año, ej: 2026." },
                },
                required: ["month", "year"],
            },
        },
        {
            name: "get_yearly_revenue",
            description:
                "USAR PARA: facturación MENSUAL de todo un año (12 meses). Devuelve un objeto {enero: monto, febrero: monto, ...} en soles. Útil para ver evolución anual o sumar año completo.",
            inputSchema: {
                type: "object",
                properties: {
                    year: { type: "number", description: "Año, ej: 2026." },
                },
                required: ["year"],
            },
        },
        {
            name: "get_active_today",
            description:
                "USAR PARA: saber AHORA MISMO qué casas están ocupadas (con huéspedes adentro) y cuáles tienen check-in agendado para hoy. Considera horarios reales (check-in 12 PM, check-out 11 AM hora Perú). Devuelve total ocupadas, lista de reservas activas con casa+cliente+huéspedes, y check-ins programados para el día. NO usar para mes completo (eso es get_monthly_operations).",
            inputSchema: { type: "object", properties: {} },
        },
        // ── Home Assistant (control de dispositivos en las casas) ──
        {
            name: "ha_list_devices",
            description:
                "USAR PARA: listar dispositivos de Home Assistant en las casas (luces, switches, climate, sensores). Permite filtrar por casa (Casa Austin 1-4) o por tipo. Devuelve friendly_name, ubicación dentro de la casa, tipo y estado actual (on/off). Usar como exploración antes de controlar, o cuando el usuario pregunta '¿qué dispositivos hay en X casa?'.",
            inputSchema: {
                type: "object",
                properties: {
                    property: {
                        type: "string",
                        description: "Filtrar por casa: nombre ('Casa Austin 3') o slug ('casa-austin-3'). Opcional.",
                    },
                    device_type: {
                        type: "string",
                        description: "Filtrar por tipo: light, switch, climate, sensor, etc. Opcional.",
                    },
                },
            },
        },
        {
            name: "ha_control_device",
            description:
                "USAR PARA: prender/apagar/togglear un dispositivo de Home Assistant. Acepta búsqueda en lenguaje natural (`query`) — no necesitas el UUID. Ej: query='luces del garaje casa 3' busca y matchea el dispositivo más relevante. Soporta brightness (0-255) para luces y temperature para climate. Si la búsqueda matchea múltiples, devuelve la lista para que elijas más específico.",
            inputSchema: {
                type: "object",
                properties: {
                    query: {
                        type: "string",
                        description: "Descripción del dispositivo en lenguaje natural. Ej: 'luces sala casa austin 3', 'camarotes 2do piso', 'apagar todo casa 4'. El MCP busca por friendly_name + location + property_name.",
                    },
                    device_id: {
                        type: "string",
                        description: "UUID exacto del dispositivo (alternativa a query, para mayor precisión).",
                    },
                    action: {
                        type: "string",
                        enum: ["turn_on", "turn_off", "toggle"],
                        description: "Acción: turn_on (prender), turn_off (apagar), toggle (cambiar estado).",
                    },
                    brightness: {
                        type: "number",
                        description: "Brillo 0-255 (solo para device_type=light).",
                    },
                    temperature: {
                        type: "number",
                        description: "Temperatura en °C (solo para device_type=climate).",
                    },
                },
                required: ["action"],
            },
        },
        {
            name: "ha_test_connection",
            description:
                "USAR PARA: verificar que la conexión con Home Assistant funciona. Devuelve si está conectado, cantidad total de entidades y URL base. Útil cuando algún control falla y queremos confirmar si HA está vivo.",
            inputSchema: { type: "object", properties: {} },
        },

        {
            name: "compare_months_yoy",
            description:
                "USAR PARA: comparar mismo mes en dos años (year-over-year). Hace 2 llamadas internas y devuelve ambos meses lado a lado: noches ocupadas, facturación, etc. Útil para preguntas tipo '¿cómo viene mayo 2026 vs mayo 2025?'.",
            inputSchema: {
                type: "object",
                properties: {
                    month: { type: "number", description: "Mes 1-12." },
                    year: { type: "number", description: "Año actual a comparar." },
                    vs_year: {
                        type: "number",
                        description: "Año a comparar contra (default: year - 1).",
                    },
                },
                required: ["month", "year"],
            },
        },
    ],
}));

server.setRequestHandler(CallToolRequestSchema, async (req) => {
    const { name, arguments: args } = req.params;
    try {
        // ──────── Tools públicas ────────
        if (name === "check_availability") {
            const { check_in, check_out } = args || {};
            if (!check_in || !check_out) {
                throw new Error("Faltan check_in y check_out.");
            }
            const data = await publicJson(pricingUrl({ check_in, check_out, guests: 1 }));
            const d = data.data || {};
            const summary = {
                check_in: d.check_in_date || check_in,
                check_out: d.check_out_date || check_out,
                total_nights: d.total_nights,
                casas_disponibles: d.totalCasasDisponibles ?? (d.properties || []).length,
                casas: (d.properties || []).map((p) => ({
                    name: p.property_name,
                    slug: p.property_slug,
                    capacity_max: p.capacity_max ?? null,
                })),
            };
            return { content: [{ type: "text", text: JSON.stringify(summary, null, 2) }] };
        }

        if (name === "get_pricing") {
            const { check_in, check_out, guests, property_slug } = args || {};
            if (!check_in || !check_out || guests == null) {
                throw new Error("Faltan check_in, check_out o guests.");
            }
            const data = await publicJson(pricingUrl({ check_in, check_out, guests }));
            const d = data.data || {};
            let props = d.properties || [];
            if (property_slug) {
                props = props.filter((p) => p.property_slug === property_slug);
                if (props.length === 0) {
                    return {
                        content: [{
                            type: "text",
                            text: `Sin disponibilidad para "${property_slug}" en esas fechas para ${guests} huéspedes (o slug inválido). Slugs válidos: casa-austin-1..4.`,
                        }],
                    };
                }
            }
            const result = {
                check_in: d.check_in_date || check_in,
                check_out: d.check_out_date || check_out,
                guests: d.guests || guests,
                total_nights: d.total_nights,
                exchange_rate: d.exchange_rate,
                casas_disponibles: property_slug ? props.length : (d.totalCasasDisponibles ?? props.length),
                cotizaciones: props.map((p) => ({
                    casa: p.property_name,
                    slug: p.property_slug,
                    precio_total_sol: p.final_price_sol,
                    precio_total_usd: p.final_price_usd,
                    precio_por_noche_sol: p.base_price_sol,
                    precio_por_noche_usd: p.base_price_usd,
                    huesped_extra_total_sol: p.extra_person_total_sol,
                    huesped_extra_total_usd: p.extra_person_total_usd,
                    descuento_sol: p.discount_amount_sol,
                    descuento_usd: p.discount_amount_usd,
                    descuento_tipo: p.discount_type,
                    capacidad_max: p.capacity_max,
                })),
            };
            return { content: [{ type: "text", text: JSON.stringify(result, null, 2) }] };
        }

        if (name === "list_properties") {
            // Aprovecha el cache local de properties (5min TTL) ya que la lista cambia muy raro.
            const items = await getPropertiesCached();
            const minimal = Array.isArray(items)
                ? items.map((p) => ({
                      name: p.name,
                      slug: p.slug,
                      capacity_max: p.capacity_max,
                      dormitorios: p.dormitorios,
                      banos: p.banos,
                      precio_desde: p.precio_desde,
                  }))
                : data;
            return { content: [{ type: "text", text: JSON.stringify(minimal, null, 2) }] };
        }

        // ──────── Tools privadas (chatbot analysis) ────────
        if (name === "get_chat_sessions") {
            const { date_from, date_to, status, limit } = args || {};
            const params = new URLSearchParams();
            if (date_from) params.append("date_from", date_from);
            if (date_to) params.append("date_to", date_to);
            if (status) params.append("status", status);
            params.append("page_size", String(Math.min(Math.max(limit || 50, 1), 200)));
            const data = await authedJson(`/api/v1/chatbot/sessions/?${params}`);
            return { content: [{ type: "text", text: JSON.stringify(data, null, 2) }] };
        }

        if (name === "get_chat_session") {
            const { session_id } = args || {};
            if (!session_id) throw new Error("Falta session_id.");
            const [session, messages] = await Promise.all([
                authedJson(`/api/v1/chatbot/sessions/${session_id}/`),
                authedJson(`/api/v1/chatbot/sessions/${session_id}/messages/`),
            ]);
            return { content: [{ type: "text", text: JSON.stringify({ session, messages }, null, 2) }] };
        }

        if (name === "get_chat_analytics") {
            const { period } = args || {};
            const params = new URLSearchParams();
            if (period) params.append("period", period);
            const data = await authedJson(`/api/v1/chatbot/analytics/?${params}`);
            return { content: [{ type: "text", text: JSON.stringify(data, null, 2) }] };
        }

        if (name === "get_funnel") {
            const { month, year } = args || {};
            if (!month || !year) throw new Error("Faltan month y year.");
            const params = new URLSearchParams({ month: String(month), year: String(year) });
            const data = await authedJson(`/api/v1/chatbot/funnel/?${params}`);
            return { content: [{ type: "text", text: JSON.stringify(data, null, 2) }] };
        }

        if (name === "get_unresolved_questions") {
            const { limit } = args || {};
            const params = new URLSearchParams({ page_size: String(Math.min(Math.max(limit || 50, 1), 200)) });
            const data = await authedJson(`/api/v1/chatbot/unresolved-questions/?${params}`);
            return { content: [{ type: "text", text: JSON.stringify(data, null, 2) }] };
        }

        if (name === "get_frequent_questions") {
            const { limit } = args || {};
            const params = new URLSearchParams({ page_size: String(Math.min(Math.max(limit || 50, 1), 200)) });
            const data = await authedJson(`/api/v1/chatbot/frequent-questions/?${params}`);
            return { content: [{ type: "text", text: JSON.stringify(data, null, 2) }] };
        }

        if (name === "get_followup_opportunities") {
            const data = await authedJson(`/api/v1/chatbot/followups/`);
            return { content: [{ type: "text", text: JSON.stringify(data, null, 2) }] };
        }

        // ──────── Operaciones ────────
        if (name === "get_monthly_operations") {
            const { month, year } = args || {};
            if (!month || !year) throw new Error("Faltan month y year.");
            const params = new URLSearchParams({ month: String(month), year: String(year) });
            const data = await authedJson(`/api/v1/dashboard/?${params}`);
            // Normalizar free_days_per_house: viene como array de objetos
            // con keys diferentes. Lo reorganizamos por casa con campos claros.
            const porCasa = (data.free_days_per_house || []).map((h) => ({
                casa: h.casa,
                noches_libres: h.dias_libres,
                noches_ocupadas: h.dias_ocupada,
                noches_mantenimiento: h.noches_man,
                ingresos_facturados_sol: h.dinero_facturado,
                ingresos_por_cobrar_sol: h.dinero_por_cobrar,
            }));
            const summary = {
                month,
                year,
                por_casa: porCasa,
                total: {
                    noches_libres: data.free_days_total,
                    noches_ocupadas: data.ocuppied_days_total,
                    noches_mantenimiento: data.noches_man,
                    facturacion_sol: data.dinero_total_facturado,
                    por_cobrar_sol: data.dinero_por_cobrar,
                    puntos_canjeados: data.puntos_canjeados,
                },
                top_vendedores: (data.best_sellers || [])
                    .map((v) => ({
                        nombre: `${v.nombre || ""} ${v.apellido || ""}`.trim(),
                        ventas_soles: v.ventas_soles,
                    }))
                    .filter((v) => parseFloat(v.ventas_soles || 0) > 0)
                    .sort((a, b) => parseFloat(b.ventas_soles || 0) - parseFloat(a.ventas_soles || 0))
                    .slice(0, 5),
            };
            return { content: [{ type: "text", text: JSON.stringify(summary, null, 2) }] };
        }

        if (name === "get_yearly_revenue") {
            const { year } = args || {};
            if (!year) throw new Error("Falta year.");
            const params = new URLSearchParams({ year: String(year) });
            const data = await authedJson(`/api/v1/profit-resume/?${params}`);
            return { content: [{ type: "text", text: JSON.stringify({ year, facturacion_mensual_sol: data }, null, 2) }] };
        }

        if (name === "get_active_today") {
            const data = await authedJson(`/api/v1/active/`);
            const ocupadas = (data.active_reservations || []).map((r) => ({
                casa: r.property_name || r.property,
                cliente: r.client_name,
                huespedes: r.guests,
                check_in: r.check_in_date,
                check_out: r.check_out_date,
                origin: r.origin,
            }));
            const checkInsHoy = (data.check_in_today || []).map((r) => ({
                casa: r.property,
                cliente: r.client_name,
                huespedes: r.guests,
                check_in_time: r.checkin_time,
                phone: r.phone,
                origin: r.origin,
            }));
            const summary = {
                ahora: new Date().toLocaleString("es-PE", { timeZone: "America/Lima" }),
                casas_ocupadas_ahora: ocupadas.length,
                casas_con_checkin_hoy: checkInsHoy.length,
                reservas_activas: ocupadas,
                checkins_hoy: checkInsHoy,
            };
            return { content: [{ type: "text", text: JSON.stringify(summary, null, 2) }] };
        }

        // ──────── Home Assistant ────────

        if (name === "ha_test_connection") {
            const data = await authedJson(`/api/v1/ha/admin/test/`);
            return { content: [{ type: "text", text: JSON.stringify(data, null, 2) }] };
        }

        if (name === "ha_list_devices") {
            const { property, device_type } = args || {};
            // Usar caché local (TTL 30s). El endpoint en frío tarda ~12s.
            const data = await getHaDevicesCached();
            let devices = data.devices || [];

            // Filtrar localmente (no necesitamos ir al server otra vez)
            if (property) {
                const q = _norm(property);
                devices = devices.filter((d) => {
                    const name = _norm(d.property_name);
                    return name === q || name.includes(q) || q.includes(name);
                });
            }
            if (device_type) {
                const dt = device_type.toLowerCase();
                devices = devices.filter((d) => (d.device_type || "").toLowerCase() === dt);
            }

            const summary = {
                total: devices.length,
                has_active_reservation: data.has_active_reservation,
                temperature_pool_active: data.temperature_pool_active,
                cache_age_seconds: Math.max(
                    0,
                    Math.round((HA_DEVICES_TTL_MS - (haDevicesCache.expiresAt - _now())) / 1000),
                ),
                devices: devices.map((d) => ({
                    id: d.id,
                    nombre: d.friendly_name,
                    casa: d.property_name,
                    ubicacion: d.location,
                    tipo: d.device_type,
                    estado: d.current_state,
                    entity_id: d.entity_id,
                })),
            };
            return { content: [{ type: "text", text: JSON.stringify(summary, null, 2) }] };
        }

        if (name === "ha_control_device") {
            const { query, device_id, action, brightness, temperature } = args || {};
            if (!action) throw new Error("Falta action (turn_on, turn_off o toggle).");

            let targetId = device_id;
            let candidates = [];

            // Si no vino UUID, buscar por query fuzzy en la lista CACHEADA.
            if (!targetId) {
                if (!query) throw new Error("Pasá query o device_id.");
                const list = await getHaDevicesCached();
                const all = list.devices || [];
                const tokens = _norm(query).split(/\s+/).filter((t) => t.length > 0);

                // Scoring mejorado:
                //  - +3 si token aparece exacto como palabra en friendly_name
                //  - +2 si aparece como substring en friendly_name o location
                //  - +1 si aparece en property_name o entity_id
                //  - bonus si el conjunto matchea la ubicación completa
                const scored = all
                    .map((d) => {
                        const fn = _norm(d.friendly_name);
                        const loc = _norm(d.location);
                        const prop = _norm(d.property_name);
                        const ent = _norm(d.entity_id);
                        const fnWords = new Set(fn.split(/\s+/));
                        let score = 0;
                        for (const t of tokens) {
                            if (fnWords.has(t)) score += 3;
                            else if (fn.includes(t)) score += 2;
                            else if (loc.includes(t)) score += 2;
                            else if (prop.includes(t)) score += 1;
                            else if (ent.includes(t)) score += 1;
                        }
                        return { device: d, score };
                    })
                    .filter((x) => x.score > 0)
                    .sort((a, b) => b.score - a.score);

                if (scored.length === 0) {
                    return {
                        content: [{
                            type: "text",
                            text: `No encontré ningún dispositivo que coincida con "${query}". Probá con otra descripción o lista todos con ha_list_devices.`,
                        }],
                        isError: true,
                    };
                }

                // Solo es ambiguo si el top score se repite en 2+ candidatos.
                // Si el top está claramente por delante (diferencia ≥ 2), va directo.
                const top = scored[0];
                const sameScoreCount = scored.filter((x) => x.score === top.score).length;
                if (sameScoreCount >= 2 && top.score - (scored[sameScoreCount]?.score || 0) <= 1) {
                    candidates = scored
                        .filter((x) => x.score === top.score)
                        .slice(0, 5)
                        .map((x) => x.device);
                    return {
                        content: [{
                            type: "text",
                            text:
                                `Tu búsqueda "${query}" matchea varios dispositivos con la misma relevancia. Sé más específico o pasá el device_id exacto:\n\n` +
                                candidates
                                    .map(
                                        (d, i) =>
                                            `${i + 1}. ${d.friendly_name} | ${d.property_name} | ${d.location} | estado: ${d.current_state}\n   id: ${d.id}`,
                                    )
                                    .join("\n"),
                        }],
                    };
                }
                targetId = top.device.id;
                candidates = [top.device];
            }

            // Llamar al control
            const body = { device_id: targetId, action };
            if (brightness != null) body.brightness = brightness;
            if (temperature != null) body.temperature = temperature;

            const resp = await authedFetch(`/api/v1/ha/admin/control/`, {
                method: "POST",
                headers: { "Content-Type": "application/json" },
                body: JSON.stringify(body),
            });
            const data = await resp.json();
            if (!resp.ok) {
                return {
                    content: [{
                        type: "text",
                        text: `Error controlando dispositivo: ${data.error || JSON.stringify(data)}`,
                    }],
                    isError: true,
                };
            }
            // Invalidar cache local: el estado del device cambió, el próximo
            // list_devices debe ir al server (que también acaba de invalidar
            // su cache interno).
            invalidateHaDevicesCache();

            const matched = candidates[0];
            const summary = {
                success: data.success,
                accion: action,
                dispositivo: matched
                    ? `${matched.friendly_name} (${matched.property_name} / ${matched.location})`
                    : data.message,
                nuevo_estado: data.new_state?.state,
                sensor: data.sensor_state || null,
            };
            return { content: [{ type: "text", text: JSON.stringify(summary, null, 2) }] };
        }

        if (name === "compare_months_yoy") {
            const { month, year, vs_year } = args || {};
            if (!month || !year) throw new Error("Faltan month y year.");
            const targetVs = vs_year || (year - 1);
            const params1 = new URLSearchParams({ month: String(month), year: String(year) });
            const params2 = new URLSearchParams({ month: String(month), year: String(targetVs) });
            const [a, b] = await Promise.all([
                authedJson(`/api/v1/dashboard/?${params1}`),
                authedJson(`/api/v1/dashboard/?${params2}`),
            ]);
            const summarize = (d, y) => ({
                year: y,
                por_casa: (d.free_days_per_house || []).map((h) => ({
                    casa: h.casa,
                    noches_libres: h.dias_libres,
                    noches_ocupadas: h.dias_ocupada,
                    ingresos_sol: h.dinero_facturado,
                })),
                total: {
                    noches_ocupadas: d.ocuppied_days_total,
                    noches_libres: d.free_days_total,
                    facturacion_sol: d.dinero_total_facturado,
                    por_cobrar_sol: d.dinero_por_cobrar,
                },
            });
            const summary = {
                month,
                comparison: {
                    actual: summarize(a, year),
                    previo: summarize(b, targetVs),
                },
                diff: {
                    facturacion_delta_sol:
                        parseFloat(a.dinero_total_facturado || 0) -
                        parseFloat(b.dinero_total_facturado || 0),
                    noches_ocupadas_delta:
                        (a.ocuppied_days_total || 0) - (b.ocuppied_days_total || 0),
                },
            };
            return { content: [{ type: "text", text: JSON.stringify(summary, null, 2) }] };
        }

        throw new Error(`Tool desconocida: ${name}`);
    } catch (err) {
        return {
            content: [{ type: "text", text: err.message || String(err) }],
            isError: true,
        };
    }
});

const transport = new StdioServerTransport();
await server.connect(transport);

// ─── Pre-warm en background ───
// Si tenemos credenciales, hacemos login + fetch de devices al iniciar.
// Cuando el usuario haga su primera llamada a HA, ya está caliente y
// responde en ~300ms en vez de 12s. Esto se ejecuta sin bloquear el
// MCP transport — si falla, no rompe nada (cada tool reintenta).
if (ADMIN_USERNAME && ADMIN_PASSWORD) {
    (async () => {
        try {
            await loginFresh();
            // Pre-cargar properties y devices en paralelo
            await Promise.all([
                getPropertiesCached().catch(() => {}),
                getHaDevicesCached().catch(() => {}),
            ]);
        } catch {
            // El warmup es best-effort; si falla, las tools harán su propio
            // login en la primera llamada real.
        }
    })();
}
