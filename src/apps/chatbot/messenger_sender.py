import os
import requests
import logging

logger = logging.getLogger(__name__)


class MessengerSender:
    """Envía mensajes por Facebook Messenger (Page Messaging API)"""

    def __init__(self):
        self.access_token = os.getenv('MESSENGER_PAGE_ACCESS_TOKEN')
        self.api_url = "https://graph.facebook.com/v22.0/me/messages"
        self.headers = {
            'Content-Type': 'application/json',
        }

    def send_text_message(self, to, text):
        """
        Envía un mensaje de texto por Messenger.

        Args:
            to: Page-scoped ID (PSID) del destinatario
            text: Contenido del mensaje

        Returns:
            str|None: message_id del mensaje enviado
        """
        payload = {
            'recipient': {'id': to},
            'message': {'text': text},
        }

        try:
            response = requests.post(
                self.api_url, json=payload,
                headers=self.headers,
                params={'access_token': self.access_token},
                timeout=15
            )
            response.raise_for_status()
            data = response.json()
            message_id = data.get('message_id')
            logger.info(f"Messenger enviado a {to}: {message_id}")
            return message_id

        except requests.exceptions.RequestException as e:
            logger.error(f"Error enviando Messenger a {to}: {e}")
            if hasattr(e, 'response') and e.response is not None:
                logger.error(f"Response: {e.response.text}")
            return None

    def mark_as_read(self, to):
        """Marca mensajes como leídos en Messenger"""
        payload = {
            'recipient': {'id': to},
            'sender_action': 'mark_seen',
        }

        try:
            requests.post(
                self.api_url, json=payload,
                params={'access_token': self.access_token},
                headers=self.headers, timeout=10
            )
        except requests.exceptions.RequestException as e:
            logger.warning(f"Error marcando como leído en Messenger {to}: {e}")
