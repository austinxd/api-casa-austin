import json
import logging
from datetime import date

from django.conf import settings
from django.utils import timezone

from .models import ChatSession, ChatMessage
from .tool_executor import ToolExecutor, TOOL_DEFINITIONS
from .whatsapp_sender import WhatsAppSender

logger = logging.getLogger(__name__)


class AIOrchestrator:
    """
    Orquestador de IA que gestiona las interacciones con OpenAI.
    - Construye mensajes con contexto
    - Ejecuta function calling
    - Maneja fallback de modelo
    - Guarda mensajes y métricas
    """

    def __init__(self, config):
        self.config = config
        self.sender = WhatsAppSender()

    def process_message(self, session, inbound_message, send_wa=True):
        """Procesa un mensaje entrante y genera respuesta con IA.

        Args:
            session: ChatSession
            inbound_message: ChatMessage object o string con el contenido
            send_wa: Si True, envía respuesta por WhatsApp. False para modo test.

        Returns:
            str: Texto de la respuesta generada
        """
        try:
            response_text, tool_calls_data, model_used, tokens = self._call_ai(
                session, inbound_message, self.config.primary_model
            )
        except Exception as e:
            logger.error(f"Error con modelo primario: {e}")
            try:
                response_text, tool_calls_data, model_used, tokens = self._call_ai(
                    session, inbound_message, self.config.fallback_model
                )
            except Exception as e2:
                logger.error(f"Error con modelo fallback: {e2}")
                response_text = "Disculpa, estoy teniendo problemas técnicos. Un agente te atenderá pronto."
                tool_calls_data = []
                model_used = 'error'
                tokens = 0

        # Enviar por WhatsApp solo si está habilitado
        wa_message_id = None
        if send_wa:
            wa_message_id = self.sender.send_text_message(session.wa_id, response_text)

        ChatMessage.objects.create(
            session=session,
            direction=ChatMessage.DirectionChoices.OUTBOUND_AI,
            message_type=ChatMessage.MessageTypeChoices.TEXT,
            content=response_text,
            wa_message_id=wa_message_id,
            ai_model=model_used,
            tokens_used=tokens,
            tool_calls=tool_calls_data,
        )

        # Actualizar contadores
        session.total_messages += 1
        session.ai_messages += 1
        session.last_message_at = timezone.now()
        session.save(update_fields=[
            'total_messages', 'ai_messages', 'last_message_at'
        ])

        return response_text

    def _call_ai(self, session, inbound_message, model):
        """Realiza la llamada a OpenAI con function calling"""
        import openai

        client = openai.OpenAI(api_key=settings.OPENAI_API_KEY)

        messages = self._build_messages(session, inbound_message)

        response = client.chat.completions.create(
            model=model,
            messages=messages,
            tools=TOOL_DEFINITIONS,
            tool_choice="auto",
            temperature=self.config.temperature,
            max_tokens=self.config.max_tokens_per_response,
        )

        choice = response.choices[0]
        total_tokens = response.usage.total_tokens if response.usage else 0
        tool_calls_data = []

        # Si hay tool_calls, ejecutarlas y hacer segunda llamada
        if choice.message.tool_calls:
            messages.append(choice.message)

            executor = ToolExecutor(session)

            for tool_call in choice.message.tool_calls:
                func_name = tool_call.function.name
                try:
                    arguments = json.loads(tool_call.function.arguments)
                except json.JSONDecodeError:
                    arguments = {}

                logger.info(f"Ejecutando herramienta: {func_name}({arguments})")
                result = executor.execute(func_name, arguments)

                tool_calls_data.append({
                    'name': func_name,
                    'arguments': arguments,
                    'result_preview': str(result)[:200],
                })

                messages.append({
                    "role": "tool",
                    "tool_call_id": tool_call.id,
                    "content": str(result),
                })

            # Segunda llamada con resultados de herramientas
            response2 = client.chat.completions.create(
                model=model,
                messages=messages,
                temperature=self.config.temperature,
                max_tokens=self.config.max_tokens_per_response,
            )

            response_text = response2.choices[0].message.content or ""
            total_tokens += response2.usage.total_tokens if response2.usage else 0
        else:
            response_text = choice.message.content or ""

        return response_text, tool_calls_data, model, total_tokens

    def _build_messages(self, session, inbound_message):
        """Construye el array de mensajes para OpenAI.

        inbound_message puede ser un ChatMessage object o un string.
        """
        messages = [
            {"role": "system", "content": self._build_system_prompt(session)}
        ]

        # Determinar si es objeto ChatMessage o string
        is_obj = isinstance(inbound_message, ChatMessage)
        msg_content = inbound_message.content if is_obj else str(inbound_message)

        # Últimos 20 mensajes del historial
        recent_qs = ChatMessage.objects.filter(
            session=session, deleted=False
        )
        if is_obj:
            recent_qs = recent_qs.exclude(id=inbound_message.id)
        recent_messages = recent_qs.order_by('-created')[:20]

        # Revertir para orden cronológico
        for msg in reversed(list(recent_messages)):
            if msg.direction == ChatMessage.DirectionChoices.INBOUND:
                messages.append({"role": "user", "content": msg.content})
            elif msg.direction in [
                ChatMessage.DirectionChoices.OUTBOUND_AI,
                ChatMessage.DirectionChoices.OUTBOUND_HUMAN,
            ]:
                messages.append({"role": "assistant", "content": msg.content})

        # Mensaje actual
        messages.append({"role": "user", "content": msg_content})

        return messages

    def _build_system_prompt(self, session):
        """Construye el system prompt dinámico con contexto"""
        base_prompt = self.config.system_prompt

        context_parts = [base_prompt]

        # Fecha actual
        context_parts.append(f"\nFecha actual: {date.today().strftime('%d/%m/%Y')}")

        # Información del cliente vinculado
        if session.client:
            client = session.client
            client_info = (
                f"\n\nCliente identificado:"
                f"\n- Nombre: {client.first_name} {client.last_name or ''}"
                f"\n- Documento: {client.number_doc}"
                f"\n- Teléfono: {client.tel_number}"
                f"\n- ID: {client.id}"
            )
            if hasattr(client, 'points_balance') and client.points_balance:
                client_info += f"\n- Puntos: {float(client.points_balance):.0f}"
            context_parts.append(client_info)
        else:
            context_parts.append(
                "\n\nCliente NO identificado aún. Si necesitas crear una reserva, "
                "primero identifica al cliente pidiendo su DNI o número de teléfono."
            )

        # Instrucciones de comportamiento
        context_parts.append(
            "\n\nInstrucciones CRÍTICAS:"
            "\n- Responde siempre en español, de forma amigable y concisa."
            "\n- NUNCA inventes datos. Si el cliente no te dio fechas, huéspedes u otra info, PREGÚNTALE antes de usar cualquier herramienta."
            "\n- Para consultar disponibilidad NECESITAS que el cliente te diga: fecha check-in, fecha check-out y cantidad de huéspedes. Si no los tiene, pregúntale."
            "\n- Usa las herramientas SOLO cuando tengas los datos necesarios del cliente."
            "\n- Si el cliente quiere reservar, consulta disponibilidad y precios, y luego indícale que reserve por la web: https://casaaustin.pe"
            "\n- Si no puedes resolver algo o el cliente está insatisfecho, escala a un agente humano."
            "\n- NUNCA inventes información sobre propiedades, ubicaciones o precios; usa las herramientas."
            "\n- Mantén las respuestas cortas (máximo 3-4 párrafos)."
        )

        return '\n'.join(context_parts)
