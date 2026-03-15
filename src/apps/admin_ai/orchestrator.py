"""
Orquestador de IA para el asistente financiero del admin panel.
Sigue el patrón de apps.chatbot.ai_orchestrator pero simplificado para uso admin.
"""
import json
import logging

import openai
from django.conf import settings
from django.utils import timezone

from .models import AdminChatSession, AdminChatMessage
from .tool_definitions import ADMIN_TOOL_DEFINITIONS
from .tool_executor import AdminToolExecutor

logger = logging.getLogger(__name__)

SYSTEM_PROMPT = """Eres un analista financiero experto de Casa Austin, un servicio de alquiler de casas vacacionales en Lima, Perú.

Tu rol:
- Analizar datos financieros reales del negocio usando las herramientas disponibles.
- Siempre consulta los datos con las herramientas antes de responder. NUNCA inventes números.
- Responde en español, de forma clara y profesional.
- Cuando muestres datos, usa formato legible con bullet points o tablas.
- Si te piden análisis estratégico, basa tus recomendaciones en los datos reales que obtuviste.
- Para montos, indica la moneda (S/ para soles, $ para dólares).
- Si no hay datos para el período solicitado, dilo claramente.

Propiedades disponibles en Casa Austin: consulta con get_property_details para obtener la lista actual.

Fecha actual: {current_date}
"""


class AdminAIOrchestrator:
    """Orquestador de IA para consultas financieras del admin"""

    MODEL = 'gpt-4.1'
    TEMPERATURE = 0.3
    MAX_TOKENS = 1500

    def process_message(self, session: AdminChatSession, user_message: str) -> str:
        """Procesa un mensaje del admin y genera respuesta con IA."""

        # 1. Guardar mensaje del usuario
        AdminChatMessage.objects.create(
            session=session,
            role=AdminChatMessage.RoleChoices.USER,
            content=user_message,
        )

        # 2. Llamar a OpenAI
        try:
            response_text, tool_calls_data, tokens = self._call_ai(session, user_message)
        except Exception as e:
            logger.error(f"Error en IA admin: {e}", exc_info=True)
            response_text = (
                "Lo siento, hubo un error al procesar tu consulta. "
                "Por favor intenta de nuevo."
            )
            tool_calls_data = []
            tokens = 0

        # 3. Guardar respuesta
        AdminChatMessage.objects.create(
            session=session,
            role=AdminChatMessage.RoleChoices.ASSISTANT,
            content=response_text,
            tool_calls=tool_calls_data,
            tokens_used=tokens,
        )

        # 4. Actualizar contadores de la sesión
        session.message_count = session.messages.count()
        session.total_tokens = (session.total_tokens or 0) + tokens
        update_fields = ['message_count', 'total_tokens', 'updated']

        # 5. Auto-generar título en el primer intercambio
        if session.message_count <= 2 and session.title == 'Nueva conversación':
            session.title = self._generate_title(user_message)
            update_fields.append('title')

        session.save(update_fields=update_fields)

        return response_text

    def _call_ai(self, session, user_message):
        """Realiza la llamada a OpenAI con function calling"""
        client = openai.OpenAI(api_key=settings.OPENAI_API_KEY)

        messages = self._build_messages(session, user_message)

        # Primera llamada
        response = client.chat.completions.create(
            model=self.MODEL,
            messages=messages,
            tools=ADMIN_TOOL_DEFINITIONS,
            tool_choice="auto",
            temperature=self.TEMPERATURE,
            max_tokens=self.MAX_TOKENS,
        )

        choice = response.choices[0]
        total_tokens = response.usage.total_tokens if response.usage else 0
        tool_calls_data = []

        # Si hay tool_calls, ejecutarlas y hacer segunda llamada
        if choice.message.tool_calls:
            messages.append(choice.message)

            executor = AdminToolExecutor()
            seen_calls = set()

            for tool_call in choice.message.tool_calls:
                func_name = tool_call.function.name
                try:
                    arguments = json.loads(tool_call.function.arguments)
                except json.JSONDecodeError:
                    arguments = {}

                # Dedup
                dedup_key = f"{func_name}:{json.dumps(arguments, sort_keys=True)}"
                if dedup_key in seen_calls:
                    messages.append({
                        "role": "tool",
                        "tool_call_id": tool_call.id,
                        "content": "(Ya consultado, ver resultado anterior)",
                    })
                    continue
                seen_calls.add(dedup_key)

                logger.info(f"Admin AI - Ejecutando: {func_name}({arguments})")
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

            # Segunda llamada con resultados
            response2 = client.chat.completions.create(
                model=self.MODEL,
                messages=messages,
                temperature=self.TEMPERATURE,
                max_tokens=self.MAX_TOKENS,
            )

            response_text = response2.choices[0].message.content or ""
            total_tokens += response2.usage.total_tokens if response2.usage else 0
        else:
            response_text = choice.message.content or ""

        return response_text, tool_calls_data, total_tokens

    def _build_messages(self, session, user_message):
        """Construye el array de mensajes para OpenAI"""
        system_prompt = SYSTEM_PROMPT.format(
            current_date=timezone.now().strftime('%Y-%m-%d'),
        )

        messages = [{"role": "system", "content": system_prompt}]

        # Últimos 20 mensajes del historial (excluyendo el que acabamos de guardar)
        recent = (
            AdminChatMessage.objects
            .filter(session=session, deleted=False)
            .exclude(role=AdminChatMessage.RoleChoices.SYSTEM)
            .order_by('-created')[:20]
        )

        for msg in reversed(list(recent)):
            messages.append({"role": msg.role, "content": msg.content})

        return messages

    def _generate_title(self, user_message):
        """Genera un título corto basado en el primer mensaje"""
        msg = user_message.strip()
        if len(msg) <= 50:
            return msg
        # Cortar en el último espacio antes de 50 chars
        truncated = msg[:50]
        last_space = truncated.rfind(' ')
        if last_space > 20:
            return truncated[:last_space] + '...'
        return truncated + '...'
