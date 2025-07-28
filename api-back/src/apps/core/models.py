import uuid
from django.db import models

class TimeStampedModel(models.Model):
    created = models.DateTimeField(auto_now_add=True, verbose_name=u'creado', help_text=u'Fecha de creación')
    updated = models.DateTimeField(auto_now=True, verbose_name=u'modificado', help_text=u'Fecha de modificación')

    class Meta:
        abstract = True

class BaseModel(models.Model):
    """Abstract base model for general use."""

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    created = models.DateTimeField(
        "created at", auto_now_add=True, help_text="When the instance was created."
    )

    updated = models.DateTimeField(
        "updated at",
        auto_now=True,
        help_text="The last time at the instance was modified.",
    )

    deleted = models.BooleanField(
        default=False,
        help_text="It can be set to false, usefull to simulate deletion",
    )

    class Meta:
        abstract = True