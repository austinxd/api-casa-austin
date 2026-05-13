"""ReservationMagicLink — link temporal de un solo uso para que un cliente
EXISTENTE continúe su reserva sin login manual.

Reglas de seguridad:
- El token visible es opaco (no JWT, sin datos personales).
- En BD solo guardamos token_hash (sha256). El raw NUNCA se persiste.
- Expira en 1h.
- max_uses=1 por defecto.
- Vinculado a client + chat_session + property + check_in/out + guests.
- Al redimir se emite un JWT acotado con scope limitado.
"""
import builtins  # @builtins.property — el field 'property' (casa) ensombrece el decorador
from django.db import models

from apps.core.models import BaseModel


class ReservationMagicLink(BaseModel):
    """Magic link para continuar reserva.

    Dos tipos (R4.2):
    - existing_client: cliente vinculado con tel_number == wa_id. R4.1 actual.
    - guest_express: cliente nuevo con DNI validado por RENIEC desde el chat.
      No tiene Client aún; se creará al confirmar reserva en el front.
    """

    class LinkType(models.TextChoices):
        EXISTING_CLIENT = 'existing_client', 'Cliente existente'
        GUEST_EXPRESS = 'guest_express', 'Cliente nuevo — DNI validado'

    link_type = models.CharField(
        max_length=20,
        choices=LinkType.choices,
        default=LinkType.EXISTING_CLIENT,
        db_index=True,
        help_text='Tipo de magic link: cliente existente o express con DNI.',
    )
    client = models.ForeignKey(
        'clients.Clients',
        on_delete=models.CASCADE,
        related_name='magic_links',
        null=True, blank=True,
        help_text='Cliente vinculado. Null para guest_express (se crea al confirmar).',
    )
    # === Campos guest_express (null para existing_client) ===
    document_type = models.CharField(
        max_length=3,
        null=True, blank=True,
        help_text='Solo "dni" en R4.2 MVP. Null para existing_client.',
    )
    document_number = models.CharField(
        max_length=15,
        null=True, blank=True,
        help_text='DNI de 8 dígitos validado por RENIEC. Null para existing_client.',
    )
    validated_full_name = models.CharField(
        max_length=120,
        null=True, blank=True,
        help_text='Nombre completo devuelto por RENIEC y confirmado en chat.',
    )
    dni_validated_at = models.DateTimeField(
        null=True, blank=True,
        help_text='Cuándo se validó el DNI con RENIEC.',
    )
    token_hash = models.CharField(
        max_length=64,
        unique=True,
        db_index=True,
        help_text='sha256 del token visible. El raw NUNCA se persiste.',
    )
    property = models.ForeignKey(
        'property.Property',
        on_delete=models.SET_NULL,
        null=True, blank=True,
        related_name='magic_links',
        help_text='Casa pre-seleccionada (opcional).',
    )
    check_in = models.DateField(help_text='Fecha de check-in pre-seleccionada.')
    check_out = models.DateField(help_text='Fecha de check-out pre-seleccionada.')
    guests = models.PositiveSmallIntegerField(
        help_text='Personas pre-seleccionadas.',
    )
    chat_session = models.ForeignKey(
        'chatbot.ChatSession',
        on_delete=models.SET_NULL,
        null=True, blank=True,
        related_name='magic_links',
        help_text='Sesión de chat que generó el link.',
    )
    wa_id = models.CharField(
        max_length=20,
        help_text='WhatsApp ID al que se envió el link (para auditoría).',
    )
    expires_at = models.DateTimeField(
        db_index=True,
        help_text='Fecha de expiración (típicamente 1h tras creación).',
    )
    used_at = models.DateTimeField(
        null=True, blank=True,
        help_text='Cuándo fue redimido por primera vez. Si max_uses=1, '
                  'bloquea redenciones posteriores.',
    )
    max_uses = models.PositiveSmallIntegerField(
        default=1,
        help_text='Cuántas veces se puede redimir. Por defecto 1 (one-time).',
    )
    use_count = models.PositiveSmallIntegerField(
        default=0,
        help_text='Cuántas veces se redimió efectivamente.',
    )
    created_ip = models.GenericIPAddressField(
        null=True, blank=True,
        help_text='IP del servidor que generó el link (siempre la del bot).',
    )
    redeemed_ip = models.GenericIPAddressField(
        null=True, blank=True,
        help_text='IP del cliente al redimir.',
    )
    redeemed_user_agent = models.CharField(
        max_length=255, blank=True, default='',
        help_text='User-Agent al redimir.',
    )

    class Meta:
        verbose_name = '🔗 Magic Link de Reserva'
        verbose_name_plural = '🔗 Magic Links de Reserva'
        ordering = ['-created']
        indexes = [
            models.Index(fields=['expires_at']),
            models.Index(fields=['client', 'created']),
            models.Index(fields=['chat_session', 'created']),
        ]

    def __str__(self):
        if self.link_type == self.LinkType.GUEST_EXPRESS:
            name = self.validated_full_name or '?'
        else:
            name = self.client.first_name if self.client_id else '?'
        return (
            f"MagicLink[{self.link_type}] {name} "
            f"→ {self.property.name if self.property_id else 'sin casa'} "
            f"({self.check_in}→{self.check_out}, {self.guests}p) "
            f"[{self.status_label}]"
        )

    @builtins.property
    def status_label(self):
        """Etiqueta humana del estado actual.

        Semántica:
        - 'consumido' = el cliente ya creó la reserva con este link (used_at).
        - 'expirado'  = pasó la ventana de 1h sin haberse reservado.
        - 'vigente'   = aún se puede redimir y crear reserva.

        IMPORTANTE: NO matamos el link en cada redeem (open de /r/<token>).
        El cliente puede abrir, cerrar, volver, compartir en sus devices
        cuantas veces quiera dentro de la ventana de 1h. Solo la CREACIÓN
        de la reserva consume el link.
        """
        from django.utils import timezone
        if self.used_at:
            return 'consumido'
        if self.expires_at and timezone.now() >= self.expires_at:
            return 'expirado'
        return 'vigente'

    @builtins.property
    def is_valid(self):
        """True si el link puede redimirse / usarse ahora.

        Validez = no consumido + no expirado + no soft-deleted.
        Los redeems múltiples (abrir varias veces) NO invalidan; solo
        consumirlo (crear reserva) o que pase la ventana de 1h lo hace.
        """
        from django.utils import timezone
        if self.deleted:
            return False
        if self.used_at:
            return False
        if self.expires_at and timezone.now() >= self.expires_at:
            return False
        return True
