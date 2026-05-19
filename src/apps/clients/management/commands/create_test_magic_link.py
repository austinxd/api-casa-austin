"""Genera un magic link de prueba sin pasar por el chatbot.

Permite testear el flujo /r/<token> → /booking sin tener que mandar
mensajes reales por WhatsApp.

Uso:
    # Modo guest_express (cliente nuevo, sin DNI prevalidado)
    python manage.py create_test_magic_link \\
        --wa-id 51900000000 \\
        --property casa-austin-1 \\
        --check-in 2026-06-10 \\
        --check-out 2026-06-13 \\
        --guests 4

    # Con DNI prevalidado (simula que el bot ya consultó RENIEC)
    python manage.py create_test_magic_link \\
        --wa-id 51900000000 \\
        --property casa-austin-1 \\
        --check-in 2026-06-10 \\
        --check-out 2026-06-13 \\
        --guests 4 \\
        --dni 12345678 \\
        --name "JUAN PEREZ GOMEZ"

    # Modo existing_client (requiere que exista un Clients con
    # tel_number=wa_id en la BD)
    python manage.py create_test_magic_link \\
        --wa-id 51900000000 \\
        --property casa-austin-1 \\
        --check-in 2026-06-10 \\
        --check-out 2026-06-13 \\
        --guests 4 \\
        --link-type existing_client

Output: imprime la URL completa para abrir en el navegador.
"""
from datetime import datetime

from django.core.management.base import BaseCommand, CommandError

from apps.chatbot.models import ChatSession
from apps.clients.models import Clients
from apps.clients.magic_link_service import find_or_create_magic_link
from apps.property.models import Property


class Command(BaseCommand):
    help = 'Genera un magic link de prueba (sin pasar por WhatsApp)'

    def add_arguments(self, parser):
        parser.add_argument(
            '--wa-id', required=True,
            help='Número WhatsApp formato 51XXXXXXXXX (sin +)',
        )
        parser.add_argument(
            '--property',
            help='Slug de la propiedad (ej: casa-austin-1). Opcional.',
        )
        parser.add_argument('--check-in', required=True, help='YYYY-MM-DD')
        parser.add_argument('--check-out', required=True, help='YYYY-MM-DD')
        parser.add_argument('--guests', type=int, required=True)
        parser.add_argument(
            '--link-type', default='guest_express',
            choices=['guest_express', 'existing_client'],
            help='Tipo de link. Default: guest_express',
        )
        parser.add_argument('--dni', help='Solo para guest_express con RENIEC prevalidado')
        parser.add_argument('--name', help='Nombre completo (solo si --dni)')
        parser.add_argument(
            '--base-url', default='https://casaaustin.pe',
            help='Base URL para el redirect (default casaaustin.pe)',
        )

    def handle(self, *args, **opts):
        wa_id = opts['wa_id']
        try:
            check_in = datetime.strptime(opts['check_in'], '%Y-%m-%d').date()
            check_out = datetime.strptime(opts['check_out'], '%Y-%m-%d').date()
        except ValueError:
            raise CommandError("Las fechas deben ser YYYY-MM-DD")

        prop = None
        if opts.get('property'):
            prop = Property.objects.filter(
                slug=opts['property'], deleted=False,
            ).first()
            if not prop:
                raise CommandError(
                    f"Propiedad '{opts['property']}' no encontrada.",
                )

        # Sesión de chat sintética (no se conecta a WhatsApp real)
        session, _ = ChatSession.objects.get_or_create(
            wa_id=wa_id,
            channel='whatsapp',
            defaults={
                'wa_profile_name': 'TEST USER',
                'status': 'active',
                'ai_enabled': False,
            },
        )

        link_type = opts['link_type']
        client = None
        if link_type == 'existing_client':
            client = Clients.objects.filter(
                tel_number=wa_id, deleted=False,
            ).first()
            if not client:
                raise CommandError(
                    f"No se encontró Cliente con tel_number={wa_id}. "
                    "Para usar --link-type existing_client primero crea "
                    "el Cliente o usa guest_express."
                )

        magic, raw_token, reused = find_or_create_magic_link(
            chat_session=session,
            wa_id=wa_id,
            check_in=check_in,
            check_out=check_out,
            guests=opts['guests'],
            property=prop,
            client=client,
            link_type=link_type,
            document_type='dni' if opts.get('dni') else None,
            document_number=opts.get('dni'),
            validated_full_name=opts.get('name'),
        )

        url = f"{opts['base_url'].rstrip('/')}/r/{raw_token}"
        self.stdout.write(self.style.SUCCESS(
            f"\n{'='*70}\n"
            f"✓ Magic link {'REUSADO' if reused else 'CREADO'}\n"
            f"{'='*70}\n"
            f"  Tipo:        {link_type}\n"
            f"  Magic ID:    {magic.id}\n"
            f"  wa_id:       {wa_id}\n"
            f"  Casa:        {prop.name if prop else '(sin asignar — el form la pedirá)'}\n"
            f"  Fechas:      {check_in} → {check_out}\n"
            f"  Huéspedes:   {opts['guests']}\n"
            f"  DNI:         {opts.get('dni') or '(no prevalidado)'}\n"
            f"  Expira:      {magic.expires_at}\n"
            f"\nURL: {url}\n"
            f"{'='*70}\n"
        ))
