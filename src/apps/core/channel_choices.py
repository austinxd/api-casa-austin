"""Choices compartidas para atribución de canal (lead source).

Usado por:
- ChatSession.first_touch_channel
- Clients.acquisition_channel (canal de adquisición — set una sola vez)
- Reservation.touch_channel (canal del touchpoint de ESTA reserva)

Importar desde otros apps:
    from apps.core.channel_choices import CHANNEL_CHOICES, ChannelChoice
"""
from django.db import models


class ChannelChoice(models.TextChoices):
    META_AD = 'meta_ad', 'Meta Ads (CTW o web)'
    GOOGLE = 'google', 'Google Search'
    WEB_DIRECT = 'web_direct', 'Web directa'
    ORGANIC_WA = 'organic_wa', 'WhatsApp organic'
    REFERRAL = 'referral', 'Referido por otro cliente'
    BOT_MAGIC_LINK = 'bot_magic_link', 'Bot - Magic Link'
    LEGACY_UNKNOWN = 'legacy_unknown', 'Histórico sin atribución'
    UNKNOWN = 'unknown', 'Desconocido'


CHANNEL_CHOICES = ChannelChoice.choices
