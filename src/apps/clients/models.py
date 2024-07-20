from django.db import models

from apps.core.models import BaseModel

class MensajeFidelidad(models.Model):
    activo = models.BooleanField(default=True)
    mensaje = models.CharField(
        max_length=255,
        null=False,
        blank=False, 
        help_text="Mensaje que se enviará a los clientes luego de saludarlos. Ej: Hola Augusto, --mensaje--"
    )

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
        RUC = "ruc", ("RUC")

    class GeneroChoice(models.TextChoices):
        M = "m", ("Masculino")
        F = "f", ("Femenino")

    document_type = models.CharField(
        max_length=3,
        choices=DocumentTypeChoice.choices,
        default=DocumentTypeChoice.DNI,
        null=False,
        blank=False
    )
    number_doc = models.CharField(max_length=50, null=False, blank=False, default="1")
    first_name = models.CharField(max_length=30, null=False, blank=False, default="nombre")
    last_name = models.CharField(max_length=30, null=True, blank=True)
    sex = models.CharField(
        max_length=1, choices=GeneroChoice.choices, default=None, null=True, blank=True
    )

    email = models.EmailField(max_length=150, null=True, blank=True)
    date = models.DateField()
    tel_number = models.CharField(max_length=50, null=False, blank=False)

    manychat = models.PositiveIntegerField(null=True, blank=True)
    id_manychat = models.PositiveIntegerField(null=True, blank=True)
    comentarios_clientes = models.TextField(blank=True, null=True, help_text="Comentarios sobre el cliente")


    class Meta:
        unique_together = ('document_type', 'number_doc')

    def __str__(self):
        return f"{self.email} {self.first_name} {self.last_name} {self.document_type} {self.number_doc}"


    def delete(self, *args, **kwargs):
        self.deleted = True
        self.save()
