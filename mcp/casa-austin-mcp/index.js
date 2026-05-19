#!/usr/bin/env node
/**
 * MCP server de Casa Austin: expone tools para consultar disponibilidad
 * y precios de las casas de playa desde Claude Desktop.
 *
 * Tools:
 *   check_availability(check_in, check_out)
 *     → SOLO disponibilidad sin precios (lista casas libres + capacidad).
 *   get_pricing(check_in, check_out, guests, property_slug?)
 *     → Disponibilidad + precios para N huéspedes (cotización completa).
 *   list_properties()
 *     → Info estática de las 4 casas (capacidad, dormitorios, etc).
 *
 * Uso desde Claude Desktop una vez registrado en claude_desktop_config.json:
 *   "¿Hay disponibilidad del 15 al 18 de junio?"  → check_availability
 *   "¿Cuánto sale Casa Austin 3 para 6 personas?" → get_pricing
 *   "¿Cuáles son las 4 casas de Casa Austin?"     → list_properties
 */
import { Server } from "@modelcontextprotocol/sdk/server/index.js";
import { StdioServerTransport } from "@modelcontextprotocol/sdk/server/stdio.js";
import {
    CallToolRequestSchema,
    ListToolsRequestSchema,
} from "@modelcontextprotocol/sdk/types.js";

const API_BASE = process.env.CASA_AUSTIN_API_BASE || "https://api.casaaustin.pe";

const server = new Server(
    { name: "casa-austin", version: "0.2.0" },
    { capabilities: { tools: {} } },
);

server.setRequestHandler(ListToolsRequestSchema, async () => ({
    tools: [
        {
            name: "check_availability",
            description:
                "Consulta SOLO disponibilidad (sin precios) de las casas de Casa Austin para un rango de fechas. Devuelve cuántas casas hay libres y la lista de casas disponibles con su capacidad máxima. Usar cuando el usuario pregunta '¿hay disponibilidad?' sin especificar cantidad de personas ni pedir precio. Para cotizar con precios usar la herramienta get_pricing.",
            inputSchema: {
                type: "object",
                properties: {
                    check_in: {
                        type: "string",
                        description: "Fecha de check-in en formato YYYY-MM-DD.",
                    },
                    check_out: {
                        type: "string",
                        description: "Fecha de check-out en formato YYYY-MM-DD. Posterior al check_in.",
                    },
                },
                required: ["check_in", "check_out"],
            },
        },
        {
            name: "get_pricing",
            description:
                "Consulta disponibilidad y PRECIOS de las casas de Casa Austin para fechas y cantidad de huéspedes específicos. Devuelve precio total en soles y dólares por cada casa disponible, con descuentos aplicables. Usar cuando el usuario pregunta cuánto cuesta una estadía o pide cotización para N personas.",
            inputSchema: {
                type: "object",
                properties: {
                    check_in: {
                        type: "string",
                        description: "Fecha de check-in en formato YYYY-MM-DD.",
                    },
                    check_out: {
                        type: "string",
                        description: "Fecha de check-out en formato YYYY-MM-DD.",
                    },
                    guests: {
                        type: "number",
                        description: "Cantidad total de huéspedes (adultos + niños). Mínimo 1.",
                    },
                    property_slug: {
                        type: "string",
                        description: "Opcional. Slug de una propiedad específica (casa-austin-1, casa-austin-2, casa-austin-3, casa-austin-4) si solo se quiere cotizar esa casa. Si se omite, devuelve cotización de todas las casas disponibles.",
                    },
                },
                required: ["check_in", "check_out", "guests"],
            },
        },
        {
            name: "list_properties",
            description:
                "Lista las 4 casas de Casa Austin con sus características: nombre, slug, capacidad máxima, dormitorios, baños y precio mínimo. Útil para saber qué propiedades existen antes de cotizar una específica.",
            inputSchema: {
                type: "object",
                properties: {},
            },
        },
    ],
}));

/** Helper: arma URL del endpoint calculate-pricing. */
function pricingUrl({ check_in, check_out, guests }) {
    const params = new URLSearchParams({
        check_in_date: String(check_in),
        check_out_date: String(check_out),
        guests: String(guests),
    });
    return `${API_BASE}/api/v1/properties/calculate-pricing/?${params.toString()}`;
}

/** Helper: hace fetch JSON con manejo uniforme de errores. */
async function fetchJson(url) {
    const resp = await fetch(url, {
        method: "GET",
        headers: { Accept: "application/json" },
    });
    const data = await resp.json();
    if (data && data.error && data.error !== 0) {
        const msg = data.error_message || data.detail || "sin mensaje";
        const err = new Error(`Error de la API (code ${data.error}): ${msg}`);
        err.apiData = data;
        throw err;
    }
    return data;
}

server.setRequestHandler(CallToolRequestSchema, async (req) => {
    const { name, arguments: args } = req.params;

    // ───────────────────────────────────────────────────────────────
    // check_availability — SOLO disponibilidad, sin precios.
    // El endpoint calculate-pricing requiere guests. Usamos guests=1
    // (el mínimo) para que considere TODAS las casas disponibles, y
    // proyectamos la respuesta para devolver únicamente disponibilidad.
    // ───────────────────────────────────────────────────────────────
    if (name === "check_availability") {
        const { check_in, check_out } = args || {};
        if (!check_in || !check_out) {
            return {
                content: [{ type: "text", text: "Faltan parámetros: check_in y check_out son requeridos." }],
                isError: true,
            };
        }
        try {
            const data = await fetchJson(pricingUrl({ check_in, check_out, guests: 1 }));
            const d = data.data || {};
            const props = (d.properties || []).map((p) => ({
                name: p.property_name,
                slug: p.property_slug,
                capacity_max: p.capacity_max ?? null,
                available: true,
            }));
            const summary = {
                check_in: d.check_in_date || check_in,
                check_out: d.check_out_date || check_out,
                total_nights: d.total_nights,
                casas_disponibles: d.totalCasasDisponibles ?? props.length,
                casas: props,
            };
            return {
                content: [{ type: "text", text: JSON.stringify(summary, null, 2) }],
            };
        } catch (err) {
            return {
                content: [{ type: "text", text: err.message }],
                isError: true,
            };
        }
    }

    // ───────────────────────────────────────────────────────────────
    // get_pricing — disponibilidad + precios para N huéspedes.
    // ───────────────────────────────────────────────────────────────
    if (name === "get_pricing") {
        const { check_in, check_out, guests, property_slug } = args || {};
        if (!check_in || !check_out || guests == null) {
            return {
                content: [{ type: "text", text: "Faltan parámetros: check_in, check_out y guests son requeridos." }],
                isError: true,
            };
        }
        try {
            const data = await fetchJson(pricingUrl({ check_in, check_out, guests }));
            const d = data.data || {};
            let props = d.properties || [];
            if (property_slug) {
                props = props.filter((p) => p.property_slug === property_slug);
                if (props.length === 0) {
                    return {
                        content: [{
                            type: "text",
                            text: `No hay disponibilidad para "${property_slug}" en esas fechas para ${guests} huéspedes, o el slug no existe. Slugs válidos: casa-austin-1, casa-austin-2, casa-austin-3, casa-austin-4.`,
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
            return {
                content: [{ type: "text", text: JSON.stringify(result, null, 2) }],
            };
        } catch (err) {
            return {
                content: [{ type: "text", text: err.message }],
                isError: true,
            };
        }
    }

    // ───────────────────────────────────────────────────────────────
    // list_properties — info estática de las casas.
    // ───────────────────────────────────────────────────────────────
    if (name === "list_properties") {
        try {
            const resp = await fetch(`${API_BASE}/api/v1/property/`, {
                method: "GET",
                headers: { Accept: "application/json" },
            });
            if (!resp.ok) {
                throw new Error(`HTTP ${resp.status}`);
            }
            const data = await resp.json();
            const items = data.results || data || [];
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
            return {
                content: [{ type: "text", text: JSON.stringify(minimal, null, 2) }],
            };
        } catch (err) {
            return {
                content: [{ type: "text", text: `Error consultando propiedades: ${err.message}` }],
                isError: true,
            };
        }
    }

    return {
        content: [{ type: "text", text: `Tool desconocida: ${name}` }],
        isError: true,
    };
});

const transport = new StdioServerTransport();
await server.connect(transport);
