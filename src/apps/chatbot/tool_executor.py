import logging
from datetime import date, datetime, timedelta

logger = logging.getLogger(__name__)


# Definiciones de herramientas para OpenAI Function Calling
TOOL_DEFINITIONS = [
    {
        "type": "function",
        "function": {
            "name": "check_calendar",
            "description": (
                "Consulta qué casas están disponibles u ocupadas en un rango de fechas. "
                "NO calcula precios, solo muestra disponibilidad. "
                "Usa esta herramienta cuando el cliente pregunta '¿hay disponibilidad?' o '¿qué fechas tienen?' "
                "sin haber dado número de personas. "
                "Después de mostrar disponibilidad, pregunta cuántas personas para cotizar precios con check_availability. "
                "IMPORTANTE: SIEMPRE llama esta herramienta cuando el cliente pregunte por fechas, "
                "aunque ya hayas consultado antes. NUNCA uses resultados de consultas anteriores."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "from_date": {
                        "type": "string",
                        "description": "Fecha inicio del rango en formato YYYY-MM-DD. Es EXACTAMENTE el día que el cliente dijo, sin sumar nada. Si no se indica, usar hoy."
                    },
                    "to_date": {
                        "type": "string",
                        "description": "Fecha fin del rango en formato YYYY-MM-DD. Es EXACTAMENTE el día que el cliente dijo. Si no se indica, usar 30 días desde from_date."
                    },
                    "property_name": {
                        "type": "string",
                        "description": "Nombre de una propiedad específica (opcional, si no se indica se muestran todas)"
                    }
                },
                "required": []
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "check_availability",
            "description": "Consulta disponibilidad Y PRECIOS de propiedades para fechas específicas. Requiere fechas y número de huéspedes para calcular precio. Si el cliente no dijo cuántos huéspedes, usa 1 como default. Usa esta herramienta cuando ya tengas fechas Y personas para dar una cotización con precios. IMPORTANTE: SIEMPRE llama esta herramienta para cada consulta de fechas, NUNCA reutilices precios o disponibilidad de consultas anteriores en la conversación. REGLA CRÍTICA DE FECHAS: check_in es EXACTAMENTE el día que el cliente mencionó. Ejemplos: 'para el 21 de marzo' → check_in='2026-03-21'. 'del 15 al 17' → check_in='2026-03-15', check_out='2026-03-17'. NUNCA sumes días a la fecha que dijo el cliente.",
            "parameters": {
                "type": "object",
                "properties": {
                    "check_in": {
                        "type": "string",
                        "description": "Fecha de check-in en formato YYYY-MM-DD. Es EXACTAMENTE el día que el cliente dijo, sin sumar nada. Ejemplo: cliente dice '21 de marzo' → check_in='2026-03-21'. Usa el calendario del sistema para obtener el año correcto."
                    },
                    "check_out": {
                        "type": "string",
                        "description": "Fecha de check-out en formato YYYY-MM-DD. Si el cliente no indicó fecha de salida, es check_in + 1 día. Ejemplo: cliente dice 'el 21 de marzo' sin salida → check_out='2026-03-22'."
                    },
                    "guests": {
                        "type": "integer",
                        "description": "Número de huéspedes. Si no se indica, usar 1."
                    },
                    "property_name": {
                        "type": "string",
                        "description": "Nombre de la propiedad específica (opcional, si no se indica se buscan todas)"
                    }
                },
                "required": ["check_in", "check_out"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "identify_client",
            "description": "Busca un cliente por número de documento o teléfono y vincula la sesión de chat.",
            "parameters": {
                "type": "object",
                "properties": {
                    "document_number": {
                        "type": "string",
                        "description": "Número de DNI o documento del cliente"
                    },
                    "phone_number": {
                        "type": "string",
                        "description": "Número de teléfono del cliente"
                    }
                }
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "check_client_points",
            "description": "Consulta el balance de puntos de un cliente identificado.",
            "parameters": {
                "type": "object",
                "properties": {
                    "client_id": {
                        "type": "string",
                        "description": "ID del cliente"
                    }
                },
                "required": ["client_id"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "check_reservations",
            "description": (
                "Consulta las reservas activas de un cliente identificado. "
                "Muestra reservas confirmadas (aprobadas) y pendientes de pago. "
                "Requiere que el cliente esté vinculado a la sesión."
            ),
            "parameters": {
                "type": "object",
                "properties": {}
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "validate_discount_code",
            "description": "Valida un código de descuento y calcula el descuento aplicable.",
            "parameters": {
                "type": "object",
                "properties": {
                    "code": {
                        "type": "string",
                        "description": "Código de descuento"
                    },
                    "property_name": {
                        "type": "string",
                        "description": "Nombre de la propiedad (opcional)"
                    },
                    "check_in_date": {
                        "type": "string",
                        "description": "Fecha de check-in para validar restricciones (YYYY-MM-DD)"
                    }
                },
                "required": ["code"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "get_property_info",
            "description": "Obtiene información detallada de una propiedad: nombre, capacidad, descripción, dormitorios, baños, características.",
            "parameters": {
                "type": "object",
                "properties": {
                    "property_name": {
                        "type": "string",
                        "description": "Nombre de la propiedad (opcional, si no se indica retorna todas)"
                    }
                }
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "schedule_visit",
            "description": "Agenda una visita a una propiedad. Primero verifica que la propiedad esté disponible (no ocupada) en la fecha solicitada. Requiere nombre de propiedad, fecha de visita y datos del visitante.",
            "parameters": {
                "type": "object",
                "properties": {
                    "property_name": {
                        "type": "string",
                        "description": "Nombre de la propiedad a visitar"
                    },
                    "visit_date": {
                        "type": "string",
                        "description": "Fecha de la visita en formato YYYY-MM-DD"
                    },
                    "visit_time": {
                        "type": "string",
                        "description": "Hora preferida de la visita en formato HH:MM (opcional, por defecto 10:00)"
                    },
                    "visitor_name": {
                        "type": "string",
                        "description": "Nombre completo del visitante"
                    },
                    "guests_count": {
                        "type": "integer",
                        "description": "Cantidad de personas que asistirán (opcional, por defecto 1)"
                    },
                    "notes": {
                        "type": "string",
                        "description": "Notas o comentarios adicionales del visitante (opcional)"
                    }
                },
                "required": ["property_name", "visit_date", "visitor_name"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "check_late_checkout",
            "description": (
                "Consulta precio de late checkout (salida tardía hasta las 8PM). "
                "⚠️ El late checkout es una EXTENSIÓN de una reserva o cotización existente — "
                "NUNCA una cotización independiente. El backend toma automáticamente "
                "property, guests y checkout_date de la reserva activa del cliente o de la "
                "última cotización de la sesión. "
                "PRE-REQUISITO: debe existir previamente una reserva del cliente o una "
                "cotización (check_availability) en la conversación. Si no hay ninguna, "
                "PRIMERO cotiza con check_availability. "
                "Los argumentos son hints opcionales; si se pasan pero no coinciden con el "
                "contexto, se ignoran y se usa el contexto como fuente de verdad. "
                "NUNCA inventes el precio — SIEMPRE usa esta herramienta cuando el cliente pregunte por late checkout."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "property_name": {
                        "type": "string",
                        "description": "(Opcional) Nombre de propiedad solo como hint — el backend usa la del contexto."
                    },
                    "checkout_date": {
                        "type": "string",
                        "description": "(Opcional) Fecha checkout solo como hint — el backend usa la del contexto."
                    },
                    "guests": {
                        "type": "integer",
                        "description": "(Opcional) Guests solo como hint — el backend usa el de la reserva/cotización del contexto."
                    }
                },
                "required": []
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "escalate_to_human",
            "description": "Escala la conversación a un agente humano. Usar cuando el cliente lo solicita, cuando hay quejas, o cuando la IA no puede resolver la consulta.",
            "parameters": {
                "type": "object",
                "properties": {
                    "reason": {
                        "type": "string",
                        "description": "Razón de la escalación"
                    }
                },
                "required": ["reason"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "notify_team",
            "description": (
                "Envía una alerta al equipo de Casa Austin. NO pausa la IA ni escala. "
                "Usar SOLO en estos casos:\n"
                "- ready_to_book: El cliente dice explícitamente que quiere reservar YA "
                "(ej: 'quiero reservar', 'cómo pago', 'listo, vamos', 'me interesa reservar').\n"
                "- needs_human_assist: El cliente necesita atención humana para cerrar — "
                "negociación de precio, propuesta de colaboración/canje, solicitud especial, "
                "grupo corporativo con requisitos específicos, o cualquier situación que "
                "el bot no puede resolver solo pero hay interés real del cliente.\n"
                "- query_not_understood: No entiendes lo que el cliente pide o no puedes ayudarlo "
                "con la información disponible.\n"
                "NO usar para consultas normales de precio, disponibilidad o información general."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "reason": {
                        "type": "string",
                        "enum": ["ready_to_book", "needs_human_assist", "query_not_understood"],
                        "description": "Tipo de alerta"
                    },
                    "details": {
                        "type": "string",
                        "description": "Descripción breve del contexto"
                    }
                },
                "required": ["reason", "details"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "log_unanswered_question",
            "description": (
                "Registra una pregunta que NO puedes responder con la información disponible. "
                "Usa esta herramienta SIEMPRE que el cliente haga una pregunta que no puedas resolver: "
                "políticas que no conoces, servicios no mencionados en tu prompt, precios especiales, "
                "preguntas sobre la zona, eventos, o cualquier tema donde no tengas información suficiente. "
                "DESPUÉS de registrar, responde al cliente que consultarás con el equipo. "
                "NO uses esta herramienta para preguntas que SÍ puedes responder con tu información."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "question": {
                        "type": "string",
                        "description": "La pregunta exacta del cliente que no puedes responder"
                    },
                    "category": {
                        "type": "string",
                        "enum": ["pricing", "policy", "property_info", "service", "location", "other"],
                        "description": "Categoría de la pregunta"
                    }
                },
                "required": ["question", "category"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "get_pricing_table",
            "description": (
                "Obtiene la tabla de precios actual de todas las propiedades directamente de la base de datos. "
                "Muestra tarifas base por tipo de día (entre semana vs fin de semana) y temporada (alta/baja), "
                "costo extra por persona, temporadas configuradas y fechas especiales. "
                "Usa esta herramienta cuando el cliente pregunte por rangos de precios generales, "
                "estructura de tarifas, o '¿desde qué precios?' SIN dar fechas ni personas específicas. "
                "Para cotización exacta con fechas y personas, usa check_availability en su lugar."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "property_name": {
                        "type": "string",
                        "description": "Nombre de una propiedad específica (opcional, muestra todas si no se indica)"
                    }
                },
                "required": []
            }
        }
    },
]


class ToolExecutor:
    """Ejecuta las herramientas (function calls) invocadas por la IA"""

    def __init__(self, session):
        self.session = session

    def execute(self, tool_name, arguments):
        """Ejecuta una herramienta y retorna el resultado como string"""
        tool_map = {
            'check_calendar': self._check_calendar,
            'check_availability': self._check_availability,
            'identify_client': self._identify_client,
            'check_client_points': self._check_client_points,
            'check_reservations': self._check_reservations,
            'validate_discount_code': self._validate_discount_code,
            'get_property_info': self._get_property_info,
            'schedule_visit': self._schedule_visit,
            'check_late_checkout': self._check_late_checkout,
            'escalate_to_human': self._escalate_to_human,
            'notify_team': self._notify_team,
            'log_unanswered_question': self._log_unanswered_question,
            'get_pricing_table': self._get_pricing_table,
        }

        handler = tool_map.get(tool_name)
        if not handler:
            return f"Error: herramienta '{tool_name}' no encontrada"

        try:
            return handler(**arguments)
        except Exception as e:
            logger.error(f"Error ejecutando {tool_name}: {e}", exc_info=True)
            return f"Error al ejecutar {tool_name}: {str(e)}"

    def _check_calendar(self, from_date=None, to_date=None, property_name=None):
        """Consulta disponibilidad de casas en un rango de fechas (sin precios)."""
        from apps.property.models import Property
        from apps.reservation.models import Reservation
        from datetime import timedelta

        today = date.today()

        # Guard: si no viene ninguna fecha, rechazar con instrucción al modelo.
        # Visto en producción (Ricardo Vasquez): el bot llamó check_calendar
        # sin fechas en los primeros turnos, gastando tokens sin valor.
        if not from_date and not to_date:
            return (
                "⚠️ BLOQUEADO: check_calendar requiere al menos una fecha (from_date). "
                "PRIMERO pregúntale al cliente: '¿Para qué fechas te gustaría alquilar?'. "
                "NO ejecutes check_calendar sin fechas."
            )

        # Parsear fechas
        if from_date:
            try:
                start = datetime.strptime(from_date, '%Y-%m-%d').date()
            except ValueError:
                return (
                    "⚠️ BLOQUEADO: from_date no tiene formato YYYY-MM-DD válido. "
                    "Pídele al cliente una fecha clara (día y mes)."
                )
        else:
            start = today

        if start < today:
            start = today

        if to_date:
            try:
                end = datetime.strptime(to_date, '%Y-%m-%d').date()
            except ValueError:
                end = start + timedelta(days=30)
        else:
            end = start + timedelta(days=30)

        # Limitar a máximo 60 días
        if (end - start).days > 60:
            end = start + timedelta(days=60)

        # Obtener propiedades
        properties = Property.objects.filter(deleted=False)
        if property_name:
            filtered = properties.filter(name__icontains=property_name)
            if filtered.exists():
                properties = filtered

        if not properties.exists():
            return "No hay propiedades registradas."

        # Obtener reservas activas en el rango (ampliar +1 día para late checkout)
        active_statuses = ['approved', 'pending', 'under_review']
        reservations = Reservation.objects.filter(
            deleted=False,
            status__in=active_statuses,
            check_out_date__gt=start - timedelta(days=1),
            check_in_date__lt=end,
        ).select_related('property')

        # Construir mapa de ocupación considerando late checkout
        occupation = {}
        for r in reservations:
            effective_checkout = r.check_out_date
            if r.late_checkout and r.late_check_out_date:
                if r.late_check_out_date > r.check_out_date:
                    effective_checkout = r.late_check_out_date
                elif r.check_out_date == r.late_check_out_date:
                    effective_checkout = r.late_check_out_date + timedelta(days=1)
            occupation.setdefault(r.property_id, []).append(
                (r.check_in_date, effective_checkout)
            )

        # Para la fecha específica consultada o rango corto, mostrar por fecha
        days_range = (end - start).days
        months_es = {
            1: 'ene', 2: 'feb', 3: 'mar', 4: 'abr',
            5: 'may', 6: 'jun', 7: 'jul', 8: 'ago',
            9: 'sep', 10: 'oct', 11: 'nov', 12: 'dic',
        }
        days_es = {
            0: 'lun', 1: 'mar', 2: 'mié',
            3: 'jue', 4: 'vie', 5: 'sáb', 6: 'dom',
        }

        if days_range <= 7:
            # Rango corto: mostrar cada día con cada casa
            lines = [f"📅 Disponibilidad del {start.strftime('%d/%m')} al {end.strftime('%d/%m')}:\n"]

            for i in range(days_range):
                d = start + timedelta(days=i)
                day_label = f"{days_es[d.weekday()]} {d.day} {months_es[d.month]}"
                available = []
                occupied = []

                for prop in properties:
                    is_occupied = False
                    for (ci, co) in occupation.get(prop.id, []):
                        if ci <= d < co:
                            is_occupied = True
                            break
                    if is_occupied:
                        occupied.append(prop.name)
                    else:
                        available.append(prop.name)

                if available:
                    avail_str = ", ".join(available)
                    lines.append(f"✅ {day_label}: {avail_str}")
                else:
                    lines.append(f"📅 {day_label}: Ocupado")

            lines.append("")
            lines.append(
                "[INSTRUCCIÓN IA: Muestra esta disponibilidad al cliente. "
                "Pregunta cuántas personas serán para dar precios exactos. "
                "Si el cliente elige una fecha, usa check_availability con esa fecha para cotizar.]"
            )
            return '\n'.join(lines)

        else:
            # Rango largo: mostrar resumen por casa con fines de semana explícitos
            lines = [f"📅 Disponibilidad del {start.strftime('%d/%m')} al {end.strftime('%d/%m')}:\n"]

            # Calcular fines de semana (viernes y sábado como check-in) en el rango
            all_free_weekends = {}  # prop_id -> list of "sáb DD/mmm"
            for prop in properties:
                prop_reservations = occupation.get(prop.id, [])
                free_weekends = []
                for i in range(days_range):
                    d = start + timedelta(days=i)
                    # viernes (4) y sábado (5) como días de check-in de fin de semana
                    if d.weekday() not in (4, 5):
                        continue
                    is_free = True
                    for (ci, co) in prop_reservations:
                        if ci <= d < co:
                            is_free = False
                            break
                    if is_free:
                        free_weekends.append(
                            f"{days_es[d.weekday()]} {d.day} {months_es[d.month]}"
                        )
                all_free_weekends[prop.id] = free_weekends

            for prop in properties:
                prop_reservations = occupation.get(prop.id, [])

                if not prop_reservations:
                    lines.append(f"🏠 {prop.name}: ✅ Disponible TODO el período")
                else:
                    # Encontrar fechas ocupadas
                    occupied_ranges = []
                    for (ci, co) in sorted(prop_reservations):
                        ci_display = max(ci, start)
                        co_display = min(co, end)
                        occupied_ranges.append(
                            f"{ci_display.day}-{co_display.day} {months_es[ci_display.month]}"
                        )

                    # Contar noches libres
                    free_nights = 0
                    for i in range(days_range):
                        d = start + timedelta(days=i)
                        is_free = True
                        for (ci, co) in prop_reservations:
                            if ci <= d < co:
                                is_free = False
                                break
                        if is_free:
                            free_nights += 1

                    occ_str = ", ".join(occupied_ranges)
                    lines.append(
                        f"🏠 {prop.name}: {free_nights} noches libres "
                        f"(ocupada: {occ_str})"
                    )

                # Fines de semana libres
                weekends = all_free_weekends.get(prop.id, [])
                if weekends:
                    lines.append(f"  🗓️ Fines de semana libres: {', '.join(weekends)}")
                else:
                    lines.append(f"  🗓️ Sin fines de semana disponibles en este período")

            lines.append("")
            lines.append(
                "[INSTRUCCIÓN IA: Muestra esta disponibilidad al cliente. "
                "IMPORTANTE: Usa EXACTAMENTE los nombres de días (sáb, vie, dom, etc.) que aparecen arriba. "
                "NUNCA calcules ni adivines qué día de la semana es una fecha — confía en los datos de la herramienta. "
                "Pregunta por qué fechas específicas le interesan y cuántas personas serán. "
                "Luego usa check_availability para cotizar precios.]"
            )
            return '\n'.join(lines)

    def _check_availability(self, check_in, check_out, guests=1, property_name=None):
        """Consulta disponibilidad usando PricingCalculationService.
        Si no hay disponibilidad, busca automáticamente fechas alternativas."""
        from apps.property.pricing_service import PricingCalculationService
        from apps.property.models import Property
        from datetime import timedelta

        try:
            check_in_date = datetime.strptime(check_in, '%Y-%m-%d').date()
            check_out_date = datetime.strptime(check_out, '%Y-%m-%d').date()
        except ValueError:
            return "Las fechas proporcionadas no son válidas. Pide al cliente que confirme las fechas en formato día/mes."

        today = date.today()
        if check_in_date < today:
            return (
                f"La fecha de entrada ({check_in}) ya pasó. "
                f"Hoy es {today.strftime('%d/%m/%Y')}. "
                "Pide al cliente una fecha a futuro."
            )

        if check_out_date <= check_in_date:
            check_out_date = check_in_date + timedelta(days=1)

        nights = (check_out_date - check_in_date).days

        property_id = None
        if property_name:
            prop = Property.objects.filter(
                name__icontains=property_name, deleted=False
            ).first()
            if prop:
                property_id = prop.id
            else:
                return f"No se encontró propiedad con nombre '{property_name}'"

        service = PricingCalculationService()
        client_id = str(self.session.client.id) if self.session.client else None

        try:
            result = service.calculate_pricing(
                check_in_date=check_in_date,
                check_out_date=check_out_date,
                guests=int(guests),
                property_id=property_id,
                client_id=client_id,
            )
        except ValueError as e:
            error_msg = str(e)
            if 'pasado' in error_msg.lower() or 'past' in error_msg.lower():
                return f"La fecha de entrada ({check_in}) ya pasó. Hoy es {date.today().strftime('%d/%m/%Y')}. Pide al cliente una fecha futura."
            return f"No se pudo consultar disponibilidad: {error_msg}. Pide al cliente que confirme las fechas."
        except Exception as e:
            logger.error(f"Error en check_availability: {e}", exc_info=True)
            return "Hubo un problema consultando disponibilidad. Pide al cliente que intente de nuevo o contacte soporte."

        formatted = self._format_pricing_result(result)

        # Marcar sesión como cotizada si hay disponibilidad
        available_count = result.get('totalCasasDisponibles', 0)
        if available_count > 0 and not self.session.quoted_at:
            from django.utils import timezone
            self.session.quoted_at = timezone.now()
            self.session.save(update_fields=['quoted_at'])

        # Registrar búsqueda en SearchTracking (dedup por cliente+fechas o wa_id+fechas)
        try:
            from apps.clients.models import SearchTracking
            from apps.property.models import Property as PropModel
            from django.utils import timezone as tz

            prop_obj = None
            if property_id:
                prop_obj = PropModel.objects.filter(id=property_id).first()

            lookup = {
                'check_in_date': check_in_date,
                'check_out_date': check_out_date,
                'deleted': False,
            }
            if self.session.client:
                lookup['client'] = self.session.client
            else:
                lookup['client__isnull'] = True
                lookup['session_key'] = f'chatbot_{self.session.wa_id}'

            defaults = {
                'guests': int(guests),
                'property': prop_obj,
                'search_timestamp': tz.now(),
                'user_agent': f'chatbot/{self.session.channel}',
                'referrer': f'chatbot_session:{self.session.id}',
            }
            if self.session.client:
                defaults['session_key'] = f'chatbot_{self.session.wa_id}'
            else:
                defaults['client'] = None

            SearchTracking.objects.update_or_create(defaults=defaults, **lookup)
        except Exception as e:
            logger.warning(f"Error registrando SearchTracking desde chatbot: {e}")

        # Si ninguna propiedad está disponible, buscar alternativas
        if available_count == 0:
            alternatives = []
            today = date.today()

            # Búsqueda amplia: día antes, +1, +2, +3, +4, +5, próxima semana, +2 semanas
            offsets = [-1, 1, 2, 3, 4, 5, 7, 14]

            # También buscar próximo viernes y sábado si no están en los offsets
            days_until_friday = (4 - check_in_date.weekday()) % 7
            if days_until_friday == 0:
                days_until_friday = 7
            days_until_saturday = (5 - check_in_date.weekday()) % 7
            if days_until_saturday == 0:
                days_until_saturday = 7
            for extra in [days_until_friday, days_until_saturday]:
                if extra not in offsets and extra > 0:
                    offsets.append(extra)

            offsets = sorted(set(offsets))
            max_alternatives = 3  # Limitar a 3 para no saturar

            for offset in offsets:
                if len(alternatives) >= max_alternatives:
                    break
                alt_in = check_in_date + timedelta(days=offset)
                alt_out = alt_in + timedelta(days=nights)
                if alt_in <= today:
                    continue
                try:
                    alt_result = service.calculate_pricing(
                        check_in_date=alt_in,
                        check_out_date=alt_out,
                        guests=int(guests),
                        property_id=property_id,
                        client_id=client_id,
                    )
                    alt_available = alt_result.get('totalCasasDisponibles', 0)
                    if alt_available > 0:
                        alternatives.append(self._format_pricing_result(alt_result))
                except Exception:
                    continue

            if alternatives:
                formatted += "\n\n📅 *Fechas disponibles más cercanas:*\n\n"
                formatted += "\n\n".join(alternatives)
                formatted += (
                    "\n\n[INSTRUCCIÓN IA — OBLIGATORIO — NO MOSTRAR AL CLIENTE]"
                    "\nPresenta las fechas alternativas de arriba TAL CUAL con sus precios formateados."
                    "\nNO repitas que las fechas originales están ocupadas — enfócate en las opciones disponibles."
                    "\nPregunta si alguna de esas fechas le interesa."
                    "\nSi dice que sí, confirma la cantidad exacta de personas y la fecha elegida para recotizar."
                    "\nNO inventes otras fechas ni busques más opciones por tu cuenta."
                    "\nNO incluyas texto que empiece con [INSTRUCCIÓN o ⚠️ PRECIO BASE."
                )
            else:
                # No se encontraron alternativas cercanas
                formatted += (
                    "\n\n--- SIN ALTERNATIVAS CERCANAS ---"
                    "\nNo se encontraron fechas disponibles en las próximas 2 semanas "
                    "para este número de personas."
                    "\n\n[INSTRUCCIÓN IA — NO MOSTRAR AL CLIENTE]"
                    "\nMuestra la primera línea (📅 fechas) y el mensaje de ocupadas. Sé empático."
                    "\nNO incluyas detalles de cada propiedad ni enlaces de reserva."
                    "\nSugiere al cliente:"
                    "\n- Considerar fechas más adelante (siguiente mes)"
                    "\n- Reducir el número de personas (casas más pequeñas pueden tener disponibilidad)"
                    "\n- Probar fechas entre semana (generalmente más disponibilidad)"
                    "\nPregunta qué prefiere el cliente."
                )

        return formatted

    def _format_pricing_result(self, result):
        """Formatea el resultado del pricing service como cotización WhatsApp-friendly"""
        if not isinstance(result, dict):
            return str(result)

        properties = result.get('properties', [])
        if not properties:
            return "No se encontraron propiedades para consultar."

        total_nights = result.get('total_nights', 0)
        guests = result.get('guests', 0)
        check_in = result.get('check_in_date', '')
        check_out = result.get('check_out_date', '')

        # Formatear fechas para mostrar
        months_es = {
            1: 'enero', 2: 'febrero', 3: 'marzo', 4: 'abril',
            5: 'mayo', 6: 'junio', 7: 'julio', 8: 'agosto',
            9: 'septiembre', 10: 'octubre', 11: 'noviembre', 12: 'diciembre',
        }
        try:
            ci = datetime.strptime(str(check_in), '%Y-%m-%d').date()
            co = datetime.strptime(str(check_out), '%Y-%m-%d').date()
            if ci.month == co.month and ci.year == co.year:
                fecha_display = f"Del {ci.day} al {co.day} de {months_es[ci.month]} de {ci.year}"
            elif ci.year == co.year:
                fecha_display = f"Del {ci.day} de {months_es[ci.month]} al {co.day} de {months_es[co.month]} de {ci.year}"
            else:
                fecha_display = f"Del {ci.day} de {months_es[ci.month]} de {ci.year} al {co.day} de {months_es[co.month]} de {co.year}"
            # URL con formato D/MM/YYYY
            url_ci = f"{ci.day}/{ci.month:02d}/{ci.year}"
            url_co = f"{co.day}/{co.month:02d}/{co.year}"
        except (ValueError, KeyError):
            fecha_display = f"Del {check_in} al {check_out}"
            url_ci = str(check_in)
            url_co = str(check_out)

        # Separar disponibles y no disponibles
        available_lines = []
        unavailable_lines = []
        discount_label = None  # Descuento compartido (se muestra una sola vez)

        capacity_warnings = []

        for prop in properties:
            name = prop.get('property_name', 'Propiedad')
            available = prop.get('available', False)

            if not available:
                msg = prop.get('availability_message', 'No disponible')
                unavailable_lines.append(f"⚠️ {name}: {msg}")
                continue

            # Advertencia de capacidad excedida
            recs = prop.get('recommendations', [])
            for rec in recs:
                if 'capacidad máxima' in rec.lower():
                    capacity_warnings.append(f"⚠️ {name}: {rec}")

            final_usd = prop.get('final_price_usd', 0)
            final_sol = prop.get('final_price_sol', 0)
            base_usd = prop.get('base_price_usd', 0)
            extra_per_night_usd = prop.get('extra_person_price_per_night_usd', 0)
            extra_guests_count = prop.get('extra_guests', 0)
            extra_total_usd = prop.get('extra_person_total_usd', 0)

            # Capturar descuento (se muestra una sola vez al final)
            discount = prop.get('discount_applied')
            if discount and discount.get('type') not in ('none', None):
                disc_pct = discount.get('discount_percentage', 0)
                disc_desc = discount.get('description', '')
                if disc_pct and not discount_label:
                    discount_label = f"{disc_desc} (-{disc_pct}%)" if disc_desc else f"-{disc_pct}%"

            line = f"🏠 {name}: *${final_usd:.2f}* ó *S/{final_sol:.2f}*"
            available_lines.append(line)

        # Construir cotización
        lines = [f"📅 {fecha_display}", ""]

        if available_lines:
            lines.append(f"*PRECIO PARA {guests} PERSONA{'S' if guests != 1 else ''}*")
            if guests == 1:
                lines.append("⚠️ Este precio es solo para 1 persona. Cada persona adicional tiene un costo extra por noche.")
            lines.extend(available_lines)

            if discount_label:
                lines.append(f"\n🎁 *Descuento aplicado:* {discount_label}")

            if capacity_warnings:
                lines.append("")
                lines.extend(capacity_warnings)
                lines.append("👉 Te recomendamos elegir una casa con capacidad suficiente para tu grupo.")

            # No mostrar casas no disponibles — solo genera confusión

            lines.append("")
            lines.append(
                "⚠️ *Importante:* Cualquier visitante, sea de día o de noche, "
                "cuenta como persona adicional. Por favor, indícanos el número exacto de personas."
            )

            # Link directo con fechas y personas
            lines.append("")
            lines.append(
                f"🔗 Fotos y detalles: "
                f"https://casaaustin.pe/disponibilidad?checkIn={url_ci}&checkOut={url_co}&guests={guests}"
            )

            # Instrucción para la IA (NO visible al cliente)
            lines.append("")
            ia_instruction = (
                "[INSTRUCCIÓN IA — OBLIGATORIO — NO MOSTRAR AL CLIENTE]"
                "\nTu respuesta DEBE ser EXACTAMENTE el texto de arriba copiado tal cual, carácter por carácter."
                "\nPROHIBIDO: resumir, parafrasear, cambiar formato, quitar emojis, quitar asteriscos, juntar líneas."
                "\nPROHIBIDO: escribir algo como 'el precio sería $X ó S/X' en prosa. La cotización YA está formateada."
                "\nPROHIBIDO: incluir CUALQUIER texto que empiece con [INSTRUCCIÓN o ⚠️ PRECIO BASE en tu respuesta."
                "\nSolo agrega UNA pregunta de cierre breve DESPUÉS (ej: '¿Te animas a reservar? 😊')."
            )
            if guests <= 1:
                ia_instruction += (
                    "\n\nNOTA INTERNA: Este es precio base para 1 persona. "
                    "Pregunta cuántas personas serán para recotizar con check_availability."
                )
            lines.append(ia_instruction)
        else:
            lines.append("Esas fechas están muy pedidas 🔥 ¡Pero tenemos opciones cercanas!")

        return '\n'.join(lines)

    def _identify_client(self, document_number=None, phone_number=None):
        """Busca cliente por documento o teléfono"""
        from apps.clients.models import Clients
        import re

        client = None

        if document_number:
            client = Clients.objects.filter(
                number_doc=document_number, deleted=False
            ).first()

        if not client and phone_number:
            digits = re.sub(r'\D', '', phone_number)
            # Buscar variantes
            for variant in [digits, digits[-9:], f'51{digits[-9:]}']:
                client = Clients.objects.filter(
                    tel_number__icontains=variant, deleted=False
                ).first()
                if client:
                    break

        if client:
            self.session.client = client
            self.session.client_was_new = client.created >= self.session.created
            self.session.save(update_fields=['client', 'client_was_new'])
            referral = client.referral_code or 'No tiene'
            return (
                f"Cliente identificado:\n"
                f"- Nombre: {client.first_name} {client.last_name or ''}\n"
                f"- Documento: {client.number_doc}\n"
                f"- Teléfono: {client.tel_number}\n"
                f"- Email: {client.email or 'No registrado'}\n"
                f"- Código de referido: {referral}\n"
                f"- ID: {client.id}"
            )

        return "No se encontró ningún cliente con esos datos."

    def _check_client_points(self, client_id):
        """Consulta puntos de un cliente"""
        from apps.clients.models import Clients

        try:
            client = Clients.objects.get(id=client_id, deleted=False)
            balance = float(client.points_balance) if hasattr(client, 'points_balance') and client.points_balance else 0
            return (
                f"Balance de puntos de {client.first_name}:\n"
                f"- Puntos disponibles: {balance:.0f}\n"
                f"- Los puntos pueden usarse como descuento en futuras reservas."
            )
        except Clients.DoesNotExist:
            return "Cliente no encontrado."

    def _check_reservations(self):
        """Consulta reservas activas del cliente vinculado a la sesión"""
        from apps.reservation.models import Reservation
        from django.utils import timezone

        if not self.session.client:
            return (
                "No hay un cliente identificado en esta conversación. "
                "Pide el DNI o teléfono del cliente para identificarlo primero."
            )

        client = self.session.client
        today = timezone.now().date()

        reservations = Reservation.objects.filter(
            client=client,
            deleted=False,
            status__in=['approved', 'pending', 'under_review'],
            check_out_date__gte=today,
        ).select_related('property').order_by('check_in_date')

        if not reservations.exists():
            return f"{client.first_name} no tiene reservas activas en este momento."

        STATUS_LABELS = {
            'approved': 'Confirmada',
            'pending': 'Pendiente de pago',
            'under_review': 'En revisión',
        }

        lines = [f"Reservas activas de {client.first_name}:\n"]
        for r in reservations:
            status_label = STATUS_LABELS.get(r.status, r.status)
            in_progress = r.check_in_date <= today <= r.check_out_date

            line = (
                f"{'🟢' if in_progress else '📅'} {r.property.name}\n"
                f"   📆 {r.check_in_date.strftime('%d/%m/%Y')} al {r.check_out_date.strftime('%d/%m/%Y')}\n"
                f"   👥 {r.guests} persona{'s' if r.guests != 1 else ''}\n"
                f"   💰 S/{r.price_sol:.2f} / ${r.price_usd:.2f}\n"
                f"   📌 Estado: {status_label}"
                f"{' (EN CURSO)' if in_progress else ''}\n"
                f"   💳 {'Pagado 100%' if r.full_payment else f'Adelanto: {r.advance_payment or 0}'}"
            )
            lines.append(line)

        return '\n\n'.join(lines)

    def _validate_discount_code(self, code, property_name=None, check_in_date=None):
        """Valida un código de descuento"""
        from apps.property.pricing_models import DiscountCode
        from apps.property.models import Property

        discount = DiscountCode.objects.filter(
            code__iexact=code, deleted=False
        ).first()

        if not discount:
            return f"Código '{code}' no encontrado o inválido."

        property_id = None
        if property_name:
            prop = Property.objects.filter(
                name__icontains=property_name, deleted=False
            ).first()
            if prop:
                property_id = prop.id

        booking_date = None
        if check_in_date:
            try:
                booking_date = datetime.strptime(check_in_date, '%Y-%m-%d').date()
            except ValueError:
                pass

        is_valid, message = discount.validate(
            property_id=property_id,
            booking_check_date=booking_date,
        )

        if is_valid:
            return (
                f"Código '{code}' VÁLIDO\n"
                f"- {message}\n"
                f"- Tipo: {discount.get_discount_type_display()}\n"
                f"- Valor: {discount.discount_value}"
            )

        return f"Código '{code}' NO VÁLIDO: {message}"

    def _get_property_info(self, property_name=None):
        """Obtiene información de propiedades"""
        from django.db.models import Q
        from apps.property.models import Property

        if property_name:
            properties = Property.objects.filter(
                Q(name__icontains=property_name) |
                Q(descripcion__icontains=property_name),
                deleted=False,
            )
            # Si no encuentra, retornar todas con nota
            if not properties.exists():
                properties = Property.objects.filter(deleted=False)
                if properties.exists():
                    prefix = f"No se encontró propiedad con '{property_name}'. Estas son todas las propiedades disponibles:\n\n"
                    return prefix + self._format_properties(properties)
                return "No hay propiedades registradas."
        else:
            properties = Property.objects.filter(deleted=False)

        if not properties.exists():
            return "No se encontraron propiedades."

        return self._format_properties(properties)

    def _format_properties(self, properties):
        """Formatea lista de propiedades como texto legible"""
        from .utils import calc_bed_capacity

        lines = []
        for prop in properties:
            info = f"🏠 *{prop.name}*\n"
            if prop.descripcion:
                info += f"{prop.descripcion[:200]}\n\n"

            # Capacidades
            parts = []
            if prop.dormitorios:
                parts.append(f"{prop.dormitorios} dormitorios")
            if prop.banos:
                parts.append(f"{prop.banos} baños")
            if prop.capacity_max:
                parts.append(f"hasta {prop.capacity_max} personas")
            if parts:
                info += ' | '.join(parts) + '\n'

            # Capacidad de camas + distribución por habitación
            bed_cap, bed_summary = calc_bed_capacity(prop.detalle_dormitorios)
            if bed_cap:
                info += f"\n🛏️ *Camas para {bed_cap} personas:*\n"
                if prop.detalle_dormitorios and isinstance(prop.detalle_dormitorios, dict):
                    for room in prop.detalle_dormitorios.values():
                        if not isinstance(room, dict):
                            continue
                        nombre = room.get('nombre', '')
                        camas = room.get('camas', {})
                        camas_parts = []
                        for tipo, cant in camas.items():
                            if cant and cant > 0:
                                camas_parts.append(f"{cant} {tipo}")
                        if camas_parts:
                            info += f"  🚪 {nombre}: {', '.join(camas_parts)}\n"

            # Horarios
            horarios = []
            if prop.hora_ingreso:
                horarios.append(f"Check-in: {prop.hora_ingreso.strftime('%I:%M %p')}")
            if prop.hora_salida:
                horarios.append(f"Check-out: {prop.hora_salida.strftime('%I:%M %p')}")
            if horarios:
                info += f"\n🕐 {' | '.join(horarios)}\n"

            # Precio referencia
            if prop.precio_desde:
                info += f"💰 Desde ${prop.precio_desde} USD/noche\n"

            # Características
            if prop.caracteristicas and isinstance(prop.caracteristicas, list):
                chars = prop.caracteristicas[:6]
                if chars:
                    info += f"\n✨ {', '.join(str(c) for c in chars)}\n"

            # Link de fotos y detalles
            if prop.slug:
                info += f"\n📸 Fotos y detalles: https://casaaustin.pe/casas-en-alquiler/{prop.slug}\n"

            lines.append(info)

        return '\n'.join(lines)

    def _schedule_visit(self, property_name, visit_date, visitor_name, visit_time=None, guests_count=1, notes=''):
        """Agenda una visita a una propiedad, verificando disponibilidad"""
        from apps.property.models import Property
        from apps.reservation.models import Reservation
        from apps.chatbot.models import PropertyVisit

        # Buscar propiedad
        prop = Property.objects.filter(
            name__icontains=property_name, deleted=False
        ).first()
        if not prop:
            return f"No se encontró propiedad con nombre '{property_name}'."

        # Parsear fecha
        try:
            visit_dt = datetime.strptime(visit_date, '%Y-%m-%d').date()
        except ValueError:
            return "Error: formato de fecha inválido. Usar YYYY-MM-DD."

        # Validar que no sea fecha pasada
        if visit_dt < date.today():
            return "No se puede agendar una visita en una fecha pasada."

        # Verificar que la propiedad no esté ocupada ese día
        occupied = Reservation.objects.filter(
            property=prop,
            deleted=False,
            check_in_date__lte=visit_dt,
            check_out_date__gt=visit_dt,
            status__in=['confirmed', 'checked_in'],
        ).exists()

        if occupied:
            return (
                f"La propiedad {prop.name} está ocupada el {visit_date} "
                f"(hay una reserva activa). Por favor elige otra fecha."
            )

        # Parsear hora
        visit_time_obj = None
        if visit_time:
            try:
                visit_time_obj = datetime.strptime(visit_time, '%H:%M').time()
            except ValueError:
                visit_time_obj = None

        # Crear la visita
        visit = PropertyVisit.objects.create(
            session=self.session,
            property=prop,
            client=self.session.client,
            visit_date=visit_dt,
            visit_time=visit_time_obj,
            visitor_name=visitor_name,
            visitor_phone=self.session.wa_id,
            guests_count=int(guests_count),
            notes=notes,
        )

        # Notificar admins
        from apps.clients.expo_push_service import ExpoPushService
        time_str = visit_time_obj.strftime('%I:%M %p') if visit_time_obj else 'por confirmar'
        ExpoPushService.send_to_admins(
            title=f"🏠 Nueva visita: {prop.name}",
            body=f"{visitor_name} - {visit_date} a las {time_str}",
            data={
                'type': 'chatbot_visit',
                'visit_id': str(visit.id),
                'session_id': str(self.session.id),
                'screen': 'ChatBot',
            }
        )

        return (
            f"Visita agendada exitosamente:\n"
            f"- Propiedad: {prop.name}\n"
            f"- Fecha: {visit_date}\n"
            f"- Hora: {time_str}\n"
            f"- Visitante: {visitor_name}\n"
            f"- Personas: {guests_count}\n"
            f"El equipo de Casa Austin confirmará tu visita pronto."
        )

    def _check_late_checkout(self, property_name=None, checkout_date=None, guests=None):
        """Consulta precio y disponibilidad de late checkout.

        REGLA DE NEGOCIO: el late checkout es una EXTENSIÓN de una reserva o
        cotización existente. Por tanto `property` y `guests` DEBEN venir del
        contexto (reserva activa del cliente o último check_availability de la
        sesión), NO de lo que el modelo proponga. Los argumentos del modelo
        se usan solo como hint/verificación.

        Resolución en orden:
          1. Reserva activa aprobada del cliente vinculado (property + guests).
          2. Último check_availability de la sesión (property + guests + checkout).
          3. Si nada existe → error: el cliente debe cotizar primero.
        """
        from apps.property.models import Property
        from apps.property.pricing_service import PricingCalculationService

        # --- Resolver contexto: reserva activa del cliente ---
        ctx_property = None
        ctx_guests = None
        ctx_checkout = None
        ctx_source = None

        if self.session and self.session.client:
            from apps.reservation.models import Reservation
            today = date.today()
            active_res = Reservation.objects.filter(
                client=self.session.client,
                check_out_date__gte=today,
                status='approved',
                deleted=False,
            ).order_by('check_in_date').first()
            if active_res:
                ctx_property = active_res.property
                ctx_guests = active_res.guests
                ctx_checkout = active_res.check_out_date
                ctx_source = 'active_reservation'

        # --- Fallback: último check_availability de la sesión ---
        if not ctx_property or not ctx_guests:
            hist = self._recover_last_availability_context()
            if hist:
                if not ctx_property:
                    hist_prop_name = hist.get('property_name')
                    if hist_prop_name:
                        ctx_property = Property.objects.filter(
                            name__icontains=hist_prop_name, deleted=False
                        ).first()
                if not ctx_guests and hist.get('guests'):
                    ctx_guests = int(hist['guests'])
                if not ctx_checkout and hist.get('check_out'):
                    try:
                        ctx_checkout = datetime.strptime(hist['check_out'], '%Y-%m-%d').date()
                    except ValueError:
                        pass
                ctx_source = ctx_source or 'last_check_availability'

        # --- Si el modelo pasó property_name explícito pero no hay contexto,
        # y NO hay reserva ni cotización previa, bloquear. ---
        if not ctx_property and not ctx_guests:
            return (
                "⚠️ BLOQUEADO: No se puede cotizar late checkout sin una reserva "
                "o cotización previa en esta conversación. El late checkout es "
                "una extensión de una reserva existente. "
                "PRIMERO cotiza con check_availability o verifica la reserva activa "
                "del cliente, luego ofrece el late checkout."
            )

        # --- Si el modelo pasó property_name pero NO coincide con el contexto,
        # lo sobrescribimos con el del contexto (fuente de verdad). ---
        model_prop = None
        if property_name:
            model_prop = Property.objects.filter(
                name__icontains=property_name, deleted=False
            ).first()

        prop = ctx_property or model_prop
        if not prop:
            return (
                f"No se encontró propiedad. Cotiza primero con check_availability."
            )

        if (model_prop and ctx_property
                and model_prop.id != ctx_property.id):
            logger.warning(
                f"check_late_checkout: modelo pasó property='{property_name}' "
                f"pero contexto indica '{ctx_property.name}' (source={ctx_source}). "
                f"Usando la del contexto."
            )

        # --- Resolver checkout_date: contexto > argumento del modelo ---
        checkout_dt = None
        if ctx_checkout:
            checkout_dt = ctx_checkout
        elif checkout_date:
            try:
                checkout_dt = datetime.strptime(checkout_date, '%Y-%m-%d').date()
            except ValueError:
                return "Error: formato de fecha inválido. Usar YYYY-MM-DD"
        else:
            return (
                "⚠️ BLOQUEADO: No hay fecha de checkout en el contexto ni en los "
                "argumentos. El cliente debe tener una reserva o cotización previa."
            )

        # --- Resolver guests: contexto SIEMPRE gana sobre lo que pase el modelo ---
        final_guests = ctx_guests
        if guests and ctx_guests and int(guests) != int(ctx_guests):
            logger.warning(
                f"check_late_checkout: modelo pasó guests={guests} pero contexto "
                f"indica guests={ctx_guests} (source={ctx_source}). "
                f"Usando el del contexto para coherencia con la reserva/cotización."
            )
        if not final_guests:
            final_guests = int(guests) if guests and int(guests) >= 1 else 1

        service = PricingCalculationService()
        try:
            result = service.calculate_late_checkout_pricing(
                prop, checkout_dt, int(final_guests)
            )
        except Exception as e:
            logger.error(f"Error en check_late_checkout: {e}", exc_info=True)
            return f"Error consultando late checkout: {str(e)}"

        if not result.get('is_available'):
            message = result.get('message', 'Late checkout no disponible')
            return (
                f"Late checkout no disponible para {prop.name} el "
                f"{checkout_dt.strftime('%Y-%m-%d')}.\n"
                f"Motivo: {message}"
            )

        base_usd = result.get('base_price_usd', 0)
        base_sol = result.get('base_price_sol', 0)
        final_usd = result.get('late_checkout_price_usd', base_usd)
        final_sol = result.get('late_checkout_price_sol', base_sol)
        discount_pct = result.get('discount_percentage', 0)
        guests_used = int(final_guests)

        text = (
            f"✅ *Late checkout disponible* — {prop.name}\n"
            f"📅 Fecha: {checkout_dt.strftime('%Y-%m-%d')} "
            f"({result.get('checkout_day', '')})\n"
            f"👥 Para {guests_used} persona{'s' if guests_used != 1 else ''} "
            f"(de tu {'reserva' if ctx_source == 'active_reservation' else 'cotización'})\n"
            f"🕐 Salida extendida hasta las 8:00 PM\n"
        )

        if discount_pct > 0:
            text += (
                f"💰 Precio base noche: ${base_usd:.2f} / S/{base_sol:.2f}\n"
                f"🏷️ Descuento late checkout: {discount_pct:.0f}%\n"
                f"💵 *Precio late checkout: ${final_usd:.2f} / S/{final_sol:.2f}*\n"
            )
        else:
            text += f"💵 *Precio late checkout: ${final_usd:.2f} / S/{final_sol:.2f}*\n"

        text += "\n⚠️ El late checkout se solicita después de reservar, sujeto a disponibilidad."

        return text

    def _recover_last_availability_context(self):
        """Recupera property + guests + check_out del último check_availability
        o check_late_checkout de la sesión. Se usa para mantener coherencia
        entre cotización y late checkout (misma reserva = mismas personas)."""
        from .models import ChatMessage
        if not self.session:
            return None
        recent_ai = ChatMessage.objects.filter(
            session=self.session,
            deleted=False,
            direction=ChatMessage.DirectionChoices.OUTBOUND_AI,
        ).exclude(tool_calls=[]).order_by('-created')[:10]
        for msg in recent_ai:
            for tc in (msg.tool_calls or []):
                if tc.get('name') in ('check_availability', 'check_late_checkout'):
                    args = tc.get('arguments') or {}
                    guests = args.get('guests')
                    if guests and int(guests) >= 1:
                        return {
                            'property_name': args.get('property_name'),
                            'guests': int(guests),
                            'check_out': args.get('check_out') or args.get('checkout_date'),
                        }
        return None

    def _escalate_to_human(self, reason):
        """Escala la conversación a un agente humano"""
        from apps.clients.expo_push_service import ExpoPushService

        self.session.ai_enabled = False
        self.session.status = 'escalated'
        self.session.save(update_fields=['ai_enabled', 'status'])

        name = self.session.wa_profile_name or self.session.wa_id

        # Notificar admins
        ExpoPushService.send_to_admins(
            title=f"🚨 Escalación: {name}",
            body=f"Razón: {reason}",
            data={
                'type': 'chatbot_escalation',
                'session_id': str(self.session.id),
                'reason': reason,
                'screen': 'ChatBot',
            }
        )

        return (
            f"Conversación escalada a un agente humano.\n"
            f"Razón: {reason}\n"
            f"Un miembro del equipo atenderá al cliente pronto."
        )

    def _notify_team(self, reason, details=''):
        """Envía alerta al equipo sin pausar la IA ni escalar.
        Throttle: máximo 1 notificación por sesión cada 5 horas."""
        from django.utils import timezone
        from datetime import timedelta
        from apps.clients.expo_push_service import ExpoPushService

        # Throttle: verificar si ya se notificó en las últimas 5 horas
        now = timezone.now()
        if self.session.last_notify_at:
            elapsed = now - self.session.last_notify_at
            if elapsed < timedelta(hours=5):
                logger.info(
                    f"Notificación throttled para sesión {self.session.id} "
                    f"(última hace {elapsed.total_seconds() / 60:.0f} min)"
                )
                return "Equipo ya fue notificado recientemente. Continúa atendiendo al cliente normalmente."

        name = self.session.wa_profile_name or self.session.wa_id
        if self.session.client:
            name = f"{self.session.client.first_name} {self.session.client.last_name or ''}".strip()

        ALERT_CONFIG = {
            'ready_to_book': {
                'title': f"🎯 Quiere reservar: {name}",
                'type': 'chatbot_ready_to_book',
            },
            'needs_human_assist': {
                'title': f"🤝 Necesita agente: {name}",
                'type': 'chatbot_needs_human',
            },
            'query_not_understood': {
                'title': f"❓ Consulta no entendida: {name}",
                'type': 'chatbot_query_unclear',
            },
        }

        config = ALERT_CONFIG.get(reason, {
            'title': f"📢 Alerta: {name}",
            'type': 'chatbot_alert',
        })

        ExpoPushService.send_to_admins(
            title=config['title'],
            body=details or reason,
            data={
                'type': config['type'],
                'session_id': str(self.session.id),
                'screen': 'ChatBot',
            }
        )

        # Registrar timestamp de la notificación
        self.session.last_notify_at = now
        self.session.save(update_fields=['last_notify_at'])

        return "Equipo notificado. Continúa atendiendo al cliente normalmente."

    def _log_unanswered_question(self, question, category='other'):
        """Registra una pregunta que el bot no pudo responder."""
        from apps.chatbot.models import UnresolvedQuestion, ChatMessage

        # Obtener contexto: últimos 3 mensajes del cliente
        recent_msgs = ChatMessage.objects.filter(
            session=self.session,
            deleted=False,
            direction='inbound',
        ).order_by('-created')[:3]

        context = '\n'.join(
            f"[{m.created.strftime('%d/%m %H:%M')}] {m.content[:200]}"
            for m in reversed(list(recent_msgs))
        )

        UnresolvedQuestion.objects.create(
            session=self.session,
            question=question,
            context=context,
            category=category,
        )

        logger.info(f"Pregunta sin resolver registrada: {question[:80]} (sesión {self.session.id})")
        return "Pregunta registrada. Responde al cliente que consultarás con el equipo y le darás una respuesta pronto."

    def _get_pricing_table(self, property_name=None):
        """Obtiene resumen de precios contextualizado por temporada actual."""
        from apps.property.models import Property
        from apps.property.pricing_models import (
            PropertyPricing, SeasonPricing, ExchangeRate
        )
        from datetime import date

        rate = ExchangeRate.get_current_rate()
        today = date.today()

        properties = Property.objects.filter(deleted=False).order_by('name')
        if property_name:
            filtered = properties.filter(name__icontains=property_name)
            if filtered.exists():
                properties = filtered

        if not properties.exists():
            return "No hay propiedades registradas."

        # Determinar temporada actual
        is_high = SeasonPricing.is_high_season(today)
        current_season = SeasonPricing.get_season_for_date(today)
        season_label = "ALTA" if is_high else "BAJA"
        season_name = current_season.name if current_season else ("Temporada alta" if is_high else "Temporada baja")

        # Encontrar próximo cambio de temporada (el más cercano)
        next_change_info = ""
        closest_days = None
        all_seasons = SeasonPricing.objects.filter(is_active=True)
        for s in all_seasons:
            try:
                start = date(today.year, s.start_month, s.start_day)
                if start <= today:
                    start = date(today.year + 1, s.start_month, s.start_day)
                days_until = (start - today).days
                if days_until <= 90 and (closest_days is None or days_until < closest_days):
                    closest_days = days_until
                    tipo = "alta" if s.season_type == 'high' else "baja"
                    next_change_info = f"Próximo cambio: temporada {tipo} ({s.name}) inicia en {days_until} días ({start.strftime('%d/%m')})"
            except ValueError:
                continue

        # Calcular rangos de precios por temporada (mín entre todas las casas)
        mins = {
            'weekday_low': None, 'weekend_low': None,
            'weekday_high': None, 'weekend_high': None,
        }
        min_extra = None

        for prop in properties:
            try:
                pricing = PropertyPricing.objects.get(property=prop)
                for key, field in [
                    ('weekday_low', pricing.weekday_low_season_usd),
                    ('weekend_low', pricing.weekend_low_season_usd),
                    ('weekday_high', pricing.weekday_high_season_usd),
                    ('weekend_high', pricing.weekend_high_season_usd),
                ]:
                    if field and (mins[key] is None or field < mins[key]):
                        mins[key] = field
            except PropertyPricing.DoesNotExist:
                pass

            extra = prop.precio_extra_persona
            if extra and (min_extra is None or extra < min_extra):
                min_extra = extra

        # Construir respuesta concisa
        lines = [f"TEMPORADA ACTUAL: {season_label} ({season_name})"]
        if next_change_info:
            lines.append(next_change_info)

        lines.append("")
        lines.append("PRECIOS BASE (1 persona/noche, casa más económica):")
        if mins['weekday_low'] is not None:
            lines.append(f"  Temp. baja entre semana: desde ${mins['weekday_low']:.0f}")
        if mins['weekend_low'] is not None:
            lines.append(f"  Temp. baja fin de semana: desde ${mins['weekend_low']:.0f}")
        if mins['weekday_high'] is not None:
            lines.append(f"  Temp. alta entre semana: desde ${mins['weekday_high']:.0f}")
        if mins['weekend_high'] is not None:
            lines.append(f"  Temp. alta fin de semana: desde ${mins['weekend_high']:.0f}")
        if min_extra:
            lines.append(f"  Extra por persona adicional: desde ${min_extra:.0f}/noche")

        lines.append(f"\nTipo de cambio: 1 USD = S/{rate} SOL")

        lines.append("")
        lines.append(
            "[INSTRUCCIÓN IA — NO MOSTRAR AL CLIENTE]\n"
            "PROHIBIDO mencionar precios específicos de esta tabla al cliente.\n"
            "Responde SIEMPRE: 'Los precios van desde $65/noche para 2 personas (toda la casa) "
            "y varían según la fecha, temporada y cantidad de personas. "
            "¿Para qué fechas y cuántas personas sería? Te doy el precio exacto al instante 😊'\n"
            "Para dar el precio EXACTO, usa check_availability() con fechas y personas específicas.\n"
            "NUNCA menciones montos de la tabla de precios directamente."
        )

        return '\n'.join(lines)
