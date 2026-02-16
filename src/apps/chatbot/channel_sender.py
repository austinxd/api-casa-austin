"""
Factory para obtener el sender correcto según el canal de la sesión.
"""
from .whatsapp_sender import WhatsAppSender
from .instagram_sender import InstagramSender
from .messenger_sender import MessengerSender


def get_sender(channel):
    """
    Retorna la instancia del sender apropiado para el canal.

    Args:
        channel: 'whatsapp', 'instagram', o 'messenger'

    Returns:
        Sender con métodos send_text_message() y mark_as_read()
    """
    if channel == 'instagram':
        return InstagramSender()
    elif channel == 'messenger':
        return MessengerSender()
    return WhatsAppSender()
