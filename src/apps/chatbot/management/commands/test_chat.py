"""
Prueba el chatbot IA directamente desde la terminal, sin WhatsApp.

Uso: python manage.py test_chat
     python manage.py test_chat --session-id <uuid>  (retomar sesión)
     python manage.py test_chat --verbose              (mostrar logs internos)
"""
import logging

from django.core.management.base import BaseCommand
from django.utils import timezone

from apps.chatbot.models import ChatSession, ChatMessage, ChatbotConfiguration


class Command(BaseCommand):
    help = 'Prueba interactiva del chatbot IA en la terminal'

    def add_arguments(self, parser):
        parser.add_argument(
            '--session-id', type=str, default=None,
            help='ID de sesión existente para retomar conversación'
        )
        parser.add_argument(
            '--verbose', action='store_true',
            help='Mostrar logs internos (herramientas, OpenAI, etc.)'
        )

    def handle(self, *args, **options):
        # Silenciar logs internos salvo que pidan --verbose
        if not options['verbose']:
            for logger_name in [
                'apps.chatbot', 'apps.property.pricing_service',
                'apps.property.pricing_models', 'openai', 'httpx', 'httpcore',
            ]:
                logging.getLogger(logger_name).setLevel(logging.WARNING)

        # Verificar config
        config = ChatbotConfiguration.get_config()
        if not config.is_active:
            self.stdout.write(self.style.WARNING('El chatbot está desactivado. Activando para prueba...'))
            config.is_active = True
            config.save()

        # Crear o retomar sesión
        if options['session_id']:
            try:
                session = ChatSession.objects.get(id=options['session_id'])
                self.stdout.write(f'Retomando sesión: {session}')
            except ChatSession.DoesNotExist:
                self.stdout.write(self.style.ERROR('Sesión no encontrada.'))
                return
        else:
            session = ChatSession.objects.create(
                wa_id='TEST_TERMINAL',
                wa_profile_name='Test Terminal',
                status='active',
                last_message_at=timezone.now(),
            )
            self.stdout.write(f'Nueva sesión creada: {session.id}')

        self.stdout.write('')
        self.stdout.write(self.style.SUCCESS('=' * 50))
        self.stdout.write(self.style.SUCCESS('  CHATBOT IA - Modo prueba terminal'))
        self.stdout.write(self.style.SUCCESS(f'  Modelo: {config.primary_model}'))
        self.stdout.write(self.style.SUCCESS(f'  Sesión: {session.id}'))
        self.stdout.write(self.style.SUCCESS('=' * 50))
        self.stdout.write('  Escribe tu mensaje y presiona Enter.')
        self.stdout.write('  Escribe "salir" para terminar.')
        self.stdout.write('')

        while True:
            try:
                user_input = input('\n🧑 Tú: ').strip()
            except (EOFError, KeyboardInterrupt):
                self.stdout.write('\n\nSesión terminada.')
                break

            if not user_input:
                continue
            if user_input.lower() in ('salir', 'exit', 'quit'):
                self.stdout.write('\nSesión terminada.')
                break

            # Guardar mensaje del "cliente"
            ChatMessage.objects.create(
                session=session,
                direction='inbound',
                content=user_input,
            )
            session.total_messages += 1
            session.last_message_at = timezone.now()
            session.last_customer_message_at = timezone.now()
            session.save(update_fields=['total_messages', 'last_message_at', 'last_customer_message_at'])

            # Procesar con IA
            self.stdout.write(self.style.WARNING('⏳ Procesando...'))

            try:
                from apps.chatbot.ai_orchestrator import AIOrchestrator
                orchestrator = AIOrchestrator(config)
                response_text = orchestrator.process_message(session, user_input, send_wa=False)

                if response_text:
                    self.stdout.write(f'\n🤖 Austin Bot: {response_text}')
                else:
                    self.stdout.write(self.style.ERROR('\n❌ Sin respuesta de la IA.'))

            except Exception as e:
                self.stdout.write(self.style.ERROR(f'\n❌ Error: {e}'))
                import traceback
                traceback.print_exc()
