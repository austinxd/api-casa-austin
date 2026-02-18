import logging
from datetime import date, datetime

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
                "Después de mostrar disponibilidad, pregunta cuántas personas para cotizar precios con check_availability."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "from_date": {
                        "type": "string",
                        "description": "Fecha inicio del rango en formato YYYY-MM-DD. Si no se indica, usar hoy."
                    },
                    "to_date": {
                        "type": "string",
                        "description": "Fecha fin del rango en formato YYYY-MM-DD. Si no se indica, usar 30 días desde from_date."
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
            "description": "Consulta disponibilidad Y PRECIOS de propiedades para fechas específicas. Requiere fechas y número de huéspedes para calcular precio. Si el cliente no dijo cuántos huéspedes, usa 1 como default. Usa esta herramienta cuando ya tengas fechas Y personas para dar una cotización con precios.",
            "parameters": {
                "type": "object",
                "properties": {
                    "check_in": {
                        "type": "string",
                        "description": "Fecha de check-in en formato YYYY-MM-DD. Usa el calendario del sistema."
                    },
                    "check_out": {
                        "type": "string",
                        "description": "Fecha de check-out en formato YYYY-MM-DD. Si no se indica, asumir 1 noche (check-in + 1 día)."
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
                "Consulta precio y disponibilidad de late checkout (salida tardía hasta las 8PM). "
                "Requiere el nombre de la propiedad y la fecha de checkout. "
                "El precio es DINÁMICO y depende del día de la semana y disponibilidad. "
                "NUNCA inventes el precio — SIEMPRE usa esta herramienta cuando el cliente pregunte por late checkout."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "property_name": {
                        "type": "string",
                        "description": "Nombre de la propiedad (ej: Casa Austin 2)"
                    },
                    "checkout_date": {
                        "type": "string",
                        "description": "Fecha de checkout en formato YYYY-MM-DD"
                    },
                    "guests": {
                        "type": "integer",
                        "description": "Número de huéspedes (por defecto 1)"
                    }
                },
                "required": ["property_name", "checkout_date"]
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
                "- query_not_understood: No entiendes lo que el cliente pide o no puedes ayudarlo "
                "con la información disponible.\n"
                "NO usar para consultas normales de precio, disponibilidad o información general."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "reason": {
                        "type": "string",
                        "enum": ["ready_to_book", "query_not_understood"],
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

        # Parsear fechas
        if from_date:
            try:
                start = datetime.strptime(from_date, '%Y-%m-%d').date()
            except ValueError:
                start = today
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

        # Obtener reservas activas en el rango
        active_statuses = ['approved', 'pending', 'under_review']
        reservations = Reservation.objects.filter(
            deleted=False,
            status__in=active_statuses,
            check_out_date__gt=start,
            check_in_date__lt=end,
        ).select_related('property')

        # Construir mapa de ocupación: {property_id: [(check_in, check_out), ...]}
        occupation = {}
        for r in reservations:
            occupation.setdefault(r.property_id, []).append(
                (r.check_in_date, r.check_out_date)
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
                    lines.append(f"❌ {day_label}: Todo ocupado")

            lines.append("")
            lines.append(
                "[INSTRUCCIÓN IA: Muestra esta disponibilidad al cliente. "
                "Pregunta cuántas personas serán para dar precios exactos. "
                "Si el cliente elige una fecha, usa check_availability con esa fecha para cotizar.]"
            )
            return '\n'.join(lines)

        else:
            # Rango largo: mostrar resumen por casa
            lines = [f"📅 Disponibilidad del {start.strftime('%d/%m')} al {end.strftime('%d/%m')}:\n"]

            for prop in properties:
                prop_reservations = occupation.get(prop.id, [])

                if not prop_reservations:
                    lines.append(f"🏠 {prop.name}: ✅ Disponible TODO el período")
                    continue

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

            lines.append("")
            lines.append(
                "[INSTRUCCIÓN IA: Muestra esta disponibilidad al cliente. "
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
            return "Error: formato de fecha inválido. Usar YYYY-MM-DD"

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
            return str(e)
        except Exception as e:
            logger.error(f"Error en check_availability: {e}", exc_info=True)
            return f"Error consultando disponibilidad: {str(e)}"

        formatted = self._format_pricing_result(result)

        # Marcar sesión como cotizada si hay disponibilidad
        available_count = result.get('totalCasasDisponibles', 0)
        if available_count > 0 and not self.session.quoted_at:
            from django.utils import timezone
            self.session.quoted_at = timezone.now()
            self.session.save(update_fields=['quoted_at'])

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
                formatted += "\n\n--- FECHAS ALTERNATIVAS DISPONIBLES ---\n\n"
                formatted += "\n\n".join(alternatives)
            else:
                # No se encontraron alternativas cercanas
                formatted += (
                    "\n\n--- SIN ALTERNATIVAS CERCANAS ---"
                    "\nNo se encontraron fechas disponibles en las próximas 2 semanas "
                    "para este número de personas."
                    "\n\nSUGERENCIAS PARA EL CLIENTE:"
                    "\n- Preguntar si puede considerar fechas más adelante (siguiente mes)"
                    "\n- Preguntar si puede reducir el número de personas (casas más pequeñas pueden tener disponibilidad)"
                    "\n- Ofrecer avisarle si se libera alguna fecha"
                    "\n- Preguntar si le interesa una fecha entre semana (generalmente más disponibilidad)"
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
            fecha_display = f"Del {ci.day} al {co.day} de {months_es[ci.month]} de {ci.year}"
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

        for prop in properties:
            name = prop.get('property_name', 'Propiedad')
            available = prop.get('available', False)

            if not available:
                msg = prop.get('availability_message', 'No disponible')
                unavailable_lines.append(f"❌ {name}: {msg}")
                continue

            final_usd = prop.get('final_price_usd', 0)
            final_sol = prop.get('final_price_sol', 0)

            # Descuento
            discount = prop.get('discount_applied')
            discount_text = ""
            if discount and discount.get('type') not in ('none', None):
                disc_pct = discount.get('discount_percentage', 0)
                disc_desc = discount.get('description', '')
                if disc_pct:
                    if disc_desc:
                        discount_text = f"\n   🎁 Descuento: {disc_desc} (-{disc_pct}%)"
                    else:
                        discount_text = f"\n   🎁 Descuento: -{disc_pct}%"

            available_lines.append(
                f"🏠 {name}: *${final_usd:.2f}* ó *S/{final_sol:.2f}*{discount_text}"
            )

        # Construir cotización
        lines = [f"📅 {fecha_display}", ""]

        if available_lines:
            lines.append(f"*PRECIO PARA {guests} PERSONA{'S' if guests != 1 else ''}*")
            lines.extend(available_lines)
        else:
            lines.append("❌ No hay casas disponibles para estas fechas.")

        if unavailable_lines:
            lines.append("")
            lines.extend(unavailable_lines)

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

        if guests <= 1:
            lines.append("")
            lines.append(
                "⚠️ PRECIO BASE PARA 1 PERSONA. "
                "Pregunta cuántas personas serán y llama check_availability de nuevo para recotizar."
            )

        # Instrucción para la IA (no visible al cliente)
        lines.append("")
        lines.append(
            "[INSTRUCCIÓN IA: COPIA Y PEGA todo el texto de arriba EXACTAMENTE como está. "
            "NO reformatees, NO agregues encabezados, NO cambies el orden. "
            "Solo agrega una pregunta de cierre breve DESPUÉS de la cotización.]"
        )

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
            self.session.save(update_fields=['client'])
            return (
                f"Cliente identificado:\n"
                f"- Nombre: {client.first_name} {client.last_name or ''}\n"
                f"- Documento: {client.number_doc}\n"
                f"- Teléfono: {client.tel_number}\n"
                f"- Email: {client.email or 'No registrado'}\n"
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
        lines = []
        for prop in properties:
            info = f"🏠 {prop.name}\n"
            if prop.descripcion:
                info += f"  {prop.descripcion[:200]}\n"
            if prop.capacity_max:
                info += f"  Capacidad máxima: {prop.capacity_max} personas\n"
            if prop.dormitorios:
                info += f"  Dormitorios: {prop.dormitorios}\n"
            if prop.banos:
                info += f"  Baños: {prop.banos}\n"
            if prop.precio_desde:
                info += f"  Precio desde: ${prop.precio_desde} USD/noche\n"
            if prop.hora_ingreso:
                info += f"  Check-in: {prop.hora_ingreso.strftime('%I:%M %p')}\n"
            if prop.hora_salida:
                info += f"  Check-out: {prop.hora_salida.strftime('%I:%M %p')}\n"
            if prop.caracteristicas:
                chars = prop.caracteristicas[:5] if isinstance(prop.caracteristicas, list) else []
                if chars:
                    info += f"  Características: {', '.join(str(c) for c in chars)}\n"
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

    def _check_late_checkout(self, property_name, checkout_date, guests=1):
        """Consulta precio y disponibilidad de late checkout."""
        from apps.property.models import Property
        from apps.property.pricing_service import PricingCalculationService

        try:
            checkout_dt = datetime.strptime(checkout_date, '%Y-%m-%d').date()
        except ValueError:
            return "Error: formato de fecha inválido. Usar YYYY-MM-DD"

        prop = Property.objects.filter(
            name__icontains=property_name, deleted=False
        ).first()
        if not prop:
            return f"No se encontró propiedad con nombre '{property_name}'"

        service = PricingCalculationService()
        try:
            result = service.calculate_late_checkout_pricing(prop, checkout_dt, int(guests))
        except Exception as e:
            logger.error(f"Error en check_late_checkout: {e}", exc_info=True)
            return f"Error consultando late checkout: {str(e)}"

        if not result.get('is_available'):
            message = result.get('message', 'Late checkout no disponible')
            return (
                f"❌ Late checkout NO disponible para {prop.name} el {checkout_date}.\n"
                f"Motivo: {message}"
            )

        base_usd = result.get('base_price_usd', 0)
        base_sol = result.get('base_price_sol', 0)
        final_usd = result.get('late_checkout_price_usd', base_usd)
        final_sol = result.get('late_checkout_price_sol', base_sol)
        discount_pct = result.get('discount_percentage', 0)

        text = (
            f"✅ *Late checkout disponible* — {prop.name}\n"
            f"📅 Fecha: {checkout_date} ({result.get('checkout_day', '')})\n"
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
        """Envía alerta al equipo sin pausar la IA ni escalar"""
        from apps.clients.expo_push_service import ExpoPushService

        name = self.session.wa_profile_name or self.session.wa_id
        if self.session.client:
            name = f"{self.session.client.first_name} {self.session.client.last_name or ''}".strip()

        ALERT_CONFIG = {
            'ready_to_book': {
                'title': f"🎯 Quiere reservar: {name}",
                'type': 'chatbot_ready_to_book',
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

        return "Equipo notificado. Continúa atendiendo al cliente normalmente."
