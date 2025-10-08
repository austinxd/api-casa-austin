from django.db import models
from apps.core.models import BaseModel
from apps.reservation.models import Reservation
from apps.clients.models import Clients


class MusicSessionParticipant(BaseModel):
    """
    Participante/solicitante de acceso para controlar la música de una reserva.
    El anfitrión (dueño de la reserva) debe aceptar la solicitud.
    """
    STATUS_CHOICES = [
        ('pending', 'Pendiente'),
        ('accepted', 'Aceptado'),
        ('rejected', 'Rechazado'),
    ]
    
    reservation = models.ForeignKey(
        Reservation,
        on_delete=models.CASCADE,
        related_name='music_participants',
        verbose_name="Reserva"
    )
    client = models.ForeignKey(
        Clients,
        on_delete=models.CASCADE,
        related_name='music_session_requests',
        verbose_name="Cliente solicitante"
    )
    status = models.CharField(
        max_length=20,
        choices=STATUS_CHOICES,
        default='pending',
        verbose_name="Estado"
    )
    requested_at = models.DateTimeField(
        auto_now_add=True,
        verbose_name="Solicitado el"
    )
    accepted_at = models.DateTimeField(
        null=True,
        blank=True,
        verbose_name="Aceptado el"
    )
    rejected_at = models.DateTimeField(
        null=True,
        blank=True,
        verbose_name="Rechazado el"
    )
    
    class Meta:
        verbose_name = "Participante de Música"
        verbose_name_plural = "Participantes de Música"
        ordering = ['-requested_at']
        unique_together = ['reservation', 'client']
    
    def __str__(self):
        return f"{self.client} - {self.get_status_display()} - Reserva {self.reservation.id}"
