"""
Management command para renovar el token de Instagram automáticamente.
El token de larga duración dura 60 días. Este comando lo renueva
y actualiza el .env automáticamente.

Uso manual:  python manage.py refresh_ig_token
Cron (cada 50 días):  0 3 */50 * * cd /srv/casaaustin/api-casa-austin/src && /srv/casaaustin/api-casa-austin/venv-py311/bin/python manage.py refresh_ig_token
"""
import os
import re
import requests
import logging

from django.core.management.base import BaseCommand
from django.conf import settings

logger = logging.getLogger(__name__)


class Command(BaseCommand):
    help = 'Renueva el token de Instagram de larga duración y actualiza .env'

    def add_arguments(self, parser):
        parser.add_argument(
            '--dry-run', action='store_true',
            help='Solo muestra el resultado sin actualizar .env'
        )

    def handle(self, *args, **options):
        dry_run = options['dry_run']
        current_token = os.getenv('INSTAGRAM_ACCESS_TOKEN', '')

        if not current_token:
            self.stderr.write(self.style.ERROR(
                'INSTAGRAM_ACCESS_TOKEN no está configurado en .env'
            ))
            return

        self.stdout.write(f"Token actual: {current_token[:20]}...{current_token[-10:]}")

        # Llamar al endpoint de refresh
        url = "https://graph.instagram.com/refresh_access_token"
        params = {
            'grant_type': 'ig_refresh_token',
            'access_token': current_token,
        }

        try:
            response = requests.get(url, params=params, timeout=30)
            data = response.json()
        except requests.exceptions.RequestException as e:
            self.stderr.write(self.style.ERROR(f'Error de conexión: {e}'))
            logger.error(f'refresh_ig_token: Error de conexión: {e}')
            return

        if 'error' in data:
            error_msg = data['error'].get('message', 'Unknown error')
            self.stderr.write(self.style.ERROR(f'Error de Meta API: {error_msg}'))
            logger.error(f'refresh_ig_token: {error_msg}')
            return

        new_token = data.get('access_token')
        expires_in = data.get('expires_in', 0)
        days_remaining = expires_in // 86400

        if not new_token:
            self.stderr.write(self.style.ERROR('No se recibió nuevo token'))
            return

        self.stdout.write(self.style.SUCCESS(
            f'Token renovado exitosamente. Expira en {days_remaining} días.'
        ))
        self.stdout.write(f"Nuevo token: {new_token[:20]}...{new_token[-10:]}")

        if dry_run:
            self.stdout.write(self.style.WARNING('--dry-run: No se actualizó .env'))
            return

        # Actualizar .env
        env_path = self._find_env_file()
        if not env_path:
            self.stderr.write(self.style.ERROR(
                'No se encontró archivo .env. Actualiza manualmente.'
            ))
            self.stdout.write(f"Nuevo token completo: {new_token}")
            return

        self._update_env_file(env_path, new_token)

        # Actualizar en memoria para este proceso
        os.environ['INSTAGRAM_ACCESS_TOKEN'] = new_token

        self.stdout.write(self.style.SUCCESS(
            f'.env actualizado en {env_path}'
        ))
        logger.info(
            f'refresh_ig_token: Token renovado. Expira en {days_remaining} días.'
        )

    def _find_env_file(self):
        """Busca el archivo .env del proyecto."""
        # Intentar rutas conocidas
        candidates = [
            os.path.join(settings.BASE_DIR, '.env'),
            os.path.join(settings.BASE_DIR, '..', '.env'),
            '/srv/casaaustin/api-casa-austin/.env',
        ]
        for path in candidates:
            full = os.path.abspath(path)
            if os.path.isfile(full):
                return full
        return None

    def _update_env_file(self, env_path, new_token):
        """Reemplaza INSTAGRAM_ACCESS_TOKEN en el archivo .env."""
        with open(env_path, 'r') as f:
            content = f.read()

        pattern = r'^INSTAGRAM_ACCESS_TOKEN=.*$'
        replacement = f'INSTAGRAM_ACCESS_TOKEN={new_token}'

        if re.search(pattern, content, re.MULTILINE):
            content = re.sub(pattern, replacement, content, flags=re.MULTILINE)
        else:
            content += f'\n{replacement}\n'

        with open(env_path, 'w') as f:
            f.write(content)
