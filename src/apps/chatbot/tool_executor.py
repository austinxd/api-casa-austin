import logging
from datetime import date, datetime

logger = logging.getLogger(__name__)


# Definiciones de herramientas para OpenAI Function Calling
TOOL_DEFINITIONS = [
    {
        "type": "function",
        "function": {
            "name": "check_availability",
            "description": "Consulta disponibilidad y precios de propiedades para fechas específicas. IMPORTANTE: NO inventes fechas ni número de huéspedes. Si el cliente no proporcionó estos datos, NO llames esta herramienta; primero pregúntale las fechas de check-in, check-out y cantidad de huéspedes.",
            "parameters": {
                "type": "object",
                "properties": {
                    "check_in": {
                        "type": "string",
                        "description": "Fecha de check-in en formato YYYY-MM-DD"
                    },
                    "check_out": {
                        "type": "string",
                        "description": "Fecha de check-out en formato YYYY-MM-DD"
                    },
                    "guests": {
                        "type": "integer",
                        "description": "Número de huéspedes"
                    },
                    "property_name": {
                        "type": "string",
                        "description": "Nombre de la propiedad específica (opcional, si no se indica se buscan todas)"
                    }
                },
                "required": ["check_in", "check_out", "guests"]
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
]


class ToolExecutor:
    """Ejecuta las herramientas (function calls) invocadas por la IA"""

    def __init__(self, session):
        self.session = session

    def execute(self, tool_name, arguments):
        """Ejecuta una herramienta y retorna el resultado como string"""
        tool_map = {
            'check_availability': self._check_availability,
            'identify_client': self._identify_client,
            'check_client_points': self._check_client_points,
            'validate_discount_code': self._validate_discount_code,
            'get_property_info': self._get_property_info,
            'schedule_visit': self._schedule_visit,
            'escalate_to_human': self._escalate_to_human,
        }

        handler = tool_map.get(tool_name)
        if not handler:
            return f"Error: herramienta '{tool_name}' no encontrada"

        try:
            return handler(**arguments)
        except Exception as e:
            logger.error(f"Error ejecutando {tool_name}: {e}", exc_info=True)
            return f"Error al ejecutar {tool_name}: {str(e)}"

    def _check_availability(self, check_in, check_out, guests, property_name=None):
        """Consulta disponibilidad usando PricingCalculationService"""
        from apps.property.pricing_service import PricingCalculationService
        from apps.property.models import Property

        try:
            check_in_date = datetime.strptime(check_in, '%Y-%m-%d').date()
            check_out_date = datetime.strptime(check_out, '%Y-%m-%d').date()
        except ValueError:
            return "Error: formato de fecha inválido. Usar YYYY-MM-DD"

        property_id = None
        if property_name:
            prop = Property.objects.filter(
                name__icontains=property_name, deleted=False
            ).first()
            if prop:
                property_id = prop.id
            else:
                return f"No se encontró propiedad con nombre '{property_name}'"

        try:
            service = PricingCalculationService()
            client_id = str(self.session.client.id) if self.session.client else None
            result = service.calculate_pricing(
                check_in_date=check_in_date,
                check_out_date=check_out_date,
                guests=int(guests),
                property_id=property_id,
                client_id=client_id,
            )
            return self._format_pricing_result(result)
        except ValueError as e:
            return str(e)
        except Exception as e:
            logger.error(f"Error en check_availability: {e}", exc_info=True)
            return f"Error consultando disponibilidad: {str(e)}"

    def _format_pricing_result(self, result):
        """Formatea el resultado del pricing service para la IA"""
        if isinstance(result, dict):
            lines = []
            properties = result.get('properties', [result])
            for prop in properties:
                name = prop.get('property_name', prop.get('name', 'Propiedad'))
                available = prop.get('available', prop.get('is_available', False))
                if not available:
                    lines.append(f"- {name}: NO DISPONIBLE")
                    continue
                price_usd = prop.get('total_price_usd', prop.get('price_usd', 0))
                price_sol = prop.get('total_price_sol', prop.get('price_sol', 0))
                nights = prop.get('total_nights', prop.get('nights', 0))
                lines.append(
                    f"- {name}: DISPONIBLE\n"
                    f"  Noches: {nights}\n"
                    f"  Precio: ${price_usd} USD / S/{price_sol} PEN"
                )
                # Descuentos automáticos
                discounts = prop.get('automatic_discounts', [])
                if discounts:
                    for d in discounts:
                        lines.append(f"  Descuento: {d.get('name', '')} ({d.get('percentage', '')}%)")
            return '\n'.join(lines) if lines else "Sin resultados de disponibilidad"

        return str(result)

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
