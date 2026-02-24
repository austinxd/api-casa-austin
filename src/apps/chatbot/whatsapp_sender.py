import os
import re
import requests
import logging

logger = logging.getLogger(__name__)

# Cache de plantillas para no consultar Meta en cada envío
_template_cache = {}


class WhatsAppSender:
    """Envía mensajes por WhatsApp Business API (Meta Cloud API v22.0)"""

    def __init__(self):
        self.access_token = os.getenv('WHATSAPP_ACCESS_TOKEN')
        self.phone_number_id = os.getenv('WHATSAPP_PHONE_NUMBER_ID')
        self.waba_id = os.getenv('WHATSAPP_BUSINESS_ACCOUNT_ID', '')
        self.api_url = f"https://graph.facebook.com/v22.0/{self.phone_number_id}/messages"
        self.headers = {
            'Authorization': f'Bearer {self.access_token}',
            'Content-Type': 'application/json',
        }

    def send_text_message(self, to, text):
        """
        Envía un mensaje de texto simple.

        Args:
            to: Número WhatsApp (formato 51XXXXXXXXX)
            text: Contenido del mensaje

        Returns:
            str|None: wa_message_id del mensaje enviado
        """
        payload = {
            'messaging_product': 'whatsapp',
            'recipient_type': 'individual',
            'to': to,
            'type': 'text',
            'text': {'body': text},
        }

        try:
            response = requests.post(
                self.api_url, json=payload,
                headers=self.headers, timeout=15
            )
            response.raise_for_status()
            data = response.json()
            wa_message_id = data.get('messages', [{}])[0].get('id')
            logger.info(f"WhatsApp mensaje enviado a {to}: {wa_message_id}")
            return wa_message_id

        except requests.exceptions.RequestException as e:
            logger.error(f"Error enviando WhatsApp a {to}: {e}")
            return None

    def send_interactive_buttons(self, to, body, buttons):
        """
        Envía un mensaje con botones de respuesta rápida.

        Args:
            to: Número WhatsApp
            body: Texto del cuerpo del mensaje
            buttons: Lista de dicts con 'id' y 'title' (máx 3)

        Returns:
            str|None: wa_message_id
        """
        button_list = []
        for btn in buttons[:3]:
            button_list.append({
                'type': 'reply',
                'reply': {
                    'id': btn['id'],
                    'title': btn['title'][:20],
                }
            })

        payload = {
            'messaging_product': 'whatsapp',
            'recipient_type': 'individual',
            'to': to,
            'type': 'interactive',
            'interactive': {
                'type': 'button',
                'body': {'text': body},
                'action': {'buttons': button_list},
            }
        }

        try:
            response = requests.post(
                self.api_url, json=payload,
                headers=self.headers, timeout=15
            )
            response.raise_for_status()
            data = response.json()
            wa_message_id = data.get('messages', [{}])[0].get('id')
            logger.info(f"WhatsApp interactive enviado a {to}: {wa_message_id}")
            return wa_message_id

        except requests.exceptions.RequestException as e:
            logger.error(f"Error enviando interactive a {to}: {e}")
            return None

    def send_template_message(self, to, template_name, language_code, components):
        """
        Envía un mensaje de plantilla aprobada por Meta (para mensajes fuera de ventana 24h).

        Args:
            to: Número WhatsApp (formato 51XXXXXXXXX)
            template_name: Nombre de la plantilla aprobada en Meta
            language_code: Código de idioma (ej: 'es')
            components: Lista de componentes con parámetros, ej:
                [{"type": "body", "parameters": [{"type": "text", "text": "Juan"}, ...]}]

        Returns:
            str|None: wa_message_id del mensaje enviado
        """
        payload = {
            'messaging_product': 'whatsapp',
            'recipient_type': 'individual',
            'to': to,
            'type': 'template',
            'template': {
                'name': template_name,
                'language': {'code': language_code},
                'components': components,
            }
        }

        try:
            response = requests.post(
                self.api_url, json=payload,
                headers=self.headers, timeout=15
            )
            response.raise_for_status()
            data = response.json()
            wa_message_id = data.get('messages', [{}])[0].get('id')
            logger.info(f"WhatsApp template '{template_name}' enviado a {to}: {wa_message_id}")
            return wa_message_id

        except requests.exceptions.RequestException as e:
            logger.error(f"Error enviando template '{template_name}' a {to}: {e}")
            if hasattr(e, 'response') and e.response is not None:
                logger.error(f"Response body: {e.response.text}")
            return None

    def render_template(self, template_name, language_code, components):
        """
        Obtiene el body de la plantilla de Meta y reemplaza {{1}}, {{2}}, etc.
        con los parámetros enviados. Usa cache en memoria para no repetir llamadas.

        Returns:
            str|None: Texto renderizado de la plantilla, o None si falla
        """
        cache_key = f"{template_name}:{language_code}"

        # Obtener body de la plantilla (cache o API)
        if cache_key not in _template_cache:
            if not self.waba_id:
                logger.warning("WHATSAPP_BUSINESS_ACCOUNT_ID no configurado, no se puede obtener plantilla")
                return None
            try:
                url = f"https://graph.facebook.com/v22.0/{self.waba_id}/message_templates"
                resp = requests.get(url, params={'name': template_name}, headers=self.headers, timeout=10)
                resp.raise_for_status()
                templates = resp.json().get('data', [])
                body_text = None
                for tmpl in templates:
                    if tmpl.get('language') == language_code:
                        for comp in tmpl.get('components', []):
                            if comp.get('type') == 'BODY':
                                body_text = comp.get('text', '')
                                break
                        break
                if not body_text:
                    logger.warning(f"No se encontró body para plantilla '{template_name}' ({language_code})")
                    return None
                _template_cache[cache_key] = body_text
            except Exception as e:
                logger.error(f"Error obteniendo plantilla '{template_name}': {e}")
                return None

        body = _template_cache[cache_key]

        # Extraer parámetros del body component
        params = []
        for comp in components:
            if comp.get('type') == 'body':
                params = [p.get('text', '') for p in comp.get('parameters', [])]
                break

        # Reemplazar {{1}}, {{2}}, etc.
        for i, value in enumerate(params, start=1):
            body = body.replace(f'{{{{{i}}}}}', value)

        return body

    def mark_as_read(self, wa_message_id):
        """Marca un mensaje como leído en WhatsApp"""
        payload = {
            'messaging_product': 'whatsapp',
            'status': 'read',
            'message_id': wa_message_id,
        }

        try:
            requests.post(
                self.api_url, json=payload,
                headers=self.headers, timeout=10
            )
        except requests.exceptions.RequestException as e:
            logger.warning(f"Error marcando como leído {wa_message_id}: {e}")
