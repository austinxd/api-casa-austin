from django.db import models
from apps.core.models import BaseModel
from apps.property.models import Property


class TVDevice(BaseModel):
    """
    Represents a TV device installed in a property room.
    Each TV has a unique room_id used for API authentication.
    """
    property = models.ForeignKey(
        Property,
        on_delete=models.CASCADE,
        related_name='tv_devices'
    )
    room_id = models.CharField(
        max_length=50,
        unique=True,
        help_text="Unique identifier for this TV/room"
    )
    room_name = models.CharField(
        max_length=100,
        blank=True,
        help_text="Friendly name for the room (e.g., 'Living Room', 'Master Bedroom')"
    )
    is_active = models.BooleanField(default=True)
    last_heartbeat = models.DateTimeField(null=True, blank=True)

    class Meta:
        verbose_name = "TV Device"
        verbose_name_plural = "TV Devices"
        ordering = ['property', 'room_name']

    def __str__(self):
        return f"{self.property.name} - {self.room_name or self.room_id}"


class TVSession(BaseModel):
    """
    Tracks TV session events (check-in, check-out, heartbeats).
    """
    class EventType(models.TextChoices):
        CHECK_IN = 'check_in', 'Check In'
        CHECK_OUT = 'check_out', 'Check Out'
        HEARTBEAT = 'heartbeat', 'Heartbeat'
        APP_LAUNCH = 'app_launch', 'App Launch'
        IDLE = 'idle', 'Idle'

    tv_device = models.ForeignKey(
        TVDevice,
        on_delete=models.CASCADE,
        related_name='sessions'
    )
    reservation = models.ForeignKey(
        'reservation.Reservation',
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='tv_sessions'
    )
    event_type = models.CharField(
        max_length=20,
        choices=EventType.choices
    )
    event_data = models.JSONField(
        null=True,
        blank=True,
        help_text="Additional event data (e.g., app name for app_launch)"
    )

    class Meta:
        verbose_name = "TV Session"
        verbose_name_plural = "TV Sessions"
        ordering = ['-created']

    def __str__(self):
        return f"{self.tv_device} - {self.event_type} - {self.created}"
