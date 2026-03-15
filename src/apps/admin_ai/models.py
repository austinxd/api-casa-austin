from django.db import models
from django.conf import settings
from apps.core.models import BaseModel


class AdminChatSession(BaseModel):
    """Sesión de chat del asistente IA financiero para admins"""

    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name='admin_chat_sessions',
    )
    title = models.CharField(
        max_length=200,
        default='Nueva conversación',
        help_text='Título auto-generado o editado por el usuario',
    )
    model_used = models.CharField(
        max_length=50,
        default='gpt-4.1',
        help_text='Modelo de IA utilizado',
    )
    total_tokens = models.PositiveIntegerField(default=0)
    message_count = models.PositiveIntegerField(default=0)

    class Meta:
        verbose_name = '🧠 Sesión IA Admin'
        verbose_name_plural = '🧠 Sesiones IA Admin'
        ordering = ['-updated']

    def __str__(self):
        return f"{self.user} - {self.title}"


class AdminChatMessage(BaseModel):
    """Mensaje individual de una sesión de chat IA admin"""

    class RoleChoices(models.TextChoices):
        USER = 'user', 'Usuario'
        ASSISTANT = 'assistant', 'Asistente'
        SYSTEM = 'system', 'Sistema'

    session = models.ForeignKey(
        AdminChatSession,
        on_delete=models.CASCADE,
        related_name='messages',
    )
    role = models.CharField(
        max_length=10,
        choices=RoleChoices.choices,
    )
    content = models.TextField()
    tool_calls = models.JSONField(
        default=list,
        blank=True,
        help_text='Herramientas usadas por la IA en este mensaje',
    )
    tokens_used = models.PositiveIntegerField(default=0)

    class Meta:
        verbose_name = '📝 Mensaje IA Admin'
        verbose_name_plural = '📝 Mensajes IA Admin'
        ordering = ['created']

    def __str__(self):
        preview = self.content[:50] + '...' if len(self.content) > 50 else self.content
        return f"[{self.get_role_display()}] {preview}"
