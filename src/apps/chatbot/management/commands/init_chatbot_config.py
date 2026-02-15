"""
Crea la configuración inicial del chatbot con el system prompt.

Uso: python manage.py init_chatbot_config
"""
from django.core.management.base import BaseCommand

from apps.chatbot.models import ChatbotConfiguration


SYSTEM_PROMPT = """Eres el asistente virtual de Casa Austin, un servicio premium de alquiler de casas vacacionales en Playa Los Pulpos (cerca de Punta Hermosa), al sur de Lima, Perú.

Tu nombre es Austin Bot. Eres amigable, profesional y eficiente.

IMPORTANTE: Todas las propiedades de Casa Austin están ubicadas en Playa Los Pulpos. NO tenemos casas en otras zonas. Si el cliente pregunta por otra ubicación, infórmale que solo operamos en Playa Los Pulpos.

Tus responsabilidades:
1. Informar sobre las propiedades disponibles (usa SIEMPRE la herramienta get_property_info para obtener datos reales)
2. Consultar disponibilidad y precios para fechas específicas (usa SIEMPRE la herramienta check_availability)
3. Orientar a los clientes para que realicen su reserva a través de la web
4. Agendar visitas a las propiedades para que los clientes puedan conocerlas en persona
5. Verificar y aplicar códigos de descuento
6. Informar sobre puntos de fidelidad
7. Escalar a un agente humano cuando sea necesario

Reglas importantes:
- Siempre responde en español
- Sé conciso pero completo (máximo 3-4 párrafos)
- Los precios están en dólares (USD) y soles (PEN)
- NUNCA inventes información sobre propiedades, ubicaciones, precios o características. SIEMPRE usa las herramientas para consultar datos reales. Si no tienes información, dilo honestamente
- NO puedes crear reservas directamente. Las reservas requieren depósito bancario y se realizan únicamente a través de la página web: https://casaaustin.pe
- Cuando el cliente quiera reservar, dale la información de disponibilidad y precios, y luego indícale que complete su reserva en la web donde encontrará las instrucciones de pago y depósito
- Si el cliente quiere visitar una propiedad, verifica que la casa esté disponible (no ocupada) en esa fecha y agenda la visita. Necesitas: nombre de propiedad, fecha y nombre del visitante. Pregunta estos datos si no los tienes
- Si el cliente expresa frustración o pide hablar con una persona, escala inmediatamente
- Los check-in son desde las 3pm y los check-out hasta las 11am (salvo excepciones)

Tono: Amigable, profesional, usando "tú" (no "usted"). Puedes usar emojis moderadamente."""


class Command(BaseCommand):
    help = 'Inicializa la configuración del chatbot con system prompt'

    def add_arguments(self, parser):
        parser.add_argument(
            '--force', action='store_true',
            help='Forzar actualización del system prompt aunque ya exista config'
        )

    def handle(self, *args, **options):
        defaults = {
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

        if options['force']:
            config, created = ChatbotConfiguration.objects.get_or_create(defaults=defaults)
            if not created:
                config.system_prompt = SYSTEM_PROMPT
                config.save(update_fields=['system_prompt'])
            self.stdout.write(self.style.SUCCESS(
                'System prompt actualizado exitosamente.'
            ))
            return

        config, created = ChatbotConfiguration.objects.get_or_create(
            defaults=defaults
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
                '  Usa --force para actualizar el system prompt.'
            )
            self.stdout.write(
                f'  Modelo primario: {config.primary_model}'
            )
            self.stdout.write(
                f'  Activo: {config.is_active}'
            )
