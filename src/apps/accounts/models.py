from django.contrib.auth.models import AbstractUser
from django.db import models

from apps.core.functions import user_directory_path


class CustomUser(AbstractUser):
    email = models.EmailField(unique=True)
    profile_photo = models.ImageField(upload_to=user_directory_path, null=True, blank=True, default=None)

    created = models.DateTimeField(auto_now_add=True, verbose_name=u'creado', help_text=u'Fecha de creacion')

    USERNAME_FIELD = "email"
    REQUIRED_FIELDS = ("username",)

    def __str__(self):
        return  f'{self.last_name}, {self.first_name}'
