"""
Definiciones de herramientas (function calling) para el asistente IA financiero.
Formato OpenAI tools API.
"""

ADMIN_TOOL_DEFINITIONS = [
    {
        "type": "function",
        "function": {
            "name": "get_revenue_summary",
            "description": (
                "Obtiene un resumen de ingresos por propiedad y período. "
                "Incluye total en soles y dólares, RevPAR, ingreso promedio por reserva, "
                "y desglose por propiedad. Usa esto cuando pregunten sobre ingresos, "
                "facturación, revenue o cuánto se ha generado."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "date_from": {
                        "type": "string",
                        "description": "Fecha inicio en formato YYYY-MM-DD. Si no se especifica, usa últimos 30 días."
                    },
                    "date_to": {
                        "type": "string",
                        "description": "Fecha fin en formato YYYY-MM-DD. Si no se especifica, usa fecha actual."
                    },
                    "property_name": {
                        "type": "string",
                        "description": "Nombre de la propiedad para filtrar (parcial, case-insensitive). Opcional."
                    }
                },
                "required": []
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "get_occupancy_rates",
            "description": (
                "Calcula la tasa de ocupación por propiedad en un período. "
                "Devuelve porcentaje de noches ocupadas vs disponibles, comparativa entre casas. "
                "Usa esto cuando pregunten sobre ocupación, qué casa se renta más, o disponibilidad."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "date_from": {
                        "type": "string",
                        "description": "Fecha inicio en formato YYYY-MM-DD."
                    },
                    "date_to": {
                        "type": "string",
                        "description": "Fecha fin en formato YYYY-MM-DD."
                    }
                },
                "required": []
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "get_reservation_stats",
            "description": (
                "Obtiene estadísticas de reservas: conteo por estado, estancia promedio, "
                "cancelaciones, y origen de las reservas. "
                "Usa esto cuando pregunten sobre cantidad de reservas, cancelaciones, o fuentes de reserva."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "date_from": {
                        "type": "string",
                        "description": "Fecha inicio en formato YYYY-MM-DD."
                    },
                    "date_to": {
                        "type": "string",
                        "description": "Fecha fin en formato YYYY-MM-DD."
                    },
                    "property_name": {
                        "type": "string",
                        "description": "Nombre de propiedad para filtrar. Opcional."
                    }
                },
                "required": []
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "get_pricing_overview",
            "description": (
                "Muestra las tarifas actuales de todas las propiedades: precios base por temporada, "
                "temporadas configuradas, y fechas especiales con precios. "
                "Usa esto cuando pregunten sobre precios, tarifas, o configuración de pricing."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "property_name": {
                        "type": "string",
                        "description": "Nombre de propiedad para filtrar. Opcional, si no se da muestra todas."
                    }
                },
                "required": []
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "get_property_details",
            "description": (
                "Obtiene detalles de las propiedades: capacidad, dormitorios, baños, amenidades, estado. "
                "Usa esto cuando pregunten sobre características de las casas o comparativas de propiedades."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "property_name": {
                        "type": "string",
                        "description": "Nombre de propiedad específica. Opcional."
                    }
                },
                "required": []
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "get_financial_projections",
            "description": (
                "Genera proyecciones financieras basadas en datos históricos. "
                "Compara período actual vs anterior, calcula tendencias y estimados. "
                "Usa esto cuando pregunten sobre proyecciones, tendencias, o estimados futuros."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "months_back": {
                        "type": "integer",
                        "description": "Meses de histórico a analizar (default: 3)."
                    },
                    "months_forward": {
                        "type": "integer",
                        "description": "Meses a proyectar (default: 1)."
                    }
                },
                "required": []
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "get_client_analytics",
            "description": (
                "Analiza datos de clientes: top clientes por gasto, retención, "
                "nuevos vs recurrentes, frecuencia de reservas. "
                "Usa esto cuando pregunten sobre clientes, fidelización, o quiénes son los mejores clientes."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "date_from": {
                        "type": "string",
                        "description": "Fecha inicio en formato YYYY-MM-DD."
                    },
                    "date_to": {
                        "type": "string",
                        "description": "Fecha fin en formato YYYY-MM-DD."
                    },
                    "top_n": {
                        "type": "integer",
                        "description": "Cantidad de top clientes a mostrar (default: 10)."
                    }
                },
                "required": []
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "get_chatbot_performance",
            "description": (
                "Muestra métricas de rendimiento del chatbot de WhatsApp: sesiones, mensajes, "
                "conversiones, leads generados, costo estimado. "
                "Usa esto cuando pregunten sobre el chatbot, su rendimiento o ROI."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "date_from": {
                        "type": "string",
                        "description": "Fecha inicio en formato YYYY-MM-DD."
                    },
                    "date_to": {
                        "type": "string",
                        "description": "Fecha fin en formato YYYY-MM-DD."
                    }
                },
                "required": []
            }
        }
    },
]
