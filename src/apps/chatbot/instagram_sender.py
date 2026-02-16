import os
import requests
import logging

logger = logging.getLogger(__name__)


class InstagramSender:
    """Envía mensajes por Instagram DM (Meta Send API)"""

    def __init__(self):
        self.access_token = os.getenv('INSTAGRAM_ACCESS_TOKEN')
        self.api_url = "https://graph.instagram.com/v22.0/me/messages"
        self.headers = {
            'Authorization': f'Bearer {self.access_token}',
            'Content-Type': 'application/json',
        }

    def send_text_message(self, to, text):
        """
        Envía un mensaje de texto por Instagram DM.

        Args:
            to: Instagram-scoped ID (IGSID) del destinatario
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
                headers=self.headers, timeout=15
            )
            response.raise_for_status()
            data = response.json()
            message_id = data.get('message_id')
            logger.info(f"Instagram DM enviado a {to}: {message_id}")
            return message_id

        except requests.exceptions.RequestException as e:
            logger.error(f"Error enviando Instagram DM a {to}: {e}")
            if hasattr(e, 'response') and e.response is not None:
                logger.error(f"Response: {e.response.text}")
            return None

    def mark_as_read(self, message_id):
        """Marca un mensaje como visto en Instagram (no soportado via API)"""
        pass
