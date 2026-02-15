import os
import requests
import logging

logger = logging.getLogger(__name__)


class WhatsAppSender:
    """Envía mensajes por WhatsApp Business API (Meta Cloud API v22.0)"""

    def __init__(self):
        self.access_token = os.getenv('WHATSAPP_ACCESS_TOKEN')
        self.phone_number_id = os.getenv('WHATSAPP_PHONE_NUMBER_ID')
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
