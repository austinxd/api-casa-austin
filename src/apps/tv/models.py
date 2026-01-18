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
    welcome_message = models.TextField(
        null=True,
        blank=True,
        verbose_name="Mensaje de bienvenida",
        help_text="Mensaje que se muestra en la TV cuando hay un huésped activo"
    )

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


class TVAppVersion(BaseModel):
    """
    Tracks TV app versions for OTA updates.
    Only one version should be marked as current at a time.
    """
    version_code = models.PositiveIntegerField(
        help_text="Numeric version code (e.g., 1, 2, 3). Must be higher than previous for updates."
    )
    version_name = models.CharField(
        max_length=20,
        help_text="Human-readable version (e.g., '1.0.0', '1.1.0')"
    )
    apk_file = models.FileField(
        upload_to='tv-app/apks/',
        help_text="APK file for this version"
    )
    release_notes = models.TextField(
        blank=True,
        help_text="What's new in this version (shown to admins)"
    )
    is_current = models.BooleanField(
        default=False,
        help_text="Mark as current version to push updates to all TVs"
    )
    force_update = models.BooleanField(
        default=False,
        help_text="Force update even if user is watching content"
    )
    min_version_code = models.PositiveIntegerField(
        default=1,
        help_text="Minimum version code required to update (for compatibility)"
    )

    class Meta:
        verbose_name = "TV App Version"
        verbose_name_plural = "TV App Versions"
        ordering = ['-version_code']

    def __str__(self):
        current = " (CURRENT)" if self.is_current else ""
        return f"v{self.version_name} (code: {self.version_code}){current}"

    def save(self, *args, **kwargs):
        # Ensure only one version is marked as current
        if self.is_current:
            TVAppVersion.objects.filter(is_current=True).exclude(pk=self.pk).update(is_current=False)
        super().save(*args, **kwargs)

    def get_apk_url(self):
        """Get the full URL for the APK file."""
        if self.apk_file:
            return self.apk_file.url
        return None
