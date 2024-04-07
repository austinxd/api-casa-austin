from django.db import models
from apps.core.models import BaseModel

class TokenApiClients(BaseModel):
    token = models.CharField(max_length=250, null=False, blank=False)

    class Meta:
        verbose_name = "Token rutificador"
        verbose_name_plural = "Tokens rutificadores"
        ordering = ['-created']

    def __str__(self):
        return f"Token: {self.token} creado: {self.created}"

class Clients(BaseModel):
    class DocumentTypeChoice(models.TextChoices):
        DNI = "dni", ("Documento Nacional de Identidad")
        CARNET_EXTRANJERIA = "cex", ("Carnet de Extranjeria")
        PAS = "pas", ("Pasaporte")

    class GeneroChoice(models.TextChoices):
        M = "m", ("Masculino")
        F = "f", ("Femenino")

    document_type = models.CharField(
        max_length=3,
        choices=DocumentTypeChoice.choices,
        default=DocumentTypeChoice.DNI,
        null=True,
    )
    number_doc = models.CharField(max_length=50, null=False, blank=False)
    first_name = models.CharField(max_length=30, null=True, blank=True)
    last_name = models.CharField(max_length=30, null=True, blank=True)
    sex = models.CharField(
        max_length=1, choices=GeneroChoice.choices, default=GeneroChoice.F
    )

    email = models.EmailField(max_length=150, null=True, blank=True)
    date = models.DateField()
    tel_number = models.CharField(max_length=50, null=False, blank=False)

    class Meta:
        unique_together = ('document_type', 'number_doc')

    def __str__(self):
        return self.email
