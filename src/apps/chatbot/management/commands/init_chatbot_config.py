"""
Crea la configuración inicial del chatbot con el system prompt.

Uso: python manage.py init_chatbot_config
"""
from django.core.management.base import BaseCommand

from apps.chatbot.models import ChatbotConfiguration


SYSTEM_PROMPT = """Eres el asistente virtual de Casa Austin, un servicio premium de alquiler de casas vacacionales en Lima, Perú.

Tu nombre es Austin Bot. Eres amigable, profesional y eficiente.

Tus responsabilidades:
1. Informar sobre las propiedades disponibles (casas de playa/campo)
2. Consultar disponibilidad y precios para fechas específicas
3. Ayudar a los clientes a crear reservas
4. Verificar y aplicar códigos de descuento
5. Informar sobre puntos de fidelidad
6. Escalar a un agente humano cuando sea necesario

Reglas importantes:
- Siempre responde en español
- Sé conciso pero completo (máximo 3-4 párrafos)
- Los precios están en dólares (USD) y soles (PEN)
- Para crear una reserva, necesitas identificar al cliente primero (DNI o teléfono)
- Nunca inventes información; usa las herramientas disponibles
- Si el cliente expresa frustración o pide hablar con una persona, escala inmediatamente
- Los check-in son desde las 3pm y los check-out hasta las 11am (salvo excepciones)
- Casa Austin cuenta con varias propiedades, cada una con características únicas

Tono: Amigable, profesional, usando "tú" (no "usted"). Puedes usar emojis moderadamente."""


class Command(BaseCommand):
    help = 'Inicializa la configuración del chatbot con system prompt'

    def handle(self, *args, **options):
        config, created = ChatbotConfiguration.objects.get_or_create(
            defaults={
                'is_active': True,
                'system_prompt': SYSTEM_PROMPT,
                'primary_model': 'gpt-4.1-nano',
                'fallback_model': 'gpt-4o-mini',
                'temperature': 0.7,
                'max_tokens_per_response': 500,
                'ai_auto_resume_minutes': 30,
                'escalation_keywords': [
                    'hablar con persona',
                    'agente humano',
                    'queja',
                    'reclamo',
                    'supervisor',
                    'gerente',
                ],
                'max_consecutive_ai_messages': 10,
            }
        )

        if created:
            self.stdout.write(self.style.SUCCESS(
                'Configuración del chatbot creada exitosamente.'
            ))
        else:
            self.stdout.write(self.style.WARNING(
                'La configuración ya existe. No se modificó.'
            ))
            self.stdout.write(
                f'  Modelo primario: {config.primary_model}'
            )
            self.stdout.write(
                f'  Activo: {config.is_active}'
            )
