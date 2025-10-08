from django.db import models
from apps.core.models import BaseModel
from apps.reservation.models import Reservation
from apps.clients.models import Clients


class MusicSession(BaseModel):
    """
    Sesión de control de música vinculada a una reserva.
    Permite al huésped gestionar quién puede controlar el reproductor de Music Assistant.
    """
    reservation = models.OneToOneField(
        Reservation,
        on_delete=models.CASCADE,
        related_name='music_session',
        verbose_name="Reserva"
    )
    host_client = models.ForeignKey(
        Clients,
        on_delete=models.CASCADE,
        related_name='hosted_music_sessions',
        verbose_name="Cliente anfitrión"
    )
    is_active = models.BooleanField(
        default=True,
        verbose_name="Sesión activa"
    )
    
    class Meta:
        verbose_name = "Sesión de Música"
        verbose_name_plural = "Sesiones de Música"
        ordering = ['-created']
    
    def __str__(self):
        return f"Sesión de {self.host_client} - Reserva {self.reservation.id}"


class MusicSessionParticipant(BaseModel):
    """
    Participante de una sesión de música.
    Representa a un cliente que ha sido aceptado para controlar el reproductor.
    """
    session = models.ForeignKey(
        MusicSession,
        on_delete=models.CASCADE,
        related_name='participants',
        verbose_name="Sesión"
    )
    client = models.ForeignKey(
        Clients,
        on_delete=models.CASCADE,
        related_name='music_session_participations',
        verbose_name="Cliente participante"
    )
    accepted_at = models.DateTimeField(
        auto_now_add=True,
        verbose_name="Aceptado el"
    )
    
    class Meta:
        verbose_name = "Participante de Sesión de Música"
        verbose_name_plural = "Participantes de Sesiones de Música"
        ordering = ['-accepted_at']
        unique_together = ['session', 'client']
    
    def __str__(self):
        return f"{self.client} en sesión {self.session.id}"
