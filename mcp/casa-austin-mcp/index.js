#!/usr/bin/env node
/**
 * MCP server de Casa Austin: expone tools para consultar disponibilidad
 * y precios de las casas de playa desde Claude Desktop.
 *
 * Tool principal:
 *   check_availability(check_in, check_out, guests, property?)
 *     → GET /api/v1/properties/calculate-pricing/?check_in_date=...&check_out_date=...&guests=...
 *
 * Tool secundaria:
 *   list_properties()
 *     → GET /api/v1/property/ (info estática de las 4 casas)
 *
 * Uso desde Claude Desktop una vez registrado en claude_desktop_config.json:
 *   "¿Hay disponibilidad del 15 al 18 de junio para 6 personas?"
 *   "¿Cuánto sale Casa Austin 3 el primer fin de semana de agosto?"
 *   "Listame todas las casas disponibles para 4 personas el 25/12"
 */
import { Server } from "@modelcontextprotocol/sdk/server/index.js";
import { StdioServerTransport } from "@modelcontextprotocol/sdk/server/stdio.js";
import {
    CallToolRequestSchema,
    ListToolsRequestSchema,
} from "@modelcontextprotocol/sdk/types.js";

const API_BASE = process.env.CASA_AUSTIN_API_BASE || "https://api.casaaustin.pe";

const server = new Server(
    { name: "casa-austin", version: "0.1.0" },
    { capabilities: { tools: {} } },
);

server.setRequestHandler(ListToolsRequestSchema, async () => ({
    tools: [
        {
            name: "check_availability",
            description:
                "Consulta disponibilidad y precios de las casas de playa de Casa Austin para fechas y cantidad de huéspedes específicos. Devuelve el listado de casas disponibles con su precio total en soles y dólares, descuentos aplicables y características de cada casa.",
            inputSchema: {
                type: "object",
                properties: {
                    check_in: {
                        type: "string",
                        description: "Fecha de check-in en formato YYYY-MM-DD (ej: 2026-06-15).",
                    },
                    check_out: {
                        type: "string",
                        description: "Fecha de check-out en formato YYYY-MM-DD (ej: 2026-06-18). Debe ser posterior al check_in.",
                    },
                    guests: {
                        type: "number",
                        description: "Cantidad total de huéspedes (adultos + niños). Mínimo 1.",
                    },
                },
                required: ["check_in", "check_out", "guests"],
            },
        },
        {
            name: "list_properties",
            description:
                "Lista las 4 casas de Casa Austin con sus características: nombre, capacidad máxima, dormitorios, baños, slug y descripción. Útil para entender qué propiedades existen antes de consultar disponibilidad de una específica.",
            inputSchema: {
                type: "object",
                properties: {},
            },
        },
    ],
}));

server.setRequestHandler(CallToolRequestSchema, async (req) => {
    const { name, arguments: args } = req.params;

    if (name === "check_availability") {
        const { check_in, check_out, guests } = args || {};
        if (!check_in || !check_out || guests == null) {
            return {
                content: [{ type: "text", text: "Faltan parámetros: check_in, check_out y guests son requeridos." }],
                isError: true,
            };
        }
        const params = new URLSearchParams({
            check_in_date: String(check_in),
            check_out_date: String(check_out),
            guests: String(guests),
        });
        const url = `${API_BASE}/api/v1/properties/calculate-pricing/?${params.toString()}`;
        try {
            const resp = await fetch(url, {
                method: "GET",
                headers: { Accept: "application/json" },
            });
            const data = await resp.json();
            // Si la API devolvió un error estructurado, lo incluimos legible.
            if (data && data.error && data.error !== 0) {
                return {
                    content: [
                        {
                            type: "text",
                            text:
                                `Error de la API (code ${data.error}): ${data.error_message || data.detail || "sin mensaje"}\n\n` +
                                JSON.stringify(data, null, 2),
                        },
                    ],
                    isError: true,
                };
            }
            return {
                content: [{ type: "text", text: JSON.stringify(data, null, 2) }],
            };
        } catch (err) {
            return {
                content: [{ type: "text", text: `Error consultando la API: ${err.message}` }],
                isError: true,
            };
        }
    }

    if (name === "list_properties") {
        const url = `${API_BASE}/api/v1/property/`;
        try {
            const resp = await fetch(url, {
                method: "GET",
                headers: { Accept: "application/json" },
            });
            if (!resp.ok) {
                throw new Error(`HTTP ${resp.status}`);
            }
            const data = await resp.json();
            // Devolvemos un subset relevante para que Claude no procese ruido.
            const items = (data.results || data) || [];
            const minimal = Array.isArray(items)
                ? items.map((p) => ({
                      id: p.id,
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
