from django.db import models
# from apps.usuarios.models import Usuarios
from apps.core.models import BaseModel


class Property(BaseModel):
    name = models.CharField(max_length=150, null=False, blank=False)
    location = models.CharField(max_length=250, null=True, blank=True)
    airbnb_url = models.URLField(null=True, blank=True)
    capacity_max = models.IntegerField(null=True, blank=True)

    def __str__(self):
        return self.name